"""
settings.json -- the one file you edit by hand to tune how the game plays.

Written next to the .exe on first run, complete with a built-in explanation of
every value. Hot-reloaded by mtime, so saving the file applies within a few
seconds; no restart needed.

Precedence: environment variable > settings.json > built-in default. (The env
vars stayed supported so older shortcuts/batch files keep working.)

Things the World Manager UI owns -- placed stops/gyms (places.json) and the live
event (events.json) -- deliberately live elsewhere, so hand-edits here are never
fighting the web UI.
"""
import json
import os
import time
import sys
import threading

def _data_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

SETTINGS_FILE = os.path.join(_data_dir(), "settings.json")

# What a PokeStop spin drops. Each entry rolls independently with its own
# chance; "min"/"max" bound the count when it does. Keep the ids within
# admin.GIVEABLE -- validated_pokestop_loot enforces that.
DEFAULT_POKESTOP_LOOT = [
    {"item": 1,   "chance": 1.00, "min": 1, "max": 3},  # Poke Ball
    {"item": 101, "chance": 1.00, "min": 1, "max": 2},  # Potion
    {"item": 201, "chance": 1.00, "min": 1, "max": 1},  # Revive
    {"item": 2,   "chance": 0.30, "min": 1, "max": 2},  # Great Ball
    {"item": 3,   "chance": 0.10, "min": 1, "max": 1},  # Ultra Ball
    {"item": 701, "chance": 0.35, "min": 1, "max": 2},  # Razz Berry
]

# Every tunable, with the shape the file is written in. Keep the comments here in
# sync with the "_readme" block below -- that's what the user actually reads.
DEFAULTS = {
    "catching": {
        "xp_per_catch": 100,
        "candy_per_catch": 3,
        "stardust_per_catch": 100,
        "xp_nice_throw": 500,
        "xp_great_throw": 1000,
        "xp_excellent_throw": 2000,
        "xp_curveball": 10,
        "base_catch_rate": 0.55,    # chance a Poke Ball holds a weak Pokemon
        "flee_chance": 0.12,        # chance it runs off after breaking out
        "razz_capture_mult": 1.8,   # how much a Razz Berry helps
        "razz_flee_mult": 0.4,      # ...and how much less likely it is to flee
    },
    "pokestops": {
        "per_l15_cell": 1,          # PokeStops per level-15 cell (~300m across)
        "max_per_request": 200,     # safety cap on one GetMapObjects batch
        "xp_per_spin": 50,
        "cooldown_minutes": 5,
        "min_items_per_spin": 5,        # a spin never gives fewer items than this
        "max_items_per_spin": 8,
        "loot": DEFAULT_POKESTOP_LOOT,  # what a spin drops (item/chance/min/max)
    },
    "gyms": {
        "chance_per_l15_cell": 0.25,   # ~1 gym per 4 level-15 cells
        "team": 1,
        "defender_minutes": 15,
        "defender_coins": 20,
        "max_defenders": 6,
    },
    "spawns": {
        "per_l15_cell": 20,         # wild Pokemon per level-15 cell (~300m across)
        "max_per_request": 120,     # HARD cap per map refresh. The phone has to
                                    # draw every one of these; ~180 was enough to
                                    # crash the 2016 client on a real device.
        "refresh_minutes": 15,
        "how_many_near_you": 5,
        "nearest_distance_m": 25,
        "farthest_distance_m": 65,
        "min_cp": 100,
        "max_cp": 1200,
        "allow_legendaries": False,
    },
    "eggs": {
        "max_eggs": 9,              # egg bag size
        "drop_chance": 0.35,        # chance a PokeStop spin gives an egg
        "min_step_m": 1.0,          # GPS moves smaller than this are jitter
        "max_step_m": 120.0,        # bigger than this is a teleport: doesn't count
    },
    "boosts": {
        "lucky_egg_minutes": 30,    # double XP while it burns
        "incense_minutes": 30,      # extra wild Pokemon around you
        "incense_extra_spawns": 6,  # how many more, on top of the usual
        "lure_minutes": 30,         # a Lure on a PokeStop
        "lure_extra_spawns": 4,     # extra Pokemon around a lured stop
    },
    "pokemon": {
        "powerup_candy": 1,
        "powerup_stardust": 200,
        "powerup_cp_gain": 12,
        "evolve_xp": 500,
        "transfer_candy": 1,
        "faint_after_gym": True,
    },
    "battles": {
        "attack_damage": 12,
        "special_damage": 30,
        "defender_damage": 8,
        "win_xp": 1000,
    },
    "storage": {
        "pokemon_upgrade_step": 50,
        "pokemon_upgrade_cost": 200,
        "max_pokemon_limit": 1000,
        "items_upgrade_step": 50,
        "items_upgrade_cost": 200,
        "max_items_limit": 1000,
    },
    "server": {
        "world_manager_port": 8080,
    },
}

