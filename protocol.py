"""
PoGO 0.29 RPC protocol: field-number map + message builders.

Field numbers/enum values are the canonical community POGOProtos values for
this era. They are kept as NAMED CONSTANTS in one place so that if the real
client's logged layout (see rpc.py request dumps) ever disagrees, it's a
one-line fix. The request side is parsed generically (pb.decode), so only the
RESPONSE builders below depend on these numbers being right.
"""
import os
import time
import pb
import settings as _cfg

__path__ = [os.path.join(os.path.dirname(__file__), "protocol")]

# ----------------------------------------------------------- RequestEnvelope
# (request side — VERIFIED against the real 0.29 client's raw envelope dump:
#  #1 status_code, #3 request_id, #4 requests, #6 signature(ignored),
#  #10 auth_info, #12 ms_since_last_locationfix. Note these differ from the
#  commonly-documented POGOProtos numbers — this build uses 3/4, not 2/3.)
RE_STATUS_CODE = 1
RE_REQUEST_ID = 3
RE_REQUESTS = 4          # repeated Request
RE_LATITUDE = 7
RE_LONGITUDE = 8
RE_ACCURACY = 9
RE_AUTH_INFO = 10
RE_AUTH_TICKET = 11

# Request { request_type = 1 (enum), request_message = 2 (bytes) }
REQ_TYPE = 1
REQ_MESSAGE = 2

# ---------------------------------------------------------- ResponseEnvelope
RESP_STATUS_CODE = 1
RESP_REQUEST_ID = 2
RESP_API_URL = 3         # == Niantic internal "assigned_host"
RESP_ERROR = 4           # == "debug_message"
RESP_AUTH_TICKET = 7
RESP_RETURNS = 100       # repeated bytes, positional with requests

# ResponseEnvelope.status_code values
STATUS_OK = 2            # request handled, returns[] valid
STATUS_REDIRECT = 53     # client must re-send to api_url

# AuthInfo { provider=1 string, token=2 {contents=1 string, unknown2=2 int} }
AI_PROVIDER = 1
AI_TOKEN = 2
AI_TOKEN_CONTENTS = 1

# AuthTicket { start=1 bytes, expire_timestamp_ms=2 uint64, end=3 bytes }
AT_START = 1
AT_EXPIRE = 2
AT_END = 3
_AT_MAGIC = b"U:"        # we stash the username in AuthTicket.start so it
                         # survives the client switching from token to ticket

# ------------------------------------------------------------- RequestType
# Only the ones we are confident about; everything else is logged numerically
# and answered with an empty response. The live client will reveal any others.
class RT:
    METHOD_UNSET = 0
    GET_PLAYER = 2
    GET_INVENTORY = 4
    DOWNLOAD_SETTINGS = 5
    DOWNLOAD_ITEM_TEMPLATES = 6
    DOWNLOAD_REMOTE_CONFIG_VERSION = 7
    FORT_SEARCH = 101
    ENCOUNTER = 102
    CATCH_POKEMON = 103
    FORT_DETAILS = 104
    FORT_DEPLOY_POKEMON = 110
    RELEASE_POKEMON = 112
    START_GYM_BATTLE = 135
    ATTACK_GYM = 136
    EVOLVE_POKEMON = 125
    UPGRADE_POKEMON = 147
    SET_FAVORITE_POKEMON = 148
    NICKNAME_POKEMON = 149
    GET_HATCHED_EGGS = 126
    ENCOUNTER_TUTORIAL_COMPLETE = 127
    LEVEL_UP_REWARDS = 128
    CHECK_AWARDED_BADGES = 129
    GET_GYM_DETAILS = 134
    USE_ITEM_POTION = 113
    USE_ITEM_EGG_INCUBATOR = 140
    USE_ITEM_CAPTURE = 114
    USE_ITEM_XP_BOOST = 139
    USE_INCENSE = 141
    GET_INCENSE_POKEMON = 142
    ADD_FORT_MODIFIER = 144
    SET_AVATAR = 404
    CLAIM_CODENAME = 403
    SET_PLAYER_TEAM = 405
    MARK_TUTORIAL_COMPLETE = 406
    USE_ITEM_REVIVE = 116
    RECYCLE_INVENTORY_ITEM = 137
    GET_MAP_OBJECTS = 106
    GET_PLAYER_PROFILE = 121
    GET_ASSET_DIGEST = 300
    GET_DOWNLOAD_URLS = 301

NAME = {v: k for k, v in vars(RT).items() if not k.startswith("_")}
def rt_name(n): return NAME.get(n, f"UNKNOWN_{n}")


# ------------------------------------------------------------- GET_INVENTORY
# (VERIFIED field numbers, POGOProtos 2016 layout:
#  GetInventoryResponse{success=1, inventory_delta=2}
#  InventoryDelta{original_ts=1, new_ts=2, inventory_items=3}
#  InventoryItem{modified_ts=1, deleted_item_key=2, inventory_item_data=3}
#  InventoryItemData{pokemon_data=1, item=2, pokedex_entry=3, player_stats=4, ...}
#  Item{item_id=1, count=2, unseen=3}   PlayerStats{level=1, xp=2, prev=3, next=4})
# Returning a real (non-empty) inventory clears the client's perpetual "syncing"
# spinner, which otherwise suppresses the live map (Pokemon/PokeStops).













