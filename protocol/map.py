"""Map, fort, encounter, and gym-detail protocol builders."""
import hashlib as _hashlib
import math as _math
import os
import random as _random
import struct as _struct
import time

import pb
import s2sphere
import settings as _cfg
import world as _world
from protocol.inventory import (
    ITEM_GREAT_BALL,
    ITEM_POKE_BALL,
    ITEM_POTION,
    ITEM_RAZZ_BERRY,
    ITEM_REVIVE,
    ITEM_ULTRA_BALL,
)
from protocol.player import build_player_avatar, build_pokemon_data, default_gym_team

# ------------------------------------------------------------- GET_MAP_OBJECTS
import struct as _struct
import random as _random
import hashlib as _hashlib
import math as _math
import s2sphere
import world as _world


def _hex_id(seed, n=32):
    """Deterministic random-looking hex id, so fort/spawn ids look like the real
    Niantic ones ('108dc9c703a94b619a53a3c29b5c676f') rather than a padded int."""
    return _hashlib.md5(str(seed).encode()).hexdigest()[:n]

KANTO_MIN, KANTO_MAX = 1, 151        # all of Gen 1 (Kanto)


def _kanto_for(seed):
    # deterministic per-seed so a given cell always shows the same mon (no flicker)
    return _random.Random(seed).randint(KANTO_MIN, KANTO_MAX)


def _f64_to_double(v):
    return _struct.unpack("<d", _struct.pack("<Q", v))[0] if v is not None else 0.0


def parse_get_map_objects(msg: bytes):
    """GetMapObjectsMessage { cell_id=1 (repeated uint64 packed),
    since_timestamp_ms=2, latitude=3 double, longitude=4 double }."""
    f = pb.decode(msg)
    raw = pb.get(f, 1, pb.WT_LEN)
    cell_ids = []
    if isinstance(raw, bytes):
        pos = 0
        while pos < len(raw):
            v, pos = pb._read_varint(raw, pos)
            cell_ids.append(v)
    return cell_ids, _f64_to_double(pb.get(f, 3, pb.WT_64)), _f64_to_double(pb.get(f, 4, pb.WT_64))


def build_map_pokemon(spawn_id, encounter_id, pokemon_id, lat, lng, expire_ms) -> bytes:
    # MapPokemon { spawn_point_id=1, encounter_id=2 fixed64, pokemon_id=3,
    #   expiration_timestamp_ms=4, latitude=5, longitude=6 }
    # expiration is x1000 like MapCell.current_timestamp_ms -- POGOServer sends
    # `(getTime() + 1e6) * 1e3`. In plain ms the spawn reads as long expired and
    # the client filters it out before drawing.
    return (pb.Writer()
            .string(1, spawn_id)
            .fixed64(2, encounter_id)
            .uint(3, pokemon_id)
            .int_(4, expire_ms * 1000)
            .double(5, lat)
            .double(6, lng)
            .to_bytes())



def build_nearby_pokemon(pokemon_id, distance_m, encounter_id=None) -> bytes:
    # NearbyPokemon { pokemon_id=1, distance_in_meters=2 FLOAT, encounter_id=3 fixed64 }
    # The "nearby tracker" (bottom-right of the map). It draws from 2D icons bundled
    # in the APK, so it shows up even when a 3D model bundle doesn't load.
    # POGOServer omits encounter_id here, so it's optional for us too.
    w = pb.Writer().uint(1, pokemon_id).float_(2, float(distance_m))
    if encounter_id is not None:
        w.fixed64(3, encounter_id)
    return w.to_bytes()


def build_spawn_point(lat, lng) -> bytes:
    # SpawnPoint { latitude=2, longitude=3 }  (note: no field 1)
    return pb.Writer().double(2, lat).double(3, lng).to_bytes()


def build_wild_pokemon(encounter_id, lat, lng, spawn_id, pokemon_id, now_ms,
                       time_till_hidden_ms=15 * 60 * 1000, cp=500) -> bytes:
    # WildPokemon { encounter_id=1 fixed64, last_modified_ts=2 int64,
    #   latitude=3 double, longitude=4 double, spawnpoint_id=5 string,
    #   pokemon_data=7 PokemonData, time_till_hidden_ms=11 int32 }
    # (VERIFIED against POGOProtos 2016 layout — the 0.29 client renders the
    #  live map spawns from THIS list, not catchable_pokemons.)
    return (pb.Writer()
            .fixed64(1, encounter_id)
            .int_(2, now_ms)
            .double(3, lat)
            .double(4, lng)
            .string(5, spawn_id)
            .message(7, build_pokemon_data(pokemon_id, encounter_id, cp))
            .uint(11, time_till_hidden_ms)
            .to_bytes())


def build_fort(fort_id, lat, lng, now_ms, is_gym=False) -> bytes:
    # FortData { id=1, last_modified_ts=2, latitude=3, longitude=4,
    #   owned_by_team=5, guard_pokemon_id=6, guard_pokemon_cp=7, enabled=8,
    #   type=9, gym_points=10, is_in_battle=11,
    #   cooldown_complete_timestamp_ms=14 }
    w = (pb.Writer()
         .string(1, fort_id)
         .int_(2, now_ms)
         .double(3, lat)
         .double(4, lng))

    if not is_gym:
        import world

        _m = world.fort_modifier(fort_id)
        if _m:
            w.uint(12, int(_m["item"]))

        _p = world.current()
        _cooldowns = getattr(_p, "POKESTOP_COOLDOWNS", {})
        _cooldown_until = int(_cooldowns.get(str(fort_id), 0) or 0)
        if _cooldown_until > now_ms:
            w.int_(14, _cooldown_until)

    if is_gym:
        import world
        guard = world.gym_guard(fort_id)
        if guard:
            pid, cp, points = guard
            w.uint(5, world.gym_team(fort_id) or default_gym_team()).uint(6, pid).int_(7, cp)
        else:
            points = 0
            w.uint(5, 0)
        w.bool_(8, True).uint(9, 0).int_(10, points).bool_(11, False)
    else:
        w.bool_(8, True).uint(9, 1)

    return w.to_bytes()


