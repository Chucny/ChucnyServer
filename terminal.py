"""
ChucnyServer terminal admin console.

A terminal-only replacement for the web UI in admin.py.  It deliberately
shares the same underlying modules (places, events, world, helpcenter, etc.)
so changes are written through the same code paths as the web panel.

Commands use a slash-command syntax, for example:
    /world
    /place stop 60.1708 24.9375 "Central Stop"
    /spawn 60.1708 24.9375 25
    /give item 1 20 Ash
    /raid on 150 3000 raid
    /help

Remember this is full of bugs and doesn't work properly.
"""

from __future__ import annotations

import math
import shlex
import sys
import threading
import urllib.parse
import urllib.request
import hashlib
import random

import events as EV
import places as PL


GIVEABLE = [
    (1, "Poke Ball"), (2, "Great Ball"), (3, "Ultra Ball"),
    (101, "Potion"), (102, "Super Potion"), (103, "Hyper Potion"),
    (104, "Max Potion"), (201, "Revive"), (202, "Max Revive"),
    (701, "Razz Berry"), (401, "Incense"), (301, "Lucky Egg"),
    (501, "Lure Module"), (902, "Egg Incubator"),
]

DEX = [""] + """Bulbasaur Ivysaur Venusaur Charmander Charmeleon Charizard Squirtle Wartortle
Blastoise Caterpie Metapod Butterfree Weedle Kakuna Beedrill Pidgey Pidgeotto Pidgeot Rattata
Raticate Spearow Fearow Ekans Arbok Pikachu Raichu Sandshrew Sandslash NidoranF Nidorina
Nidoqueen NidoranM Nidorino Nidoking Clefairy Clefable Vulpix Ninetales Jigglypuff Wigglytuff
Zubat Golbat Oddish Gloom Vileplume Paras Parasect Venonat Venomoth Diglett Dugtrio Meowth
Persian Psyduck Golduck Mankey Primeape Growlithe Arcanine Poliwag Poliwhirl Poliwrath Abra
Kadabra Alakazam Machop Machoke Machamp Bellsprout Weepinbell Victreebel Tentacool Tentacruel
Geodude Graveler Golem Ponyta Rapidash Slowpoke Slowbro Magnemite Magneton Farfetchd Doduo
Dodrio Seel Dewgong Grimer Muk Shellder Cloyster Gastly Haunter Gengar Onix Drowzee Hypno
Krabby Kingler Voltorb Electrode Exeggcute Exeggutor Cubone Marowak Hitmonlee Hitmonchan
Lickitung Koffing Weezing Rhyhorn Rhydon Chansey Tangela Kangaskhan Horsea Seadra Goldeen
Seaking Staryu Starmie MrMime Scyther Jynx Electabuzz Magmar Pinsir Tauros Magikarp Gyarados
Lapras Ditto Eevee Vaporeon Jolteon Flareon Porygon Omanyte Omastar Kabuto Kabutops Aerodactyl
Snorlax Articuno Zapdos Moltres Dratini Dragonair Dragonite Mewtwo Mew""".split()

ITEM_NAMES = dict(GIVEABLE)


def _ok(message: str, **extra):
    out = {"ok": True, "message": message}
    out.update(extra)
    return out


def _err(message: str, **extra):
    out = {"ok": False, "message": message}
    out.update(extra)
    return out


def _float(value: str, name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"invalid {name}: {value!r}")


def _int(value: str, name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f"invalid {name}: {value!r}")


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def _pokemon_id(value: str) -> int:
    """Accept a numeric Kanto ID or an exact case-insensitive species name."""
    try:
        pid = int(value)
    except ValueError:
        wanted = value.casefold()
        matches = [i for i, name in enumerate(DEX) if name.casefold() == wanted]
        if not matches:
            raise ValueError(f"unknown Pokemon: {value!r}")
        pid = matches[0]
    if not 1 <= pid <= 151:
        raise ValueError("Pokemon ID must be between 1 and 151")
    return pid


def _trainer_location():
    try:
        import rpc
        return float(rpc._last_loc[0]), float(rpc._last_loc[1])
    except Exception:
        return 0.0, 0.0