# Asset/template versions we pin the world to. Returning matching timestamps in
# DOWNLOAD_REMOTE_CONFIG_VERSION and the digest/settings responses keeps the
# client from looping on downloads it can't complete.
                                    # (bump this to force the client to re-fetch the
                                    #  asset digest after we change bundle entries;
                                    #  bumped when we swapped the fake egg for the real
                                    #  151-bundle digest w/ genuine keys, 2026-08-02)
                                    # values (candy pools). MUST be bumped in
                                    # lockstep with resp.timestamp_ms in
                                    # tools/convert_gm.py -- this constant OVERRIDES
                                    # the timestamp baked into game_master.bin, so
                                    # bumping only the converter changes nothing and
                                    # the client silently keeps its cached copy.
                                    # 1_473_100_000_000 was the flattened
                                    # camera_encounterintro (instant encounter).
                                    # Previously 1_473_000_000_000 for the 832-template master (Camera +
                                    # MoveSequence restored). Without a bump the client never
                                    # sends DOWNLOAD_ITEM_TEMPLATES at all -- it just keeps using
                                    # its cached copy, so a rebuilt game_master.bin has no effect.
                                    # (2026-08-02 bump was for the stale-templates/no-Pokemon fix.)
                                    # build_download_item_templates_response OVERRIDES the bin's
                                    # baked timestamp_ms with this, so the two always agree.
                                     # fixed -> forces the client to re-read settings
                                     # instead of reusing the cached (broken) ones




# --- real 2016 CDN bundles (encrypted) + their genuine digest, served for download ---
# assets/ holds the encrypted pm#### bundles AND the shipped `asset_digest`
# (the real GetAssetDigestResponse). We serve the encrypted bytes verbatim and
# hand the client the REAL per-bundle key/checksum/version/size from that digest,
# so the client's own DecodeAndroid decrypts + CRC-validates each bundle.

# Photos for your PokeStops/Gyms: drop image files here and reference them by
# filename in the World Manager. Lives next to the .exe so it's easy to find.

# PLAIN_ASSETS=1 (default): serve the PRE-DECRYPTED bundles from assets_plain/ with
# an EMPTY digest key (tells the client "no decryption needed") and a checksum we
# compute ourselves. The encrypted path provably reaches the device intact (43
# bundles cached on-device, byte-identical to ours) yet no model ever renders, so
# the failure is in the client's decrypt/validate step -- this takes both out of
# the picture. PLAIN_ASSETS=0 restores the encrypted bundles + genuine keys.
# DISPROVEN 2026-08-02: served pm0142 decrypted with an empty key; the client
# downloaded it and REFUSED TO CACHE IT (0 plain bundles on device afterwards),
# i.e. it always runs DecodeAndroid and rejects anything that isn't the encrypted
# [ver|IV|ct|HMAC] container. Encrypted is the only format it accepts -- default OFF.
# CRC_FIX=1 (default): advertise CRC32(decrypted bundle) as the digest checksum
# instead of the genuine (unidentified-algorithm) value. Set 0 to pass through.
























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




# --------------------------------------------------------------------- EGGS






















# HoloItemType, read off the client: the applied-item entry has to say WHICH
# kind of buff it is or the game shows no timer at all. This was hardcoded to 1
# (ITEM_TYPE_POKEBALL), so a burning Lucky Egg matched nothing and looked dead.































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
def parse_encounter(msg: bytes):
    """EncounterMessage { encounter_id=1 fixed64, spawnpoint_id=2,
    player_latitude=3, player_longitude=4 }."""
    f = pb.decode(msg)
    return pb.get(f, 1, pb.WT_64)


def parse_catch(msg: bytes):
    """CatchPokemonMessage { encounter_id=1 fixed64, pokeball=2,
    normalized_reticle_size=3 double, spawn_point_guid=4, hit_pokemon=5,
    spin_modifier=6 double, normalized_hit_position=7 double }.

    Returns (encounter_id, pokeball, hit, reticle, spin)."""
    f = pb.decode(msg)
    return (pb.get(f, 1, pb.WT_64),
            pb.get(f, 2, pb.WT_VARINT) or ITEM_POKE_BALL,
            bool(pb.get(f, 5, pb.WT_VARINT)),
            _f64_to_double(pb.get(f, 3, pb.WT_64)),
            _f64_to_double(pb.get(f, 6, pb.WT_64)))


# ActivityType values used for catch bonuses
ACT_CATCH = 1
ACT_NICE = 10
ACT_GREAT = 11
ACT_EXCELLENT = 12
ACT_CURVEBALL = 13

# Throw quality comes from normalized_reticle_size: the ring shrinks as you hold,
# and a bigger number means a tighter ring. Thresholds match the 2016 game.
def _throw_tiers():
    return [(1.7, ACT_EXCELLENT, "Excellent",
             _cfg.get("catching", "xp_excellent_throw", cast=int)),
            (1.3, ACT_GREAT, "Great",
             _cfg.get("catching", "xp_great_throw", cast=int)),
            (1.0, ACT_NICE, "Nice",
             _cfg.get("catching", "xp_nice_throw", cast=int))]