# ----------------------------------------------------- FORT_DETAILS / SEARCH
# Personalized names; chosen deterministically per fort_id so each stop/gym keeps
# its name. (Edit these to taste.)
STOP_NAMES = [
    "Dad's PokeStop", "Home Sweet Home", "The Backyard", "Front Porch Stop",
    "Memory Lane Marker", "Old Neighborhood Stop", "Kanto Korner", "The Big Oak",
    "Mailbox Marker", "Garden Gnome", "Corner Hangout", "The Birdhouse",
    "Sunset Bench", "Grandpa's Spot", "The Lucky Tree",
]
GYM_NAMES = [
    "Dad's Gym", "Home Field Arena", "The Backyard Battleground",
    "Neighborhood Gym", "Living Room League",
]


def _fort_is_gym(fort_id: str) -> bool:
    # Fort ids use the real Niantic shape "<32 hex>.<n>" where the suffix encodes the
    # type (16 = Gym, 11 = PokeStop). The old "GYM"/"FORT" prefix check stopped working
    # when the ids were made authentic, which made every Gym report as a PokeStop.
    return fort_id.rsplit(".", 1)[-1] == "16"


def l17_forts(cid15, now_ms):
    """Forts for ONE requested level-15 cell (~300m across).

    Real 2016 GetMapObjects returns only a HANDFUL of forts per level-15 cell.
    We used to emit 1 Gym + 3 stops in each of the 16 level-17 children = 64 forts
    in a single cell, which is wildly denser than anything Niantic ever sent; a
    client that sanity-checks cell contents can reject the batch outright. Emit a
    realistic 2-3 forts per cell, spread over the cell, deterministic per cell id.
    """
    out = []
    try:
        rnd = _random.Random(cid15 ^ 0xF0E7)
        kids = _l17_centres(cid15)
        if not kids:
            return out                                     # 16 level-17
        per = max(0, _cfg.get("pokestops", "per_l15_cell", cast=int))
        gym_chance = _cfg.get("gyms", "chance_per_l15_cell", cast=float)
        # Sit each stop on a DIFFERENT level-17 child so several in one cell are
        # properly spread out rather than clustered at the centre.
        picks = rnd.sample(kids, min(per + 1, len(kids)))
        for kid, klat, klng in picks[:per]:
            out.append(build_fort(f"{_hex_id(kid)}.11", klat, klng,
                                  now_ms, is_gym=False))
        if rnd.random() < gym_chance and len(picks) > per:
            kid, klat, klng = picks[per]
            out.append(build_fort(f"{_hex_id(kid)}.16", klat, klng,
                                  now_ms, is_gym=True))
    except Exception:
        pass
    return out


def build_fort_details_response(fort_id, lat, lng) -> bytes:
    # FortDetailsResponse { fort_id=1, team_color=2, name=4, image_urls=5,
    #   type=9 (GYM=0, CHECKPOINT=1), latitude=10, longitude=11, description=12 }
    gym = _fort_is_gym(fort_id)
    names = GYM_NAMES if gym else STOP_NAMES
    import world as _w
    _mod = None if gym else _w.fort_modifier(fort_id)
    name = _PLACED_NAMES.get(fort_id) or names[abs(hash(fort_id)) % len(names)]
    w = (pb.Writer()
         .string(1, fort_id)
         .string(4, name))
    # FortDetailsResponse.image_urls = 5 -- always at least one, same reason.
    w.string(5, _fort_image_url(fort_id))
    w.uint(9, 0 if gym else 1)
    w.double(10, lat)
    w.double(11, lng)
    w.string(12, "A little piece of home.")
    if _mod:
        # On the DETAIL screen the lure is a full message -- FortDetailsOutProto
        # .Modifier = 13, ClientFortModifierProto{ type=1, expires=2, by=3 }.
        w.message(13, pb.Writer()
                  .uint(1, int(_mod["item"]))
                  .int_(2, int(_mod["expires_ms"]))
                  .string(3, str(_mod.get("by", "")))
                  .to_bytes())
    return w.to_bytes()


def build_item_award(item_id, count) -> bytes:
    return pb.Writer().uint(1, item_id).int_(2, count).to_bytes()


# ------------------------------------------------------ ENCOUNTER / CATCH




# ActivityType values used for catch bonuses

# Throw quality comes from normalized_reticle_size: the ring shrinks as you hold,
# and a bigger number means a tighter ring. Thresholds match the 2016 game.













# --------------------------------------------------------------- GYMS / ITEMS
def build_gym_membership(m) -> bytes:
    """GymMembership { pokemon_data=1, trainer_public_profile=2 }.
    PlayerPublicProfile { name=1, level=2, avatar=3 }. We used to send only the
    Pokemon; a membership with no trainer attached is a likely null/index crash in
    the gym screen, so always include the owner."""
    import world
    lvl, _ = world.stats()
    profile = (pb.Writer()
               .string(1, m.get("trainer") or "Trainer")
               .int_(2, lvl)
               .message(3, build_player_avatar(world.avatar_for(m.get("owner")
                                                                or m.get("trainer"))))
               .to_bytes())
    return (pb.Writer()
            .message(1, build_pokemon_data(m["pokemon_id"], m["uid"], m["cp"]))
            .message(2, profile)
            .to_bytes())


def parse_gym_details(msg):
    """GetGymDetailsMessage { gym_id=1, player_latitude=2, player_longitude=3,
    gym_latitude=4, gym_longitude=5 }.

    NOTE this differs from FortDetailsMessage, where 2/3 ARE the fort's position.
    Reusing the fort parser here put the Gym's FortData at the PLAYER's coordinates,
    so the gym the client got back wasn't where the map said it was -- and it
    refused to open."""
    f = pb.decode(msg)
    gid = pb.get(f, 1, pb.WT_LEN)
    return (gid.decode("utf-8", "replace") if isinstance(gid, bytes) else "",
            _f64_to_double(pb.get(f, 4, pb.WT_64)),      # gym latitude
            _f64_to_double(pb.get(f, 5, pb.WT_64)))      # gym longitude