def fetch_overpass_pois(
    lat: float,
    lng: float,
    radius_m: float = 3000.0,
    limit: int = 10000,
    gym_chance: float = 0.0,
) -> int:
    """Same OSM/Overpass importer used by admin.py."""
    query = f"""
    [out:json][timeout:90];
    (
      nwr(around:{radius_m},{lat},{lng})["amenity"];
      nwr(around:{radius_m},{lat},{lng})["leisure"];
      nwr(around:{radius_m},{lat},{lng})["tourism"];
      nwr(around:{radius_m},{lat},{lng})["historic"];
      nwr(around:{radius_m},{lat},{lng})["shop"];
      nwr(around:{radius_m},{lat},{lng})["man_made"];
      nwr(around:{radius_m},{lat},{lng})["craft"];
      nwr(around:{radius_m},{lat},{lng})["amenity"="bench"];
      nwr(around:{radius_m},{lat},{lng})["amenity"="shelter"];
      nwr(around:{radius_m},{lat},{lng})["amenity"="post_box"];
      nwr(around:{radius_m},{lat},{lng})["amenity"="bicycle_parking"];
      nwr(around:{radius_m},{lat},{lng})["leisure"="picnic_table"];
      nwr(around:{radius_m},{lat},{lng})["tourism"="picnic_site"];
      nwr(around:{radius_m},{lat},{lng})["tourism"="viewpoint"];
      nwr(around:{radius_m},{lat},{lng})["barrier"="gate"];
      nwr(around:{radius_m},{lat},{lng})["barrier"="city_wall"];
      nwr(around:{radius_m},{lat},{lng})["natural"="tree"]["memorial"="yes"];
      nwr(around:{radius_m},{lat},{lng})["natural"="stone"];
      nwr(around:{radius_m},{lat},{lng})["waterway"="waterfall"];
      nwr(around:{radius_m},{lat},{lng})["highway"="bus_stop"];
      nwr(around:{radius_m},{lat},{lng})["highway"="platform"];
      nwr(around:{radius_m},{lat},{lng})["railway"="station"];
      nwr(around:{radius_m},{lat},{lng})["railway"="tram_stop"];
    );
    out center {limit};"""

    url = "https://overpass-api.de/api/interpreter"
    data = urllib.parse.urlencode({"data": query}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "PoGOServer/1.0"})

    try:
        with urllib.request.urlopen(req, timeout=35) as response:
            payload = __import__("json").loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Overpass request failed: {exc}") from exc

    placed = 0
    for elem in payload.get("elements", []):
        tags = elem.get("tags", {})
        n_lat = elem.get("lat") or elem.get("center", {}).get("lat")
        n_lng = elem.get("lon") or elem.get("center", {}).get("lon")
        if n_lat is None or n_lng is None:
            continue

        name = tags.get("name")
        if not name:
            name_parts = [
                tags.get("amenity"), tags.get("leisure"), tags.get("tourism"),
                tags.get("historic"), tags.get("shop"), tags.get("man_made"),
                tags.get("highway"),
            ]
            valid_parts = [p.replace("_", " ").title() for p in name_parts if p]
            name = valid_parts[0] if valid_parts else "Way Point"

        image = tags.get("image", "")
        if not image and "wikimedia_commons" in tags:
            commons_file = tags["wikimedia_commons"].replace("File:", "").strip()
            filename = commons_file.replace(" ", "_")
            md5_hash = hashlib.md5(filename.encode("utf-8")).hexdigest()
            image = (
                "https://upload.wikimedia.org/wikipedia/commons/"
                f"{md5_hash[0]}/{md5_hash[0:2]}/{urllib.parse.quote(filename)}"
            )

        kind = "gym" if gym_chance > 0 and random.random() < gym_chance else "stop"
        PL.add_fort(n_lat, n_lng, kind, name, image)
        placed += 1

    return placed


# ---------------------------------------------------------------------------
# Direct equivalents of admin.py's POST actions, without HTTP/UI overhead.
# ---------------------------------------------------------------------------

