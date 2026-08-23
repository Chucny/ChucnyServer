"""
"World Manager" -- local web UI for the PoGO private server.

Runs on http://127.0.0.1:<port> (localhost only). Allows setting PokeStops,
Gyms, and Pokemon spawns at real coordinates and adjusting global spawn settings.
Writes to places.json / events.json for server hot-reloading.
"""

import json
import threading
import urllib.parse
import urllib.request
import hashlib
import random
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import events as EV
import places as PL

# Items available in the Shop panel (id -> label)
GIVEABLE = [
    (1, "Poke Ball"), (2, "Great Ball"), (3, "Ultra Ball"),
    (101, "Potion"), (102, "Super Potion"), (103, "Hyper Potion"),
    (104, "Max Potion"), (201, "Revive"), (202, "Max Revive"),
    (701, "Razz Berry"), (401, "Incense"), (301, "Lucky Egg"),
    (501, "Lure Module"), (902, "Egg Incubator")
]

# Shop inventory with 2016 prices (sku, label, item_id, count, price)
SHOP = [
    ("pokeball.20",   "20 x Poke Ball",     1,  20,  100),
    ("pokeball.100",  "100 x Poke Ball",    1, 100,  460),
    ("pokeball.200",  "200 x Poke Ball",    1, 200,  800),
    ("greatball.20",  "20 x Great Ball",    2,  20,  200),
    ("ultraball.10",  "10 x Ultra Ball",    3,  10,  300),
    ("potion.20",     "20 x Potion",      101,  20,  200),
    ("revive.10",     "10 x Revive",      201,  10,  200),
    ("razz.20",       "20 x Razz Berry",  701,  20,  150),
    ("incense.1",     "1 x Incense",      401,   1,   80),
    ("incense.8",     "8 x Incense",      401,   8,  500),
    ("luckyegg.1",    "1 x Lucky Egg",    301,   1,   80),
    ("luckyegg.8",    "8 x Lucky Egg",    301,   8,  500),
    ("lure.1",        "1 x Lure Module",  501,   1,  100),
    ("lure.8",        "8 x Lure Module",  501,   8,  680),
    ("incubator.1",   "1 x Egg Incubator", 902,  1,  150),
]

# Kanto species names for the picker (index 0 unused)
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

ASSET_DIR = Path(__file__).with_name("admin")