def build_gym_details_response(fort_id, lat, lng, now_ms) -> bytes:
    """GetGymDetailsResponse { gym_state=1, name=2, urls=3, result=4, description=5 }
    Result: 1=SUCCESS, 2=ERROR_NOT_IN_RANGE.
    GymState { fort_data=1, memberships=2 }; GymMembership { pokemon_data=1,
    trainer_public_profile=2 }. Without this the client can't open a Gym at all."""
    import world
    name = _PLACED_NAMES.get(fort_id) or GYM_NAMES[abs(hash(fort_id)) % len(GYM_NAMES)]
    fort = build_fort(fort_id, lat, lng, now_ms, is_gym=True)
    gs = pb.Writer().message(1, fort)
    for m in world.gym_members(fort_id):
        gs.message(2, build_gym_membership(m))
    w = (pb.Writer()
         .message(1, gs.to_bytes())
         .string(2, name))
    w.string(3, _fort_image_url(fort_id))                 # urls = 3, never empty
    return (w
            .uint(4, 1)                                   # SUCCESS
            .string(5, "A gym in your neighbourhood.")
            .to_bytes())


def parse_deploy(msg):
    """FortDeployPokemonMessage { fort_id=1, pokemon_id=2 fixed64, lat=3, lng=4 }."""
    f = pb.decode(msg)
    fid = pb.get(f, 1, pb.WT_LEN)
    return (fid.decode("utf-8", "replace") if isinstance(fid, bytes) else "",
            pb.get(f, 2, pb.WT_64) or 0)


def build_fort_deploy_response(fort_id, uid, lat, lng, now_ms) -> bytes:
    """FortDeployPokemonResponse { result=1, fort_details=2, pokemon_data=3, gym_state=4 }
    Result: 1=SUCCESS, 2=ALREADY_HAS_POKEMON, 4=FORT_IS_FULL, 5=NOT_IN_RANGE,
    6=PLAYER_HAS_NO_TEAM."""
    import world
    ok, why = world.deploy(fort_id, uid)
    if not ok:
        code = 2 if why == "already deployed" else (4 if why == "gym full" else 5)
        return pb.Writer().uint(1, code).to_bytes()
    c = world.get_caught(uid) or {"pokemon_id": 1, "cp": 100}
    gs = pb.Writer().message(1, build_fort(fort_id, lat, lng, now_ms, is_gym=True))
    for m in world.gym_members(fort_id):
        gs.message(2, build_gym_membership(m))
    return (pb.Writer()
            .uint(1, 1)                                   # SUCCESS
            .message(3, build_pokemon_data(c["pokemon_id"], uid, c["cp"]))
            .message(4, gs.to_bytes())
            .to_bytes())


