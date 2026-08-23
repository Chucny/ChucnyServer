"""
World + player state for the PoGO private server, saved to disk.

MULTI-ACCOUNT: each username gets its own file in saves/<name>.json (bag, Pokemon,
XP, candy, storage...). The GYMS are deliberately SHARED in gyms.json, so two
accounts play in the same world and can see -- and battle -- each other's
defenders, the way the real game worked.

rpc.py calls use(username) at the top of every request. ThreadingHTTPServer gives
each request its own thread, so the "current player" is a thread-local and two
people playing at once never step on each other. Module-level names (world.BAG,
world.CANDY, ...) still work: a module __getattr__ forwards them to the player
whose request is being handled, so the rest of the server didn't have to change.
"""
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

import settings as _cfg
import pb



# ==============================================================================
# Path & Directory Configuration
# ==============================================================================

def _data_dir():
    """Where user-editable/save files live: next to the .exe when frozen (so they
    are findable and survive a rebuild), else next to the source."""
    if getattr(_sys, "frozen", False):
        return os.path.dirname(_sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


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


def new_uid(seed=0):
    """A UNIQUE id for a newly caught Pokemon.

    This used to be `encounter_id ^ 0xC0FFEE`, which is derived from the spawn
    point and therefore repeats: catching at the same place twice produced the
    SAME id. The client keys Pokemon by id, so the second catch silently replaced
    the first instead of showing up, and transferring one removed only one of the
    duplicates while the rest kept it on screen.
    """
    p = current()
    with _lock:
        used = {int(c.get("uid", 0)) for c in p.CAUGHT} | set(p.DELETED)
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



# ==============================================================================
# Player Entity Model
# ==============================================================================

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
    name = username or "player"
    with _lock:
        p = _players.get(name)
        loaded = p is None
        if loaded:
            p = Player(name)
            path = os.path.join(SAVES_DIR, _safe_name(name) + ".json")
            if os.path.exists(path):
                p.load_from(path)
            else:
                have_any = os.path.isdir(SAVES_DIR) and any(
                    f.endswith(".json") for f in os.listdir(SAVES_DIR)
                )
                if not have_any and os.path.exists(SAVE_FILE) and p.load_from(SAVE_FILE):
                    p.username = name
                p.save()
            _players[name] = p
    _current.player = p
    if loaded:
        _backfill_legacy_badge_progress()
    return p


def avatar_for(username: str) -> dict[int, int]:
    """Return an account avatar without switching the current player."""
    name = username or ""
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
    name = username or ""
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
    name = username or ""
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


@contextlib.contextmanager
def acting_as(username):
    """Run a block as another account, on THIS thread only."""
    name = (username or "").strip()
    if not name or name not in account_names():
        raise KeyError(name)
    prev = getattr(_current, "player", None)
    try:
        yield use(name)
    finally:
        _current.player = prev


def onboarding_needed(username: str) -> bool:
    """A player needs native onboarding until it has a team or full profile."""
    name = username or ""
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
    real = next(
        (n for n in account_names() if n.lower() == (username or "").lower()), None
    )
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
    real = next(
        (n for n in account_names() if n.lower() == (username or "").lower()), None
    )
    if not real:
        return False
    prev = getattr(_current, "player", None)
    try:
        return bool(use(real).PW)
    finally:
        _current.player = prev


# ==============================================================================
# Dynamic Attribute Forwarding
# ==============================================================================

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


# ==============================================================================
# Inventory (Bag) & Currency Operations
# ==============================================================================

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


# ==============================================================================
# Player Leveling, XP, Claims & Stats
# ==============================================================================

def stats():
    p = current()
    with _lock:
        return p.LEVEL, p.XP


def add_xp(n):
    p = current()
    n = int(n) * xp_multiplier()          # Lucky Egg
    with _lock:
        p.XP += n
        p.LEVEL = level_for_xp(p.XP)
    p.save()
    return p.XP


def bump(counter, n=1):
    p = current()
    with _lock:
        if counter in p.STATS:
            p.STATS[counter] += n
    p.save()
    if counter == "poke_stop_visits":
        record_badge_progress("BADGE_POKESTOPS_VISITED", n)


def level_claimed(level):
    with _lock:
        return int(level) in current().CLAIMED_LEVELS


def claim_level(level):
    p = current()
    with _lock:
        if int(level) not in p.CLAIMED_LEVELS:
            p.CLAIMED_LEVELS.append(int(level))
    p.save()


# ==============================================================================
# Pokemon Collection & Storage Operations
# ==============================================================================

def add_caught(uid, pokemon_id, cp):
    p = current()
    with _lock:
        p.DELETED.pop(int(uid), None)     # never report a live Pokemon as deleted
        p.CAUGHT.append(
            {
                "uid": uid,
                "pokemon_id": pokemon_id,
                "cp": cp,
                "caught_ms": int(time.time() * 1000),
            }
        )
        p.STATS["pokemons_captured"] += 1
        p.STATS["pokeballs_thrown"] += 1
        p.STATS["unique_pokedex_entries"] = len({c["pokemon_id"] for c in p.CAUGHT})
        n = len(p.CAUGHT)
    p.save()
    record_badge_progress("BADGE_CAPTURE_TOTAL", 1)
    if int(pokemon_id) == 25:
        record_badge_progress("BADGE_PIKACHU", 1)
    _record_type_badges(pokemon_id)
    return n


def add_tutorial_starter(pokemon_id, cp=10):
    """Persist one selected starter, or return the account's existing Pokémon."""
    p = current()
    with _lock:
        if p.CAUGHT:
            return dict(p.CAUGHT[0])
        uid = new_uid(pokemon_id)
        starter = {
            "uid": uid,
            "pokemon_id": pokemon_id,
            "cp": cp,
            "caught_ms": int(time.time() * 1000),
        }
        p.CAUGHT.append(starter)
        p.STATS["pokemons_captured"] += 1
        p.STATS["unique_pokedex_entries"] = 1
        entry = p.POKEDEX.setdefault(int(pokemon_id), [0, 0])
        entry[1] += 1
        entry[0] = max(entry[0], entry[1])
    p.save()
    record_badge_progress("BADGE_CAPTURE_TOTAL", 1)
    if int(pokemon_id) == 25:
        record_badge_progress("BADGE_PIKACHU", 1)
    record_badge_progress("BADGE_POKEDEX_ENTRIES", 1)
    return dict(starter)


def caught():
    with _lock:
        return list(current().CAUGHT)


def get_caught(uid):
    with _lock:
        for c in current().CAUGHT:
            if c["uid"] == uid:
                return dict(c)
    return None


def update_caught(uid, **fields):
    p = current()
    with _lock:
        for c in p.CAUGHT:
            if c["uid"] == uid:
                c.update(fields)
                out = dict(c)
                break
        else:
            return None
    p.save()
    return out


def release(uid):
    if is_deployed(uid):
        return False, "deployed"
    p = current()
    with _lock:
        for i, c in enumerate(p.CAUGHT):
            if c["uid"] == uid:
                p.CAUGHT.pop(i)
                break
        else:
            return False, "not found"
        p.DELETED[int(uid)] = int(time.time() * 1000)
    p.save()
    return True, "ok"


def recent_deletions(max_age_ms=1800000):
    """Pokemon removed recently, so the inventory delta can keep confirming the deletion."""
    p = current()
    cutoff = int(time.time() * 1000) - max_age_ms
    with _lock:
        stale = [u for u, ts in p.DELETED.items() if ts < cutoff]
        for u in stale:
            p.DELETED.pop(u, None)
        return sorted(p.DELETED.items())


def pokemon_full():
    p = current()
    return len(p.CAUGHT) + len(p.EGGS) >= p.MAX_POKEMON


def buy_storage(kind):
    p = current()
    step = _cfg.get(
        "storage",
        "pokemon_upgrade_step" if kind == "pokemon" else "items_upgrade_step",
        cast=int,
    )
    cost = _cfg.get(
        "storage",
        "pokemon_upgrade_cost" if kind == "pokemon" else "items_upgrade_cost",
        cast=int,
    )
    cap = _cfg.get(
        "storage",
        "max_pokemon_limit" if kind == "pokemon" else "max_items_limit",
        cast=int,
    )
    with _lock:
        cur = p.MAX_POKEMON if kind == "pokemon" else p.MAX_ITEMS
        if cur + step > cap:
            return False, f"already at the maximum ({cap})", cur
        if p.COINS < cost:
            return False, f"need {cost} PokeCoins, you have {p.COINS}", cur
        p.COINS -= cost
        if kind == "pokemon":
            p.MAX_POKEMON = cur + step
            new = p.MAX_POKEMON
        else:
            p.MAX_ITEMS = cur + step
            new = p.MAX_ITEMS
    p.save()
    return True, f"+{step} space for {cost} coins", new


def storage():
    p = current()
    with _lock:
        return {
            "max_pokemon": p.MAX_POKEMON,
            "max_items": p.MAX_ITEMS,
            "pokemon_used": len(p.CAUGHT),
            "items_used": sum(p.BAG.values()),
            "coins": p.COINS,
            "stardust": p.STARDUST,
        }


# ==============================================================================
# Pokédex Mechanics
# ==============================================================================

def pokedex_saw(pokemon_id):
    p = current()
    with _lock:
        e = p.POKEDEX.setdefault(int(pokemon_id), [0, 0])
        e[0] += 1
    p.save()


def pokedex_caught(pokemon_id):
    p = current()
    with _lock:
        e = p.POKEDEX.setdefault(int(pokemon_id), [0, 0])
        new_entry = e[1] == 0
        e[1] += 1
        if e[0] < e[1]:
            e[0] = e[1]          # caught implies seen
    p.save()
    if new_entry:
        record_badge_progress("BADGE_POKEDEX_ENTRIES", 1)


def pokedex():
    with _lock:
        return sorted((pid, v[0], v[1]) for pid, v in current().POKEDEX.items())


# ==============================================================================
# Eggs, Incubation & Walking Mechanics
# ==============================================================================

def km_walked():
    return float(current().STATS.get("km_walked", 0.0) or 0.0)


def add_distance(lat, lng):
    """Accumulate real walked distance from successive GPS fixes."""
    p = current()
    prev = p.LAST_POS
    p.LAST_POS = (lat, lng)
    if not prev:
        return 0.0
    dlat = (lat - prev[0]) * 111320.0
    dlng = (lng - prev[1]) * 111320.0 * math.cos(math.radians((lat + prev[0]) / 2.0))
    metres = math.hypot(dlat, dlng)
    lo = _cfg.get("eggs", "min_step_m", cast=float)
    hi = _cfg.get("eggs", "max_step_m", cast=float)
    if metres < lo or metres > hi:
        return 0.0
    with _lock:
        p.STATS["km_walked"] = km_walked() + metres / 1000.0
    record_badge_progress("BADGE_TRAVEL_KM", metres / 1000.0)
    return metres


def eggs():
    with _lock:
        return [dict(e) for e in current().EGGS]


def incubators():
    with _lock:
        return [dict(i) for i in current().INCUBATORS]


def give_egg(target_km):
    """A new egg from a PokeStop. Returns None if the egg bag is full."""
    p = current()
    with _lock:
        if len(p.EGGS) >= _cfg.get("eggs", "max_eggs", cast=int):
            return None
        uid = _fresh_uid(
            {c["uid"] for c in p.CAUGHT}
            | {e["uid"] for e in p.EGGS}
            | set(p.DELETED)
        )
        egg = {
            "uid": uid,
            "target_km": float(target_km),
            "start_km": 0.0,
            "incubator": "",
        }
        p.EGGS.append(egg)
    p.save()
    return dict(egg)


def use_incubator(incubator_id, egg_uid):
    """Put an egg in an incubator."""
    p = current()
    with _lock:
        inc = next((i for i in p.INCUBATORS if i["id"] == incubator_id), None)
        if inc is None:
            return 2, None
        egg = next((e for e in p.EGGS if e["uid"] == egg_uid), None)
        if egg is None:
            return (4, None) if any(c["uid"] == egg_uid for c in p.CAUGHT) else (3, None)
        if inc.get("egg"):
            return 5, None
        if egg.get("incubator"):
            return 6, None
        if inc.get("uses", -1) == 0:
            return 7, None
        start = km_walked()
        egg["start_km"] = start
        egg["incubator"] = incubator_id
        inc.update(egg=egg_uid, start_km=start, target_km=start + egg["target_km"])
    p.save()
    return 1, dict(inc)


def check_hatches(pick_species):
    """Hatch any egg that has covered its distance."""
    p = current()
    done = []
    with _lock:
        walked = km_walked()
        for egg in list(p.EGGS):
            if not egg.get("incubator"):
                continue
            if walked - egg["start_km"] < egg["target_km"]:
                continue
            tier = egg["target_km"]
            pid, cp = pick_species(tier)
            uid = _fresh_uid(
                {c["uid"] for c in p.CAUGHT}
                | {e["uid"] for e in p.EGGS}
                | set(p.DELETED)
            )
            p.CAUGHT.append(
                {
                    "uid": uid,
                    "pokemon_id": pid,
                    "cp": cp,
                    "caught_ms": int(time.time() * 1000),
                }
            )
            p.EGGS.remove(egg)
            for i in p.INCUBATORS:
                if i["id"] == egg["incubator"]:
                    i.update(egg=0, start_km=0.0, target_km=0.0)
                    if i.get("uses", -1) > 0:
                        i["uses"] -= 1
            xp = int(tier) * 100
            candy = 2 + int(tier)
            dust = int(tier) * 100
            rec = {
                "uid": uid,
                "pokemon_id": pid,
                "cp": cp,
                "km": tier,
                "xp": xp,
                "candy": candy,
                "stardust": dust,
                "egg_uid": egg["uid"],
            }
            p.HATCHED.append(rec)
            done.append(rec)
    if done:
        p.save()
        record_badge_progress("BADGE_HATCHED_TOTAL", len(done))
    return done


def drain_hatched():
    """Hand the client the eggs that hatched since it last asked."""
    p = current()
    with _lock:
        out, p.HATCHED = list(p.HATCHED), []
    if out:
        p.save()
    return out


# ==============================================================================
# Temporary Buffs, Items & Fort Modifiers
# ==============================================================================

def apply_item(item_id, minutes):
    """Start a Lucky Egg / Incense."""
    p = current()
    now = int(time.time() * 1000)
    with _lock:
        p.APPLIED = [a for a in p.APPLIED if a.get("expires_ms", 0) > now]
        if any(a["item"] == int(item_id) for a in p.APPLIED):
            return 2, None
    if not take_item(int(item_id), 1):
        return 3, None
    entry = {
        "item": int(item_id),
        "applied_ms": now,
        "expires_ms": now + int(minutes * 60000),
    }
    with _lock:
        p.APPLIED.append(entry)
    p.save()
    return 1, dict(entry)


def applied_items():
    p = current()
    now = int(time.time() * 1000)
    with _lock:
        p.APPLIED = [a for a in p.APPLIED if a.get("expires_ms", 0) > now]
        return [dict(a) for a in p.APPLIED]


def item_active(item_id):
    return any(a["item"] == int(item_id) for a in applied_items())


def xp_multiplier():
    """A Lucky Egg doubles everything you earn while it burns."""
    return 2 if item_active(301) else 1


def add_fort_modifier(fort_id, item_id, minutes, by):
    """Attach a Lure to a PokeStop."""
    now = int(time.time() * 1000)
    with _lock:
        cur = FORT_MODIFIERS.get(fort_id)
        if cur and cur.get("expires_ms", 0) > now:
            return 2, None
    if not take_item(int(item_id), 1):
        return 4, None
    mod = {"item": int(item_id), "expires_ms": now + int(minutes * 60000), "by": by}
    with _lock:
        FORT_MODIFIERS[fort_id] = mod
    return 1, dict(mod)


def fort_modifier(fort_id):
    now = int(time.time() * 1000)
    with _lock:
        m = FORT_MODIFIERS.get(fort_id)
        if not m:
            return None
        if m.get("expires_ms", 0) <= now:
            FORT_MODIFIERS.pop(fort_id, None)
            return None
        return dict(m)


def lured_forts():
    now = int(time.time() * 1000)
    with _lock:
        for fid in [
            k for k, m in FORT_MODIFIERS.items() if m.get("expires_ms", 0) <= now
        ]:
            FORT_MODIFIERS.pop(fid, None)
        return {k: dict(v) for k, v in FORT_MODIFIERS.items()}


def use_berry(encounter_id, mult):
    """Remember that a berry is in effect for this encounter."""
    current().BERRIES[int(encounter_id)] = float(mult)


def berry_mult(encounter_id, consume=False):
    p = current()
    m = p.BERRIES.get(int(encounter_id), 1.0)
    if consume:
        p.BERRIES.pop(int(encounter_id), None)
    return m


# ==============================================================================
# Shared World State Data & Spawns
# ==============================================================================

GYMS = {}                          # fort_id -> [{uid, pokemon_id, cp, trainer, team}]
BATTLES = {}                       # battle_id -> live battle state
SPAWNS = {}                        # transient
DESPAWNED = {}                     # encounter_id -> expiry_ms
FORT_MODIFIERS = {}                # fort_id -> {item, expires_ms, by}
RAID = {"on": False, "pokemon_id": 150, "cp": 3000, "trainer": "raid"}
BONUS_SPAWNS = {}                  # username -> [ {eid,pid,cp,lat,lng,expires_ms} ]
_MAX_SPAWNS = 4000


def remember_spawn(encounter_id, pokemon_id, lat, lng, cp, spawn_id, expires_ms):
    with _lock:
        if len(SPAWNS) >= _MAX_SPAWNS:
            for k in sorted(SPAWNS, key=lambda k: SPAWNS[k]["expires_ms"])[: _MAX_SPAWNS // 2]:
                SPAWNS.pop(k, None)
        SPAWNS[encounter_id] = {
            "pokemon_id": pokemon_id,
            "lat": lat,
            "lng": lng,
            "cp": cp,
            "spawn_id": spawn_id,
            "expires_ms": expires_ms,
        }


def get_spawn(encounter_id):
    with _lock:
        s = SPAWNS.get(encounter_id)
        return dict(s) if s else None


def remove_spawn(encounter_id):
    with _lock:
        SPAWNS.pop(encounter_id, None)


def mark_despawned(encounter_id, until_ms):
    with _lock:
        DESPAWNED[encounter_id] = until_ms
        if len(DESPAWNED) > 5000:
            now = int(time.time() * 1000)
            for k in [k for k, v in DESPAWNED.items() if v < now]:
                DESPAWNED.pop(k, None)


def is_despawned(encounter_id):
    with _lock:
        exp = DESPAWNED.get(encounter_id)
        if exp is None:
            return False
        if exp < int(time.time() * 1000):
            DESPAWNED.pop(encounter_id, None)
            return False
        return True


# ==============================================================================
# Shared Raids & Bonus Spawns
# ==============================================================================

def load_raid():
    global RAID
    try:
        with open(RAID_FILE, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        RAID.update(
            {
                "on": bool(d.get("on", False)),
                "pokemon_id": int(d.get("pokemon_id", 150) or 150),
                "cp": int(d.get("cp", 3000) or 3000),
                "trainer": str(d.get("trainer", "raid") or "raid"),
            }
        )
    except (OSError, ValueError, TypeError):
        pass
    return dict(RAID)


def save_raid():
    try:
        tmp = RAID_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(RAID, fh, indent=1)
        os.replace(tmp, RAID_FILE)
    except OSError:
        pass


def set_raid(on=None, pokemon_id=None, cp=None, trainer=None):
    """Turn raid mode on/off."""
    sent_home = 0
    with _lock:
        if on is not None:
            RAID["on"] = bool(on)
        if pokemon_id is not None:
            RAID["pokemon_id"] = max(1, min(151, int(pokemon_id)))
        if cp is not None:
            RAID["cp"] = max(10, min(9999, int(cp)))
        if trainer is not None:
            RAID["trainer"] = str(trainer)[:16] or "raid"
        if RAID["on"]:
            sent_home = sum(len(v) for v in GYMS.values())
            GYMS.clear()
    save_gyms()
    save_raid()
    return dict(RAID), sent_home


def raid():
    with _lock:
        return dict(RAID)


def _raid_member(fort_id):
    uid = (abs(hash(("raid", fort_id))) & 0x3FFFFFFFFFFFFFFF) | 1
    return {
        "uid": uid,
        "pokemon_id": int(RAID["pokemon_id"]),
        "cp": int(RAID["cp"]),
        "trainer": RAID.get("trainer", "raid"),
        "team": 0,
        "raid": True,
        "deployed_ms": int(time.time() * 1000),
    }


def is_raid_uid(fort_id, uid):
    return RAID["on"] and _raid_member(fort_id)["uid"] == uid


def add_bonus_spawn(username, eid, pid, cp, lat, lng, expires_ms):
    """A one-off wild Pokemon placed for ONE trainer."""
    with _lock:
        lst = BONUS_SPAWNS.setdefault(username, [])
        lst.append(
            {
                "eid": eid,
                "pid": pid,
                "cp": cp,
                "lat": lat,
                "lng": lng,
                "expires_ms": expires_ms,
            }
        )
        del lst[:-10]


def bonus_spawns(username):
    now = int(time.time() * 1000)
    with _lock:
        lst = [b for b in BONUS_SPAWNS.get(username, []) if b["expires_ms"] > now]
        BONUS_SPAWNS[username] = lst
        return [dict(b) for b in lst]


def drop_bonus_spawn(username, eid):
    with _lock:
        lst = BONUS_SPAWNS.get(username, [])
        BONUS_SPAWNS[username] = [b for b in lst if b["eid"] != eid]


# ==============================================================================
# Shared Gyms Operations
# ==============================================================================

def _defender_minutes():
    return _cfg.get("gyms", "defender_minutes", env="DEFENDER_MINUTES", cast=float)


def _defender_coins():
    return _cfg.get("gyms", "defender_coins", env="DEFENDER_COINS", cast=int)


def _max_defenders():
    return _cfg.get("gyms", "max_defenders", cast=int)


def save_gyms():
    try:
        tmp = GYMS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"gyms": GYMS}, fh, indent=1)
        os.replace(tmp, GYMS_FILE)
    except OSError:
        pass


def load_gyms():
    try:
        with open(GYMS_FILE, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        GYMS.clear()
        GYMS.update(
            {k: v for k, v in (d.get("gyms") or {}).items() if isinstance(v, list)}
        )
        return True
    except (OSError, ValueError):
        pass
    try:                       # migrate gyms out of old single-player save
        with open(SAVE_FILE, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        GYMS.update(
            {k: v for k, v in (d.get("gyms") or {}).items() if isinstance(v, list)}
        )
        if GYMS:
            save_gyms()
    except (OSError, ValueError):
        pass
    return False


def my_team():
    """The team this trainer picked in game."""
    t = current().TEAM
    return t if t else _cfg.get("gyms", "team", env="TEAM", cast=int)


def set_team(team):
    """SetPlayerTeam."""
    p = current()
    with _lock:
        if p.TEAM:
            return 2, p.TEAM
        p.TEAM = max(1, min(3, int(team)))
        out = p.TEAM
    p.save()
    return 1, out


def gym_members(fort_id):
    with _lock:
        if RAID["on"]:
            return [_raid_member(fort_id)]
        return list(GYMS.get(fort_id, []))


def gym_team(fort_id):
    """Which team holds this gym (0 = neutral/white)."""
    ms = gym_members(fort_id)
    return ms[0].get("team", 0) if ms else 0


def is_deployed(uid):
    with _lock:
        return any(m["uid"] == uid for ms in GYMS.values() for m in ms)


def deploy(fort_id, uid, trainer=None, team=None):
    p = current()
    trainer = trainer or p.username
    team = team if team is not None else my_team()
    c = get_caught(uid)
    if not c:
        return False, "unknown pokemon"
    with _lock:
        members = GYMS.setdefault(fort_id, [])
        if members and members[0].get("team", team) != team:
            return False, "held by another team"
        if any(m["uid"] == uid for m in members):
            return False, "already deployed"
        if len(members) >= _max_defenders():
            return False, "gym full"
        members.append(
            {
                "uid": uid,
                "pokemon_id": c["pokemon_id"],
                "cp": c["cp"],
                "trainer": trainer,
                "team": team,
                "owner": p.username,
                "deployed_ms": int(time.time() * 1000),
            }
        )
    save_gyms()
    return True, "ok"


def recall(fort_id, uid):
    with _lock:
        members = GYMS.get(fort_id, [])
        n = len(members)
        GYMS[fort_id] = [m for m in members if m["uid"] != uid]
        changed = n != len(GYMS[fort_id])
        if not GYMS[fort_id]:
            GYMS.pop(fort_id, None)
    save_gyms()
    return changed


def clear_gym(fort_id):
    """Every defender is knocked out -- the gym goes neutral."""
    with _lock:
        GYMS.pop(fort_id, None)
    save_gyms()


def gym_guard(fort_id):
    ms = gym_members(fort_id)
    if not ms:
        return None
    best = max(ms, key=lambda m: m.get("cp", 0))
    return best["pokemon_id"], best["cp"], 500 * len(ms)


def collect_gym_returns():
    """Bring home any Pokemon that has served its shift and pay its coins."""
    now = int(time.time() * 1000)
    cutoff = _defender_minutes() * 60_000
    coins = _defender_coins()
    faint = _cfg.get("pokemon", "faint_after_gym", cast=bool)
    returned = []
    with _lock:
        for fid in list(GYMS):
            keep = []
            for m in GYMS.get(fid, []):
                dep = m.get("deployed_ms")
                if dep is None:
                    m["deployed_ms"] = now
                    keep.append(m)
                elif now - dep >= cutoff:
                    returned.append(
                        (fid, m["pokemon_id"], coins, m.get("owner"), m["uid"])
                    )
                else:
                    keep.append(m)
            if keep:
                GYMS[fid] = keep
            else:
                GYMS.pop(fid, None)
    mine = []
    if returned:
        save_gyms()
        me = current()
        for fid, pid, c, owner, uid in returned:
            if owner and owner != me.username:
                continue
            with _lock:
                me.COINS += c
                if faint:
                    for pk in me.CAUGHT:
                        if pk["uid"] == uid:
                            pk["stamina"] = 0
                            break
            mine.append((fid, pid, c))
        if mine:
            me.save()
    return mine


def time_left(fort_id, uid):
    for m in gym_members(fort_id):
        if m["uid"] == uid:
            dep = m.get("deployed_ms") or 0
            return max(0, int(_defender_minutes() * 60 - (time.time() - dep / 1000)))
    return 0


# ==============================================================================
# Initialization
# ==============================================================================

load_gyms()
load_raid()
