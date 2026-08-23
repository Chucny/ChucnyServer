"""Persistent per-player state and account context."""
import contextlib
import hashlib
import hmac
import json
import math
import os
import random as _random
import sys as _sys
import threading
import time

import pb


def _data_dir():
    """Where user-editable/save files live: next to the .exe when frozen (so they
    are findable and survive a rebuild), else next to the source."""
    if getattr(_sys, "frozen", False):
        return os.path.dirname(_sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


HERE = _data_dir()
SAVE_FILE = os.path.join(HERE, "save.json")       # legacy single-player save
SAVES_DIR = os.path.join(HERE, "saves")           # one file per account
GYMS_FILE = os.path.join(HERE, "gyms.json")       # SHARED between accounts
RAID_FILE = os.path.join(HERE, "raid.json")


# ==============================================================================
# Threading & Global Synchronization
# ==============================================================================

_lock = threading.RLock()
_current = threading.local()
_players = {}                                     # username -> Player


# ==============================================================================
# Constants & Level Tables
# ==============================================================================

ITEM_POKE_BALL = 1
ITEM_GREAT_BALL = 2
ITEM_POTION = 101
ITEM_REVIVE = 201
ITEM_RAZZ_BERRY = 701

_STARTING_BAG = {
    ITEM_POKE_BALL: 50,
    ITEM_GREAT_BALL: 20,
    ITEM_POTION: 20,
    ITEM_REVIVE: 10,
    ITEM_RAZZ_BERRY: 20,
}

DEFAULT_AVATAR = {2: 1, 3: 1, 4: 1, 5: 1, 6: 0, 7: 1, 8: 0, 9: 1, 10: 1}


# Real 2016 XP thresholds (PlayerLevelSettings.required_experience).
LEVEL_XP = [
    0, 1000, 3000, 6000, 10000, 15000, 21000, 28000, 36000, 45000,
    55000, 65000, 75000, 85000, 100000, 120000, 140000, 160000, 185000,
    210000, 260000, 335000, 435000, 560000, 710000, 900000, 1100000,
    1350000, 1650000, 2000000, 2500000, 3000000, 3750000, 4750000,
    6000000, 7500000, 9500000, 12000000, 15000000, 20000000
]


def _unpack_badge_thresholds(raw):
    values, value, shift = [], 0, 0
    for byte in raw:
        value |= (byte & 0x7F) << shift
        if byte & 0x80:
            shift += 7
        else:
            values.append(value)
            value = shift = 0
    return tuple(values) if shift == 0 else ()


def _load_badge_definitions():
    try:
        with open(os.path.join(HERE, "fixtures", "badges",
                               "game_master_badges_0.29.0.json"),
                  encoding="utf-8") as fh:
            fixture = json.load(fh)
    except (OSError, ValueError):
        return {}

    definitions = {}
    for key, body in fixture.items():
        if not isinstance(key, str) or not isinstance(body, str):
            continue
        try:
            fields = pb.decode(bytes.fromhex(body))
        except ValueError:
            continue
        badge_type = pb.get(fields, 1, pb.WT_VARINT)
        max_rank = pb.get(fields, 2, pb.WT_VARINT)
        packed = pb.get(fields, 3, pb.WT_LEN)
        thresholds = _unpack_badge_thresholds(packed) if isinstance(packed, bytes) else ()
        if (type(badge_type) is int and badge_type >= 0
                and type(max_rank) is int and max_rank >= 0 and thresholds):
            definitions[key] = {
                "type": badge_type,
                "max_rank": max_rank,
                "thresholds": thresholds,
            }
    return definitions


BADGE_DEFINITIONS = _load_badge_definitions()


_POKEMON_TYPE_NAMES = (
    "", "NORMAL", "FIGHTING", "FLYING", "POISON", "GROUND", "ROCK", "BUG",
    "GHOST", "STEEL", "FIRE", "WATER", "GRASS", "ELECTRIC", "PSYCHIC",
    "ICE", "DRAGON", "DARK", "FAIRY",
)
_TYPE_BADGES = None


def type_badges_from_game_master(data):
    """Return every species' fixture-backed primary and secondary type badges."""
    badges = {}
    for raw_template in pb.get_all(pb.decode(data), 2):
        template = pb.decode(raw_template)
        settings = pb.get(template, 2, pb.WT_LEN)
        if not isinstance(settings, bytes):
            continue
        pokemon = pb.decode(settings)
        pokemon_id = pb.get(pokemon, 1, pb.WT_VARINT)
        if not isinstance(pokemon_id, int) or pokemon_id <= 0:
            continue
        keys = []
        for type_id in (pb.get(pokemon, 4, pb.WT_VARINT),
                        pb.get(pokemon, 5, pb.WT_VARINT)):
            if isinstance(type_id, int) and 0 < type_id < len(_POKEMON_TYPE_NAMES):
                key = "BADGE_TYPE_" + _POKEMON_TYPE_NAMES[type_id]
                if key in BADGE_DEFINITIONS and key not in keys:
                    keys.append(key)
        if keys:
            badges[pokemon_id] = tuple(keys)
    return badges


def _type_badges():
    global _TYPE_BADGES
    if _TYPE_BADGES is None:
        try:
            with open(os.path.join(HERE, "game_master.bin"), "rb") as fh:
                _TYPE_BADGES = type_badges_from_game_master(fh.read())
        except (OSError, IndexError, ValueError):
            _TYPE_BADGES = {}
    return _TYPE_BADGES


def _record_type_badges(pokemon_id):
    for key in dict.fromkeys(_type_badges().get(int(pokemon_id), ())):
        record_badge_progress(key, 1)


# ==============================================================================
# General Helpers
# ==============================================================================

def level_for_xp(xp):
    lvl = 1
    for i, need in enumerate(LEVEL_XP):
        if xp >= need:
            lvl = i + 1
    return min(40, lvl)


def level_bounds(xp):
    lvl = level_for_xp(xp)
    prev = LEVEL_XP[lvl - 1] if lvl - 1 < len(LEVEL_XP) else LEVEL_XP[-1]
    nxt = LEVEL_XP[lvl] if lvl < len(LEVEL_XP) else LEVEL_XP[-1]
    return prev, nxt


def _safe_name(username):
    keep = "".join(c for c in (username or "player") if c.isalnum() or c in "-_")
    return (keep or "player")[:32].lower()


_uid_rng = _random.Random()


def _fresh_uid(used):
    """An unused 63-bit Pokemon id."""
    while True:
        u = _uid_rng.getrandbits(62) | 1
        if u not in used:
            return u


def _all_known_uids():
    """Every Pokemon uid across ALL accounts (loaded plus saves on disk).

    Uniqueness must be global: two trainers catching the same spawn must not
    receive the same Pokemon id, or gym deploy and any uid-keyed shared state
    collides between them.
    """
    uids = set()
    with _lock:
        for p in _players.values():
            uids.update(int(c.get("uid", 0)) for c in p.CAUGHT)
            uids.update(p.DELETED)
    try:
        for fn in os.listdir(SAVES_DIR):
            if not fn.endswith(".json") or fn.startswith("_"):
                continue
            try:
                with open(os.path.join(SAVES_DIR, fn), encoding="utf-8") as fh:
                    d = json.load(fh)
                uids.update(int(c.get("uid", 0)) for c in (d.get("caught") or []))
                uids.update(int(k) for k in (d.get("deleted") or {}))
            except (OSError, ValueError, TypeError):
                continue
    except OSError:
        pass
    return uids


def new_uid(seed=0):
    """A UNIQUE id for a newly caught Pokemon.

    This used to be `encounter_id ^ 0xC0FFEE`, which is derived from the spawn
    point and therefore repeats: catching at the same place twice produced the
    SAME id. The client keys Pokemon by id, so the second catch silently replaced
    the first instead of showing up, and transferring one removed only one of the
    duplicates while the rest kept it on screen.
    """
    used = _all_known_uids()
    base = (int(seed) ^ 0xC0FFEE) & 0x3FFFFFFFFFFFFFFF
    return base if base and base not in used else _fresh_uid(used)


def _hash_pw(password, salt=None):
    """PBKDF2 -- passwords are never stored in the clear, not even on a server
    that only your family can reach."""
    salt = salt or os.urandom(8).hex()
    h = hashlib.pbkdf2_hmac(
        "sha256", (password or "").encode("utf-8"), salt.encode("ascii"), 60000
    ).hex()
    return f"{salt}${h}"


def _load_badge_counters(raw):
    if not isinstance(raw, dict):
        return {}
    counters = {}
    for key, value in raw.items():
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        if isinstance(key, str) and math.isfinite(value) and value >= 0:
            counters[key] = int(value) if value.is_integer() else value
    return counters


def _load_badge_pending(raw):
    if not isinstance(raw, list):
        return []
    pending = []
    for value in raw:
        try:
            value = int(value)
        except (TypeError, ValueError):
            continue
        if value >= 0:
            pending.append(value)
    return pending
class Player:
    def __init__(self, username):
        self.username = username
        self.file = os.path.join(SAVES_DIR, _safe_name(username) + ".json")
        self.BAG = dict(_STARTING_BAG)
        self.CAUGHT = []
        self.CANDY = {}
        self.STARDUST = 5000
        self.XP = 0
        self.LEVEL = 1
        self.COINS = 0
        self.MAX_POKEMON = 250
        self.MAX_ITEMS = 350
        self.CLAIMED_LEVELS = []
        # uid -> ms it was removed.
        self.DELETED = {}
        # pokemon_id -> [times_encountered, times_captured].
        self.POKEDEX = {}
        # Eggs live apart from CAUGHT.
        self.EGGS = []
        # One unlimited incubator.
        self.INCUBATORS = [
            {
                "id": "incubator-unlimited",
                "item": 901,
                "uses": -1,
                "egg": 0,
                "start_km": 0.0,
                "target_km": 0.0,
            }
        ]
        self.HATCHED = []        # hatched, not yet reported to the client
        self.LAST_POS = None     # (lat, lng) for the walked-distance tally
        self.TEAM = 0            # 0 = not chosen yet; set in game at level 5
        self.BERRIES = {}        # encounter_id -> capture multiplier in effect
        self.PW = ""             # "salt$hash"; empty until the account is claimed
        self.AVATAR = dict(DEFAULT_AVATAR)
        self.CODENAME = ""
        self.BADGE_PROGRESS = {}
        self.BADGE_LEVELS = {}
        self.BADGE_PENDING = []


        self.APPLIED = []        # active Lucky Egg / Incense
        self.STATS = {
            "pokemons_encountered": 0,
            "pokemons_captured": 0,
            "poke_stop_visits": 0,
            "pokeballs_thrown": 0,
            "unique_pokedex_entries": 0,
            "km_walked": 0.0,
        }

    def snapshot(self):
        return {
            "username": self.username,
            "bag": {str(k): v for k, v in self.BAG.items()},
            "caught": self.CAUGHT,
            "candy": {str(k): v for k, v in self.CANDY.items()},
            "stardust": self.STARDUST,
            "xp": self.XP,
            "level": self.LEVEL,
            "coins": self.COINS,
            "stats": self.STATS,
            "claimed_levels": self.CLAIMED_LEVELS,
            "deleted": {str(k): v for k, v in self.DELETED.items()},
            "pokedex": {str(k): list(v) for k, v in self.POKEDEX.items()},
            "team": self.TEAM,
            "pw": self.PW,
            "applied": self.APPLIED,
            "eggs": self.EGGS,
            "incubators": self.INCUBATORS,
            "hatched": self.HATCHED,
            "max_pokemon": self.MAX_POKEMON,
            "max_items": self.MAX_ITEMS,
            "avatar": {str(slot): value for slot, value in self.AVATAR.items()},
            "codename": self.CODENAME,
            "badge_progress": self.BADGE_PROGRESS,
            "badge_levels": self.BADGE_LEVELS,
            "badge_pending": self.BADGE_PENDING,

        }


    def save(self):
        try:
            os.makedirs(SAVES_DIR, exist_ok=True)
            tmp = self.file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.snapshot(), fh, indent=1)
            os.replace(tmp, self.file)     # atomic; never a half-written save
        except OSError:
            pass                         # a failed save must never break play

    def load_from(self, path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            return False

        self.BAG = {}
        for k, v in (d.get("bag") or {}).items():
            try:
                self.BAG[int(k)] = int(v)
            except (TypeError, ValueError):
                pass
        if not self.BAG:
            self.BAG = dict(_STARTING_BAG)

        self.CAUGHT = [c for c in (d.get("caught") or []) if isinstance(c, dict)]
        seen = set()
        for c in self.CAUGHT:
            u = int(c.get("uid", 0) or 0)
            if not u or u in seen:
                u = _fresh_uid(seen)
                c["uid"] = u
            seen.add(u)

        self.CANDY = {}
        for k, v in (d.get("candy") or {}).items():
            try:
                self.CANDY[int(k)] = int(v)
            except (TypeError, ValueError):
                pass

        self.DELETED = {}
        for k, v in (d.get("deleted") or {}).items():
            try:
                self.DELETED[int(k)] = int(v)
            except (TypeError, ValueError):
                pass

        self.POKEDEX = {}
        for k, v in (d.get("pokedex") or {}).items():
            try:
                self.POKEDEX[int(k)] = [int(v[0]), int(v[1])]
            except (TypeError, ValueError, IndexError):
                pass

        for c in self.CAUGHT:
            pid = int(c.get("pokemon_id", 0) or 0)
            if pid and pid not in self.POKEDEX:
                self.POKEDEX[pid] = [1, 1]

        now_ms = int(time.time() * 1000)
        self.POKESTOP_COOLDOWNS = {}
        for fid, ts in (d.get("pokestop_cooldowns") or {}).items():
            try:
                ts = int(ts)
                if ts > now_ms:
                    self.POKESTOP_COOLDOWNS[str(fid)] = ts
            except (TypeError, ValueError):
                pass

        self.TEAM = int(d.get("team", 0) or 0)
        self.PW = str(d.get("pw", "") or "")
        codename = d.get("codename", "")
        if (isinstance(codename, str) and 3 <= len(codename) <= 15
                and codename.isascii() and codename.isalnum()):
            self.CODENAME = codename
        self.APPLIED = [a for a in (d.get("applied") or []) if isinstance(a, dict)]
        self.EGGS = [e for e in (d.get("eggs") or []) if isinstance(e, dict)]
        inc = [i for i in (d.get("incubators") or []) if isinstance(i, dict)]
        if inc:
            self.INCUBATORS = inc
        self.HATCHED = [h for h in (d.get("hatched") or []) if isinstance(h, dict)]
        self.STARDUST = int(d.get("stardust", self.STARDUST) or self.STARDUST)
        self.XP = int(d.get("xp", 0) or 0)
        self.COINS = int(d.get("coins", 0) or 0)
        self.MAX_POKEMON = int(d.get("max_pokemon", 250) or 250)
        self.MAX_ITEMS = int(d.get("max_items", 350) or 350)


        saved_avatar = d.get("avatar")
        if isinstance(saved_avatar, dict):
            for slot, value in saved_avatar.items():
                try:
                    slot = int(slot)
                except (TypeError, ValueError):
                    continue
                if 2 <= slot <= 10 and type(value) is int and 0 <= value <= 255:
                    self.AVATAR[slot] = value

        for k, v in (d.get("stats") or {}).items():
            if k in self.STATS:
                self.STATS[k] = v

        self.BADGE_PROGRESS = _load_badge_counters(d.get("badge_progress"))
        self.BADGE_LEVELS = _load_badge_counters(d.get("badge_levels"))
        self.BADGE_PENDING = _load_badge_pending(d.get("badge_pending"))

        self.CLAIMED_LEVELS = [
            int(x)
            for x in (d.get("claimed_levels") or [])
            if str(x).lstrip("-").isdigit()
        ]
        self.LEVEL = level_for_xp(self.XP)
        if not self.CLAIMED_LEVELS:
            self.CLAIMED_LEVELS = list(range(1, self.LEVEL + 1))
        return True

    def set_avatar_slots(self, slots: dict[int, int]) -> bool:
        if (not isinstance(slots, dict) or not slots
                or any(type(slot) is not int or not 2 <= slot <= 10
                       or type(value) is not int or not 0 <= value <= 255
                       for slot, value in slots.items())):
            return False
        with _lock:
            avatar = dict(self.AVATAR)
            avatar.update(slots)
            self.AVATAR = avatar
        return True

    def set_codename(self, codename: str) -> bool:
        if (not isinstance(codename, str) or not 3 <= len(codename) <= 15
                or not codename.isascii() or not codename.isalnum()):
            return False
        with _lock:
            self.CODENAME = codename
        return True


# ==============================================================================
# Player Session & Account Context Management
# ==============================================================================

def use(username):
    """Make `username` the account for this request (called by rpc.py)."""
    # Resolve a codename typed at login/RPC to the technical account so a second
    # device logging in with the displayed name hits the SAME save, not a new one.
    # The cache key is the SAFE filename key, so Trainer/trainer/TRAINER all map
    # to one Player object instead of duplicating state over the same JSON file.
    key = _safe_name(resolve_account(username) or (username or "player"))
    with _lock:
        p = _players.get(key)
        loaded = p is None
        if loaded:
            p = Player(key)
            path = os.path.join(SAVES_DIR, key + ".json")
            if os.path.exists(path):
                p.load_from(path)
            else:
                have_any = os.path.isdir(SAVES_DIR) and any(
                    f.endswith(".json") for f in os.listdir(SAVES_DIR)
                )
                if not have_any and os.path.exists(SAVE_FILE) and p.load_from(SAVE_FILE):
                    p.username = key
                p.save()
            _players[key] = p
    _current.player = p
    if loaded:
        _backfill_legacy_badge_progress()
    return p


def avatar_for(username: str) -> dict[int, int]:
    """Return an account avatar without switching the current player."""
    name = _safe_name(username) if username else ""
    if not name:
        return dict(DEFAULT_AVATAR)
    with _lock:
        player = _players.get(name)
        if player is not None:
            return dict(player.AVATAR)
    player = Player(name)
    if player.load_from(player.file):
        return dict(player.AVATAR)
    return dict(DEFAULT_AVATAR)


def codename_for(username: str) -> str:
    """Return an account display name without switching the current player."""
    name = _safe_name(username) if username else ""
    if not name:
        return ""
    with _lock:
        player = _players.get(name)
        if player is not None:
            return player.CODENAME
    player = Player(name)
    return player.CODENAME if player.load_from(player.file) else ""



def team_for(username: str) -> int:
    """Return an account team without switching the current player."""
    name = _safe_name(username) if username else ""
    if not name:
        return 0
    with _lock:
        player = _players.get(name)
        if player is not None:
            return player.TEAM
    player = Player(name)
    return player.TEAM if player.load_from(player.file) else 0

def current():
    p = getattr(_current, "player", None)
    if p is None:
        p = use("player")
    return p

def get_caught(uid):
    with _lock:
        for c in current().CAUGHT:
            if c["uid"] == uid:
                return dict(c)
    return None


def save():
    current().save()


def record_badge_progress(key, amount):
    """Add progress for one fixture-defined badge and queue newly reached ranks."""
    definition = BADGE_DEFINITIONS.get(key)
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return 0
    if definition is None or not math.isfinite(amount) or amount < 0:
        return current().BADGE_LEVELS.get(key, 0)

    p = current()
    with _lock:
        progress = p.BADGE_PROGRESS.get(key, 0) + amount
        p.BADGE_PROGRESS[key] = int(progress) if progress.is_integer() else progress
        level = min(
            definition["max_rank"],
            sum(progress >= threshold for threshold in definition["thresholds"]),
        )
        previous = p.BADGE_LEVELS.get(key, 0)
        if level > previous:
            p.BADGE_LEVELS[key] = level
            p.BADGE_PENDING.extend([definition["type"]] * (level - previous))
    p.save()
    return level

def _backfill_legacy_badge_progress():
    """Bring fixture-backed aggregate badges up to their saved stat counters."""
    p = current()
    for key, stat in (
        ("BADGE_CAPTURE_TOTAL", "pokemons_captured"),
        ("BADGE_POKEDEX_ENTRIES", "unique_pokedex_entries"),
        ("BADGE_POKESTOPS_VISITED", "poke_stop_visits"),
        ("BADGE_TRAVEL_KM", "km_walked"),
    ):
        try:
            value = float(p.STATS[stat])
        except (KeyError, TypeError, ValueError):
            continue
        if not math.isfinite(value) or value < 0:
            continue
        progress = p.BADGE_PROGRESS.get(key, 0)
        if value > progress:
            record_badge_progress(key, value - progress)
        elif key in p.BADGE_PROGRESS:
            record_badge_progress(key, 0)


def drain_badge_pending():
    """Return and persistently clear the badges awaiting client acknowledgement."""
    p = current()
    with _lock:
        pending = list(p.BADGE_PENDING)
        p.BADGE_PENDING.clear()
    p.save()
    return pending


def accounts():
    """Summary of every save on disk, for the World Manager."""
    out = []
    try:
        for fn in sorted(os.listdir(SAVES_DIR)):
            if not fn.endswith(".json"):
                continue
            try:
                with open(os.path.join(SAVES_DIR, fn), encoding="utf-8") as fh:
                    d = json.load(fh)
                out.append(
                    {
                        "username": d.get("username", fn[:-5]),
                        "level": level_for_xp(int(d.get("xp", 0) or 0)),
                        "xp": int(d.get("xp", 0) or 0),
                        "caught": len(d.get("caught") or []),
                        "coins": int(d.get("coins", 0) or 0),
                    }
                )
            except (OSError, ValueError):
                continue
    except OSError:
        pass
    return out


def account_names():
    """Every account we know of: loaded ones plus saved files."""
    names = set(_players)
    try:
        for fn in os.listdir(SAVES_DIR):
            if fn.endswith(".json") and not fn.startswith("_"):
                names.add(fn[:-len(".json")])
    except OSError:
        pass
    return sorted(names)


def resolve_account(name):
    """Map a typed name to the technical account key: exact username first,
    then a case-insensitive codename match across saves."""
    n = (name or "").strip()
    if not n:
        return None
    if n in account_names():
        return n
    lower = n.lower()
    for real in account_names():
        if codename_for(real).lower() == lower:
            return real
    return None


@contextlib.contextmanager
def acting_as(username):
    """Run a block as another account, on THIS thread only."""
    name = resolve_account(username)
    if not name:
        raise KeyError((username or "").strip())
    prev = getattr(_current, "player", None)
    try:
        yield use(name)
    finally:
        _current.player = prev


def onboarding_needed(username: str) -> bool:
    """A player needs native onboarding until it has a team or full profile."""
    name = _safe_name(username) if username else ""
    if not name:
        return True
    with _lock:
        player = _players.get(name)
        if player is not None:
            return player.TEAM == 0 and (not player.CODENAME or not player.CAUGHT)
    player = Player(name)
    if not player.load_from(player.file):
        return True
    return player.TEAM == 0 and (not player.CODENAME or not player.CAUGHT)

def check_login(username, password):
    """(ok, reason, name). The FIRST login for a name claims it and sets the password."""
    name = (username or "").strip()
    if not name:
        return False, "no username", None
    real = next((n for n in account_names() if n.lower() == name.lower()), name)
    prev = getattr(_current, "player", None)
    try:
        p = use(real)
        if not p.PW:
            p.PW = _hash_pw(password)
            p.save()
            return True, "claimed", real
        salt = p.PW.split("$", 1)[0]
        if hmac.compare_digest(p.PW, _hash_pw(password, salt)):
            return True, "ok", real
        return False, "wrong password", real
    finally:
        _current.player = prev


def set_password(username, password):
    """Used by the World Manager to reset a forgotten password."""
    real = resolve_account(username)
    if not real:
        return False
    prev = getattr(_current, "player", None)
    try:
        p = use(real)
        p.PW = _hash_pw(password)
        p.save()
        return True
    finally:
        _current.player = prev


def has_password(username):
    real = resolve_account(username)
    if not real:
        return False
    prev = getattr(_current, "player", None)
    try:
        return bool(use(real).PW)
    finally:
        _current.player = prev


_FORWARD = {
    "BAG", "CAUGHT", "CANDY", "STARDUST", "XP", "LEVEL", "COINS", "DELETED",
    "POKEDEX", "EGGS", "INCUBATORS", "HATCHED", "TEAM", "BERRIES", "APPLIED",
    "MAX_POKEMON", "MAX_ITEMS", "CLAIMED_LEVELS", "STATS", "BADGE_PROGRESS",
    "BADGE_LEVELS", "BADGE_PENDING"
}


def __getattr__(name):
    if name in _FORWARD:
        return getattr(current(), name)
    raise AttributeError(name)


def add_item(item_id, count):
    p = current()
    with _lock:
        p.BAG[item_id] = p.BAG.get(item_id, 0) + count
        n = p.BAG[item_id]
    p.save()
    return n


def take_item(item_id, count=1):
    p = current()
    with _lock:
        if p.BAG.get(item_id, 0) < count:
            return False
        p.BAG[item_id] -= count
    p.save()
    return True


def bag_items():
    p = current()
    with _lock:
        return [(i, c) for i, c in sorted(p.BAG.items()) if c > 0]


def bag_count():
    return sum(current().BAG.values())


def bag_full():
    return bag_count() >= current().MAX_ITEMS


def room_in_bag():
    return max(0, current().MAX_ITEMS - bag_count())


def add_coins(n):
    p = current()
    with _lock:
        p.COINS += int(n)
        out = p.COINS
    p.save()
    return out


def spend_coins(n):
    """Take PokeCoins for a shop purchase. False if there aren't enough."""
    p = current()
    with _lock:
        if p.COINS < int(n):
            return False
        p.COINS -= int(n)
    p.save()
    return True


def add_stardust(n):
    """Stardust adder."""
    p = current()
    with _lock:
        p.STARDUST += int(n)
        out = p.STARDUST
    p.save()
    return out


def candy(family):
    with _lock:
        return current().CANDY.get(family, 0)


def add_candy(family, n):
    p = current()
    with _lock:
        p.CANDY[family] = p.CANDY.get(family, 0) + n
        out = p.CANDY[family]
    p.save()
    return out


def spend(family=None, candy_n=0, dust_n=0):
    p = current()
    with _lock:
        if candy_n and p.CANDY.get(family, 0) < candy_n:
            return False
        if dust_n and p.STARDUST < dust_n:
            return False
        if candy_n:
            p.CANDY[family] = p.CANDY.get(family, 0) - candy_n
        if dust_n:
            p.STARDUST -= dust_n
    p.save()
    return True