def throw_bonus(reticle, spin=0.0):
    """(activity, label, xp) for the throw, or None for an ordinary one."""
    for threshold, act, label, xp in _throw_tiers():
        if reticle >= threshold:
            return act, label, xp
    return None


def build_capture_award(reticle=0.0, spin=0.0):
    """CaptureAward { activity_type=1, xp=2, candy=3, stardust=4 } -- four PARALLEL
    repeated arrays, one slot per bonus line the client shows on the catch screen."""
    acts, xps, candy, dust = ([ACT_CATCH],
                              [_cfg.get("catching", "xp_per_catch", cast=int)],
                              [_cfg.get("catching", "candy_per_catch", cast=int)],
                              [_cfg.get("catching", "stardust_per_catch", cast=int)])
    bonus = throw_bonus(reticle, spin)
    if bonus:
        act, _label, xp = bonus
        acts.append(act); xps.append(xp); candy.append(0); dust.append(0)
    if spin and spin >= 1.0:                       # curveball
        acts.append(ACT_CURVEBALL)
        xps.append(_cfg.get("catching", "xp_curveball", cast=int))
        candy.append(0); dust.append(0)
    return (pb.Writer()
            .packed_varints(1, acts)
            .packed_varints(2, xps)
            .packed_varints(3, candy)
            .packed_varints(4, dust)
            .to_bytes()), sum(xps)


def build_capture_probability() -> bytes:
    # CaptureProbability { pokeball_type=1 (repeated enum), capture_probability=2
    #   (repeated FLOAT), reticle_difficulty_scale=12 }
    return (pb.Writer()
            .packed_varints(1, [ITEM_POKE_BALL, ITEM_GREAT_BALL, 3])
            .packed_floats(2, [0.55, 0.75, 0.9])
            .to_bytes())


def build_encounter_response(encounter_id, now_ms) -> bytes:
    """EncounterResponse { wild_pokemon=1, background=2, status=3, capture_probability=4 }
    Status: 1=ENCOUNTER_SUCCESS, 2=NOT_FOUND, 5=NOT_IN_RANGE.

    Tapping a Pokemon sends ENCOUNTER. We used to answer with an EMPTY response,
    which the client reads as 'this spawn is gone' -- so the Pokemon vanished on tap.
    Look the spawn up in world.SPAWNS (recorded when we announced it on the map) and
    hand back the full WildPokemon so the catch screen can open.
    """
    import world
    s = world.get_spawn(encounter_id)
    if not s:
        return pb.Writer().uint(3, 2).to_bytes()          # ENCOUNTER_NOT_FOUND
    world.bump("pokemons_encountered")
    world.pokedex_saw(s["pokemon_id"])
    wild = build_wild_pokemon(encounter_id, s["lat"], s["lng"], s["spawn_id"],
                              s["pokemon_id"], now_ms, 10 * 60 * 1000, cp=s["cp"])
    return (pb.Writer()
            .message(1, wild)
            .uint(3, 1)                                   # ENCOUNTER_SUCCESS
            .message(4, build_capture_probability())
            .to_bytes())