_README = [
    "==================== POKEMON GO SERVER SETTINGS ====================",
    "Edit the numbers below, save the file, and they apply within a few",
    "seconds. You do NOT need to restart the server.",
    "",
    "To reset everything: delete this file. It will be recreated.",
    "",
    "catching:",
    "   xp_per_catch ......... XP for catching anything at all",
    "   xp_nice_throw ........ bonus XP for a Nice throw",
    "   xp_great_throw ....... bonus XP for a Great throw",
    "   xp_excellent_throw ... bonus XP for an Excellent throw",
    "   xp_curveball ......... small extra bonus for a curveball",
    "",
    "pokestops:",
    "   xp_per_spin .......... XP each time you spin a stop",
    "   cooldown_minutes ..... how long a stop stays purple before reuse",
    "   min/max_items_per_spin  how many items a spin gives",
    "   loot ................. what a spin can drop: a list of",
    "                          {item, chance, min, max} entries; item ids are",
    "                          the Shop panel ones, chance is 0-1, and a spin",
    "                          always gives between min/max_items_per_spin items",
    "",
    "gyms:",
    "   team ................. your team: 1=Blue, 2=Red, 3=Yellow",
    "   defender_minutes ..... how long a Pokemon guards before coming home",
    "   defender_coins ....... PokeCoins paid when it returns",
    "   max_defenders ........ how many Pokemon fit in one gym",
    "",
    "spawns:",
    "   refresh_minutes ...... how often all wild Pokemon change",
    "   how_many_near_you .... wild Pokemon around you (0-60)",
    "   nearest/farthest_distance_m   how spread out they are, in metres",
    "   min_cp / max_cp ...... how strong wild Pokemon are",
    "",
    " catching",
    "   base_catch_rate ...... Pokemon can now BREAK OUT. Raise towards 1.0 to",
    "                          make catching easier, lower it to make it a fight.",
    "                          Strong Pokemon resist more; Great/Ultra Balls,",
    "                          good throws and Razz Berries all help.",
    "   flee_chance .......... chance it runs away after breaking out",
    "",
    " eggs",
    "   drop_chance .......... how often a PokeStop hands you an egg (0-1)",
    "   max_step_m ........... distance only counts if you really walked it --",
    "                          a GPS jump bigger than this is ignored, so you",
    "                          cannot hatch an egg by teleporting",
    "   per_l15_cell ......... wild Pokemon in each level-15 cell (~300m across).",
    "                          The client asks for several cells at once, so this",
    "                          multiplies -- lower it if the map gets sluggish.",
    "   max_per_request ...... hard cap per map refresh, so a big per_l17_cell",
    "                          cannot produce a batch the client chokes on",
    "   allow_legendaries .... true = Mewtwo etc. can appear in the wild",
    "",
    "pokemon:  (powering up, evolving, transferring)",
    "   powerup_candy / powerup_stardust   cost of one power-up",
    "   powerup_cp_gain ...... % CP added per power-up",
    "   evolve_xp ............ XP for evolving one Pokemon",
    "   transfer_candy ....... candy you get for transferring",
    "   faint_after_gym ...... true = gym defenders come home with 0 HP",
    "",
    "battles:  (attacking a Gym)",
    "   attack_damage ........ damage your normal tap does",
    "   special_damage ....... damage your charged move does",
    "   defender_damage ...... damage the gym Pokemon does back to you",
    "   win_xp ............... XP for taking down a whole Gym",
    "",
    "storage:  (bought from the World Manager with gym PokeCoins)",
    "   pokemon_upgrade_step/cost  space added per purchase, and its price",
    "   items_upgrade_step/cost    same for the item bag",
    "   max_pokemon_limit / max_items_limit   the ceiling you can buy up to",
    "",
    "server:",
    "   world_manager_port ... the http://127.0.0.1:PORT control panel",
    "====================================================================",
]

_lock = threading.Lock()
_cache = {"mtime": None, "data": None, "checked": 0.0}


def _merged(user):
    out = {k: dict(v) for k, v in DEFAULTS.items()}
    for section, vals in (user or {}).items():
        if section.startswith("_") or section not in out or not isinstance(vals, dict):
            continue
        for k, v in vals.items():
            if not k.startswith("_") and k in out[section]:
                out[section][k] = v
    out["pokestops"]["loot"] = validated_pokestop_loot(out["pokestops"]["loot"])
    return out


