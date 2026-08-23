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
import random as _random
import struct as _struct

def _f64_to_double(v):
    return _struct.unpack("<d", _struct.pack("<Q", v))[0] if v is not None else 0.0

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



KANTO_MIN, KANTO_MAX = 1, 151        # all of Gen 1 (Kanto)












# --------------------------------------------------------------------- EGGS






















# HoloItemType, read off the client: the applied-item entry has to say WHICH
# kind of buff it is or the game shows no timer at all. This was hardcoded to 1
# (ITEM_TYPE_POKEBALL), so a burning Lucky Egg matched nothing and looked dead.







































# ----------------------------------------------------- FORT_DETAILS / SEARCH
# Personalized names; chosen deterministically per fort_id so each stop/gym keeps
# its name. (Edit these to taste.)










def catch_chance(pokemon_id, cp, ball_id, reticle, berry_mult):
    """Probability this throw holds.

    Everything used to be a guaranteed catch, which made a Pokeball a formality.
    Stronger Pokemon resist, better balls and better throws help, and a Razz
    Berry multiplies it."""
    base = _cfg.get("catching", "base_catch_rate", cast=float)
    # a 2000 CP Pokemon should be a real fight; a 100 CP one shouldn't
    base *= max(0.18, 1.0 - (max(0, int(cp)) / 3200.0))
    base *= {1: 1.0, 2: 1.5, 3: 2.0}.get(int(ball_id), 1.0)      # poke/great/ultra
    base *= 1.0 + max(0.0, min(1.0, float(reticle))) * 0.55      # aim helps
    base *= max(1.0, float(berry_mult))
    return max(0.05, min(0.95, base))

# ------------------------------------------------------ ENCOUNTER / CATCH




# ActivityType values used for catch bonuses

# Throw quality comes from normalized_reticle_size: the ring shrinks as you hold,
# and a bigger number means a tighter ring. Thresholds match the 2016 game.













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




















# --------------------------------------------------------------- GYMS / ITEMS



























# A fort MUST come back with at least one image url: the gym screen indexes
# urls[0] and threw ArgumentOutOfRangeException ("Promise<T>.Then<T> threw an
# exception") when we sent an empty list for a photo-less gym. This little PNG is
# served at /fortimg/_default.png whenever the user hasn't set their own picture.








# ------------------------------------------------- realistic spawn distribution
# A uniform randint(1,151) meant Mewtwo was as common as a Pidgey. These tiers
# reproduce the feel of a normal 2016 day: mostly city-trash Pokemon, occasional
# evolved ones, rare starters/pseudo-legendaries, and NO legendaries in the wild.
# (Legendary Hunt and the other presets still force them via species_mode.)






# Wild Pokemon rotate on a fixed clock: every SPAWN_WINDOW_MIN minutes the whole
# map re-rolls. Spawn ids/species are seeded from (cell, window), so a spawn lasts
# exactly one window and then a fresh set appears -- and a Pokemon you caught can
# be suppressed for the rest of its window instead of reappearing next refresh.




                                                             # (real spawns are sparse; a huge
                                                             #  cluster looks bogus to the client)















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


def catch_chance(pokemon_id, cp, ball_id, reticle, berry_mult):
    """Probability this throw holds.

    Everything used to be a guaranteed catch, which made a Pokeball a formality.
    Stronger Pokemon resist, better balls and better throws help, and a Razz
    Berry multiplies it."""
    base = _cfg.get("catching", "base_catch_rate", cast=float)
    # a 2000 CP Pokemon should be a real fight; a 100 CP one shouldn't
    base *= max(0.18, 1.0 - (max(0, int(cp)) / 3200.0))
    base *= {1: 1.0, 2: 1.5, 3: 2.0}.get(int(ball_id), 1.0)      # poke/great/ultra
    base *= 1.0 + max(0.0, min(1.0, float(reticle))) * 0.55      # aim helps
    base *= max(1.0, float(berry_mult))
    return max(0.05, min(0.95, base))

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




from protocol import assets as assets
from protocol import gym as gym
from protocol import inventory as inventory
from protocol import map as map
from protocol import player as player
for _module in (player, inventory, assets, gym, map):
    globals().update((name, value) for name, value in vars(_module).items() if not name.startswith("__"))