def build_catch_pokemon_response(encounter_id, pokeball, hit, now_ms,
                                 reticle=0.0, spin=0.0) -> bytes:
    """CatchPokemonResponse { status=1, miss_percent=2, captured_pokemon_id=3,
    capture_award=4 }. CatchStatus: 1=SUCCESS, 2=ESCAPE, 3=FLEE, 4=MISSED."""
    import world
    s = world.get_spawn(encounter_id)
    if not s:
        return pb.Writer().uint(1, 3).to_bytes()          # CATCH_FLEE (unknown spawn)
    if not hit:
        return pb.Writer().uint(1, 4).double(2, 0.0).to_bytes()   # CATCH_MISSED
    if world.pokemon_full():
        # Nowhere to put it. Fleeing is the closest honest answer the protocol has.
        return pb.Writer().uint(1, 3).to_bytes()          # CATCH_FLEE
    if not world.take_item(pokeball, 1):                  # consume the thrown ball
        return pb.Writer().uint(1, 4).double(2, 0.0).to_bytes()   # out of that ball

    # Does it hold? A berry bought for THIS encounter is spent here.
    mult = world.berry_mult(encounter_id)
    chance = catch_chance(s["pokemon_id"], s["cp"], pokeball, reticle, mult)
    # Mix the seed properly. `encounter_id ^ now_ms` looks random but both values
    # climb together, so their low bits cancel and successive throws came out
    # correlated -- the flee roll never fired once in 64 break-outs.
    seed = (int(encounter_id) * 0x9E3779B97F4A7C15) ^ (int(now_ms) * 0xC2B2AE3D27D4EB4F)
    seed = (seed ^ (seed >> 29)) & 0x7FFFFFFFFFFFFFFF
    rnd = _random.Random(seed)
    if world.current().STATS["pokemons_captured"] > 0 and rnd.random() > chance:
        world.berry_mult(encounter_id, consume=True)      # the berry is used up
        flee = _cfg.get("catching", "flee_chance", cast=float) / max(1.0, mult)
        if rnd.random() < flee:
            world.remove_spawn(encounter_id)              # gone for good
            world.mark_despawned(encounter_id, _window(now_ms)[1])
            return pb.Writer().uint(1, 3).to_bytes()      # CATCH_FLEE
        return pb.Writer().uint(1, 2).to_bytes()          # CATCH_ESCAPE - try again
    world.berry_mult(encounter_id, consume=True)
    # NOT `encounter_id ^ 0xC0FFEE` any more -- that is fixed per spawn point, so
    # catching at the same place twice reused the id and the client, which keys
    # Pokemon by id, just overwrote the earlier one.
    uid = world.new_uid(encounter_id)
    world.add_caught(uid, s["pokemon_id"], s["cp"])
    world.pokedex_caught(s["pokemon_id"])
    world.remove_spawn(encounter_id)                      # it's ours now; clear the map
    world.drop_bonus_spawn(world.current().username, encounter_id)
    # ...and keep it gone. Spawns are regenerated deterministically per window, so
    # without this the next GET_MAP_OBJECTS would put it right back on the map.
    world.mark_despawned(encounter_id, _window(now_ms)[1])
    award, total_xp = build_capture_award(reticle, spin)
    world.add_xp(total_xp)
    # The catch screen has always SHOWN "+candy, +stardust", but nothing ever
    # credited them -- stardust sat at its starting value forever and the only
    # candy you could get was 1 per transfer.
    world.add_candy(pokemon_family(s["pokemon_id"]),
                    _cfg.get("catching", "candy_per_catch", cast=int))
    world.add_stardust(_cfg.get("catching", "stardust_per_catch", cast=int))
    return (pb.Writer()
            .uint(1, 1)                                   # CATCH_SUCCESS
            .double(2, 0.0)                               # miss_percent
            .uint(3, uid)                                 # captured_pokemon_id
            .message(4, award)                            # capture_award
            .to_bytes())



# ------------------------------------------------------------- GYM BATTLES
# BattleState: 1=ACTIVE 2=VICTORY 3=DEFEATED 4=TIMED_OUT
# BattleActionType: 1=ATTACK 2=DODGE 3=SPECIAL_ATTACK 5=FAINT 8=VICTORY 9=DEFEAT
BS_ACTIVE, BS_VICTORY, BS_DEFEATED = 1, 2, 3
# BattleType: 0=UNSET 1=NORMAL 2=TRAINING. Leaving this UNSET meant the client
# never knew which kind of battle to run, so it started one and then refused to
# send a single ATTACK_GYM. Attacking your OWN team's gym is TRAINING.
BT_NORMAL, BT_TRAINING = 1, 2
BA_ATTACK, BA_DODGE, BA_SPECIAL, BA_FAINT = 1, 2, 3, 5
BA_PLAYER_JOIN, BA_VICTORY, BA_DEFEAT = 6, 8, 9


def _battle_pokemon_info(pokemon_id, uid, cp, hp, energy=0, extra=None,
                         hp_max=None) -> bytes:
    """BattlePokemonInfo { pokemon_data=1, current_health=2, current_energy=3 }.
    The HP BAR the client draws comes from pokemon_data.stamina/stamina_max, so
    those must carry the battle HP -- leaving stamina_max at 20 made a 260-HP
    defender look nearly dead and the fight ended on the first tap."""
    e = dict(extra or {})
    e["stamina"] = int(hp)
    e["stamina_max"] = int(hp_max if hp_max is not None else max(hp, 1))
    return (pb.Writer()
            .message(1, build_pokemon_data(pokemon_id, uid, cp, extra=e))
            .int_(2, int(hp))
            .int_(3, int(energy))
            .to_bytes())


def _battle_participant(pokemon_id, uid, cp, hp, trainer, level, avatar=None) -> bytes:
    """BattleParticipant { active_pokemon=1, trainer_public_profile=2,
    reverse_pokemon=3, defeated_pokemon=4 }."""
    profile = (pb.Writer().string(1, trainer).int_(2, level)
               .message(3, build_player_avatar(avatar)).to_bytes())
    return (pb.Writer()
            .message(1, _battle_pokemon_info(pokemon_id, uid, cp, hp))
            .message(2, profile)
            .to_bytes())




def parse_start_gym_battle(msg):
    """StartGymBattleMessage { gym_id=1, attacking_pokemon_ids=2 (repeated fixed64),
    defending_pokemon_id=3, player_latitude=4, player_longitude=5 }."""
    f = pb.decode(msg)
    gid = pb.get(f, 1, pb.WT_LEN)
    # attacking_pokemon_ids is `repeated fixed64` and the client sends it PACKED,
    # so it arrives as ONE length-delimited blob of 8-byte ids -- not as separate
    # fixed64 fields. Reading it as ints found nothing, so every battle reported
    # ERROR_ALL_POKEMON_FAINTED. Handle both encodings.
    attackers = []
    for v in pb.get_all(f, 2):
        if isinstance(v, int):
            attackers.append(v)                       # unpacked fixed64
        elif isinstance(v, bytes):
            for i in range(0, len(v) - 7, 8):         # packed: 8 bytes each
                attackers.append(_struct.unpack_from("<Q", v, i)[0])
    return (gid.decode("utf-8", "replace") if isinstance(gid, bytes) else "",
            attackers, pb.get(f, 3, pb.WT_VARINT) or pb.get(f, 3, pb.WT_64) or 0)