def world_state():
    import settings as CFG
    import world

    lat, lng = _trainer_location()
    return {
        "places": PL.get(),
        "config": EV.get(),
        "presets": list(EV.PRESETS),
        "storage": world.storage(),
        "prices": {
            "pokemon_step": CFG.get("storage", "pokemon_upgrade_step"),
            "pokemon_cost": CFG.get("storage", "pokemon_upgrade_cost"),
            "items_step": CFG.get("storage", "items_upgrade_step"),
            "items_cost": CFG.get("storage", "items_upgrade_cost"),
        },
        "player": {"lat": lat, "lng": lng},
    }


def place_fort(lat, lng, kind="stop", name="", image=""):
    if kind not in {"stop", "gym"}:
        return _err("kind must be 'stop' or 'gym'")
    result = PL.add_fort(lat, lng, kind, name, image)
    return _ok(f"placed {kind} {name!r} at {float(lat):.5f}, {float(lng):.5f}", result=result)


def place_spawn(lat, lng, pokemon_id=1, name=""):
    result = PL.add_spawn(lat, lng, pokemon_id, name)
    label = DEX[pokemon_id] if 0 <= pokemon_id < len(DEX) else str(pokemon_id)
    return _ok(f"placed {label} at {float(lat):.5f}, {float(lng):.5f}", result=result)


def remove_object(object_id):
    removed = PL.remove(object_id)
    return _ok(f"removed {object_id!r}") if removed else _err(f"object {object_id!r} not found")


def clear_objects(what="all"):
    if what not in {"all", "forts", "spawns"}:
        return _err("clear target must be all, forts, or spawns")
    result = PL.clear(what)
    return _ok(f"cleared {what}", result=result)


def set_procedural(what, on):
    if what not in {"forts", "spawns", "both"}:
        return _err("target must be forts, spawns, or both")
    result = PL.set_procedural(bool(on), what)
    return _ok(f"random {what} {'ON' if on else 'OFF'}", result=result)


def build_ring(lat, lng, count=8, radius_m=60, gym=True):
    count = max(1, min(24, int(count)))
    radius_m = max(10.0, min(500.0, float(radius_m)))
    made = []
    for i in range(count):
        a = 2 * math.pi * i / count
        dlat = (radius_m * math.cos(a)) / 111320.0
        dlng = (radius_m * math.sin(a)) / (
            111320.0 * max(0.2, math.cos(math.radians(lat)))
        )
        made.append(PL.add_fort(lat + dlat, lng + dlng, "stop", f"Ring Stop {i + 1}"))
    if gym:
        made.append(PL.add_fort(lat, lng, "gym", "Home Gym"))
    return _ok(f"placed {len(made)} ring objects", placed=len(made), objects=made)


def give(player, kind, count, item_id=None, pokemon_id=None):
    import contextlib
    import world

    who = (player or "").strip()
    try:
        ctx = world.acting_as(who) if who else contextlib.nullcontext()
    except KeyError:
        return _err(f"no account called {who!r}")

    try:
        with ctx:
            target = who or world.current().username
            if kind == "stardust":
                cnt = _clamp(int(count), 1, 999999)
                total = world.add_stardust(cnt)
                return _ok(f"gave {target} {cnt} stardust (now {total})")

            if kind == "candy":
                import protocol as P
                pid = _pokemon_id(str(pokemon_id))
                cnt = _clamp(int(count), 1, 999)
                fam = P.pokemon_family(pid)
                total = world.add_candy(fam, cnt)
                label = DEX[pid]
                fam_label = DEX[fam] if fam < len(DEX) else str(fam)
                msg = f"gave {target} {cnt} {fam_label} candy (now {total})"
                if fam != pid:
                    msg += f" — {label}'s family"
                return _ok(msg)

            if kind != "item":
                return _err("give kind must be item, candy, or stardust")

            iid = int(item_id)
            cnt = _clamp(int(count), 1, 999)
            if iid not in ITEM_NAMES:
                return _err("unknown item")
            total = world.add_item(iid, cnt)
            return _ok(f"gave {target} {cnt} x {ITEM_NAMES[iid]} (now {total})")
    except KeyError:
        return _err(f"no account called {who!r}")


