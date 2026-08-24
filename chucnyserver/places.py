"""
Hand-placed world objects: PokeStops, Gyms and Pokemon spawns.

The map is normally generated procedurally around wherever the player stands.
This module stores objects the user has PLACED at specific real-world coordinates
from the World Manager web UI (admin.py), so you can build your own neighbourhood
-- a stop on your porch, a gym at the park, a Snorlax on the couch.

Stored in places.json next to this module, hot-reloaded by mtime so edits from the
UI take effect on the next map refresh without restarting the server.
"""
import json
import os
import threading
import time

import sys as _sys

def _data_dir():
    """Where user-editable/save files live: next to the .exe when frozen (so they
    are findable and survive a rebuild), else next to the source."""
    if getattr(_sys, "frozen", False):
        return os.path.dirname(_sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

HERE = _data_dir()
PLACES_FILE = os.path.join(HERE, "places.json")

_lock = threading.RLock()
_cache = {"mtime": None, "data": None}

DEFAULT = {
    # Two independent switches. Forts default OFF because you place your own
    # PokeStops/Gyms in the World Manager; wild Pokemon still spawn randomly so
    # there's always something to catch as you walk.
    "procedural_forts": False,   # auto-generate random PokeStops/Gyms
    "procedural_spawns": True,   # auto-generate random wild Pokemon
    "forts": [],            # {id, lat, lng, kind: "stop"|"gym", name, image}
    "spawns": [],           # {id, lat, lng, pokemon_id (0=random), name}
}


def _read():
    try:
        with open(PLACES_FILE, "r", encoding="utf-8") as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return dict(DEFAULT)
    out = dict(DEFAULT)
    out.update(d if isinstance(d, dict) else {})
    for k in ("forts", "spawns"):
        if not isinstance(out.get(k), list):
            out[k] = []
    return out


def get():
    """Current places, hot-reloaded when places.json changes on disk."""
    with _lock:
        try:
            m = os.path.getmtime(PLACES_FILE)
        except OSError:
            m = None
        if _cache["data"] is None or m != _cache["mtime"]:
            _cache["data"] = _read()
            _cache["mtime"] = m
        d = _cache["data"]
        # back-compat: an older places.json only had a single "procedural" flag
        legacy = d.get("procedural")
        pf = d.get("procedural_forts", False if legacy is None else bool(legacy))
        ps = d.get("procedural_spawns", True if legacy is None else bool(legacy))
        return {"procedural_forts": bool(pf), "procedural_spawns": bool(ps),
                "forts": list(d.get("forts", [])),
                "spawns": list(d.get("spawns", []))}


def _write(d):
    with _lock:
        with open(PLACES_FILE, "w", encoding="utf-8") as fh:
            json.dump(d, fh, indent=1)
        _cache["data"] = None          # force reload on next get()


def _new_id(prefix):
    return f"{prefix}{int(time.time() * 1000) % 100000000:08d}"


def _clamp_ll(lat, lng):
    return max(-90.0, min(90.0, float(lat))), max(-180.0, min(180.0, float(lng)))


def add_fort(lat, lng, kind="stop", name="", image=""):
    lat, lng = _clamp_ll(lat, lng)
    kind = "gym" if str(kind).lower() == "gym" else "stop"
    d = _read()
    d.setdefault("forts", []).append({
        "id": _new_id("GYM" if kind == "gym" else "FORT"),
        "lat": lat, "lng": lng, "kind": kind,
        "name": (name or ("My Gym" if kind == "gym" else "My PokeStop"))[:40],
        # Photo shown on the stop/gym. Either a full http(s) URL, or the name of
        # a file you dropped in the photos/ folder next to the server.
        "image": (image or "").strip()[:300],
    })
    _write(d)
    return d["forts"][-1]


def add_spawn(lat, lng, pokemon_id, name=""):
    """pokemon_id 0 = a RANDOM Pokemon each time (a permanent spawn point)."""
    lat, lng = _clamp_ll(lat, lng)
    try:
        pid = max(0, min(151, int(pokemon_id)))      # 0 => random each refresh
    except (TypeError, ValueError):
        pid = 0
    d = _read()
    d.setdefault("spawns", []).append({
        "id": _new_id("SPAWN"), "lat": lat, "lng": lng,
        "pokemon_id": pid, "name": (name or "")[:40],
    })
    _write(d)
    return d["spawns"][-1]


def remove(obj_id):
    d = _read()
    before = len(d.get("forts", [])) + len(d.get("spawns", []))
    d["forts"] = [f for f in d.get("forts", []) if f.get("id") != obj_id]
    d["spawns"] = [s for s in d.get("spawns", []) if s.get("id") != obj_id]
    _write(d)
    return before != len(d["forts"]) + len(d["spawns"])


def clear(what="all"):
    d = _read()
    if what in ("all", "forts"):
        d["forts"] = []
    if what in ("all", "spawns"):
        d["spawns"] = []
    _write(d)
    return d


def set_procedural(on, what="both"):
    """Toggle auto-generated forts and/or wild spawns."""
    d = _read()
    if what in ("both", "forts"):
        d["procedural_forts"] = bool(on)
    if what in ("both", "spawns"):
        d["procedural_spawns"] = bool(on)
    d.pop("procedural", None)              # drop the legacy single flag
    _write(d)
    return d