def build_start_gym_battle_response(gym_id, attacker_uids, defender_uid, now_ms) -> bytes:
    """StartGymBattleResponse { result=1, battle_start_timestamp_ms=2,
    battle_end_timestamp_ms=3, battle_id=4, defender=5, battle_log=6 }.
    1=SUCCESS 3=GYM_NEUTRAL 5=GYM_EMPTY 8=ALL_POKEMON_FAINTED 13=NOT_IN_RANGE."""
    import world
    members = world.gym_members(gym_id)
    if not members:
        return pb.Writer().uint(1, 5).to_bytes()               # GYM_EMPTY
    defender = next((m for m in members if m["uid"] == defender_uid),
                    max(members, key=lambda m: m.get("cp", 0)))
    # A Pokemon defending the gym cannot also attack it. Allowing that gave both
    # participants the SAME ActivePokemonId, so the client could not tell the two
    # sides apart -- it quietly restarted the battle under a fresh id, and every
    # reply we sent for the old id came back as "mismatched battleId".
    def _usable(c):
        return (c is not None and int(c.get("stamina", 20)) > 0
                and c["uid"] != defender["uid"]
                and not world.is_deployed(c["uid"]))

    atk = next((c for c in (world.get_caught(u) for u in attacker_uids)
                if _usable(c)), None)
    if atk is None:
        # Fall back to your strongest healthy Pokemon. The client's chosen team
        # should normally be honoured, but refusing the battle outright over a
        # parsing detail is much worse than picking a sensible attacker.
        healthy = [c for c in world.caught() if _usable(c)]
        if healthy:
            atk = max(healthy, key=lambda c: c.get("cp", 0))
    if atk is None:
        return pb.Writer().uint(1, 8).to_bytes()               # ALL_POKEMON_FAINTED

    is_raid = bool(defender.get("raid"))
    bid = "B%x%04x" % (now_ms, (defender["uid"] ^ atk["uid"]) & 0xFFFF)
    dhp = _hp_for(defender["cp"], defender["pokemon_id"], defender["uid"])
    ahp = _hp_for(atk["cp"], atk["pokemon_id"], atk["uid"])
    btype = BT_TRAINING if world.gym_team(gym_id) == world.my_team() else BT_NORMAL
    world.BATTLES[bid] = {"gym": gym_id, "attacker": atk["uid"],
                          "defender": defender["uid"],
                          "atk_pid": atk["pokemon_id"], "def_pid": defender["pokemon_id"],
                          "atk_cp": atk["cp"], "def_cp": defender["cp"],
                          "atk_hp": ahp, "def_hp": dhp,
                          "atk_max": ahp, "def_max": dhp, "type": btype,
                          "raid": is_raid,
                          "start": now_ms, "player": world.current().username}
    lvl, _xp = world.stats()
    me = _battle_participant(atk["pokemon_id"], atk["uid"], atk["cp"], ahp,
                             world.current().username, lvl, world.current().AVATAR)
    # A raid boss is not a person -- report level -1 so nobody mistakes "raid"
    # for a real trainer who parked a Mewtwo in every gym.
    def_lvl = -1 if is_raid else lvl
    join = (pb.Writer()
            .uint(1, BA_PLAYER_JOIN)
            .int_(2, now_ms)
            .int_(3, 0)
            .uint(8, atk["uid"])
            .message(9, me)                        # player_joined
            .to_bytes())
    log = (pb.Writer()
           .uint(1, BS_ACTIVE)
           .uint(2, btype)                         # <- was missing entirely
           .int_(3, now_ms)
           .message(4, join)
           .int_(5, now_ms).int_(6, now_ms + 180000)
           .to_bytes())
    return (pb.Writer()
            .uint(1, 1)                                        # SUCCESS
            .int_(2, now_ms)
            .int_(3, now_ms + 180000)
            .string(4, bid)
            .message(5, _battle_participant(defender["pokemon_id"], defender["uid"],
                                            defender["cp"], dhp,
                                            defender.get("trainer", "Rival"), def_lvl,
                                            world.avatar_for(defender.get("owner")
                                                             or defender.get("trainer"))))
            .message(6, log)
            .to_bytes())