def fetch_overpass_pois(lat: float, lng: float, radius_m: float = 3000.0, limit: int = 10000, gym_chance: float = 0.0) -> int:
    """Broadly queries OpenStreetMap via Overpass API for nodes, ways, and relations,
    extracting features (parks, art, transport, amenities) and photos.
    """
    query = f"""
    [out:json][timeout:90];
    (
      // 1. Core Points of Interest (Expanded)
      nwr(around:{radius_m},{lat},{lng})["amenity"];
      nwr(around:{radius_m},{lat},{lng})["leisure"];
      nwr(around:{radius_m},{lat},{lng})["tourism"];
      nwr(around:{radius_m},{lat},{lng})["historic"];
      nwr(around:{radius_m},{lat},{lng})["shop"];
      nwr(around:{radius_m},{lat},{lng})["man_made"];
      nwr(around:{radius_m},{lat},{lng})["craft"];

      // 2. Micro-Features & Street Furniture (Massive Density Boost)
      nwr(around:{radius_m},{lat},{lng})["amenity"="bench"];
      nwr(around:{radius_m},{lat},{lng})["amenity"="shelter"];
      nwr(around:{radius_m},{lat},{lng})["amenity"="post_box"];
      nwr(around:{radius_m},{lat},{lng})["amenity"="bicycle_parking"];
      nwr(around:{radius_m},{lat},{lng})["leisure"="picnic_table"];
      nwr(around:{radius_m},{lat},{lng})["tourism"="picnic_site"];
      nwr(around:{radius_m},{lat},{lng})["tourism"="viewpoint"];

      // 3. Specific Landmarks, Gates, and Elements
      nwr(around:{radius_m},{lat},{lng})["barrier"="gate"];
      nwr(around:{radius_m},{lat},{lng})["barrier"="city_wall"];
      nwr(around:{radius_m},{lat},{lng})["natural"="tree"]["memorial"="yes"]; // Historic trees
      nwr(around:{radius_m},{lat},{lng})["natural"="stone"]; // Large prominent boulders
      nwr(around:{radius_m},{lat},{lng})["waterway"="waterfall"];

      // 4. Transportation Nodes
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
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return 0

    placed = 0
    for elem in payload.get("elements", []):
        tags = elem.get("tags", {})

        # Nodes have lat/lon; ways and relations return center coords via 'out center'
        n_lat = elem.get("lat") or elem.get("center", {}).get("lat")
        n_lng = elem.get("lon") or elem.get("center", {}).get("lon")

        if n_lat is None or n_lng is None:
            continue

        # Extract name or synthesize a recognizable tag description if no name is specified
        name = tags.get("name")
        if not name:
            name_parts = [
                tags.get("amenity"), tags.get("leisure"), tags.get("tourism"),
                tags.get("historic"), tags.get("shop"), tags.get("man_made"),
                tags.get("highway")
            ]
            valid_parts = [p.replace("_", " ").title() for p in name_parts if p]
            name = valid_parts[0] if valid_parts else "Way Point"

        # Resolve image URL via direct tag or Wikimedia Commons hash resolver
        image = tags.get("image", "")
        if not image and "wikimedia_commons" in tags:
            commons_file = tags["wikimedia_commons"].replace("File:", "").strip()
            filename = commons_file.replace(" ", "_")
            # MD5 hash is required to fetch raw images direct from Wikipedia's upload server structure
            md5_hash = hashlib.md5(filename.encode('utf-8')).hexdigest()
            image = f"https://upload.wikimedia.org/wikipedia/commons/{md5_hash[0]}/{md5_hash[0:2]}/{urllib.parse.quote(filename)}"

        # Enforce dynamic gym probability based on admin UI input
        kind = "gym" if (gym_chance > 0 and random.random() < gym_chance) else "stop"
        
        PL.add_fort(n_lat, n_lng, kind, name, image)
        placed += 1

    return placed


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, ctype, body):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, "application/json", json.dumps(obj))

    def do_GET(self):
        p = self.path.split("?")[0]
        assets = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/admin/styles.css": ("styles.css", "text/css; charset=utf-8"),
            "/admin/app.js": ("app.js", "application/javascript; charset=utf-8"),
            "/admin/dashboard.js": ("dashboard.js", "application/javascript; charset=utf-8"),
            "/admin/world.js": ("world.js", "application/javascript; charset=utf-8"),
            "/admin/economy.js": ("economy.js", "application/javascript; charset=utf-8"),
        }
        if p in assets:
            name, ctype = assets[p]
            try:
                body = (ASSET_DIR / name).read_text(encoding="utf-8")
            except OSError:
                return self._send(404, "text/plain; charset=utf-8", "not found")
            if name == "app.js":
                body = (body.replace("__DEX__", json.dumps(DEX))
                            .replace("__GIVEABLE__", json.dumps(GIVEABLE))
                            .replace("__SHOP__", json.dumps(SHOP)))
            return self._send(200, ctype, body)
        if p == "/api/world":
            try:
                import rpc
                lat, lng = rpc._last_loc[0], rpc._last_loc[1]
            except Exception:
                lat, lng = 0.0, 0.0
            import settings as CFG, world
            return self._json({"places": PL.get(), "config": EV.get(),
                               "presets": list(EV.PRESETS),
                               "storage": world.storage(),
                               "teleports": {
                                   world.codename_for(k) or k: v
                                   for k, v in rpc.teleports().items()},
                               "prices": {
                                   "pokemon_step": CFG.get("storage", "pokemon_upgrade_step"),
                                   "pokemon_cost": CFG.get("storage", "pokemon_upgrade_cost"),
                                   "items_step": CFG.get("storage", "items_upgrade_step"),
                                   "items_cost": CFG.get("storage", "items_upgrade_cost")},
                               "loot": CFG.all()["pokestops"]["loot"],
                               "player": {"lat": lat, "lng": lng}})
        self._send(404, "text/plain", "not found")

    def do_POST(self):
        p = self.path.split("?")[0]
        n = int(self.headers.get("Content-Length", 0) or 0)
        try:
            d = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            d = {}
        try:
            if p == "/api/fetch_pois":
                lat = float(d.get("lat", 0.0))
                lng = float(d.get("lng", 0.0))
                radius_m = float(d.get("radius_m", 0.0))
                limit = int(d.get("limit", 5000))
                gym_chance = float(d.get("gym_chance", 0.0))
                if "radius_km" in d:
                    radius_m = float(d["radius_km"]) * 1000.0
                if radius_m <= 0:
                    radius_m = 3000.0
                count = fetch_overpass_pois(lat, lng, radius_m, limit, gym_chance)
                return self._json({"placed": count, "message": f"Successfully imported {count} Objects."})
            if p == "/api/teleport":
                import math, rpc, world
                player = (d.get("player") or "").strip()
                try:
                    lat = float(d["lat"])
                    lng = float(d["lng"])
                except (KeyError, TypeError, ValueError):
                    return self._json(
                        {"ok": False, "message": "latitude and longitude are required"}, 400)
                player = world.resolve_account(player)
                if not player:
                    return self._json({"ok": False, "message": "unknown trainer"}, 400)
                if not (math.isfinite(lat) and math.isfinite(lng)
                        and -90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0):
                    return self._json({"ok": False, "message": "invalid coordinates"}, 400)
                rpc.set_teleport(player, lat, lng)
                return self._json({"ok": True, "player": player, "lat": lat, "lng": lng})
            if p == "/api/fort":
                return self._json(PL.add_fort(d.get("lat"), d.get("lng"),
                                              d.get("kind", "stop"), d.get("name", ""),
                                              d.get("image", "")))
            if p == "/api/spawn":
                return self._json(PL.add_spawn(d.get("lat"), d.get("lng"),
                                               d.get("pokemon_id", 1), d.get("name", "")))
            if p == "/api/remove":
                return self._json({"removed": PL.remove(d.get("id", ""))})
            if p == "/api/clear":
                return self._json(PL.clear(d.get("what", "all")))
            if p == "/api/give":
                import contextlib as _ctx, world
                who = (d.get("player") or "").strip()
                kind = d.get("kind", "item")
                try:
                    ctx = world.acting_as(who) if who else _ctx.nullcontext()
                except KeyError:
                    return self._json({"ok": False,
                                       "message": f"no account called {who!r}"})
                try:
                    with ctx:
                        target = who or world.current().username
                        if kind == "stardust":
                            cnt = max(1, min(999999, int(d.get("count", 1))))
                            total = world.add_stardust(cnt)
                            msg = f"gave {target} {cnt} stardust (now {total})"
                        elif kind == "coins":
                            cnt = max(1, min(999999, int(d.get("count", 1))))
                            try:
                                total = world.add_coins(cnt)
                            except AttributeError:
                                # Fallback logic handling if standard add_coins is missing
                                world.spend_coins(-cnt)
                                total = world.COINS
                            msg = f"gave {target} {cnt} PokeCoins (now {total})"
                        elif kind == "candy":
                            import protocol as P
                            pid = int(d.get("pokemon_id", 0))
                            cnt = max(1, min(999, int(d.get("count", 1))))
                            if not 1 <= pid <= 151:
                                return self._json({"ok": False,
                                                   "message": "unknown Pokemon"})
                            fam = P.pokemon_family(pid)
                            total = world.add_candy(fam, cnt)
                            label = DEX[pid] if pid < len(DEX) else str(pid)
                            fam_label = DEX[fam] if fam < len(DEX) else str(fam)
                            msg = (f"gave {target} {cnt} {fam_label} candy "
                                   f"(now {total})")
                            if fam != pid:
                                msg += f" — {label}'s family"
                        else:
                            iid = int(d.get("item_id", 0))
                            cnt = max(1, min(999, int(d.get("count", 1))))
                            names = dict(GIVEABLE)
                            if iid not in names:
                                return self._json({"ok": False,
                                                   "message": "unknown item"})
                            total = world.add_item(iid, cnt)
                            msg = (f"gave {target} {cnt} x {names[iid]} "
                                   f"(now {total})")
                except KeyError:
                    return self._json({"ok": False,
                                       "message": f"no account called {who!r}"})
                return self._json({"ok": True, "message": msg})
            if p == "/api/noms":
                import helpcenter
                return self._json({"rows": helpcenter.recent()})
            if p == "/api/noms/resolve":
                import helpcenter
                row = helpcenter.resolve(d.get("id", ""), d.get("status", "rejected"))
                if not row:
                    return self._json({"ok": False, "message": "unknown nomination"})
                for f in list(PL.get()["forts"]):
                    if (abs(f["lat"] - row["lat"]) < 1e-6
                            and abs(f["lng"] - row["lng"]) < 1e-6):
                        PL.remove(f["id"])
                return self._json({"ok": True,
                                   "message": f"removed {row['name']!r}"})
            if p == "/api/setpw":
                import world
                who = (d.get("player") or "").strip()
                pw = d.get("password") or ""
                if not pw:
                    return self._json({"ok": False, "message": "pick a password"})
                if world.set_password(who, pw):
                    return self._json({"ok": True,
                                       "message": f"{who}'s password has been reset"})
                return self._json({"ok": False,
                                   "message": f"no account called {who!r}"})
            if p == "/api/buyitem":
                import contextlib as _ctx, world
                who = (d.get("player") or "").strip()
                entry = next((e for e in SHOP if e[0] == d.get("sku")), None)
                if not entry:
                    return self._json({"ok": False, "message": "unknown item"})
                _sku, label, iid, cnt, price = entry
                try:
                    ctx = world.acting_as(who) if who else _ctx.nullcontext()
                    ctx.__enter__()
                except KeyError:
                    return self._json({"ok": False,
                                       "message": f"no account called {who!r}"})
                try:
                    target = who or world.current().username
                    if world.room_in_bag() < cnt:
                        return self._json({"ok": False,
                                           "message": f"{target}'s bag has no room "
                                                      f"for {cnt} more items"})
                    if not world.spend_coins(price):
                        return self._json({"ok": False,
                                           "message": f"need {price} PokeCoins, "
                                                      f"{target} has {world.COINS}"})
                    total = world.add_item(iid, cnt)
                    return self._json({"ok": True,
                                       "message": f"bought {label} for {price}c "
                                                  f"-- {target} now has {total}",
                                       "coins": world.COINS})
                finally:
                    ctx.__exit__(None, None, None)
            if p == "/api/raid":
                import world
                if not d:
                    return self._json(world.raid())
                cfg, sent = world.set_raid(d.get("on"), d.get("pokemon_id"),
                                           d.get("cp"), d.get("trainer"))
                who = DEX[cfg["pokemon_id"]] if cfg["pokemon_id"] < len(DEX) else "?"
                msg = (f"Raid ON — {who} CP{cfg['cp']} is now defending every gym"
                       + (f"; {sent} defender(s) sent home" if sent else "")
                       if cfg["on"] else
                       "Raid off — gyms are back to normal and empty")
                return self._json(dict(cfg, message=msg))
            if p == "/api/accounts":
                import world
                return self._json({"accounts": [
                    world.codename_for(n) or n for n in world.account_names()]})
            if p == "/api/buy":
                import world
                ok, message, new = world.buy_storage(
                    "pokemon" if d.get("what") == "pokemon" else "items")
                return self._json({"ok": ok, "message": message, "new": new})
            if p == "/api/procedural":
                return self._json(PL.set_procedural(d.get("on", True), d.get("what", "both")))
            if p == "/api/pokestop-loot":
                import settings as CFG
                table = CFG.save_pokestop_loot(d.get("loot"))
                if table is None:
                    return self._json({"ok": False,
                                       "message": "invalid loot table: each entry needs a GIVEABLE item, chance 0-1, min >= 1, and min <= max"}, 400)
                return self._json({"ok": True, "loot": table})
            if p == "/api/preset":
                m = EV.apply_preset(d.get("name", ""))
                return self._json(m if m else {"error": "unknown preset"},
                                  200 if m else 400)
            if p == "/api/ring":
                import math
                lat = float(d.get("lat", 0.0)); lng = float(d.get("lng", 0.0))
                n = max(1, min(24, int(d.get("count", 8))))
                r_m = max(10.0, min(500.0, float(d.get("radius_m", 60))))
                gym = bool(d.get("gym", True))
                made = []
                for i in range(n):
                    a = 2 * math.pi * i / n
                    dlat = (r_m * math.cos(a)) / 111320.0
                    dlng = (r_m * math.sin(a)) / (111320.0 * max(0.2, math.cos(math.radians(lat))))
                    made.append(PL.add_fort(lat + dlat, lng + dlng, "stop", f"Ring Stop {i+1}"))
                if gym:
                    made.append(PL.add_fort(lat, lng, "gym", "Home Gym"))
                return self._json({"placed": len(made)})
        except Exception as e:
            return self._json({"error": str(e)}, 400)
        self._send(404, "text/plain", "not found")


def serve(port=8080, host="127.0.0.1"):
    ThreadingHTTPServer((host, port), _Handler).serve_forever()


def start(port=8080, host="127.0.0.1"):
    t = threading.Thread(target=serve, kwargs={"port": port, "host": host}, daemon=True)
    t.start()
    return t