def reset_password(player, password):
    import world
    who = (player or "").strip()
    if not password:
        return _err("pick a password")
    if world.set_password(who, password):
        return _ok(f"{who}'s password has been reset")
    return _err(f"no account called {who!r}")


def raid(on=None, pokemon_id=None, cp=None, trainer=None):
    import world
    if on is None and pokemon_id is None and cp is None and trainer is None:
        return world.raid()

    cfg, sent = world.set_raid(on, pokemon_id, cp, trainer)
    who = DEX[cfg["pokemon_id"]] if cfg["pokemon_id"] < len(DEX) else "?"
    if cfg["on"]:
        msg = f"Raid ON — {who} CP{cfg['cp']} is now defending every gym"
        if sent:
            msg += f"; {sent} defender(s) sent home"
    else:
        msg = "Raid off — gyms are back to normal and empty"
    return dict(cfg, message=msg)


def save_event(event_name, density, mode, species_list, single_species, min_cp, max_cp):
    payload = {
        "event_name": event_name,
        "spawn_density": density,
        "species_mode": mode,
        "species_list": species_list,
        "single_species": single_species,
        "min_cp": min_cp,
        "max_cp": max_cp,
    }
    return EV.save(payload)


def nominations():
    import helpcenter
    return helpcenter.recent()


def resolve_nomination(nomination_id, status="rejected"):
    import helpcenter
    row = helpcenter.resolve(nomination_id, status)
    if not row:
        return _err("unknown nomination")
    for fort in list(PL.get()["forts"]):
        if abs(fort["lat"] - row["lat"]) < 1e-6 and abs(fort["lng"] - row["lng"]) < 1e-6:
            PL.remove(fort["id"])
    return _ok(f"removed {row['name']!r}")