def _raid_drop(b, now_ms):
    """Put the defeated raid boss on the map at the trainer's feet, catchable."""
    import world
    import rpc as _rpc
    lat, lng = _rpc._last_loc[0], _rpc._last_loc[1]
    if not (abs(lat) > 1e-6 or abs(lng) > 1e-6):
        return None
    # a couple of metres away so it isn't inside the avatar
    lat += 0.00002
    eid = (now_ms ^ (b["def_uid"] if "def_uid" in b else b["defender"])
           ^ 0x5A1DD40D) & ((1 << 62) - 1)
    sid = _hex_id((eid, "raid"), 11)
    expires = now_ms + 10 * 60 * 1000               # ten minutes to catch it
    world.remember_spawn(eid, b["def_pid"], lat, lng, b["def_cp"], sid, expires)
    world.add_bonus_spawn(world.current().username, eid, b["def_pid"],
                          b["def_cp"], lat, lng, expires)
    return eid


def parse_attack_gym(msg):
    """AttackGymMessage { gym_id=1, battle_id=2, attack_actions=3 (repeated),
    last_retrieved_actions=4, player_latitude=5, player_longitude=6 }."""
    f = pb.decode(msg)
    gid = pb.get(f, 1, pb.WT_LEN)
    bid = pb.get(f, 2, pb.WT_LEN)
    actions = []
    for raw in pb.get_all(f, 3):
        if isinstance(raw, bytes):
            a = pb.decode(raw)
            actions.append({"type": pb.get(a, 1, pb.WT_VARINT) or 0,
                            "start": pb.get(a, 2, pb.WT_VARINT) or 0,
                            "duration": pb.get(a, 3, pb.WT_VARINT) or 0})
    last = 0
    raw_last = pb.get(f, 4, pb.WT_LEN)
    if isinstance(raw_last, bytes):
        la = pb.decode(raw_last)
        last = pb.get(la, 2, pb.WT_VARINT) or 0
    return (gid.decode("utf-8", "replace") if isinstance(gid, bytes) else "",
            bid.decode("utf-8", "replace") if isinstance(bid, bytes) else "",
            actions, last)


