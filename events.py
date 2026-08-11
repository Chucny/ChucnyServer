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
    # --- CORE BASE PRESETS ---
    "Normal":           {"event_name": "Normal", "spawn_density": 5, "species_mode": "all",
                         "min_cp": 100, "max_cp": 1200},
    "Swarm":            {"event_name": "Swarm", "spawn_density": 25, "species_mode": "all",
                         "min_cp": 100, "max_cp": 1500},
    "Pikachu Festival": {"event_name": "Pikachu Festival", "spawn_density": 10, "species_mode": "single",
                         "single_species": 25, "min_cp": 300, "max_cp": 1000},
    "Starter Party":    {"event_name": "Starter Party", "spawn_density": 8, "species_mode": "list",
                         "species_list": [1, 4, 7], "min_cp": 200, "max_cp": 1200},
    "Legendary Hunt":   {"event_name": "Legendary Hunt", "spawn_density": 4, "species_mode": "list",
                         "species_list": [144, 145, 146, 150, 151], "min_cp": 2000, "max_cp": 3500},
    "High CP":          {"event_name": "High CP", "spawn_density": 5, "species_mode": "all",
                         "min_cp": 2500, "max_cp": 4000},
    "Low CP":           {"event_name": "Low CP", "spawn_density": 8, "species_mode": "all",
                         "min_cp": 42, "max_cp": 500},

    # --- 25 KANTO-ONLY COMMUNITY DAYS (Single-Item Lists, 3-Stage Families Only) ---
    "Community Day: Squirtle":  {"event_name": "Community Day: Squirtle", "spawn_density": 30, "species_mode": "list",
                                 "species_list": [7], "min_cp": 10, "max_cp": 1000},
    "Community Day: Zubat":     {"event_name": "Community Day: Zubat", "spawn_density": 30, "species_mode": "list",
                                 "species_list": [41], "min_cp": 10, "max_cp": 850},
    "Community Day: Pidgey":    {"event_name": "Community Day: Pidgey", "spawn_density": 35, "species_mode": "list",
                                 "species_list": [16], "min_cp": 10, "max_cp": 700},
    "Community Day: Bulbasaur": {"event_name": "Community Day: Bulbasaur", "spawn_density": 30, "species_mode": "list",
                                 "species_list": [1], "min_cp": 10, "max_cp": 1000},
    "Community Day: Charmander":{"event_name": "Community Day: Charmander", "spawn_density": 30, "species_mode": "list",
                                 "species_list": [4], "min_cp": 10, "max_cp": 1000},
    "Community Day: Poliwag":   {"event_name": "Community Day: Poliwag", "spawn_density": 28, "species_mode": "list",
                                 "species_list": [60], "min_cp": 15, "max_cp": 900},
    "Community Day: Abra":      {"event_name": "Community Day: Abra", "spawn_density": 25, "species_mode": "list",
                                 "species_list": [63], "min_cp": 10, "max_cp": 1200},
    "Community Day: Machop":    {"event_name": "Community Day: Machop", "spawn_density": 28, "species_mode": "list",
                                 "species_list": [66], "min_cp": 20, "max_cp": 1100},
    "Community Day: Geodude":   {"event_name": "Community Day: Geodude", "spawn_density": 27, "species_mode": "list",
                                 "species_list": [74], "min_cp": 15, "max_cp": 1150},
    "Community Day: Gastly":    {"event_name": "Community Day: Gastly", "spawn_density": 32, "species_mode": "list",
                                 "species_list": [92], "min_cp": 10, "max_cp": 1050},
    "Community Day: Dratini":   {"event_name": "Community Day: Dratini", "spawn_density": 22, "species_mode": "list",
                                 "species_list": [147], "min_cp": 30, "max_cp": 1250},
    "Community Day: Caterpie":  {"event_name": "Community Day: Caterpie", "spawn_density": 33, "species_mode": "list",
                                 "species_list": [10], "min_cp": 10, "max_cp": 650},
    "Community Day: Weedle":    {"event_name": "Community Day: Weedle", "spawn_density": 33, "species_mode": "list",
                                 "species_list": [13], "min_cp": 10, "max_cp": 650},
    "Community Day: Nidoran F": {"event_name": "Community Day: Nidoran F", "spawn_density": 26, "species_mode": "list",
                                 "species_list": [29], "min_cp": 15, "max_cp": 950},
    "Community Day: Oddish":    {"event_name": "Community Day: Oddish", "spawn_density": 28, "species_mode": "list",
                                 "species_list": [43], "min_cp": 15, "max_cp": 1000},
    "Community Day: Nidoran M": {"event_name": "Community Day: Nidoran M", "spawn_density": 26, "species_mode": "list",
                                 "species_list": [32], "min_cp": 15, "max_cp": 950},
    "Community Day: Bellsprout":{"event_name": "Community Day: Bellsprout", "spawn_density": 28, "species_mode": "list",
                                 "species_list": [69], "min_cp": 12, "max_cp": 920},
    "Community Day: Tentacool": {"event_name": "Community Day: Tentacool", "spawn_density": 25, "species_mode": "list",
                                 "species_list": [72], "min_cp": 15, "max_cp": 950},
    "Community Day: Magnemite": {"event_name": "Community Day: Magnemite", "spawn_density": 24, "species_mode": "list",
                                 "species_list": [81], "min_cp": 20, "max_cp": 1020},
    "Community Day: Doduo":     {"event_name": "Community Day: Doduo", "spawn_density": 27, "species_mode": "list",
                                 "species_list": [84], "min_cp": 15, "max_cp": 980},
    "Community Day: Seel":      {"event_name": "Community Day: Seel", "spawn_density": 23, "species_mode": "list",
                                 "species_list": [86], "min_cp": 18, "max_cp": 940},
    "Community Day: Shellder":  {"event_name": "Community Day: Shellder", "spawn_density": 25, "species_mode": "list",
                                 "species_list": [90], "min_cp": 10, "max_cp": 1050},
    "Community Day: Krabby":    {"event_name": "Community Day: Krabby", "spawn_density": 26, "species_mode": "list",
                                 "species_list": [98], "min_cp": 20, "max_cp": 1100},
    "Community Day: Exeggcute": {"event_name": "Community Day: Exeggcute", "spawn_density": 22, "species_mode": "list",
                                 "species_list": [102], "min_cp": 15, "max_cp": 1120},
    "Community Day: Rhyhorn":   {"event_name": "Community Day: Rhyhorn", "spawn_density": 21, "species_mode": "list",
                                 "species_list": [111], "min_cp": 30, "max_cp": 1200},

    # --- DESCRIPTIVE KANTO ENVIRONMENTAL EVENTS ---
    "World of Birds":           {"event_name": "World of Birds", "spawn_density": 20, "species_mode": "list",
                                 "species_list": [16, 17, 18, 21, 22, 83, 84, 85, 144, 145, 146], "min_cp": 100, "max_cp": 1500},
    "Power Plant Malfunction":  {"event_name": "Power Plant Malfunction", "spawn_density": 15, "species_mode": "list",
                                 "species_list": [25, 26, 81, 82, 100, 101, 125, 135], "min_cp": 200, "max_cp": 2400},
    "Safari Zone Classic":      {"event_name": "Safari Zone Classic", "spawn_density": 18, "species_mode": "list",
                                 "species_list": [113, 115, 123, 127, 128], "min_cp": 300, "max_cp": 2500},
    "Mt. Moon Excavation":      {"event_name": "Mt. Moon Excavation", "spawn_density": 14, "species_mode": "list",
                                 "species_list": [35, 36, 41, 42, 74, 75, 76, 138, 140], "min_cp": 100, "max_cp": 2100},
    "Cinnabar Island Eruption": {"event_name": "Cinnabar Island Eruption", "spawn_density": 12, "species_mode": "list",
                                 "species_list": [4, 5, 6, 58, 59, 77, 78, 126], "min_cp": 400, "max_cp": 2800},
    "Lavender Town Haunting":   {"event_name": "Lavender Town Haunting", "spawn_density": 16, "species_mode": "list",
                                 "species_list": [92, 93, 94, 104, 105], "min_cp": 50, "max_cp": 2000},
    "Seafoam Islands Cruise":   {"event_name": "Seafoam Islands Cruise", "spawn_density": 13, "species_mode": "list",
                                 "species_list": [86, 87, 90, 91, 116, 117, 124, 131], "min_cp": 200, "max_cp": 2600},
    "Eevee Breeding Lab":       {"event_name": "Eevee Breeding Lab", "spawn_density": 20, "species_mode": "list",
                                 "species_list": [133, 134, 135, 136], "min_cp": 100, "max_cp": 2700},
    "Ditto Infiltration":       {"event_name": "Ditto Infiltration", "spawn_density": 12, "species_mode": "single",
                                 "single_species": 132, "min_cp": 10, "max_cp": 800},
    "Cerulean Cave Depths":     {"event_name": "Cerulean Cave Depths", "spawn_density": 6, "species_mode": "list",
                                 "species_list": [63, 64, 65, 149, 150, 151], "min_cp": 1500, "max_cp": 3800},
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