class TerminalAdmin:
    """Interactive slash-command terminal for the admin functionality."""

    def __init__(self, prompt="admin> "):
        self.prompt = prompt
        self.running = False
        self._commands = {
            "/help": self.cmd_help,
            "/?": self.cmd_help,
            "/world": self.cmd_world,
            "/list": self.cmd_list,
            "/accounts": self.cmd_accounts,
            "/place": self.cmd_place,
            "/spawn": self.cmd_spawn,
            "/remove": self.cmd_remove,
            "/clear": self.cmd_clear,
            "/random": self.cmd_random,
            "/ring": self.cmd_ring,
            "/import-pois": self.cmd_import_pois,
            "/raid": self.cmd_raid,
            "/give": self.cmd_give,
            "/reset-password": self.cmd_reset_password,
            "/nominations": self.cmd_nominations,
            "/nomination": self.cmd_nomination,
            "/event": self.cmd_event,
            "/preset": self.cmd_preset,
            "/exit": self.cmd_exit,
            "/quit": self.cmd_exit,
        }

    def println(self, text=""):
        print(text, flush=True)

    def error(self, message):
        self.println(f"[ERROR] {message}")

    def result(self, value):
        if isinstance(value, dict) and value.get("ok") is False:
            self.error(value.get("message", "operation failed"))
        elif isinstance(value, dict) and "message" in value:
            self.println(f"[OK] {value['message']}")
        else:
            self.println(value)

    def cmd_help(self, args):
        self.println(
            """
Available slash commands:

  /world
      Show world, spawn, trainer, event, storage and raid state.
  /list [forts|spawns|all]
      List placed objects with IDs and coordinates.
  /accounts
      List trainer accounts.
  /place <stop|gym> <lat> <lng> [name] [image]
      Place a PokeStop or Gym.
  /spawn <lat> <lng> <pokemon-id|name> [name]
      Place a Pokemon spawn.
  /remove <object-id>
      Remove one placed object.
  /clear [all|forts|spawns]
      Clear placed objects.
  /random <forts|spawns|both> <on|off>
      Toggle procedural stops/Pokemon.
  /ring [lat lng] [count] [radius-m] [gym=on|off]
      Build a stop ring. Without coordinates, uses the current trainer position.
  /import-pois [lat lng] [radius-km] [limit] [gym-percent]
      Import OSM POIs using the same Overpass logic as admin.py.
  /raid [on|off] [pokemon-id|name] [cp] [trainer]
      View or change raid boss configuration.
  /give item <item-id> <count> [player]
  /give candy <pokemon-id|name> <count> [player]
  /give stardust <count> [player]
      Grant player resources. PokeCoins are intentionally unavailable.
  /reset-password <player> <new-password>
      Reset a trainer password.
  /nominations
      Show pending player nominations.
  /nomination <id> reject
      Resolve a nomination using the admin panel's rejection behavior.
  /event <name> <density> <all|list|single> <species-list> <single-id> <min-cp> <max-cp>
      Save global event/spawn configuration.
  /preset <name>
      Apply an EV preset.
  /help
      Show this help.
  /exit
      Stop the terminal console.

Names containing spaces should be quoted, e.g. /place stop 60.17 24.94 "My Stop".
""".strip()
        )

    def cmd_world(self, args):
        import world
        state = world_state()
        places = state["places"]
        forts = places["forts"]
        spawns = places["spawns"]
        gyms = sum(1 for f in forts if f.get("kind") == "gym")
        stops = len(forts) - gyms
        player = state["player"]
        cfg = state["config"]
        storage = state["storage"]
        self.println("\n=== WORLD ===")
        self.println(f"Stops: {stops} | Gyms: {gyms} | Spawns: {len(spawns)}")
        self.println(
            f"Random Stops: {'ON' if places.get('procedural_forts') else 'OFF'} | "
            f"Random Pokemon: {'ON' if places.get('procedural_spawns') else 'OFF'}"
        )
        self.println(f"Trainer position: {player['lat']:.6f}, {player['lng']:.6f}")
        self.println(f"Event: {cfg.get('event_name')} | density={cfg.get('spawn_density')}")
        self.println(
            f"Species mode: {cfg.get('species_mode')} | list={cfg.get('species_list', [])} | "
            f"single={cfg.get('single_species')}"
        )
        self.println(f"CP range: {cfg.get('min_cp')} - {cfg.get('max_cp')}")
        self.println(
            f"Storage: Pokemon {storage.get('pokemon_used', 0)}/{storage.get('max_pokemon', 0)} | "
            f"Items {storage.get('items_used', 0)}/{storage.get('max_items', 0)}"
        )
        r = world.raid()
        self.println(
            f"Raid: {'ON' if r.get('on') else 'OFF'} | "
            f"Pokemon={DEX[r['pokemon_id']] if r.get('pokemon_id', 0) < len(DEX) else r.get('pokemon_id')} | "
            f"CP={r.get('cp')} | trainer={r.get('trainer')}"
        )

    def cmd_list(self, args):
        target = args[0].lower() if args else "all"
        if target not in {"all", "forts", "spawns"}:
            raise ValueError("list target must be all, forts, or spawns")
        places = PL.get()
        rows = []
        if target in {"all", "forts"}:
            for f in places["forts"]:
                rows.append(
                    f"{f['id']}  {f['kind'].upper():4}  {f.get('name', '')!r}  "
                    f"{f['lat']:.5f}, {f['lng']:.5f}"
                    + (" [photo]" if f.get("image") else "")
                )
        if target in {"all", "spawns"}:
            for s in places["spawns"]:
                pid = s.get("pokemon_id")
                label = DEX[pid] if pid and pid < len(DEX) else "Random Pokemon"
                rows.append(f"{s['id']}  SPAWN  {label}  {s['lat']:.5f}, {s['lng']:.5f}")
        self.println("\n" + "\n".join(rows) if rows else "No placed objects.")

    def cmd_accounts(self, args):
        import world
        names = world.account_names()
        self.println("\n".join(names) if names else "No accounts.")

    def cmd_place(self, args):
        if len(args) < 3:
            raise ValueError("usage: /place <stop|gym> <lat> <lng> [name] [image]")
        kind = args[0].lower()
        lat, lng = _float(args[1], "latitude"), _float(args[2], "longitude")
        name = args[3] if len(args) >= 4 else ""
        image = args[4] if len(args) >= 5 else ""
        self.result(place_fort(lat, lng, kind, name, image))

    def cmd_spawn(self, args):
        if len(args) < 3:
            raise ValueError("usage: /spawn <lat> <lng> <pokemon-id|name> [name]")
        lat, lng = _float(args[0], "latitude"), _float(args[1], "longitude")
        pid = _pokemon_id(args[2])
        name = args[3] if len(args) >= 4 else ""
        self.result(place_spawn(lat, lng, pid, name))

    def cmd_remove(self, args):
        if len(args) != 1:
            raise ValueError("usage: /remove <object-id>")
        self.result(remove_object(args[0]))

    def cmd_clear(self, args):
        self.result(clear_objects(args[0].lower() if args else "all"))

    def cmd_random(self, args):
        if len(args) != 2:
            raise ValueError("usage: /random <forts|spawns|both> <on|off>")
        state = args[1].lower()
        if state not in {"on", "off"}:
            raise ValueError("state must be on or off")
        self.result(set_procedural(args[0].lower(), state == "on"))

    def cmd_ring(self, args):
        lat, lng = _trainer_location()
        idx = 0
        if len(args) >= 2 and args[0].lower() != "trainer":
            lat, lng = _float(args[0], "latitude"), _float(args[1], "longitude")
            idx = 2
        elif args and args[0].lower() == "trainer":
            idx = 1
        if not lat:
            raise ValueError("no trainer position is available")
        count = _int(args[idx], "count") if len(args) > idx else 8
        radius = _float(args[idx + 1], "radius") if len(args) > idx + 1 else 60
        gym = True
        if len(args) > idx + 2:
            token = args[idx + 2].lower().replace("gym=", "")
            if token not in {"on", "off"}:
                raise ValueError("gym must be on or off")
            gym = token == "on"
        self.result(build_ring(lat, lng, count, radius, gym))

    def cmd_import_pois(self, args):
        lat, lng = _trainer_location()
        idx = 0
        if len(args) >= 2:
            lat, lng = _float(args[0], "latitude"), _float(args[1], "longitude")
            idx = 2
        radius_km = _float(args[idx], "radius-km") if len(args) > idx else 3
        limit = _int(args[idx + 1], "limit") if len(args) > idx + 1 else 5000
        gym_percent = _float(args[idx + 2], "gym-percent") if len(args) > idx + 2 else 15
        if not lat or not lng:
            raise ValueError("latitude and longitude are required (or a trainer position must be available)")
        if not 0.1 <= radius_km <= 50:
            raise ValueError("radius-km must be between 0.1 and 50")
        if not 100 <= limit <= 10000:
            raise ValueError("limit must be between 100 and 10000")
        if not 0 <= gym_percent <= 100:
            raise ValueError("gym-percent must be between 0 and 100")
        self.println("[INFO] Fetching high-density POIs from OpenStreetMap...")
        placed = fetch_overpass_pois(lat, lng, radius_km * 1000, limit, gym_percent / 100)
        self.println(f"[OK] Successfully imported {placed} Objects.")

    def cmd_raid(self, args):
        if not args:
            self.println(raid())
            return
        state = args[0].lower()
        if state not in {"on", "off"}:
            raise ValueError("usage: /raid <on|off> [pokemon-id|name] [cp] [trainer]")
        pid = _pokemon_id(args[1]) if len(args) >= 2 else 150
        cp = _int(args[2], "CP") if len(args) >= 3 else 3000
        trainer = args[3] if len(args) >= 4 else "raid"
        self.result(raid(state == "on", pid, cp, trainer))

    def cmd_give(self, args):
        if len(args) < 2:
            raise ValueError("usage: /give <item|candy|stardust> <value> <count> [player]")
        kind = args[0].lower()
        if kind == "stardust":
            count = _int(args[1], "count")
            player = args[2] if len(args) >= 3 else ""
            self.result(give(player, kind, count))
            return
        if len(args) < 3:
            raise ValueError("usage: /give item|candy <id|name> <count> [player]")
        value, count = args[1], _int(args[2], "count")
        player = args[3] if len(args) >= 4 else ""
        if kind == "item":
            self.result(give(player, kind, count, item_id=_int(value, "item-id")))
        elif kind == "candy":
            self.result(give(player, kind, count, pokemon_id=value))
        else:
            raise ValueError("give kind must be item, candy, or stardust")

    def cmd_reset_password(self, args):
        if len(args) != 2:
            raise ValueError("usage: /reset-password <player> <new-password>")
        self.result(reset_password(args[0], args[1]))

    def cmd_nominations(self, args):
        rows = nominations()
        if not rows:
            self.println("No nominations waiting.")
            return
        for row in rows:
            note = f" | {row['note']}" if row.get("note") else ""
            self.println(
                f"{row['id']}  {row['kind'].upper():4}  {row['name']!r}  "
                f"by {row['player']}{note}"
            )

    def cmd_nomination(self, args):
        if len(args) != 2:
            raise ValueError("usage: /nomination <id> reject")
        status = args[1].lower()
        if status not in {"rejected"}:
            raise ValueError("the terminal command currently supports only 'reject'")
        self.result(resolve_nomination(args[0], status))

    def cmd_event(self, args):
        if len(args) != 7:
            raise ValueError(
                "/event <name> <density> <all|list|single> <species-list> "
                "<single-id> <min-cp> <max-cp>"
            )
        name = args[0]
        density = _int(args[1], "density")
        mode = args[2].lower()
        if mode not in {"all", "list", "single"}:
            raise ValueError("event mode must be all, list, or single")
        species_list = [] if args[3] in {"-", "none", ""} else [
            _pokemon_id(x.strip()) for x in args[3].split(",") if x.strip()
        ]
        single = _pokemon_id(args[4]) if args[4] not in {"-", "none", "0"} else 0
        min_cp = _int(args[5], "min CP")
        max_cp = _int(args[6], "max CP")
        if not 0 <= density <= 60:
            raise ValueError("density must be between 0 and 60")
        if not 10 <= min_cp <= 5000 or not 10 <= max_cp <= 5000:
            raise ValueError("CP values must be between 10 and 5000")
        result = save_event(name, density, mode, species_list, single, min_cp, max_cp)
        self.println(f"[OK] event configuration saved: {result}")

    def cmd_preset(self, args):
        if not args:
            raise ValueError("usage: /preset <name>")
        result = EV.apply_preset(" ".join(args))
        if not result:
            self.error("unknown preset")
        else:
            self.println(f"[OK] {result}")

    def cmd_exit(self, args):
        self.running = False
        self.println("[OK] Terminal admin console stopped.")

    def dispatch(self, line: str):
        try:
            tokens = shlex.split(line, posix=True)
        except ValueError as exc:
            self.error(f"parse error: {exc}")
            return
        if not tokens:
            return
        command = tokens[0].lower()
        if not command.startswith("/"):
            self.error("commands must start with '/'; use /help")
            return
        handler = self._commands.get(command)
        if not handler:
            self.error(f"unknown command {command!r}; use /help")
            return
        try:
            handler(tokens[1:])
        except Exception as exc:
            self.error(str(exc))

    def run(self):
        self.running = True
        self.println("\nChucnyServer Terminal Admin (Beta)")
        self.println("Web admin functionality is available as slash commands.")
        self.println("\n This is a Beta function. It is full of bugs and might not work as intended.")
        self.println("PokeCoins/shop functionality is disabled in this console.")
        self.println("Type /help for commands.\n")
        while self.running:
            try:
                line = input(self.prompt)
            except (EOFError, KeyboardInterrupt):
                self.running = False
                self.println("\n[OK] Terminal admin console stopped.")
                break
            self.dispatch(line)


def serve(prompt="admin> "):
    """Blocking entry point for standalone use."""
    TerminalAdmin(prompt=prompt).run()


def start(prompt="admin> "):
    """Start the console in a daemon thread, mirroring admin.start()."""
    console = TerminalAdmin(prompt=prompt)
    thread = threading.Thread(target=console.run, name="terminal-admin", daemon=True)
    thread.start()
    return thread, console


if __name__ == "__main__":
    serve()