def _action(kind, start_ms, duration, attacker_idx, target_idx,
            active_uid, target_uid, energy=0, dw_start=None, dw_end=None) -> bytes:
    # attacker_idx/target_idx index the battle's ATTACKING PLAYERS
    # (BattleResultsProto.Attackers is a repeated list, one entry per player in a
    # multi-attacker gym fight) -- they are NOT "me vs them". A solo battle has
    # exactly one entry, so anything other than 0 is out of range and the client
    # drops the action silently. WHO is acting comes from active_pokemon_id /
    # target_pokemon_id, which is how the defender is identified.
    """One BattleAction the client will replay.
    { Type=1, action_start_ms=2, duration_ms=3, energy_delta=5, attacker_index=6,
      target_index=7, active_pokemon_id=8, damage_windows_start=11,
      damage_windows_end=12, target_pokemon_id=14 }"""
    return (pb.Writer()
            .uint(1, kind)
            .int_(2, start_ms)
            .int_(3, duration)
            .int_(5, energy)
            .int_(6, attacker_idx)
            .int_(7, target_idx)
            .fixed64(8, active_uid)
            .int_(11, start_ms + (max(0, duration // 3) if dw_start is None
                                  else int(dw_start)))
            .int_(12, start_ms + (max(1, duration) if dw_end is None
                                  else int(dw_end)))
            .fixed64(14, target_uid)
            .to_bytes())


def build_attack_gym_response(gym_id, battle_id, actions, now_ms, last_seen=0) -> bytes:
    """AttackGymResponse { result=1, battle_log=2, battle_id=3,
    active_defender=4, active_attacker=5 }.

    This is a SYNC protocol, not a one-way report. The client tells us the moves it
    made and then waits for the server to hand back the authoritative list of
    actions -- its own, echoed, plus the defender hitting back -- which it replays
    as animation. Returning only a state (and no actions) is why it would take two
    taps and then sit there sending empty heartbeats."""
    import world
    b = world.BATTLES.get(battle_id)
    if not b:
        # The client keeps polling for a moment after a battle ends. Answering
        # without a battle_id made it log "AttackGymOutProto for mismatched
        # battleId"; echo the id back with a terminal log instead.
        done = (pb.Writer().uint(1, BS_VICTORY).uint(2, BT_NORMAL)
                .int_(3, now_ms).to_bytes())
        return (pb.Writer().uint(1, 1).message(2, done)
                .string(3, battle_id).to_bytes())

    if b.get("finished"):
        # The client polls a few more times before it tears the battle screen
        # down. Falling through re-ran the win logic on every one of those polls,
        # re-awarding the XP and re-emitting VICTORY -- report the settled state
        # and touch nothing.
        done = (pb.Writer().uint(1, b.get("end_state", BS_VICTORY))
                .uint(2, b.get("type", BT_NORMAL))
                .int_(3, now_ms)
                .int_(5, b["start"]).int_(6, b["start"] + 180000).to_bytes())
        return (pb.Writer().uint(1, 1).message(2, done)
                .string(3, battle_id)
                .message(4, _battle_pokemon_info(b["def_pid"], b["defender"],
                                                 b["def_cp"], max(0, b["def_hp"]),
                                                 hp_max=b.get("def_max")))
                .message(5, _battle_pokemon_info(b["atk_pid"], b["attacker"],
                                                 b["atk_cp"], max(0, b["atk_hp"]),
                                                 energy=b.get("energy", 0),
                                                 hp_max=b.get("atk_max")))
                .to_bytes())

    dmg_atk = _cfg.get("battles", "attack_damage", cast=int)
    dmg_special = _cfg.get("battles", "special_damage", cast=int)
    dmg_back = _cfg.get("battles", "defender_damage", cast=int)

    log_actions = []
    # The client SCHEDULES every action we return at its ActionStartMs, on its own
    # battle clock. The old code stacked each action onto a server cursor that ran
    # ahead of real time (it added every duration, and taps arrive faster than
    # that), so the actions were always dated in the future: the damage applied --
    # HP is read straight off active_defender -- but the animation never played,
    # and occasionally a whole backlog resolved at once. Echo the client's own
    # timestamps verbatim and hang the counter-attack off the end of each.
    # Which moves the two sides are actually using. The client resolves an action
    # to an animation via the performer's moveset, so every action we emit has to
    # carry that move's real duration and damage window.
    atk_quick, atk_charged = moves_for(b["atk_pid"], b["attacker"])
    def_quick, _dc = moves_for(b["def_pid"], b["defender"])

    cursor = max(now_ms, int(last_seen) + 1, int(b.get("last_emit", 0)) + 1)
    tail = None          # end of the last action we echoed, on the CLIENT's clock
    for a in actions:
        kind = a["type"]
        start = int(a.get("start") or 0) or cursor
        if kind == BA_ATTACK:
            move = atk_quick
            b["def_hp"] -= dmg_atk
        elif kind == BA_SPECIAL:
            move = atk_charged
            b["def_hp"] -= dmg_special
        elif kind == BA_DODGE:
            move = None                             # dodged: no counter this beat
        else:
            continue
        if move is None:
            dur = int(a["duration"] or 700)
            log_actions.append(_action(kind, start, dur, 0, 0,
                                       b["attacker"], b["defender"]))
        else:
            dur, dws, dwe, energy = move_timing(move, int(a["duration"] or 700))
            # Charged moves carry a negative energy_delta, so this drains on its
            # own -- no need to special-case the special.
            b["energy"] = max(0, min(100, b.get("energy", 0) + energy))
            log_actions.append(_action(kind, start, dur, 0, 0,
                                       b["attacker"], b["defender"],
                                       energy=energy, dw_start=dws, dw_end=dwe))
        end = start + dur
        if kind != BA_DODGE and b["def_hp"] > 0:
            # ...and the defender answers, which is what makes it feel like a fight
            ddur, ddws, ddwe, denergy = move_timing(def_quick)
            b["atk_hp"] -= dmg_back
            # NOTE: measured 2026-08-04 -- this client does NOT replay server-sent
            # battle actions (a probe action attributed to the player animated 0 of
            # 4 times, and "Action start:" never appears in the client log). Gym
            # battles are simulated client-side; the log we send carries the
            # authoritative outcome, not the choreography. We still emit the
            # defender's counter so the log is truthful and the HP we report is
            # explained, but the animation for it comes from the client or not at all.
            log_actions.append(_action(BA_ATTACK, end, ddur, 0, 0,
                                       b["defender"], b["attacker"],
                                       energy=denergy, dw_start=ddws, dw_end=ddwe))
            end += ddur
        tail = end if tail is None else max(tail, end)
    # Faints and the victory banner have to be dated on whatever clock the echoed
    # actions used, not on ours -- if the client turns out to send battle-relative
    # times, a wall-clock faint would land ~1.7e12 ms away and never play.
    t = tail if tail is not None else cursor

    state = BS_ACTIVE
    if b["def_hp"] <= 0:
        log_actions.append(_action(BA_FAINT, t, 0, 0, 0,
                                   b["defender"], b["defender"]))
        world.recall(gym_id, b["defender"])
        # In raid mode gym_members() always reports the boss, so looking for a
        # "next" defender would hand back the same one and the fight would never
        # end. A raid is one boss, then it's over.
        nxt = None if b.get("raid") else next(iter(world.gym_members(gym_id)), None)
        if nxt:
            b.update(defender=nxt["uid"], def_pid=nxt["pokemon_id"],
                     def_cp=nxt["cp"],
                     def_hp=_hp_for(nxt["cp"], nxt["pokemon_id"], nxt["uid"]),
                     def_max=_hp_for(nxt["cp"], nxt["pokemon_id"], nxt["uid"]))
        else:
            state = BS_VICTORY
            if b.get("raid"):
                # Beating the boss doesn't take the gym -- it drops the Pokemon at
                # your feet so you can actually catch the thing you just fought.
                _raid_drop(b, now_ms)
            else:
                world.clear_gym(gym_id)
            world.add_xp(_cfg.get("battles", "win_xp", cast=int))
            world.record_badge_progress(
                "BADGE_BATTLE_TRAINING_WON"
                if b.get("type") == BT_TRAINING else "BADGE_BATTLE_ATTACK_WON", 1)
            log_actions.append(_action(BA_VICTORY, t, 0, 0, 0,
                                       b["attacker"], b["defender"]))
    elif b["atk_hp"] <= 0:
        state = BS_DEFEATED
        world.update_caught(b["attacker"], stamina=0)           # your Pokemon fainted
        log_actions.append(_action(BA_FAINT, t, 0, 0, 0,
                                   b["attacker"], b["attacker"]))
        log_actions.append(_action(BA_DEFEAT, t, 0, 0, 0,
                                   b["defender"], b["attacker"]))

    b["last_emit"] = t
    if state != BS_ACTIVE:
        b["finished"] = now_ms          # keep it briefly so late taps still match
        b["end_state"] = state
        for old, ob in list(world.BATTLES.items()):
            if ob.get("finished") and now_ms - ob["finished"] > 30000:
                world.BATTLES.pop(old, None)

    lw = (pb.Writer().uint(1, state)
          .uint(2, b.get("type", BT_NORMAL))
          .int_(3, now_ms).int_(5, b["start"]).int_(6, b["start"] + 180000))
    for a in log_actions:
        lw.message(4, a)
    return (pb.Writer()
            .uint(1, 1)                                        # SUCCESS
            .message(2, lw.to_bytes())
            .string(3, battle_id)
            .message(4, _battle_pokemon_info(b["def_pid"], b["defender"],
                                             b["def_cp"], max(0, b["def_hp"]),
                                             hp_max=b.get("def_max")))
            .message(5, _battle_pokemon_info(b["atk_pid"], b["attacker"],
                                             b["atk_cp"], max(0, b["atk_hp"]),
                                             energy=b.get("energy", 0),
                                             hp_max=b.get("atk_max")))
            .to_bytes())


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









def build_auth_ticket(username: str = "", ttl_seconds: int = 2 * 60 * 60) -> bytes:
    start = _AT_MAGIC + username.encode("utf-8") + b"\x00" + os.urandom(16)
    return (pb.Writer()
            .bytes_(AT_START, start)
            .uint(AT_EXPIRE, int(time.time() * 1000) + ttl_seconds * 1000)
            .bytes_(AT_END, os.urandom(32))
            .to_bytes())


def username_from_auth_ticket(ticket_bytes: bytes):
    """Recover the username we stashed in AuthTicket.start, if present."""
    try:
        start = pb.get(pb.decode(ticket_bytes), AT_START, pb.WT_LEN)
        if start and start.startswith(_AT_MAGIC):
            return start[len(_AT_MAGIC):].split(b"\x00", 1)[0].decode("utf-8")
    except Exception:
        pass
    return None


def auth_token_from_envelope(fields):
    """Pull the PTC/Google token string out of RequestEnvelope.auth_info."""
    auth_info = pb.get(fields, RE_AUTH_INFO, pb.WT_LEN)
    if not isinstance(auth_info, bytes):
        return None
    ai = pb.decode(auth_info)
    token_msg = pb.get(ai, AI_TOKEN, pb.WT_LEN)
    if isinstance(token_msg, bytes):
        contents = pb.get(pb.decode(token_msg), AI_TOKEN_CONTENTS, pb.WT_LEN)
        if isinstance(contents, bytes):
            return contents.decode("utf-8", "replace")
    return None


def build_response_envelope(*, status_code, request_id, returns=(),
                            api_url=None, auth_ticket=None, error=None) -> bytes:
    w = pb.Writer().uint(RESP_STATUS_CODE, status_code)
    if request_id is not None:
        w.uint(RESP_REQUEST_ID, request_id)
    if api_url:
        w.string(RESP_API_URL, api_url)
    if error:
        w.string(RESP_ERROR, error)
    if auth_ticket is not None:
        w.message(RESP_AUTH_TICKET, auth_ticket)
    for r in returns:
        w.bytes_(RESP_RETURNS, r)
    return w.to_bytes()


def resolve_username(fields):
    """Best-effort username: from auth_info token, else from auth_ticket."""
    from sso import username_from_token
    token = auth_token_from_envelope(fields)
    if token:
        return username_from_token(token)
    ticket = pb.get(fields, RE_AUTH_TICKET, pb.WT_LEN)
    if isinstance(ticket, bytes):
        u = username_from_auth_ticket(ticket)
        if u:
            return u
    return None


def parse_request_envelope(buf: bytes):
    """Return (request_id, [(request_type, request_message_bytes), ...], fields)."""
    fields = pb.decode(buf)
    request_id = pb.get(fields, RE_REQUEST_ID, pb.WT_VARINT)
    reqs = []
    for raw in pb.get_all(fields, RE_REQUESTS):
        if isinstance(raw, bytes):
            inner = pb.decode(raw)
            rtype = pb.get(inner, REQ_TYPE, pb.WT_VARINT) or 0
            rmsg = pb.get(inner, REQ_MESSAGE, pb.WT_LEN) or b""
            reqs.append((rtype, rmsg))
    return request_id, reqs, fields


from protocol import assets as assets
from protocol import inventory as inventory
from protocol import player as player
for _module in (player, inventory, assets):
    globals().update((name, value) for name, value in vars(_module).items() if not name.startswith("__"))