def build_fort_search_response(fort_id, now_ms) -> bytes:
    # FortSearchResponse { result=1, items_awarded=2,
    #   experience_awarded=5, cooldown_complete_timestamp_ms=6 }.
    import world

    cooldown_ms = int(
        _cfg.get("pokestops", "cooldown_minutes", cast=float) * 60_000
    )
    fid = str(fort_id)
    p = world.current()

    # Check + reserve atomically. This prevents concurrent requests from
    # both receiving a reward during the same cooldown window.
    with world._lock:
        cooldowns = getattr(p, "POKESTOP_COOLDOWNS", None)
        if cooldowns is None:
            cooldowns = {}
            p.POKESTOP_COOLDOWNS = cooldowns

        current_cooldown = int(cooldowns.get(fid, 0) or 0)
        if current_cooldown > now_ms:
            return (pb.Writer()
                    .uint(1, 3)          # COOLDOWN
                    .int_(6, current_cooldown)
                    .to_bytes())

        room = world.room_in_bag()
        if room <= 0:
            return pb.Writer().uint(1, 4).to_bytes()  # INVENTORY_FULL

    rnd = _random.Random(hash(fid) ^ (now_ms // 300000))
    _lo = _cfg.get("pokestops", "min_items_per_spin", cast=int)
    _hi = max(_lo, _cfg.get("pokestops", "max_items_per_spin", cast=int))

    awards = [
        (ITEM_POTION, rnd.randint(1, 2)),
        (ITEM_REVIVE, 1),
    ]
    if rnd.random() < _cfg.get("pokestops", "great_ball_chance", cast=float):
        awards.append((ITEM_GREAT_BALL, rnd.randint(1, 2)))
    if rnd.random() < _cfg.get("pokestops", "ultra_ball_chance", cast=float):
        awards.append((ITEM_ULTRA_BALL, 1))
    if rnd.random() < _cfg.get("pokestops", "razz_berry_chance", cast=float):
        awards.append((ITEM_RAZZ_BERRY, rnd.randint(1, 2)))

    other = sum(c for _i, c in awards)
    awards.insert(0, (ITEM_POKE_BALL, max(rnd.randint(1, 3), _lo - other)))

    total = sum(c for _i, c in awards)
    for i in range(len(awards) - 1, -1, -1):
        if total <= _hi:
            break
        iid, cnt = awards[i]
        take = min(cnt - 1, total - _hi)
        if take > 0:
            awards[i] = (iid, cnt - take)
            total -= take

    # Re-check bag capacity and reserve the cooldown under the same lock.
    with world._lock:
        room = world.room_in_bag()
        if room <= 0:
            return pb.Writer().uint(1, 4).to_bytes()

        if sum(c for _i, c in awards) > room:
            trimmed, left = [], room
            for iid, cnt in awards:
                if left <= 0:
                    break
                take = min(cnt, left)
                if take > 0:
                    trimmed.append((iid, take))
                    left -= take
            awards = trimmed

        cooldown_until = now_ms + cooldown_ms
        cooldowns[fid] = cooldown_until

    w = pb.Writer().uint(1, 1)  # SUCCESS

    if rnd.random() < _cfg.get("eggs", "drop_chance", cast=float):
        tier = rnd.choices(EGG_TIERS, weights=(60, 30, 10))[0]
        world.give_egg(tier)

    world.bump("poke_stop_visits")
    xp = _cfg.get("pokestops", "xp_per_spin", cast=int)
    world.add_xp(xp)

    for iid, cnt in awards:
        w.message(2, build_item_award(iid, cnt))
        world.add_item(iid, cnt)

    return (w.int_(5, xp)
             .int_(6, cooldown_until)
             .to_bytes())


def parse_fort_request(msg):
    """fort_id + lat/lng from a FortDetails/FortSearch message."""
    f = pb.decode(msg)
    fid = pb.get(f, 1, pb.WT_LEN)
    fid = fid.decode("utf-8", "replace") if isinstance(fid, bytes) else ""
    return fid, _f64_to_double(pb.get(f, 2, pb.WT_64)), _f64_to_double(pb.get(f, 3, pb.WT_64))


def build_map_cell(cell_id, now_ms, catchable=(), forts=(), wild=(),
                   spawn_points=(), nearby=()) -> bytes:
    # MapCell { s2_cell_id=1, current_timestamp_ms=2, forts=3, spawn_points=4,
    #   wild_pokemons=5, catchable_pokemons=10, nearby_pokemons=11 }
    # (field numbers VERIFIED against POGOProtos MapCell.proto)
    #
    # NOTE the x1000 on the timestamp. Despite the "_ms" name, the working
    # maierfelix/POGOServer sends `new Date().getTime() * 1e3` here (microseconds),
    # while leaving fort/pokemon last_modified_timestamp_ms in plain ms. Sending
    # plain ms makes the cell look ancient to the client, which then discards the
    # whole cell -- no forts, no Pokemon, nothing.
    w = pb.Writer().uint(1, cell_id).int_(2, now_ms * 1000)
    for f in forts:
        w.message(3, f)
    for sp in spawn_points:
        w.message(4, sp)
    for wp in wild:
        w.message(5, wp)
    for c in catchable:
        w.message(10, c)
    for nb in nearby:
        w.message(11, nb)
    return w.to_bytes()


def _cell_center(cid):
    try:
        c = s2sphere.CellId(cid)
        if c.level() == 15:
            ll = s2sphere.LatLng.from_point(s2sphere.Cell(c).get_center())
            return ll.lat().degrees, ll.lng().degrees
    except Exception:
        pass
    return None


_FORCE_POKEMON = int(os.environ.get("FORCE_POKEMON", "0"))   # spawn only this id (debug)
_PLACED_NAMES = {}      # fort_id -> user-given name (World Manager placements)
_PLACED_IMAGES = {}     # fort_id -> user-given photo (url or photos/ filename)

# A fort MUST come back with at least one image url: the gym screen indexes
# urls[0] and threw ArgumentOutOfRangeException ("Promise<T>.Then<T> threw an
# exception") when we sent an empty list for a photo-less gym. This little PNG is
# served at /fortimg/_default.png whenever the user hasn't set their own picture.
DEFAULT_FORT_IMAGE = "_default.png"
_DEFAULT_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAQAAAAEACAIAAADTED8xAAAEZklEQVR42u3dsVUrQQyFYS3HVbkSAgpwGS7CJRBQFxEhJRCQOgCMvRrd78/fg9HcX5pdfMbb8XQpIJUnJQABAAIABAAIABAAIABAAIAAAAEAAgAEAAgAEAAgAEAAgAAAAQACAAQACAAQACAAQACAAAABAAIABAAIABAAIABAAIAAAAEAAgAEAAgAEAAgAEAAgAAAAQACAAQACAAQACAAcJ2DEjyGt/PLb//J8/lV3e7NdjxdVGH3rLOCAEJPBgIIPRkIIPdMIIDcM4EAok8DAog+DQgg+jQggOjTgACiTwMCiD4NyofhpN/aTQDbbxSYANKvGiaAzTYKTADpVx8C2F1VcgQSfcchE0D61S1cAOlXvVwBpF8NcwWQfpXMFUD61TNXAOlX1VwBpF9tcwWQfhXOFUD61TlXAOlX7VwBpF/NHYGASAG0f5XPFUD61T9XAOm3C45AQKQA2r+9yBVA+u2IIxAQKYD2b19yBZB+u1O+J7hG37NA8nItyphk3Hi5SOCSTQCX6lz5f4yF9AmwRAIe0PzUwQSI3vLvH2QgZE2Azvu9Y7dTlvKHsORt9h1HEROgZ59rFT4lMgGit9YoGCtAw97WM20Nf6v+T+reAo1qtF4QTZsArfZylWOGhxPPAOmHbI8EBEjPEweWF8BZtnxG2gTQSg0BAsgQB8IE6DA3Z6SnwyranoJMAJgAmH54cBAiQHpiOLCSAF6AlpehJoBmaV0EAAigTVpdjgAeADwGmAAAAZwQrJEAAAGAu7C9f3yqAkwAgAAAAQACAAQACAAQACAAQACAAAABAAIABAAIABAAIABAAIAAAAEAAgAt2Y6nS7k/rLLuzFFhEwAgAAigBGn38rp7mABAYwHc3lru5TUBnBCsjgAAAbRJ60oTwGOABwATQLO0IgJIjLUQAIgToMORcUbj7LCKtg91JsBwBxx+CJCbIelfWwAvQ8sLUBNAK9X+CSBP0h8pQKvpuUqqWv2ezc+xBz3gD9lqu6ka/8AjUMO09cxZw9+q/2sMzwBD0qb315hrUdba4N2bnMqYALn50/hTJkD/zX5ww1ON8hYo8wWRrh86Adba+383IXntJsDCzwY3pkG/NwHmBOKHMiSs0QTwygjlNajPSJdPPhOAA9JPAIAAhoAdIQAH7AUBAAIYAnaBABxQfwJwQOUJABDAEFBzAnBAtQnAAXUmAAdUmAAcUFsCcEBVCcAB9SQAB1SSABxQQ38J5oDqxX8UggPqVmOuRSmXMoi+CWBfVYkAdld9HIEch0TfBLDfqmECGAWibwJIgLWbAEaB6BOABqJPABqIPgFoIPoE8J00IECSBqJPAF/QCwJkmCD3BIiTQegJECeD0BMgxQpZJwBQPgwHEAAgAEAAgAAAAQACAAQACAAQACAAQACAAAABAAIABAAIABAAIAAIABAAIABAAIAAAAEAAgAEAAgAEAAgAEAAgAAAAQACAAQACAAQACAAQACAAAABAAIABAAIABAAIACwG19/ntxysev+5gAAAABJRU5ErkJggg=="


def default_fort_png():
    import base64
    return base64.b64decode(_DEFAULT_PNG_B64)


def _fort_image_url(fort_id):
    img = _PLACED_IMAGES.get(fort_id) or DEFAULT_FORT_IMAGE
    return (img if img.lower().startswith("http")
            else f"https://pgorelease.nianticlabs.com/fortimg/{img}")


def _event_cfg():
    """Live event settings (events.json), hot-reloaded. Falls back to defaults."""
    try:
        import events
        return events.get()
    except Exception:
        return {"species_mode": "all", "species_list": [25], "single_species": 25,
                "spawn_density": 6, "min_cp": 100, "max_cp": 1200}


# ------------------------------------------------- realistic spawn distribution
# A uniform randint(1,151) meant Mewtwo was as common as a Pidgey. These tiers
# reproduce the feel of a normal 2016 day: mostly city-trash Pokemon, occasional
# evolved ones, rare starters/pseudo-legendaries, and NO legendaries in the wild.
# (Legendary Hunt and the other presets still force them via species_mode.)
_LEGENDARY = {144, 145, 146, 150, 151}          # never spawn naturally
_RARE = {1, 2, 3, 4, 5, 6, 7, 8, 9,             # starters + their lines
         63, 65, 68, 71, 76, 94, 97, 113, 115, 122, 123, 124, 125, 126, 127,
         128, 131, 134, 135, 136, 137, 138, 139, 140, 141, 142, 143, 147, 148, 149}
_UNCOMMON = {17, 20, 22, 24, 25, 26, 28, 30, 33, 36, 38, 40, 42, 44, 45, 47, 49,
             51, 53, 55, 57, 59, 61, 62, 64, 67, 70, 73, 75, 78, 80, 82, 85, 87,
             89, 91, 93, 99, 101, 103, 105, 106, 107, 108, 110, 112, 114, 117,
             119, 121, 130, 132, 133}
_WEIGHTS = {"rare": 1, "uncommon": 5, "common": 20}
_POOL = None
_POOL_KEY = None


def _spawn_pool():
    """Weighted list of species for a 'normal day'. Rebuilt if the
    allow_legendaries setting changes."""
    global _POOL, _POOL_KEY
    allow_leg = _cfg.get("spawns", "allow_legendaries", cast=bool)
    if _POOL is None or _POOL_KEY != allow_leg:
        _POOL_KEY = allow_leg
        pool = []
        for pid in range(1, 152):
            if pid in _LEGENDARY and not allow_leg:
                continue
            tier = ("rare" if pid in _RARE else
                    "uncommon" if pid in _UNCOMMON else "common")
            pool += [pid] * _WEIGHTS[tier]
        _POOL = pool
    return _POOL


def _pick_species(rnd, cfg=None):
    """Which Pokemon spawns, honouring the event's species mode."""
    if _FORCE_POKEMON:
        return _FORCE_POKEMON
    c = cfg or _event_cfg()
    m = c.get("species_mode", "all")
    if m == "single":
        return int(c.get("single_species", 25))
    if m == "list":
        lst = c.get("species_list") or [25]
        return int(rnd.choice(lst))
    return int(rnd.choice(_spawn_pool()))


def _pick_cp(rnd, cfg=None):
    c = cfg or _event_cfg()
    lo = int(c.get("min_cp", _cfg.get("spawns", "min_cp", cast=int)))
    hi = int(c.get("max_cp", _cfg.get("spawns", "max_cp", cast=int)))
    return rnd.randint(min(lo, hi), max(lo, hi))
# Wild Pokemon rotate on a fixed clock: every SPAWN_WINDOW_MIN minutes the whole
# map re-rolls. Spawn ids/species are seeded from (cell, window), so a spawn lasts
# exactly one window and then a fresh set appears -- and a Pokemon you caught can
# be suppressed for the rest of its window instead of reappearing next refresh.
def _spawn_window_min():
    return _cfg.get("spawns", "refresh_minutes", env="SPAWN_WINDOW_MIN", cast=float)
def _near_player():
    return _cfg.get("spawns", "how_many_near_you", env="NEAR_PLAYER", cast=int)


def _config_generation():
    """Changes whenever events.json / settings.json / places.json is saved. Mixed
    into the spawn seed so editing a setting re-rolls the wild Pokemon IMMEDIATELY
    instead of waiting up to refresh_minutes for the next window."""
    gen = 0
    try:
        import events as _e, settings as _s, places as _p
        for f in (_e.EVENTS_FILE, _s.SETTINGS_FILE, _p.PLACES_FILE):
            try:
                gen ^= int(os.path.getmtime(f))
            except OSError:
                pass
    except Exception:
        pass
    return gen


def _window(now_ms):
    """(index of the current spawn window, ms at which it ends).

    The index also folds in a config generation, so a settings change re-rolls
    spawns straight away; the END time stays on the real clock so the client's
    despawn timers remain honest."""
    span = max(60_000, int(_spawn_window_min() * 60_000))
    idx = now_ms // span
    return (idx ^ (_config_generation() << 20)), (idx + 1) * span        # wild mons clustered on the trainer
                                                             # (real spawns are sparse; a huge
                                                             #  cluster looks bogus to the client)


_L17_CACHE = {}


def _l17_centres(cid15):
    """The 16 level-17 child centres of a level-15 cell, worked out once.

    Deriving these from s2sphere on every map refresh was one of the biggest
    remaining costs -- and the same handful of cells come round again and again
    as you walk, so caching them removes nearly all of it.
    """
    got = _L17_CACHE.get(cid15)
    if got is None:
        got = []
        try:
            c15 = s2sphere.CellId(cid15)
            if c15.level() == 15:
                for c16 in c15.children():
                    for c17 in c16.children():
                        ll = s2sphere.LatLng.from_point(
                            s2sphere.Cell(c17).get_center())
                        got.append((c17.id(), ll.lat().degrees, ll.lng().degrees))
        except Exception:
            got = []
        if len(_L17_CACHE) > 4000:          # bounded; walking can't grow it forever
            _L17_CACHE.clear()
        _L17_CACHE[cid15] = got
    return got


def build_get_map_objects_response(cell_ids, lat, lng) -> bytes:
    # GetMapObjectsResponse { map_cells=1, status=2 (1=SUCCESS), time_of_day=3 (1=DAY) }
    now = int(time.time() * 1000)
    # Everything in this batch belongs to the current spawn window and dies with it,
    # so the client's timers agree with when we actually re-roll.
    _win, _win_end = _window(now)
    expire = _win_end
    SPAWN_MS = max(60_000, _win_end - now)
    have_fix = abs(lat) > 1e-6 or abs(lng) > 1e-6

    # Answer with EXACTLY the cells the client asked for, in the SAME ORDER. The
    # client pairs cell_id[i] with since_timestamp_ms[i] in its request, so it treats
    # the response cell list positionally -- re-sorting them or appending extra cells
    # (which we used to do) desynchronises that mapping and the client silently drops
    # the whole batch. Only synthesise cells if it asked for none.
    cells = list(dict.fromkeys(cell_ids))          # requested cells (dedup, in order)
    if not cells and have_fix:
        pc = s2sphere.CellId.from_lat_lng(
            s2sphere.LatLng.from_degrees(lat, lng)).parent(15)
        cells = [pc.id()]
        try:
            cells += [n.id() for n in pc.get_edge_neighbors()]
        except Exception:
            pass

    # Which of the REQUESTED cells holds the player (that's where the dense cluster
    # goes). Prefer the exact level-15 parent; fall back to the nearest requested cell
    # so the trainer always has Pokemon at their feet even if the client's cell list
    # lags behind the GPS.
    player_cell = None
    if have_fix and cells:
        pid_cell = s2sphere.CellId.from_lat_lng(
            s2sphere.LatLng.from_degrees(lat, lng)).parent(15).id()
        if pid_cell in cells:
            player_cell = pid_cell
        else:
            def _cdist(cid):
                c = _cell_center(cid)
                return (c[0] - lat) ** 2 + (c[1] - lng) ** 2 if c else 9e9
            player_cell = min(cells, key=_cdist)

    # Per-request safety caps: the density settings are PER CELL and the client
    # asks for several cells at once, so a generous value multiplies quickly.
    # Without a ceiling one refresh can build a batch the client drops outright.
    MAX_FORTS = max(1, _cfg.get("pokestops", "max_per_request", cast=int))
    MAX_WILD = max(1, _cfg.get("spawns", "max_per_request", cast=int))
    _per_cell = max(0, _cfg.get("spawns", "per_l15_cell", cast=int))

    # live event settings drive species / CP / how many spawn around the trainer
    _ev = _event_cfg()
    _near_n = max(0, min(60, int(_ev.get("spawn_density", _near_player()))))

    # Hand-placed objects from the World Manager (places.json), bucketed by the
    # level-15 cell they fall in so they only ship with the cell that owns them.
    import places as _places
    _pl = _places.get()
    _placed_forts, _placed_spawns = {}, {}
    for _f in _pl["forts"]:
        try:
            _c = s2sphere.CellId.from_lat_lng(
                s2sphere.LatLng.from_degrees(_f["lat"], _f["lng"])).parent(15).id()
        except Exception:
            continue
        _placed_forts.setdefault(_c, []).append(_f)
    for _s in _pl["spawns"]:
        try:
            _c = s2sphere.CellId.from_lat_lng(
                s2sphere.LatLng.from_degrees(_s["lat"], _s["lng"])).parent(15).id()
        except Exception:
            continue
        _placed_spawns.setdefault(_c, []).append(_s)
    _proc_forts = _pl["procedural_forts"]
    _proc_spawns = _pl["procedural_spawns"]

    # Lured stops, and where each fort sits, so the lure cluster lands on it.
    _lured = _world.lured_forts()
    _fort_pos = {}
    for _f in _pl["forts"]:
        _gym = _f.get("kind") == "gym"
        _fort_pos[f"{_hex_id(_f['id'])}.{16 if _gym else 11}"] = (_f["lat"], _f["lng"])
    if _lured:
        for _cid2 in cells:
            for _kid, _kla, _kln in _l17_centres(_cid2):
                _fort_pos.setdefault(f"{_hex_id(_kid)}.11", (_kla, _kln))

    def _cell_of(la, ln):
        try:
            return s2sphere.CellId.from_lat_lng(
                s2sphere.LatLng.from_degrees(la, ln)).parent(15).id()
        except Exception:
            return None

    # Spread the wild-Pokemon budget by DISTANCE. Filling far-away cells first
    # and then hitting the cap left the player surrounded by nothing, and handing
    # the client 180+ Pokemon at once is what makes a 2016 phone fall over. The
    # cells you can actually walk to get the full density; the rest get a taste.
    _budget = {}
    if cells:
        def _cdist2(cid):
            c = _cell_center(cid)
            return ((c[0] - lat) ** 2 + (c[1] - lng) ** 2) if c else 9e9
        _ranked = sorted(cells, key=_cdist2)
        _left = MAX_WILD
        for _rank, _cid3 in enumerate(_ranked):
            if _rank == 0:
                _share = _per_cell                       # the cell you stand in
            elif _rank <= 4:
                _share = max(1, _per_cell // 2)          # the ring around you
            else:
                _share = max(1, _per_cell // 4)          # distant scenery
            _share = min(_share, max(0, _left))
            _budget[_cid3] = _share
            _left -= _share

    w = pb.Writer()
    spawned = forts_n = wild_n = 0
    for cid in cells:
        catch, forts, wild, spawns, nearby = [], [], [], [], []
        ctr = _cell_center(cid)
        if ctr and _proc_spawns and wild_n < MAX_WILD:
            # Wild Pokemon in EVERY level-17 child of this cell (16 of them), rather
            # than one at the level-15 centre. Seeded per (l17 cell, index, window)
            # so the map is stable for the whole window and re-rolls with it.
            _kids = _l17_centres(cid)
            for k in range(_budget.get(cid, 0)):
                if wild_n >= MAX_WILD or not _kids:
                    break
                # Spread them over the level-15 cell by walking its level-17
                # children in turn, then jittering inside whichever one we land on.
                _kid, _clat, _clng = _kids[k % len(_kids)]
                seed = (_kid ^ (_win * 0x9E3779B97F4A7C15)
                        ^ (k * 0x2545F4914F6CDD1D)) & ((1 << 63) - 1)
                rnd = _random.Random(seed)
                pid = _pick_species(rnd, _ev)
                eid = (seed ^ 0x5BD1E995ABCD) & ((1 << 63) - 1)
                sid = _hex_id((_kid, k), 11)
                _cp = _pick_cp(rnd, _ev)
                # scatter inside the level-17 cell (~75m across) so they don't sit
                # in a visible grid as you walk
                jl = _clat + (rnd.random() - 0.5) * 0.00060
                jn = _clng + (rnd.random() - 0.5) * 0.00060
                # skip it if it was already caught during this window, otherwise
                # the next map refresh hands the same Pokemon straight back
                if _world.is_despawned(eid):
                    continue
                wild.append(build_wild_pokemon(eid, jl, jn, sid, pid, now,
                                               SPAWN_MS, cp=_cp))
                catch.append(build_map_pokemon(sid, eid, pid, jl, jn, expire))
                _world.remember_spawn(eid, pid, jl, jn, _cp, sid, expire)
                spawns.append(build_spawn_point(jl, jn))
                nearby.append(build_nearby_pokemon(pid, 120.0))
                wild_n += 1
        if cid == player_cell and _proc_spawns:
            # a cluster of wild Pokemon right around the trainer (spread within ~65m)
            # so there are always plenty in view no matter which way you look
            for k in range(_near_n):
                r = _random.Random(cid ^ (_win * 0x9E3779B97F4A7C15)
                                    ^ (k * 0x2545F4914F6CDD1D))
                pid2 = _pick_species(r, _ev)
                # Spread them around the trainer instead of stacking them on the
                # same spot: each one gets its own angular slice, at 25-65m. That
                # keeps them inside MapSettings.pokemon_visible_range (~70m) while
                # leaving real walking distance between them.
                ang = (2 * _math.pi * k / max(1, _near_n)) + r.uniform(-0.35, 0.35)
                _d0 = _cfg.get("spawns", "nearest_distance_m", cast=float)
                _d1 = _cfg.get("spawns", "farthest_distance_m", cast=float)
                dist = _d0 + r.random() * max(1.0, _d1 - _d0)     # metres
                dlat = lat + (dist * _math.cos(ang)) / 111320.0
                dlng = lng + (dist * _math.sin(ang)) / (
                    111320.0 * max(0.2, _math.cos(_math.radians(lat))))
                eid2 = (cid ^ (0x1234ABCD5678 + k * 0x9E3779B1)
                        ^ (_win * 0x85EBCA6B)) & ((1 << 63) - 1)
                sid2 = _hex_id((cid, k), 11)
                _cp2 = _pick_cp(r, _ev)
                if _world.is_despawned(eid2):   # already caught in this window
                    continue
                wild.append(build_wild_pokemon(eid2, dlat, dlng, sid2, pid2, now,
                                               SPAWN_MS, cp=_cp2))
                catch.append(build_map_pokemon(sid2, eid2, pid2, dlat, dlng, expire))
                _world.remember_spawn(eid2, pid2, dlat, dlng, _cp2, sid2, expire)
                spawns.append(build_spawn_point(dlat, dlng))
                nearby.append(build_nearby_pokemon(pid2, 10.0 + k * 5))
        if _proc_forts and forts_n < MAX_FORTS:
            forts = l17_forts(cid, now)[:max(0, MAX_FORTS - forts_n)]
            forts_n += len(forts)
        if cid == player_cell and _proc_forts:
            # PokeStops at level-17 cell centres can land 100-150m away, well outside
            # the ~40m spin radius -- they draw on the map but stay grey/unspinnable.
            # Anchor a couple right next to the trainer (POGOServer does exactly this:
            # lat+0.0002, lng-0.0001 ~= 22m). ~0.00009 deg ~= 10m.
            near = [(0.00020, -0.00010, False),    # PokeStop ~24m NW
                    (-0.00012, 0.00016, False),    # PokeStop ~22m SE
                    (0.00025, 0.00028, True)]      # Gym ~40m NE
            for j, (dla, dln, is_gym) in enumerate(near):
                fid = f"{_hex_id((cid, 'near', j))}.{16 if is_gym else 11}"
                forts = list(forts) + [build_fort(fid, lat + dla, lng + dln,
                                                  now, is_gym=is_gym)]
            forts_n += len(near)
        # --- hand-placed objects from the World Manager -------------------
        for _f in _placed_forts.get(cid, []):
            _gym = _f.get("kind") == "gym"
            forts = list(forts) + [build_fort(
                f"{_hex_id(_f['id'])}.{16 if _gym else 11}",
                _f["lat"], _f["lng"], now, is_gym=_gym)]
            _fid = f"{_hex_id(_f['id'])}.{16 if _gym else 11}"
            _PLACED_NAMES[_fid] = _f.get("name", "")
            if _f.get("image"):
                _PLACED_IMAGES[_fid] = _f["image"]
            forts_n += 1
        for _s in _placed_spawns.get(cid, []):
            _pid = int(_s.get("pokemon_id", 0) or 0)
            if _pid == 0:                      # "random spawn point"
                _pid = _pick_species(_random.Random(now // 600000 ^ hash(_s["id"])), _ev)
            _eid = (hash(_s["id"]) ^ 0x50AC3D) & ((1 << 62) - 1)
            _sid = _hex_id(_s["id"], 11)
            _pcp = 200 + (_eid % 800)
            wild.append(build_wild_pokemon(_eid, _s["lat"], _s["lng"], _sid, _pid,
                                           now, SPAWN_MS, cp=_pcp))
            catch.append(build_map_pokemon(_sid, _eid, _pid, _s["lat"], _s["lng"], expire))
            _world.remember_spawn(_eid, _pid, _s["lat"], _s["lng"], _pcp, _sid, expire)
            spawns.append(build_spawn_point(_s["lat"], _s["lng"]))
            nearby.append(build_nearby_pokemon(_pid, 20.0))

        # Incense: more wild Pokemon around the trainer while it burns.
        if cid == player_cell and _proc_spawns and _world.item_active(401):
            _n = _cfg.get("boosts", "incense_extra_spawns", cast=int)
            for k in range(_n):
                r = _random.Random((cid ^ (_win * 0x9E3779B1) ^ (k * 0x51ED2701)
                                    ^ 0x1CE45E) & 0x7FFFFFFF)
                ang = 2 * _math.pi * k / max(1, _n) + r.uniform(-0.3, 0.3)
                dist = 18.0 + r.random() * 40.0
                dl = lat + (dist * _math.cos(ang)) / 111320.0
                dn = lng + (dist * _math.sin(ang)) / (
                    111320.0 * max(0.2, _math.cos(_math.radians(lat))))
                eid = (cid ^ 0x1CE45E ^ (k * 0x9E3779B1) ^ (_win * 0x85EBCA6B)) & ((1 << 62) - 1)
                if _world.is_despawned(eid):
                    continue
                pid = _pick_species(r, _ev)
                cp = _pick_cp(r, _ev)
                sid = _hex_id((eid, "inc"), 11)
                wild.append(build_wild_pokemon(eid, dl, dn, sid, pid, now, SPAWN_MS, cp=cp))
                catch.append(build_map_pokemon(sid, eid, pid, dl, dn, expire))
                _world.remember_spawn(eid, pid, dl, dn, cp, sid, expire)
                spawns.append(build_spawn_point(dl, dn))
                nearby.append(build_nearby_pokemon(pid, 15.0))

        # Lures: extra Pokemon clustered on any lured stop in this cell.
        if _proc_spawns:
            for _lf, _lm in _lured.items():
                _pos = _fort_pos.get(_lf)
                if not _pos or _cell_of(_pos[0], _pos[1]) != cid:
                    continue
                _n = _cfg.get("boosts", "lure_extra_spawns", cast=int)
                for k in range(_n):
                    r = _random.Random((hash(_lf) ^ (_win * 0x9E3779B1)
                                        ^ (k * 0x2545F491)) & 0x7FFFFFFF)
                    ang = 2 * _math.pi * k / max(1, _n) + r.uniform(-0.4, 0.4)
                    dist = 8.0 + r.random() * 22.0
                    dl = _pos[0] + (dist * _math.cos(ang)) / 111320.0
                    dn = _pos[1] + (dist * _math.sin(ang)) / (
                        111320.0 * max(0.2, _math.cos(_math.radians(_pos[0]))))
                    eid = (hash(_lf) ^ 0x1D4E ^ (k * 0x9E3779B1)
                           ^ (_win * 0x85EBCA6B)) & ((1 << 62) - 1)
                    if _world.is_despawned(eid):
                        continue
                    pid = _pick_species(r, _ev)
                    cp = _pick_cp(r, _ev)
                    sid = _hex_id((eid, "lure"), 11)
                    wild.append(build_wild_pokemon(eid, dl, dn, sid, pid, now, SPAWN_MS, cp=cp))
                    catch.append(build_map_pokemon(sid, eid, pid, dl, dn, expire))
                    _world.remember_spawn(eid, pid, dl, dn, cp, sid, expire)
                    spawns.append(build_spawn_point(dl, dn))
                    nearby.append(build_nearby_pokemon(pid, 12.0))

        # A defeated raid boss waiting at the trainer's feet (their cell only).
        if cid == player_cell:
            for _b in _world.bonus_spawns(_world.current().username):
                if _world.is_despawned(_b["eid"]):
                    continue
                _bsid = _hex_id((_b["eid"], "raid"), 11)
                wild.append(build_wild_pokemon(_b["eid"], _b["lat"], _b["lng"],
                                               _bsid, _b["pid"], now,
                                               max(60_000, _b["expires_ms"] - now),
                                               cp=_b["cp"]))
                catch.append(build_map_pokemon(_bsid, _b["eid"], _b["pid"],
                                               _b["lat"], _b["lng"], _b["expires_ms"]))
                _world.remember_spawn(_b["eid"], _b["pid"], _b["lat"], _b["lng"],
                                      _b["cp"], _bsid, _b["expires_ms"])
                spawns.append(build_spawn_point(_b["lat"], _b["lng"]))
                nearby.append(build_nearby_pokemon(_b["pid"], 5.0))

        spawned += len(wild)
        w.message(1, build_map_cell(cid, now, catch, forts, wild,
                                    spawn_points=spawns, nearby=nearby))
    w.uint(2, 1).uint(3, 1)   # status=SUCCESS, time_of_day=DAY
    # NOTE: POGOServer (0.35) omits time_of_day, but the 0.29 client defaults to
    # NIGHT without it -- the encounter screen renders black. Keep sending DAY.
    tag = "real fix -> spawns at player" if have_fix else "NO-GPS-FIX (0,0)"
    print(f"   [map] {len(cell_ids)} req cells, {len(cells)} sent; "
          f"player ({lat:.5f},{lng:.5f}) [{tag}]; "
          f"{spawned} mons, {forts_n} stops/gyms", flush=True)
    return w.to_bytes()
