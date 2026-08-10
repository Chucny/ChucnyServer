"""
Live event / spawn configuration for the PoGO private server.

A tiny JSON file (events.json, next to this module) holds the current "event"
settings — spawn density, which species appear, CP range, shiny rate, etc. It is
hot-reloaded on every read (by mtime) so changes made from the web control panel
(admin.py) take effect immediately, no server restart needed.

protocol.build_get_map_objects_response() calls get() on every map refresh.
"""
import json
import os
import threading

import sys as _sys

def _data_dir():
    """Where user-editable/save files live: next to the .exe when frozen (so they
    are findable and survive a rebuild), else next to the source."""
    if getattr(_sys, "frozen", False):
        return os.path.dirname(_sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

HERE = _data_dir()
EVENTS_FILE = os.path.join(HERE, "events.json")

DEFAULTS = {
    "event_name": "Normal",
    "spawn_density": 5,         # wild Pokemon clustered around the player.
                            # Real PoGO shows a handful; 60 is the hard cap.
                            # (Cells around you each add ~1 more, spread out.)
    "species_mode": "all",      # "all" | "list" | "single"
    "species_list": [1, 4, 7, 25, 133, 143],
    "single_species": 25,       # Pikachu
    "min_cp": 100,
    "max_cp": 1200,
    "shiny_rate": 0.0,          # 0..1  (NOTE: the 0.29 client can't render shinies)
}

# One-click events for the menu.
PRESETS = {
    "Normal":           {"event_name": "Normal", "spawn_density": 5, "species_mode": "all",
                         "min_cp": 100, "max_cp": 1200, "shiny_rate": 0.0},
    "Swarm":      {"event_name": "Swarm", "spawn_density": 25, "species_mode": "all",
                         "min_cp": 100, "max_cp": 1500, "shiny_rate": 0.0},
    "Pikachu Festival": {"event_name": "Pikachu Festival", "spawn_density": 10, "species_mode": "single",
                         "single_species": 25, "min_cp": 300, "max_cp": 1000, "shiny_rate": 0.0},
    "Starter Party":    {"event_name": "Starter Party", "spawn_density": 8, "species_mode": "list",
                         "species_list": [1, 4, 7], "min_cp": 200, "max_cp": 1200, "shiny_rate": 0.0},
    "Legendary Hunt":   {"event_name": "Legendary Hunt", "spawn_density": 4, "species_mode": "list",
                         "species_list": [144, 145, 146, 150, 151], "min_cp": 2000, "max_cp": 3500,
                         "shiny_rate": 0.0},
    "High CP":          {"event_name": "High CP", "spawn_density": 5, "species_mode": "all",
                         "min_cp": 2500, "max_cp": 4000, "shiny_rate": 0.0},
}

_lock = threading.Lock()
_cache = {"mtime": None, "cfg": None}


def _read_file():
    try:
        with open(EVENTS_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def get():
    """Current config (DEFAULTS merged with events.json), hot-reloaded by mtime."""
    with _lock:
        try:
            m = os.path.getmtime(EVENTS_FILE)
        except OSError:
            m = None
        if _cache["cfg"] is None or m != _cache["mtime"]:
            cfg = dict(DEFAULTS)
            cfg.update(_read_file())
            _cache["cfg"] = _sanitize(cfg)
            _cache["mtime"] = m
        return dict(_cache["cfg"])


def save(cfg):
    """Merge + validate + persist a (full or partial) config; returns the result."""
    merged = dict(DEFAULTS)
    merged.update(_read_file())
    merged.update(cfg or {})
    merged = _sanitize(merged)
    with _lock:
        with open(EVENTS_FILE, "w", encoding="utf-8") as fh:
            json.dump(merged, fh, indent=2)
        _cache["cfg"] = None            # force reload on next get()
    return merged


def apply_preset(name):
    p = PRESETS.get(name)
    return save(p) if p else None


def _clampi(v, lo, hi, d):
    try:
        v = int(v)
    except (TypeError, ValueError):
        v = d
    return max(lo, min(hi, v))


def _sanitize(c):
    c["spawn_density"] = _clampi(c.get("spawn_density"), 0, 60, 5)
    c["min_cp"] = _clampi(c.get("min_cp"), 10, 5000, 100)
    c["max_cp"] = _clampi(c.get("max_cp"), 10, 5000, 1200)
    if c["max_cp"] < c["min_cp"]:
        c["max_cp"] = c["min_cp"]
    if c.get("species_mode") not in ("all", "list", "single"):
        c["species_mode"] = "all"
    c["single_species"] = _clampi(c.get("single_species"), 1, 151, 25)
    clean = []
    for x in c.get("species_list") or []:
        try:
            xi = int(x)
        except (TypeError, ValueError):
            continue
        if 1 <= xi <= 151:
            clean.append(xi)
    c["species_list"] = clean or [25]
    try:
        c["shiny_rate"] = max(0.0, min(1.0, float(c.get("shiny_rate", 0.0))))
    except (TypeError, ValueError):
        c["shiny_rate"] = 0.0
    c["event_name"] = str(c.get("event_name", "Event"))[:40]
    return c