def _write_default_file():
    try:
        doc = {"_readme": _README}
        doc.update({k: dict(v) for k, v in DEFAULTS.items()})
        with open(SETTINGS_FILE, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2)
    except OSError:
        pass


# How often we're willing to stat settings.json. get() is called hundreds of
# times while building ONE map response, and stat'ing the file every time cost
# ~590 syscalls and a third of the total time. A second of staleness is
# imperceptible for a hot-reload; the saving is not.
_RECHECK_SEC = 1.0


def all():
    """The full settings dict, hot-reloaded when settings.json changes."""
    with _lock:
        now = time.monotonic()
        if _cache["data"] is not None and now - _cache.get("checked", 0.0) < _RECHECK_SEC:
            return _cache["data"]
        _cache["checked"] = now
        try:
            m = os.path.getmtime(SETTINGS_FILE)
        except OSError:
            _write_default_file()               # first run: create it for the user
            try:
                m = os.path.getmtime(SETTINGS_FILE)
            except OSError:
                m = None
        if _cache["data"] is None or m != _cache["mtime"]:
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as fh:
                    user = json.load(fh)
            except (OSError, ValueError):
                user = {}
            _cache["data"] = _merged(user)
            _cache["mtime"] = m
        return _cache["data"]


def get(section, key, env=None, cast=None):
    """One setting. An environment variable of the same name still wins, so old
    shortcuts keep working."""
    data = all()            # always first, so settings.json is created even when
                            # an env var would short-circuit the lookup below
    if env:
        raw = os.environ.get(env)
        if raw not in (None, ""):
            try:
                return (cast or type(DEFAULTS[section][key]))(raw)
            except (TypeError, ValueError):
                pass
    val = data.get(section, {}).get(key, DEFAULTS[section][key])
    if cast:
        try:
            return cast(val)
        except (TypeError, ValueError):
            return DEFAULTS[section][key]
    return val


def validated_pokestop_loot(value):
    """Sanitize a pokestops.loot table.

    Each entry must be {"item": <id from admin.GIVEABLE>, "chance": 0..1,
    "min": >= 1, "max": >= min}. Anything that does not parse -- a missing
    entry, an unknown id, an out-of-range chance, min > max -- falls back to
    the default table, so a bad hand-edit can never break spins.
    """
    if not isinstance(value, list) or not value:
        return [dict(e) for e in DEFAULT_POKESTOP_LOOT]
    from admin import GIVEABLE
    valid_ids = {iid for iid, _ in GIVEABLE}
    out = []
    for e in value:
        if not isinstance(e, dict):
            return [dict(x) for x in DEFAULT_POKESTOP_LOOT]
        try:
            item, chance, lo, hi = int(e["item"]), float(e["chance"]), int(e["min"]), int(e["max"])
        except (KeyError, TypeError, ValueError):
            return [dict(x) for x in DEFAULT_POKESTOP_LOOT]
        if item not in valid_ids or not 0.0 <= chance <= 1.0 or lo < 1 or hi < lo:
            return [dict(x) for x in DEFAULT_POKESTOP_LOOT]
        out.append({"item": item, "chance": chance, "min": lo, "max": hi})
    return out


def roll_pokestop_loot(rng):
    """Roll the effective pokestops.loot table with `rng`.

    Returns [(item_id, count)] in table order; chance 1.0 entries always drop
    and chance 0.0 never do. Per-spin min/max and bag limits are the caller's.
    """
    awards = []
    for e in all()["pokestops"]["loot"]:
        if rng.random() < e["chance"]:
            awards.append((e["item"], rng.randint(e["min"], e["max"])))
    return awards


def save_pokestop_loot(table):
    """Atomically persist a validated pokestops.loot table into settings.json.

    Returns the sanitized table on success, or None when `table` is invalid --
    in which case settings.json is left untouched, so a failed save can never
    clobber the current table. The write is atomic (temp file + rename), so a
    crash mid-save cannot corrupt the file either.
    """
    sanitized = validated_pokestop_loot(table)
    if sanitized != table:
        return None
    with _lock:
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError):
            doc = {"_readme": list(_README)}
            doc.update({k: dict(v) for k, v in DEFAULTS.items()})
        if not isinstance(doc, dict):
            doc = {}
        pokestops = doc.get("pokestops")
        if not isinstance(pokestops, dict):
            pokestops = dict(DEFAULTS["pokestops"])
            doc["pokestops"] = pokestops
        pokestops["loot"] = sanitized
        tmp = SETTINGS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2)
        os.replace(tmp, SETTINGS_FILE)
        _cache.update(data=None, mtime=None, checked=0.0)
    return sanitized
