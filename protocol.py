"""
PoGO 0.29 RPC protocol: field-number map + message builders.

Field numbers/enum values are the canonical community POGOProtos values for
this era. They are kept as NAMED CONSTANTS in one place so that if the real
client's logged layout (see rpc.py request dumps) ever disagrees, it's a
one-line fix. The request side is parsed generically (pb.decode), so only the
RESPONSE builders below depend on these numbers being right.
"""


# ---------------------------------------------------------
# CLEANED UP: library imports to top by the way :D


import os
import time
import pb
import settings as _cfg
import struct as _struct
import random as _random
import hashlib as _hashlib
import math as _math
import s2sphere
import world as _world

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

# -------------------------------------------------------------
# Cleaned up: move variables to top to make reading the code easier
ITEM_POKE_BALL = 1
ITEM_GREAT_BALL = 2
ITEM_POTION = 101
ITEM_REVIVE = 201
ITEM_ULTRA_BALL = 3
ITEM_RAZZ_BERRY = 701

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

# ----------------------------------------------------------------- PlayerData
# (VERIFIED against POGOProtos PlayerData.proto — field numbers are NOT
#  sequential; tutorial_state=7 is what makes the client skip new-user onboarding)
PD_CREATION_MS = 1
PD_USERNAME = 2
PD_TEAM = 5
PD_TUTORIAL = 7          # repeated enum (packed)  <-- was 4; the key fix
PD_AVATAR = 8
PD_MAX_POKEMON = 9
PD_MAX_ITEMS = 10
PD_DAILY_BONUS = 11
PD_CONTACT = 13
PD_CURRENCIES = 14

# GetPlayerResponse { success=1 bool, player_data=2 PlayerData }
GP_SUCCESS = 1
GP_PLAYER_DATA = 2

# Mark the whole new-user tutorial as already finished so the client skips
# straight to the map. Extra/unknown enum values are ignored by the client.
TUTORIAL_COMPLETE = [0, 1, 2, 3, 4, 5, 6, 7]
TUTORIAL_AVATAR_SELECTION = 1
TUTORIAL_FOR_AVATAR_CAPTURE = [0, 2, 3, 4, 5, 6, 7]


def tutorial_state():
    if os.environ.get("AVATAR_TUTORIAL_CAPTURE") == "1":
        return TUTORIAL_FOR_AVATAR_CAPTURE
    return TUTORIAL_COMPLETE


def avatar_onboarding_capture(username: str) -> bool:
    return (os.environ.get("AVATAR_ONBOARDING_CAPTURE") == "1"
            and username == os.environ.get("AVATAR_ONBOARDING_CAPTURE_USER")
            and _world.team_for(username) == 0)



# TeamColor: 0=NEUTRAL, 1=BLUE(Mystic), 2=RED(Valor), 3=YELLOW(Instinct).
# Must be non-zero or the client refuses Gym interaction ("join a team first").
def _team():
    return _cfg.get("gyms", "team", env="TEAM", cast=int)


def build_player_avatar(avatar: dict[int, int] | None = None) -> bytes:
    slots = _world.DEFAULT_AVATAR if avatar is None else avatar
    return (pb.Writer()
            .uint(2, slots.get(2, _world.DEFAULT_AVATAR[2]))
            .uint(3, slots.get(3, _world.DEFAULT_AVATAR[3]))
            .uint(4, slots.get(4, _world.DEFAULT_AVATAR[4]))
            .uint(5, slots.get(5, _world.DEFAULT_AVATAR[5]))
            .uint(6, slots.get(6, _world.DEFAULT_AVATAR[6]))
            .uint(7, slots.get(7, _world.DEFAULT_AVATAR[7]))
            .uint(8, slots.get(8, _world.DEFAULT_AVATAR[8]))
            .uint(9, slots.get(9, _world.DEFAULT_AVATAR[9]))
            .uint(10, slots.get(10, _world.DEFAULT_AVATAR[10]))
            .to_bytes())


def build_currency(name: str, amount: int) -> bytes:
    return pb.Writer().string(1, name).int_(2, amount).to_bytes()


def _coins():
    try:
        import world
        return world.COINS
    except Exception:
        return 0


def _stardust():
    """Stardust reaches the client ONLY through PlayerData.currencies -- the
    client's PlayerCurrencyProto has a single field, Gems, and no stardust at all,
    so the inventory route never worked. This used to be hardcoded to 5000, which
    is why the number never moved no matter what was earned or spent."""
    try:
        import world
        return world.STARDUST
    except Exception:
        return 0


def _storage():
    """(max_pokemon, max_items) -- raised by buying upgrades in the World Manager."""
    try:
        import world
        return world.MAX_POKEMON, world.MAX_ITEMS
    except Exception:
        return 250, 350


def build_player_data(username: str) -> bytes:
    display_name = _world.codename_for(username) or username
    team = _world.team_for(username) or _team()
    w = (pb.Writer()
         .uint(PD_CREATION_MS, int(time.time() * 1000) - 86_400_000)
         .string(PD_USERNAME, display_name))
    if not avatar_onboarding_capture(username):
        w = (w.uint(PD_TEAM, team)
             .packed_varints(PD_TUTORIAL, tutorial_state())
             .message(PD_AVATAR, build_player_avatar(_world.avatar_for(username))))
    return (w.uint(PD_MAX_POKEMON, _storage()[0])
            .uint(PD_MAX_ITEMS, _storage()[1])
            .message(PD_CURRENCIES, build_currency("POKECOIN", _coins()))
            .message(PD_CURRENCIES, build_currency("STARDUST", _stardust()))
            .to_bytes())


def build_get_player_response(username: str) -> bytes:
    return (pb.Writer()
            .bool_(GP_SUCCESS, True)
            .message(GP_PLAYER_DATA, build_player_data(username))
            .to_bytes())


def build_mark_tutorial_complete_response() -> bytes:
    return pb.Writer().bool_(1, True).to_bytes()


def build_claim_codename_response(codename: str) -> bytes:
    return (pb.Writer()
            .string(1, codename)
            .bool_(3, True)
            .uint(4, 1)
            .to_bytes())


def build_set_avatar_response() -> bytes:
    return pb.Writer().uint(1, 1).to_bytes()


def build_check_awarded_badges_response() -> bytes:
    """CheckAwardedBadgesResponse { success=1, awarded_badge=2 repeated }."""
    import world
    w = pb.Writer().bool_(1, True)
    for badge_id in world.drain_badge_pending():
        w.uint(2, badge_id)
    return w.to_bytes()


# ------------------------------------------------------------- GET_INVENTORY
# (VERIFIED field numbers, POGOProtos 2016 layout:
#  GetInventoryResponse{success=1, inventory_delta=2}
#  InventoryDelta{original_ts=1, new_ts=2, inventory_items=3}
#  InventoryItem{modified_ts=1, deleted_item_key=2, inventory_item_data=3}
#  InventoryItemData{pokemon_data=1, item=2, pokedex_entry=3, player_stats=4, ...}
#  Item{item_id=1, count=2, unseen=3}   PlayerStats{level=1, xp=2, prev=3, next=4})
# Returning a real (non-empty) inventory clears the client's perpetual "syncing"
# spinner, which otherwise suppresses the live map (Pokemon/PokeStops).



def build_player_stats(level=None, xp=None) -> bytes:
    # PlayerStats { level=1, experience=2, prev_level_xp=3, next_level_xp=4,
    #   km_walked=5 float, pokemons_encountered=6, unique_pokedex_entries=7,
    #   pokemons_captured=8, evolutions=9, poke_stop_visits=10,
    #   pokeballs_thrown=11, eggs_hatched=12, ... }
    # prev/next come from the REAL XP table (game master PlayerLevelSettings) --
    # the old code sent 0 and xp*2, so the client's level ring was nonsense.
    import world
    if level is None or xp is None:
        level, xp = world.LEVEL, world.XP
    prev, nxt = world.level_bounds(xp)
    st = world.STATS
    return (pb.Writer()
            .int_(1, level)
            .int_(2, xp)
            .int_(3, prev)
            .int_(4, nxt)
            .float_(5, float(st.get("km_walked", 0.0)))
            .int_(6, st.get("pokemons_encountered", 0))
            .int_(7, st.get("unique_pokedex_entries", 0))
            .int_(8, st.get("pokemons_captured", 0))
            .int_(10, st.get("poke_stop_visits", 0))
            .int_(11, st.get("pokeballs_thrown", 0))
            .to_bytes())


def build_bag_item(item_id, count) -> bytes:
    return pb.Writer().uint(1, item_id).int_(2, count).to_bytes()


def _inventory_item(data_field, body, now=None) -> bytes:
    """InventoryItemProto { ModifiedTimestamp=1, DeletedItemKey=2, Item=3 }.
    `now` is passed in so every item shares the delta's NewTimestamp -- items used
    to be stamped later than the delta they arrived in, which is backwards."""
    data = pb.Writer().message(data_field, body).to_bytes()   # InventoryItemData
    return (pb.Writer()
            .int_(1, int(now if now is not None else time.time() * 1000))
            .message(3, data)                                 # inventory_item_data
            .to_bytes())


def _deleted_item(data_field, body, now) -> bytes:
    """An inventory entry that tells the client to REMOVE something.

    DeletedItemKey is the same shape as the item data with only the identifying
    field filled in. Without this a transferred Pokemon never goes away: the delta
    is additive, so leaving it out means "no change", and the client rolls back the
    deletion it had optimistically predicted."""
    key = pb.Writer().message(data_field, body).to_bytes()
    return (pb.Writer()
            .int_(1, int(now))
            .message(2, key)                                  # DeletedItemKey
            .to_bytes())


def build_get_inventory_response() -> bytes:
    # Built from the LIVE bag/caught state (world.py) rather than a hardcoded list,
    # so items awarded by spinning a PokeStop and Pokemon you catch actually show up.
    import world
    now = int(time.time() * 1000)
    level, xp = world.stats()
    items = [_inventory_item(4, build_player_stats(level, xp), now)]  # player_stats
    for iid, cnt in world.bag_items():
        items.append(_inventory_item(2, build_bag_item(iid, cnt), now))
    for c in world.caught():
        items.append(_inventory_item(1, build_pokemon_data(          # pokemon_data
            c["pokemon_id"], c["uid"], c["cp"], extra=c), now))
    for fam, n in sorted(world.CANDY.items()):                       # pokemon_family
        if n > 0:
            items.append(_inventory_item(
                10, pb.Writer().uint(1, fam).int_(2, n).to_bytes(), now))
    _act = world.applied_items()
    if _act:                                                         # applied_items
        _aw = pb.Writer()
        for _a in _act:
            _aw.message(4, _applied_item(_a))      # AppliedItemsProto.Item = 4
        items.append(_inventory_item(8, _aw.to_bytes(), now))
    for _e in world.eggs():                                          # eggs
        items.append(_inventory_item(1, build_egg_data(_e), now))
    _incs = world.incubators()
    if _incs:                                                        # egg_incubators
        _iw = pb.Writer()
        for _i in _incs:
            _iw.message(1, build_incubator(_i))
        items.append(_inventory_item(9, _iw.to_bytes(), now))
        
    # --- Pokedex Fix ---
    pokedex_entries = {pid: (0, 0) for pid in range(1, 152)}
    for _pid, _seen, _caught in world.pokedex():                     # pokedex_entry
        pokedex_entries[_pid] = (_seen, _caught)
    pokedex_entries[151] = [1, 0]
    for _pid, (_seen, _caught) in pokedex_entries.items():
        items.append(_inventory_item(3, pb.Writer()
                                     .uint(1, _pid).int_(2, _seen)
                                     .int_(3, _caught).to_bytes(), now))
    # -------------------

    # Transferred/evolved Pokemon: tell the client they are GONE.
    alive = {int(c["uid"]) for c in world.caught()}
    for uid, _ts in world.recent_deletions():
        if uid in alive:            # belt and braces: never delete a live Pokemon
            continue
        items.append(_deleted_item(1, pb.Writer().fixed64(1, uid).to_bytes(), now))
    # NOTE: no player_currency item here. InventoryItemData.player_currency is a
    # PlayerCurrencyProto, whose only field is Gems -- putting stardust in it just
    # set gems to the stardust value. Stardust goes out via PlayerData.currencies.
    delta = pb.Writer().int_(2, now)                          # new_timestamp_ms
    for it in items:
        delta.message(3, it)                                  # inventory_items
    return (pb.Writer()
            .bool_(1, True)                                   # success
            .message(2, delta.to_bytes())                     # inventory_delta
            .to_bytes())



# Asset/template versions we pin the world to. Returning matching timestamps in
# DOWNLOAD_REMOTE_CONFIG_VERSION and the digest/settings responses keeps the
# client from looping on downloads it can't complete.
ASSET_TS = 1_470_600_000_000        # both must be NON-zero or config-version fails
                                    # (bump this to force the client to re-fetch the
                                    #  asset digest after we change bundle entries;
                                    #  bumped when we swapped the fake egg for the real
                                    #  151-bundle digest w/ genuine keys, 2026-08-02)
TEMPLATES_TS = 1_473_300_000_000    # bumped 2026-08-04 for the rebuilt family_id
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
SETTINGS_HASH = "pogoprivserver02"   # bumped when GlobalSettings field numbers were
                                     # fixed -> forces the client to re-read settings
                                     # instead of reusing the cached (broken) ones


def build_asset_digest_entry(asset_id, bundle_name, version=1, checksum=0,
                             size=1, key=b"") -> bytes:
    # AssetDigestEntry { asset_id=1, bundle_name=2, version=3 int64,
    #   checksum=4 fixed32, size=5 int32, key=6 bytes }
    w = (pb.Writer()
         .string(1, asset_id)
         .string(2, bundle_name)
         .uint(3, version)
         .fixed32(4, checksum)
         .int_(5, size))
    if key:
        w.bytes_(6, key)                    # empty key -> (test) no decryption
    return w.to_bytes()


# --- real 2016 CDN bundles (encrypted) + their genuine digest, served for download ---
# assets/ holds the encrypted pm#### bundles AND the shipped `asset_digest`
# (the real GetAssetDigestResponse). We serve the encrypted bytes verbatim and
# hand the client the REAL per-bundle key/checksum/version/size from that digest,
# so the client's own DecodeAndroid decrypts + CRC-validates each bundle.
_HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(_HERE, "assets")

# Photos for your PokeStops/Gyms: drop image files here and reference them by
# filename in the World Manager. Lives next to the .exe so it's easy to find.
import sys as _sys
PHOTO_DIR = os.path.join(
    os.path.dirname(_sys.executable) if getattr(_sys, "frozen", False) else _HERE,
    "photos")
try:
    os.makedirs(PHOTO_DIR, exist_ok=True)
except OSError:
    pass

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
PLAIN_ASSETS = os.environ.get("PLAIN_ASSETS", "0") == "1"
# CRC_FIX=1 (default): advertise CRC32(decrypted bundle) as the digest checksum
# instead of the genuine (unidentified-algorithm) value. Set 0 to pass through.
CRC_FIX = os.environ.get("CRC_FIX", "0") == "1"   # 1 = advertise CRC32(decrypted)
PLAIN_DIR = os.path.join(_HERE, "assets_plain")
_PLAIN_MANIFEST = None
_REAL_DIGEST = None


def _plain_manifest():
    """{bundle_name: {size, crc32}} for the pre-decrypted bundles, or {}."""
    global _PLAIN_MANIFEST
    if _PLAIN_MANIFEST is None:
        import json
        try:
            with open(os.path.join(PLAIN_DIR, "manifest.json"), encoding="utf-8") as fh:
                _PLAIN_MANIFEST = json.load(fh)
        except (OSError, ValueError):
            _PLAIN_MANIFEST = {}
    return _PLAIN_MANIFEST


_RAW_DIGEST_BYTES = None
_DIGEST_TS = None


def _raw_digest_bytes():
    """The genuine GetAssetDigestResponse exactly as Niantic sent it."""
    global _RAW_DIGEST_BYTES
    if _RAW_DIGEST_BYTES is None:
        try:
            with open(os.path.join(ASSETS_DIR, "asset_digest"), "rb") as fh:
                _RAW_DIGEST_BYTES = fh.read()
        except OSError:
            _RAW_DIGEST_BYTES = b""
    return _RAW_DIGEST_BYTES


def digest_timestamp():
    """The digest's OWN timestamp (field 2). DOWNLOAD_REMOTE_CONFIG_VERSION must
    advertise exactly this value as asset_digest_timestamp_ms, or the client never
    accepts the digest as current and re-requests GET_ASSET_DIGEST forever (observed
    live: 6 fetches in one session, models never usable). maierfelix/POGOServer
    hardcodes the same thing: asset_digest_timestamp_ms == '1467338276561000', which
    is the microsecond value baked into its digest file -- NOT a millisecond clock."""
    global _DIGEST_TS
    if _DIGEST_TS is None:
        raw = _raw_digest_bytes()
        _DIGEST_TS = (pb.get(pb.decode(raw), 2, pb.WT_VARINT) or 0) if raw else 0
    return _DIGEST_TS


def _load_real_digest():
    """Parse assets/asset_digest -> {bundle_name: {asset_id, version, checksum,
    size, key}}. Fields per the 0.29 AssetDigestEntry contract: asset_id=1,
    bundle_name=2, version=3, checksum=4 (fixed32 CRC32 of the DECRYPTED bundle),
    size=5 (encrypted size on the wire), key=6 (16-byte AES key)."""
    global _REAL_DIGEST
    if _REAL_DIGEST is not None:
        return _REAL_DIGEST
    _REAL_DIGEST = {}
    path = os.path.join(ASSETS_DIR, "asset_digest")
    if not os.path.isfile(path):
        return _REAL_DIGEST
    with open(path, "rb") as fh:
        data = fh.read()
    for raw in pb.get_all(pb.decode(data), 1):        # repeated AssetDigestEntry
        if not isinstance(raw, bytes):
            continue
        e = pb.decode(raw)
        name = pb.get(e, 2, pb.WT_LEN)
        if not isinstance(name, bytes):
            continue
        name = name.decode("ascii", "replace")
        aid = pb.get(e, 1, pb.WT_LEN)
        key = pb.get(e, 6, pb.WT_LEN)
        _REAL_DIGEST[name] = {
            "asset_id": aid.decode("ascii", "replace") if isinstance(aid, bytes) else name,
            "version":  pb.get(e, 3, pb.WT_VARINT) or 0,
            "checksum": pb.get(e, 4, pb.WT_32) or 0,
            "size":     pb.get(e, 5, pb.WT_VARINT) or 0,
            "key":      key if isinstance(key, bytes) else b"",
        }
    return _REAL_DIGEST


def _our_bundles():
    if not os.path.isdir(ASSETS_DIR):
        return []

    digest = _load_real_digest()
    plain_manifest = _plain_manifest()
    plain = plain_manifest if PLAIN_ASSETS else {}

    out = []
    for fn in sorted(os.listdir(ASSETS_DIR)):
        if not fn.startswith("pm") or fn not in digest:
            continue

        m = digest[fn]

        # Decrypted asset path: use local plain metadata and blank key
        if fn in plain:
            out.append({
                "asset_id": fn,
                "bundle_name": fn,
                "version": m["version"],
                "checksum": plain[fn]["crc32"],
                "size": plain[fn]["size"],
                "key": b"",
            })
            continue

        # Standard asset path: calculate CRC override if needed
        checksum = m["checksum"]
        if CRC_FIX:
            pc = plain_manifest.get(fn)
            if pc:
                checksum = pc["crc32"]

        out.append({
            "asset_id": m["asset_id"],
            "bundle_name": fn,
            "version": m["version"],
            "checksum": checksum,
            "size": m["size"],
            "key": m["key"],
        })

    return out


def bundle_path(asset_id):
    """File to serve for a download. asset_id is now the GENUINE Niantic id
    ('<guid>/<version>'), so map it back to its pm#### bundle via the digest.
    Prefers the pre-decrypted copy when PLAIN_ASSETS is on."""
    name = None
    for bn, m in _load_real_digest().items():
        if m["asset_id"] == asset_id:
            name = bn
            break
    if name is None:
        name = os.path.basename(asset_id)        # fall back to a bare 'pm####'
    if PLAIN_ASSETS:
        p = os.path.join(PLAIN_DIR, name)
        if os.path.isfile(p):
            return p
    p = os.path.join(ASSETS_DIR, name)
    return p if os.path.isfile(p) else None


def build_get_asset_digest_response() -> bytes:
    # GetAssetDigestResponse { digest=1 (repeated), timestamp_ms=2,
    #   result=3 (1=SUCCESS), page_offset=4 }. The client rejects an EMPTY digest
    # as a null response, so include at least one entry. We list our real pm####
    # bundles so the client will fetch them via GET_DOWNLOAD_URLS.
    # Preferred: hand back the GENUINE digest bytes untouched (this is exactly what
    # POGOServer does -- it serves player.asset_digest.buffer verbatim). Rebuilding it
    # risks changing the timestamp/entries the client keys off. We only append the
    # result field, which this 0.29 build wants and which protobuf tolerates anywhere.
    raw = _raw_digest_bytes()
    if raw and not PLAIN_ASSETS:
        return raw + pb.Writer().uint(3, 1).to_bytes()      # result = SUCCESS

    w = pb.Writer()
    entries = _our_bundles()
    if not entries:
        # no real digest present -> single placeholder so the client doesn't treat
        # the digest as a null response (enough to reach the map, no models).
        w.message(1, build_asset_digest_entry("A0", "bundle0", version=1, checksum=0, size=1))
    for b in entries:
        w.message(1, build_asset_digest_entry(
            b["asset_id"], b["bundle_name"], version=b["version"],
            checksum=b["checksum"], size=b["size"], key=b["key"]))
    return w.uint(2, ASSET_TS).uint(3, 1).to_bytes()


def parse_get_download_urls(msg: bytes):
    """GetDownloadUrlsMessage { asset_id = 1 (repeated string) }."""
    f = pb.decode(msg)
    ids = []
    for v in pb.get_all(f, 1):
        if isinstance(v, bytes):
            ids.append(v.decode("utf-8", "replace"))
    return ids


def build_get_download_urls_response(asset_ids, base_url) -> bytes:
    # GetDownloadUrlsResponse { download_urls=1 (repeated DownloadUrlEntry) }
    #   DownloadUrlEntry { asset_id=1, url=2, size=3 int32, checksum=4 uint32 }
    # Field numbers per POGOProtos + maierfelix/POGOServer. (Earlier builds put a
    # result at #1 and the list at #2 with no size/checksum -- WRONG; this path was
    # never reached before so it went unverified.) size/checksum are the genuine
    # digest values so the client's pre-decrypt download check passes.
    digest = _load_real_digest()
    w = pb.Writer()
    for aid in asset_ids:
        entry = pb.Writer().string(1, aid).string(2, f"{base_url}/{aid}")
        m = digest.get(aid)
        if m:
            entry.int_(3, m["size"]).uint(4, m["checksum"])
        w.message(1, entry.to_bytes())
    return w.to_bytes()


def build_item_template(template_id: str, body: bytes = b"") -> bytes:
    # ItemTemplate { template_id=1, pokemon_settings=2, item_settings=3, ... }
    w = pb.Writer().string(1, template_id)
    if body:
        w.raw(body)
    return w.to_bytes()


# ------------------------------------------------------------- GET_MAP_OBJECTS



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


# Fallback move ids that exist as real Move templates in our game master
# (Bulbasaur's quick_moves), used only if gamedata.py is missing.
_MOVE_1, _MOVE_2 = 214, 221

try:
    import gamedata as _gd                        # generated by tools/convert_gm.py
except ImportError:                               # pragma: no cover
    _gd = None


def moves_for(pokemon_id, uid):
    """The (quick, charged) move ids for one Pokemon, stable for a given uid.

    Everything used to get move_1=214/move_2=221 -- Vine Whip and Tackle, BOTH of
    which are FAST moves. So no Pokemon in the game had a charged move at all,
    and the charged attack animated as `tackle_fast`. Species movesets come
    straight from the game master now.
    """
    if _gd is None:
        return _MOVE_1, _MOVE_2
    q = _gd.QUICK.get(pokemon_id) or [_MOVE_1]
    c = _gd.CHARGED.get(pokemon_id) or [_MOVE_2]
    r = _random.Random(uid)
    return r.choice(q), r.choice(c)


def _ivs(uid):
    """The three IVs for a Pokemon, stable for a given uid."""
    r = _random.Random(uid)
    return r.randint(0, 15), r.randint(0, 15), r.randint(0, 15)


def cpm_for(pokemon_id, cp, iv_a, iv_d, iv_s):
    """The cp_multiplier that makes this Pokemon's CP add up.

    PokemonProto.CpMultiplier is field 20 and we were never sending it, so it
    arrived as 0.0 -- and the client's damage formula is
    (base_attack + iv) * cp_multiplier * ..., so EVERY attack computed zero
    damage and no health bar ever moved. Inverting the CP formula
    CP = (atk * sqrt(def) * sqrt(sta) * cpm^2) / 10
    gives a multiplier consistent with the CP we already handed out, so CP, HP
    and damage all agree instead of being three unrelated numbers.
    """
    st = _gd.STATS.get(pokemon_id) if _gd else None
    if not st:
        return 0.5
    ba, bd, bs = st
    denom = (ba + iv_a) * _math.sqrt(bd + iv_d) * _math.sqrt(bs + iv_s)
    if denom <= 0:
        return 0.5
    cpm = _math.sqrt(max(10.0, float(cp)) * 10.0 / denom)
    # Deliberately NOT clamped to the level-40 maximum (0.7903). The client
    # recomputes the CP it displays from this multiplier, so clamping meant a
    # requested CP the species cannot naturally reach was silently shown much
    # lower -- only 21 of 151 species can hit 2500 and exactly one can hit 4000,
    # which made the High CP event look broken. An event is allowed to hand out
    # Pokemon stronger than the wild game ever could; the ceiling here is only to
    # stop a silly value producing an absurd health bar.
    lo = _gd.CPM[0] if (_gd and _gd.CPM) else 0.094
    return max(lo, min(6.0, cpm))


def move_timing(move_id, fallback_duration=700):
    """(duration_ms, damage_window_start_ms, damage_window_end_ms, energy_delta),
    the windows relative to the action start. The client matches an action to an
    animation through the performer's moveset, so these have to be the move's
    REAL numbers -- an invented duration resolves to nothing and the action is
    dropped without a word in the log."""
    m = _gd.MOVES.get(move_id) if _gd else None
    if not m:
        return fallback_duration, fallback_duration // 3, fallback_duration, 0
    dur, dws, dwe, energy, _power = m
    return dur, dws, dwe, energy


# How much each healing item restores. Max Potion/Max Revive are "full".
POTIONS = {101: 20, 102: 50, 103: 200, 104: 10 ** 9}      # potion..max potion
REVIVES = {201: 0.5, 202: 1.0}                            # revive, max revive


def max_hp(pokemon_id, uid, cp):
    """A Pokemon's full health -- the same stamina formula the battle code uses."""
    return _hp_for(cp, pokemon_id, uid)


def current_hp(c):
    """Stored health, defaulting to full for Pokemon caught before HP was tracked."""
    m = max_hp(c["pokemon_id"], c["uid"], c.get("cp", 100))
    v = c.get("stamina")
    return m if v is None else max(0, min(int(v), m))


# --------------------------------------------------------------------- EGGS
EGG_TIERS = (2.0, 5.0, 10.0)


def _egg_species_pools():
    """Split the (non-legendary) Kanto species into 2/5/10 km tiers by how strong
    they can get. Deriving it from the game master's own base stats beats
    inventing an egg chart, and it gives the right feel: commons at 2 km, the
    rare and powerful at 10 km."""
    global _EGG_POOLS
    if _EGG_POOLS is None:
        pool = _spawn_pool()                       # already excludes legendaries
        ranked = sorted(set(pool), key=lambda pid: _max_reachable_cp(pid))
        n = len(ranked)
        _EGG_POOLS = {2.0: ranked[:int(n * 0.55)],
                      5.0: ranked[int(n * 0.55):int(n * 0.85)],
                      10.0: ranked[int(n * 0.85):]}
        for k, v in _EGG_POOLS.items():            # never hand back an empty tier
            if not v:
                _EGG_POOLS[k] = ranked or [1]
    return _EGG_POOLS


def _max_reachable_cp(pokemon_id):
    st = _gd.STATS.get(pokemon_id) if _gd else None
    if not st:
        return 0.0
    a, d, sta = st
    cpm = _gd.CPM[-1] if (_gd and _gd.CPM) else 0.7903
    return ((a + 15) * _math.sqrt(d + 15) * _math.sqrt(sta + 15) * cpm * cpm) / 10


def hatch_species(target_km):
    """(pokemon_id, cp) for an egg of this tier. Hatchlings skew strong, the way
    a 10 km egg felt worth the walk."""
    pools = _egg_species_pools()
    tier = min(EGG_TIERS, key=lambda t: abs(t - float(target_km)))
    rnd = _random.Random()
    pid = rnd.choice(pools[tier])
    lo = int(200 + tier * 60)
    hi = int(lo + tier * 110)
    return pid, rnd.randint(lo, hi)


def build_egg_data(egg) -> bytes:
    """An egg is just a PokemonProto with IsEgg set.
    { id=1, is_egg=10, egg_km_walked_target=11, egg_km_walked_start=12,
      egg_incubator_id=25 }."""
    w = (pb.Writer()
         .fixed64(1, egg["uid"])
         .uint(10, 1)                                   # is_egg
         .double(11, float(egg.get("target_km", 2.0)))
         .double(12, float(egg.get("start_km", 0.0))))
    if egg.get("incubator"):
        w.string(25, str(egg["incubator"]))
    return w.to_bytes()


def build_incubator(inc) -> bytes:
    """EggIncubatorProto { item_id=1, item=2, incubator_type=3, uses_remaining=4,
    pokemon_id=5, start_km_walked=6, target_km_walked=7 }."""
    w = (pb.Writer()
         .string(1, str(inc["id"]))
         .uint(2, int(inc.get("item", 901)))
         .uint(3, 1))                                   # INCUBATOR_TYPE_DISTANCE
    if int(inc.get("uses", -1)) >= 0:
        w.int_(4, int(inc["uses"]))
    if inc.get("egg"):
        w.fixed64(5, int(inc["egg"]))
        w.double(6, float(inc.get("start_km", 0.0)))
        w.double(7, float(inc.get("target_km", 0.0)))
    return w.to_bytes()


def parse_use_item_egg_incubator(msg):
    """UseItemEggIncubatorProto { item_id=1, pokemon_id=2 } -- the client really
    does spell it PokemondId."""
    f = pb.decode(msg)
    iid = pb.get(f, 1, pb.WT_LEN)
    return ((iid.decode("utf-8", "replace") if isinstance(iid, bytes) else ""),
            pb.get(f, 2, pb.WT_64) or pb.get(f, 2, pb.WT_VARINT) or 0)


def build_use_item_egg_incubator_response(incubator_id, egg_uid) -> bytes:
    """UseItemEggIncubatorOutProto { result=1, egg_incubator=2 }."""
    import world
    code, inc = world.use_incubator(incubator_id, egg_uid)
    w = pb.Writer().uint(1, code)
    if code == 1 and inc:
        w.message(2, build_incubator(inc))
    return w.to_bytes()


def build_get_hatched_eggs_response() -> bytes:
    """GetHatchedEggsOutProto { success=1, pokemon_id=2, exp_awarded=3,
    candy_awarded=4, stardust_awarded=5 } -- four PARALLEL repeated arrays."""
    import world
    done = world.drain_hatched()
    w = pb.Writer().bool_(1, True)
    for h in done:
        w.fixed64(2, h["uid"])
        world.add_xp(h["xp"])
        world.add_candy(pokemon_family(h["pokemon_id"]), h["candy"])
        world.add_stardust(h["stardust"])
        world.pokedex_caught(h["pokemon_id"])
    if done:
        w.packed_varints(3, [h["xp"] for h in done])
        w.packed_varints(4, [h["candy"] for h in done])
        w.packed_varints(5, [h["stardust"] for h in done])
    return w.to_bytes()


ITEM_LUCKY_EGG = 301
ITEM_INCENSE = 401
ITEM_LURE = 501


def parse_use_item_xp_boost(msg):
    """UseItemXpBoostProto { item=1 }."""
    return pb.get(pb.decode(msg), 1, pb.WT_VARINT) or 0


# HoloItemType, read off the client: the applied-item entry has to say WHICH
# kind of buff it is or the game shows no timer at all. This was hardcoded to 1
# (ITEM_TYPE_POKEBALL), so a burning Lucky Egg matched nothing and looked dead.
ITEM_TYPE = {301: 11,      # ITEM_TYPE_XP_BOOST
             401: 10,      # ITEM_TYPE_INCENSE
             501: 8,       # ITEM_TYPE_DISK  (Lure Module)
             902: 9}       # ITEM_TYPE_INCUBATOR


def _applied_item(entry) -> bytes:
    """AppliedItemProto { item=1, item_type=2, expiration_ms=3, applied_ms=4 }."""
    iid = int(entry["item"])
    return (pb.Writer()
            .uint(1, iid)
            .uint(2, ITEM_TYPE.get(iid, 0))
            .int_(3, int(entry["expires_ms"]))
            .int_(4, int(entry["applied_ms"]))
            .to_bytes())


def build_use_item_xp_boost_response(item_id) -> bytes:
    """UseItemXpBoostOutProto { result=1, applied_items=2 }.
    1=SUCCESS 2=INVALID_ITEM_TYPE 3=ALREADY_ACTIVE 4=NO_ITEMS_REMAINING."""
    import world
    if int(item_id) != ITEM_LUCKY_EGG:
        return pb.Writer().uint(1, 2).to_bytes()
    mins = _cfg.get("boosts", "lucky_egg_minutes", cast=float)
    code, entry = world.apply_item(ITEM_LUCKY_EGG, mins)
    code = {1: 1, 2: 3, 3: 4}.get(code, 4)
    w = pb.Writer().uint(1, code)
    if code == 1:
        aw = pb.Writer()
        for a in world.applied_items():
            # AppliedItemsProto.Item is field 4, NOT 1. Field 1 is what
            # AppliedItemProto uses internally; putting the list there meant the
            # client read an EMPTY set of active items and showed no buff at all.
            aw.message(4, _applied_item(a))
        w.message(2, aw.to_bytes())
    return w.to_bytes()


def build_use_incense_response(item_id) -> bytes:
    """UseIncenseActionOutProto { result=1, applied_incense=2 }.
    1=SUCCESS 2=ALREADY_ACTIVE 3=NONE_IN_INVENTORY."""
    import world
    mins = _cfg.get("boosts", "incense_minutes", cast=float)
    code, entry = world.apply_item(ITEM_INCENSE, mins)
    w = pb.Writer().uint(1, code)
    if code == 1 and entry:
        w.message(2, _applied_item(entry))
    return w.to_bytes()


def parse_add_fort_modifier(msg):
    """AddFortModifierProto { modifier_type=1, fort_id=2, player_lat=3,
    player_lng=4 }."""
    f = pb.decode(msg)
    fid = pb.get(f, 2, pb.WT_LEN)
    return (pb.get(f, 1, pb.WT_VARINT) or 0,
            fid.decode("utf-8", "replace") if isinstance(fid, bytes) else "",
            _f64_to_double(pb.get(f, 3, pb.WT_64)),
            _f64_to_double(pb.get(f, 4, pb.WT_64)))


def build_add_fort_modifier_response(item_id, fort_id, now_ms,
                                     lat=0.0, lng=0.0) -> bytes:
    """AddFortModifierOutProto { result=1, fort_details=2 }.
    1=SUCCESS 2=FORT_ALREADY_HAS_MODIFIER 3=TOO_FAR_AWAY 4=NO_ITEM_IN_INVENTORY.

    Field 2 is NOT optional in practice: the client holds the lure-placing
    animation open until it gets the refreshed fort back, so answering with a
    bare result left it stuck on that screen until the game was restarted.
    """
    import world
    mins = _cfg.get("boosts", "lure_minutes", cast=float)
    code, _mod = world.add_fort_modifier(fort_id, ITEM_LURE, mins,
                                         world.current().username)
    w = pb.Writer().uint(1, code)
    if code == 1:
        w.message(2, build_fort_details_response(fort_id, lat, lng))
    return w.to_bytes()


def build_get_incense_pokemon_response() -> bytes:
    """GetIncensePokemonOutProto -- we answer "nothing extra here" and instead
    make incense work by thickening the ordinary wild spawns around the trainer,
    which is the part that actually shows up on the map."""
    return pb.Writer().uint(1, 0).to_bytes()


def parse_use_item_capture(msg):
    """UseItemCaptureProto { item=1, encounter_id=2, spawn_point_guid=3 }."""
    f = pb.decode(msg)
    return (pb.get(f, 1, pb.WT_VARINT) or 0,
            pb.get(f, 2, pb.WT_64) or pb.get(f, 2, pb.WT_VARINT) or 0)


def build_use_item_capture_response(item_id, encounter_id) -> bytes:
    """UseItemCaptureOutProto { success=1, item_capture_mult=2, item_flee_mult=3,
    stop_movement=4, stop_attack=5, target_max=6, target_slow=7 }.

    A Razz Berry makes the next ball much likelier to hold and the Pokemon much
    less likely to bolt. The multiplier is remembered against THIS encounter and
    spent on the next throw."""
    import world
    if item_id != ITEM_RAZZ_BERRY or not world.take_item(item_id, 1):
        return pb.Writer().bool_(1, False).to_bytes()
    cap = _cfg.get("catching", "razz_capture_mult", cast=float)
    flee = _cfg.get("catching", "razz_flee_mult", cast=float)
    world.use_berry(encounter_id, cap)
    return (pb.Writer()
            .bool_(1, True)
            .double(2, cap)
            .double(3, flee)
            .bool_(4, True)                  # the berry calms it down
            .to_bytes())


def parse_set_player_team(msg):
    """SetPlayerTeamProto { team=1 }. 1=Mystic(blue) 2=Valor(red) 3=Instinct(yellow)."""
    return pb.get(pb.decode(msg), 1, pb.WT_VARINT) or 0


def build_set_player_team_response(team, username) -> bytes:
    """SetPlayerTeamOutProto { status=1, player=2 }.
    1=SUCCESS 2=TEAM_ALREADY_SET 3=FAILURE."""
    import world
    status, _t = world.set_team(team)
    return (pb.Writer()
            .uint(1, status)
            .message(2, build_player_data(username))
            .to_bytes())


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


def parse_use_item(msg):
    """UseItemPotionProto / UseItemReviveProto { item_id=1, pokemon_id=2 }."""
    f = pb.decode(msg)
    return (pb.get(f, 1, pb.WT_VARINT) or 0,
            pb.get(f, 2, pb.WT_64) or pb.get(f, 2, pb.WT_VARINT) or 0)


def build_use_item_potion_response(item_id, uid) -> bytes:
    """UseItemPotionOutProto { result=1, stamina=2 }.
    1=SUCCESS 2=ERROR_NO_POKEMON 3=ERROR_CANNOT_USE 4=ERROR_DEPLOYED_TO_FORT."""
    import world
    c = world.get_caught(uid)
    if not c:
        return pb.Writer().uint(1, 2).to_bytes()
    if world.is_deployed(uid):
        return pb.Writer().uint(1, 4).to_bytes()
    m = max_hp(c["pokemon_id"], uid, c.get("cp", 100))
    hp = current_hp(c)
    # A potion cannot touch a fainted Pokemon -- that needs a Revive.
    if hp <= 0 or hp >= m or item_id not in POTIONS:
        return pb.Writer().uint(1, 3).to_bytes()           # ERROR_CANNOT_USE
    if not world.take_item(item_id, 1):
        return pb.Writer().uint(1, 3).to_bytes()
    hp = min(m, hp + POTIONS[item_id])
    world.update_caught(uid, stamina=hp)
    return pb.Writer().uint(1, 1).int_(2, hp).to_bytes()


def build_use_item_revive_response(item_id, uid) -> bytes:
    """UseItemReviveOutProto { result=1, stamina=2 }. Revives only work on a
    FAINTED Pokemon, which is the whole point of them."""
    import world
    c = world.get_caught(uid)
    if not c:
        return pb.Writer().uint(1, 2).to_bytes()
    if world.is_deployed(uid):
        return pb.Writer().uint(1, 4).to_bytes()
    m = max_hp(c["pokemon_id"], uid, c.get("cp", 100))
    if current_hp(c) > 0 or item_id not in REVIVES:
        return pb.Writer().uint(1, 3).to_bytes()           # not fainted
    if not world.take_item(item_id, 1):
        return pb.Writer().uint(1, 3).to_bytes()
    hp = max(1, int(m * REVIVES[item_id]))
    world.update_caught(uid, stamina=hp)
    return pb.Writer().uint(1, 1).int_(2, hp).to_bytes()


def build_pokemon_data(pokemon_id, uid, cp=500, extra=None) -> bytes:
    # PokemonData { id=1 fixed64, pokemon_id=2 enum, cp=3, stamina=4, stamina_max=5,
    #   move_1=6, move_2=7, height_m=15 float, weight_kg=16 float,
    #   individual_attack=17, individual_defense=18, individual_stamina=19 }
    # (VERIFIED against POGOProtos PokemonData.proto.) A bare id/cp triple is legal
    # but leaves the client without moves/IVs to display; fill in a sane creature.
    import world
    e = extra if extra is not None else (world.get_caught(uid) or {})
    # Real health, so the bar means something and a fainted Pokemon reads as 0.
    # (Battle code passes stamina/stamina_max explicitly and still wins here.)
    if "stamina_max" in e:
        hp_max = int(e["stamina_max"])
        hp = int(e.get("stamina", hp_max))
    else:
        hp_max = _hp_for(cp, pokemon_id, uid)
        hp = hp_max if e.get("stamina") is None else max(0, min(int(e["stamina"]), hp_max))
    _m1, _m2 = moves_for(pokemon_id, uid)
    _iv_a, _iv_d, _iv_s = _ivs(uid)
    w = (pb.Writer()
         .fixed64(1, uid)
         .uint(2, pokemon_id)
         .int_(3, cp)
         .int_(4, hp).int_(5, max(hp, hp_max))        # stamina / stamina_max
         .uint(6, _m1).uint(7, _m2)                   # move_1 / move_2
         .float_(15, 0.6).float_(16, 8.0)             # height_m / weight_kg
         .int_(17, _iv_a)                             # individual_attack
         .int_(18, _iv_d)                             # individual_defense
         .int_(19, _iv_s)                             # individual_stamina
         .float_(20, cpm_for(pokemon_id, cp, _iv_a, _iv_d, _iv_s)))
    if e.get("num_upgrades"):
        w.int_(27, int(e["num_upgrades"]))
    if e.get("favorite"):
        w.int_(29, 1)
    if e.get("nickname"):
        w.string(30, str(e["nickname"])[:12])
    return w.to_bytes()


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
    #   type=9 (GYM=0, CHECKPOINT=1), gym_points=10, is_in_battle=11,
    #   cooldown_complete_timestamp_ms=14 }
    # The gym fields are what make a Gym render with a team colour and a defender
    # on top of it instead of an empty grey tower.
    w = (pb.Writer()
         .string(1, fort_id)
         .int_(2, now_ms)
         .double(3, lat)
         .double(4, lng))
    if not is_gym:
        # A Lure on the map fort is PokemonFortProto.ActiveFortModifier = 12, and
        # it is just the ITEM ID -- not a message.
        # This was previously written as a message into field 13, which on this
        # proto is ActivePokemon: the client parsed the lure as a Pokemon and
        # CRASHED the moment you tapped the stop.
        import world
        _m = world.fort_modifier(fort_id)
        if _m:
            w.uint(12, int(_m["item"]))
    if is_gym:
        import world
        guard = world.gym_guard(fort_id)
        # A gym with defenders flies your team's colour; an empty one goes back to
        # NEUTRAL (white/unclaimed). Sending TEAM here unconditionally was a guess
        # at the crash-on-tap -- the real cause was an empty `urls` list, so an
        # unowned gym is safe again.
        if guard:
            pid, cp, points = guard
            # whoever holds it -- may be another account's team now
            w.uint(5, world.gym_team(fort_id) or _team()).uint(6, pid).int_(7, cp)
        else:
            points = 0
            w.uint(5, 0)                     # NEUTRAL -> white gym
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


# ------------------------------------------------- POKEMON MANAGEMENT (evolve etc)
_EVO = None
_EGG_POOLS = None


def _evo_table():
    """{pokemon_id: {"family": id, "evolves_to": [ids], "candy": n}} read straight
    out of the game master we already serve, so costs match what the client shows."""
    global _EVO
    if _EVO is None:
        table = {}
        try:
            # read game_master.bin DIRECTLY -- going through the response builder
            # made this depend on SERVE_GAME_MASTER being set, so evolution data
            # silently vanished and everything reported CANNOT_EVOLVE.
            gm = os.path.join(_HERE, "game_master.bin")
            with open(gm, "rb") as fh:
                data = fh.read()
            for t in pb.get_all(pb.decode(data), 2):
                tt = pb.decode(t)
                ps = pb.get(tt, 2, pb.WT_LEN)
                if not ps:
                    continue
                p = pb.decode(ps)
                pid = pb.get(p, 1, pb.WT_VARINT)
                if not pid:
                    continue
                raw = pb.get(p, 12, pb.WT_LEN) or b""      # evolution_ids (packed)
                evo, i = [], 0
                while i < len(raw):
                    v, sh = 0, 0
                    while True:
                        b = raw[i]; i += 1
                        v |= (b & 0x7F) << sh
                        if not b & 0x80:
                            break
                        sh += 7
                    evo.append(v)
                table[pid] = {"family": pb.get(p, 21, pb.WT_VARINT) or pid,
                              "evolves_to": evo,
                              "candy": pb.get(p, 22, pb.WT_VARINT) or 0}
        except Exception:
            pass
        _EVO = table
    return _EVO

def extract_badge_templates(data: bytes) -> dict[str, bytes]:
    badges = {}
    for raw_template in pb.get_all(pb.decode(data), 2):
        template = pb.decode(raw_template)
        raw_id = pb.get(template, 1, pb.WT_LEN)
        if not isinstance(raw_id, bytes):
            continue
        try:
            template_id = raw_id.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if "BADGE" not in template_id:
            continue
        for field in template:
            if field["field"] != 1 and field["wire"] == pb.WT_LEN and field["value"]:
                badges[template_id] = field["value"]
                break
    return badges


def pokemon_family(pokemon_id):
    return _evo_table().get(pokemon_id, {}).get("family", pokemon_id)


def parse_pokemon_id(msg):
    """Every one of these messages is just { pokemon_id = 1 }."""
    f = pb.decode(msg)
    return pb.get(f, 1, pb.WT_64) or pb.get(f, 1, pb.WT_VARINT) or 0


def build_release_response(uid) -> bytes:
    """ReleasePokemonResponse { result=1, candy_awarded=2 }.
    1=SUCCESS, 2=POKEMON_DEPLOYED, 3=FAILED."""
    import world
    c = world.get_caught(uid)
    if not c:
        return pb.Writer().uint(1, 3).to_bytes()               # FAILED
    if world.is_deployed(uid):
        return pb.Writer().uint(1, 2).to_bytes()               # POKEMON_DEPLOYED
    ok, _why = world.release(uid)
    if not ok:
        return pb.Writer().uint(1, 3).to_bytes()
    fam = pokemon_family(c["pokemon_id"])
    world.add_candy(fam, 1)
    return pb.Writer().uint(1, 1).int_(2, 1).to_bytes()        # SUCCESS, 1 candy


def build_upgrade_response(uid) -> bytes:
    """UpgradePokemonResponse { result=1, upgraded_pokemon=2 }.
    1=SUCCESS, 2=NOT_FOUND, 3=INSUFFICIENT_RESOURCES, 5=IS_DEPLOYED."""
    import world
    c = world.get_caught(uid)
    if not c:
        return pb.Writer().uint(1, 2).to_bytes()
    if world.is_deployed(uid):
        return pb.Writer().uint(1, 5).to_bytes()
    fam = pokemon_family(c["pokemon_id"])
    cost_candy = _cfg.get("pokemon", "powerup_candy", cast=int)
    cost_dust = _cfg.get("pokemon", "powerup_stardust", cast=int)
    if not world.spend(fam, cost_candy, cost_dust):
        return pb.Writer().uint(1, 3).to_bytes()               # can't afford it
    gain = _cfg.get("pokemon", "powerup_cp_gain", cast=int)
    newcp = int(c["cp"] * (1 + gain / 100.0)) + 10
    upd = world.update_caught(uid, cp=newcp,
                              num_upgrades=int(c.get("num_upgrades", 0)) + 1)
    return (pb.Writer()
            .uint(1, 1)
            .message(2, build_pokemon_data(upd["pokemon_id"], uid, newcp))
            .to_bytes())


def build_evolve_response(uid) -> bytes:
    """EvolvePokemonResponse { result=1, evolved_pokemon_data=2,
    experience_awarded=3, candy_awarded=4 }.
    1=SUCCESS, 2=MISSING, 3=INSUFFICIENT_RESOURCES, 4=CANNOT_EVOLVE, 5=DEPLOYED."""
    import world
    c = world.get_caught(uid)
    if not c:
        return pb.Writer().uint(1, 2).to_bytes()
    if world.is_deployed(uid):
        return pb.Writer().uint(1, 5).to_bytes()
    info = _evo_table().get(c["pokemon_id"], {})
    evo = info.get("evolves_to") or []
    if not evo:
        return pb.Writer().uint(1, 4).to_bytes()               # CANNOT_EVOLVE
    need = info.get("candy") or 25
    fam = info.get("family", c["pokemon_id"])
    if not world.spend(fam, need, 0):
        return pb.Writer().uint(1, 3).to_bytes()
    new_id = _random.Random(uid).choice(evo)                   # Eevee branches
    newcp = int(c["cp"] * 1.6) + 20
    world.update_caught(uid, pokemon_id=new_id, cp=newcp)
    world.record_badge_progress("BADGE_EVOLVED_TOTAL", 1)
    xp = _cfg.get("pokemon", "evolve_xp", cast=int)
    world.add_xp(xp)
    world.add_candy(fam, 1)                                    # evolving pays 1 back
    return (pb.Writer()
            .uint(1, 1)
            .message(2, build_pokemon_data(new_id, uid, newcp))
            .int_(3, xp)
            .int_(4, 1)
            .to_bytes())


def build_nickname_response(uid, nickname) -> bytes:
    """NicknamePokemonResponse { result=1 } (1=SUCCESS)."""
    import world
    world.update_caught(uid, nickname=nickname[:12])
    return pb.Writer().uint(1, 1).to_bytes()


def build_favorite_response(uid, is_fav) -> bytes:
    """SetFavoritePokemonResponse { result=1 } (1=SUCCESS)."""
    import world
    world.update_caught(uid, favorite=1 if is_fav else 0)
    return pb.Writer().uint(1, 1).to_bytes()


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


def _hp_for(cp, pokemon_id=None, uid=None):
    """Battle HP.

    Uses the REAL stamina formula, (base_stamina + iv) * cp_multiplier, whenever
    we know the species. The old cp*0.6+20 gave a 1200-CP defender 740 HP while
    a hit takes off ~12 -- 60 taps to win, which just reads as "attacks do no
    damage". Real max HP for that Pokemon is about 100, so a fight now runs the
    handful of hits it should, and the bar agrees with the CP on screen.
    """
    if pokemon_id is not None and uid is not None and _gd and pokemon_id in _gd.STATS:
        _ba, _bd, bs = _gd.STATS[pokemon_id]
        iv_a, iv_d, iv_s = _ivs(uid)
        return max(10, int((bs + iv_s) * cpm_for(pokemon_id, cp, iv_a, iv_d, iv_s)))
    return max(20, int(cp * 0.6) + 20)


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


def parse_recycle(msg):
    """RecycleInventoryItemMessage { item_id=1, count=2 }."""
    f = pb.decode(msg)
    return pb.get(f, 1, pb.WT_VARINT) or 0, pb.get(f, 2, pb.WT_VARINT) or 0


def build_recycle_response(item_id, count) -> bytes:
    """RecycleInventoryItemResponse { result=1, new_count=2 }.
    Result: 1=SUCCESS, 2=ERROR_NOT_ENOUGH_COPIES. Lets you drop items from the bag."""
    import world
    if not world.take_item(item_id, count):
        return pb.Writer().uint(1, 2).to_bytes()
    remaining = dict(world.bag_items()).get(item_id, 0)
    return pb.Writer().uint(1, 1).int_(2, remaining).to_bytes()


def parse_level_up_rewards(msg):
    """LevelUpRewardsMessage { level = 1 } -- the level being claimed."""
    return pb.get(pb.decode(msg), 1, pb.WT_VARINT) or 0


def build_level_up_rewards_response(level) -> bytes:
    """LevelUpRewardsResponse { result=1, items_awarded=2, items_unlocked=4 }.
    Result: 1=SUCCESS, 2=AWARDED_ALREADY.

    The client asks on EVERY boot. Answering SUCCESS every time made it replay the
    level-up screen on every launch (and re-hand the items), so a level is now paid
    out exactly once and every later claim gets AWARDED_ALREADY."""
    import world
    if level <= 0 or world.level_claimed(level):
        return pb.Writer().uint(1, 2).to_bytes()          # AWARDED_ALREADY
    awards = [(ITEM_POKE_BALL, 10), (ITEM_POTION, 5)]
    w = pb.Writer().uint(1, 1)
    for iid, cnt in awards:
        w.message(2, build_item_award(iid, cnt))
        world.add_item(iid, cnt)
    world.claim_level(level)
    return w.to_bytes()


def build_fort_search_response(fort_id, now_ms) -> bytes:
    # FortSearchResponse { result=1 (SUCCESS=1), items_awarded=2, experience_awarded=5,
    #   cooldown_complete_timestamp_ms=6 }. ItemAward { item_id=1, item_count=2 }.
    import world
    rnd = _random.Random(hash(fort_id) ^ (now_ms // 300000))   # re-rolls per 5-min spin
    _lo = _cfg.get("pokestops", "min_items_per_spin", cast=int)
    _hi = max(_lo, _cfg.get("pokestops", "max_items_per_spin", cast=int))
    # A spin ALWAYS gives Poke Balls, a Potion and a Revive; Great/Ultra Balls and
    # berries turn up now and then. Poke Balls are topped up at the end so the haul
    # never comes to fewer than min_items_per_spin items in total.
    awards = [(ITEM_POTION, rnd.randint(1, 2)), (ITEM_REVIVE, 1)]
    if rnd.random() < _cfg.get("pokestops", "great_ball_chance", cast=float):
        awards.append((ITEM_GREAT_BALL, rnd.randint(1, 2)))
    if rnd.random() < _cfg.get("pokestops", "ultra_ball_chance", cast=float):
        awards.append((ITEM_ULTRA_BALL, 1))
    if rnd.random() < _cfg.get("pokestops", "razz_berry_chance", cast=float):
        awards.append((ITEM_RAZZ_BERRY, rnd.randint(1, 2)))
    other = sum(c for _i, c in awards)
    awards.insert(0, (ITEM_POKE_BALL, max(rnd.randint(1, 3), _lo - other)))
    # ...and trim back to the maximum, taking from the extras first and never
    # dropping any award below one, so the guaranteed three always survive.
    total = sum(c for _i, c in awards)
    for i in range(len(awards) - 1, -1, -1):
        if total <= _hi:
            break
        iid, cnt = awards[i]
        take = min(cnt - 1, total - _hi)
        if take > 0:
            awards[i] = (iid, cnt - take)
            total -= take
    room = world.room_in_bag()
    if room <= 0:
        # FortSearchResult 4 = INVENTORY_FULL: the client says "your bag is full".
        return pb.Writer().uint(1, 4).to_bytes()
    if sum(c for _i, c in awards) > room:                       # partial haul
        trimmed, left = [], room
        for iid, cnt in awards:
            if left <= 0:
                break
            take = min(cnt, left)
            trimmed.append((iid, take)); left -= take
        awards = trimmed
    w = pb.Writer().uint(1, 1)                                  # result = SUCCESS
    if rnd.random() < _cfg.get("eggs", "drop_chance", cast=float):
        # 2 km eggs are common, 10 km rare -- same shape as the real drop table.
        tier = rnd.choices(EGG_TIERS, weights=(60, 30, 10))[0]
        # No item award for the egg: item 901 is an INCUBATOR, not an egg, and
        # reporting it made the spin look like it handed out an incubator. The egg
        # itself arrives with the next inventory delta.
        world.give_egg(tier)
    world.bump("poke_stop_visits")
    world.add_xp(_cfg.get("pokestops", "xp_per_spin", cast=int))
    for iid, cnt in awards:
        w.message(2, build_item_award(iid, cnt))
        # actually PUT them in the bag -- otherwise the spin animation shows a
        # Poke Ball but GET_INVENTORY never reports it and it's nowhere to be found
        world.add_item(iid, cnt)
    _cool = _cfg.get("pokestops", "cooldown_minutes", cast=float)
    return (w.int_(5, _cfg.get("pokestops", "xp_per_spin", cast=int))   # experience_awarded
             .int_(6, now_ms + int(_cool * 60_000))            # cooldown (goes purple)
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


import math as _math
import random as _random
import time
import s2sphere


class SpawnBatch:
    def __init__(self, now, expire, spawn_ms):
        self.now = now
        self.expire = expire
        self.spawn_ms = spawn_ms
        self.catch = []
        self.forts = []
        self.wild = []
        self.spawns = []
        self.nearby = []

    def add_spawn(self, eid, sid, pid, cp, lat, lng, nearby_dist, expire_override=None):
        exp = expire_override if expire_override is not None else self.expire
        sp_ms = max(60_000, exp - self.now) if expire_override is not None else self.spawn_ms

        self.wild.append(build_wild_pokemon(eid, lat, lng, sid, pid, self.now, sp_ms, cp=cp))
        self.catch.append(build_map_pokemon(sid, eid, pid, lat, lng, exp))
        _world.remember_spawn(eid, pid, lat, lng, cp, sid, exp)
        self.spawns.append(build_spawn_point(lat, lng))
        self.nearby.append(build_nearby_pokemon(pid, nearby_dist))


def _resolve_cells(cell_ids, lat, lng, have_fix):
    cells = list(dict.fromkeys(cell_ids))
    if not cells and have_fix:
        pc = s2sphere.CellId.from_lat_lng(s2sphere.LatLng.from_degrees(lat, lng)).parent(15)
        cells = [pc.id()]
        try:
            cells += [n.id() for n in pc.get_edge_neighbors()]
        except Exception:
            pass
    return cells


def _find_player_cell(cells, lat, lng, have_fix):
    if not (have_fix and cells):
        return None
    pid_cell = s2sphere.CellId.from_lat_lng(s2sphere.LatLng.from_degrees(lat, lng)).parent(15).id()
    if pid_cell in cells:
        return pid_cell

    def _cdist(cid):
        c = _cell_center(cid)
        return (c[0] - lat) ** 2 + (c[1] - lng) ** 2 if c else 9e9

    return min(cells, key=_cdist)


def _calculate_budgets(cells, lat, lng, max_wild, per_cell):
    if not cells:
        return {}

    def _cdist(cid):
        c = _cell_center(cid)
        return (c[0] - lat) ** 2 + (c[1] - lng) ** 2 if c else 9e9

    ranked = sorted(cells, key=_cdist)
    budget = {}
    left = max_wild
    for rank, cid in enumerate(ranked):
        if rank == 0:
            share = per_cell
        elif rank <= 4:
            share = max(1, per_cell // 2)
        else:
            share = max(1, per_cell // 4)
        share = min(share, max(0, left))
        budget[cid] = share
        left -= share
    return budget


def build_get_map_objects_response(cell_ids, lat, lng) -> bytes:
    import places as _places

    now = int(time.time() * 1000)
    _win, win_end = _window(now)
    spawn_ms = max(60_000, win_end - now)
    have_fix = abs(lat) > 1e-6 or abs(lng) > 1e-6

    cells = _resolve_cells(cell_ids, lat, lng, have_fix)
    player_cell = _find_player_cell(cells, lat, lng, have_fix)

    max_forts = max(1, _cfg.get("pokestops", "max_per_request", cast=int))
    max_wild = max(1, _cfg.get("spawns", "max_per_request", cast=int))
    per_cell = max(0, _cfg.get("spawns", "per_l15_cell", cast=int))

    ev = _event_cfg()
    near_n = max(0, min(60, int(ev.get("spawn_density", _near_player()))))

    pl = _places.get()
    proc_forts = pl.get("procedural_forts")
    proc_spawns = pl.get("procedural_spawns")

    placed_forts, placed_spawns = {}, {}
    for f in pl["forts"]:
        try:
            c = s2sphere.CellId.from_lat_lng(s2sphere.LatLng.from_degrees(f["lat"], f["lng"])).parent(15).id()
            placed_forts.setdefault(c, []).append(f)
        except Exception:
            continue
    for s in pl["spawns"]:
        try:
            c = s2sphere.CellId.from_lat_lng(s2sphere.LatLng.from_degrees(s["lat"], s["lng"])).parent(15).id()
            placed_spawns.setdefault(c, []).append(s)
        except Exception:
            continue

    lured = _world.lured_forts()
    fort_pos = {}
    for f in pl["forts"]:
        gym = f.get("kind") == "gym"
        fort_pos[f"{_hex_id(f['id'])}.{16 if gym else 11}"] = (f["lat"], f["lng"])
    if lured:
        for cid in cells:
            for kid, kla, kln in _l17_centres(cid):
                fort_pos.setdefault(f"{_hex_id(kid)}.11", (kla, kln))

    budgets = _calculate_budgets(cells, lat, lng, max_wild, per_cell)

    w = pb.Writer()
    spawned = forts_n = wild_n = 0

    for cid in cells:
        batch = SpawnBatch(now, win_end, spawn_ms)
        ctr = _cell_center(cid)

        # Procedural wild spawns
        if ctr and proc_spawns and wild_n < max_wild:
            kids = _l17_centres(cid)
            for k in range(budgets.get(cid, 0)):
                if wild_n >= max_wild or not kids:
                    break
                kid, clat, clng = kids[k % len(kids)]
                seed = (kid ^ (_win * 0x9E3779B97F4A7C15) ^ (k * 0x2545F4914F6CDD1D)) & ((1 << 63) - 1)
                rnd = _random.Random(seed)
                eid = (seed ^ 0x5BD1E995ABCD) & ((1 << 63) - 1)
                if _world.is_despawned(eid):
                    continue
                jl = clat + (rnd.random() - 0.5) * 0.00060
                jn = clng + (rnd.random() - 0.5) * 0.00060
                batch.add_spawn(
                    eid=eid,
                    sid=_hex_id((kid, k), 11),
                    pid=_pick_species(rnd, ev),
                    cp=_pick_cp(rnd, ev),
                    lat=jl,
                    lng=jn,
                    nearby_dist=120.0,
                )
                wild_n += 1

        # Trainer cluster spawns
        if cid == player_cell and proc_spawns:
            d0 = _cfg.get("spawns", "nearest_distance_m", cast=float)
            d1 = _cfg.get("spawns", "farthest_distance_m", cast=float)
            for k in range(near_n):
                r = _random.Random(cid ^ (_win * 0x9E3779B97F4A7C15) ^ (k * 0x2545F4914F6CDD1D))
                eid2 = (cid ^ (0x1234ABCD5678 + k * 0x9E3779B1) ^ (_win * 0x85EBCA6B)) & ((1 << 63) - 1)
                if _world.is_despawned(eid2):
                    continue
                ang = (2 * _math.pi * k / max(1, near_n)) + r.uniform(-0.35, 0.35)
                dist = d0 + r.random() * max(1.0, d1 - d0)
                dlat = lat + (dist * _math.cos(ang)) / 111320.0
                dlng = lng + (dist * _math.sin(ang)) / (
                    111320.0 * max(0.2, _math.cos(_math.radians(lat)))
                )
                batch.add_spawn(
                    eid=eid2,
                    sid=_hex_id((cid, k), 11),
                    pid=_pick_species(r, ev),
                    cp=_pick_cp(r, ev),
                    lat=dlat,
                    lng=dlng,
                    nearby_dist=10.0 + k * 5,
                )

        # Procedural forts
        if proc_forts and forts_n < max_forts:
            batch.forts = l17_forts(cid, now)[: max(0, max_forts - forts_n)]
            forts_n += len(batch.forts)

        if cid == player_cell and proc_forts:
            near = [(0.00020, -0.00010, False), (-0.00012, 0.00016, False), (0.00025, 0.00028, True)]
            for j, (dla, dln, is_gym) in enumerate(near):
                fid = f"{_hex_id((cid, 'near', j))}.{16 if is_gym else 11}"
                batch.forts.append(build_fort(fid, lat + dla, lng + dln, now, is_gym=is_gym))
            forts_n += len(near)

        # Placed objects
        for f in placed_forts.get(cid, []):
            gym = f.get("kind") == "gym"
            fid = f"{_hex_id(f['id'])}.{16 if gym else 11}"
            batch.forts.append(build_fort(fid, f["lat"], f["lng"], now, is_gym=gym))
            _PLACED_NAMES[fid] = f.get("name", "")
            if f.get("image"):
                _PLACED_IMAGES[fid] = f["image"]
            forts_n += 1

        for s in placed_spawns.get(cid, []):
            pid = int(s.get("pokemon_id", 0) or 0)
            if pid == 0:
                pid = _pick_species(_random.Random(now // 600000 ^ hash(s["id"])), ev)
            eid = (hash(s["id"]) ^ 0x50AC3D) & ((1 << 62) - 1)
            batch.add_spawn(
                eid=eid,
                sid=_hex_id(s["id"], 11),
                pid=pid,
                cp=200 + (eid % 800),
                lat=s["lat"],
                lng=s["lng"],
                nearby_dist=20.0,
            )

        # Incense
        if cid == player_cell and proc_spawns and _world.item_active(401):
            n = _cfg.get("boosts", "incense_extra_spawns", cast=int)
            for k in range(n):
                r = _random.Random(
                    (cid ^ (_win * 0x9E3779B1) ^ (k * 0x51ED2701) ^ 0x1CE45E) & 0x7FFFFFFF
                )
                eid = (cid ^ 0x1CE45E ^ (k * 0x9E3779B1) ^ (_win * 0x85EBCA6B)) & ((1 << 62) - 1)
                if _world.is_despawned(eid):
                    continue
                ang = 2 * _math.pi * k / max(1, n) + r.uniform(-0.3, 0.3)
                dist = 18.0 + r.random() * 40.0
                dl = lat + (dist * _math.cos(ang)) / 111320.0
                dn = lng + (dist * _math.sin(ang)) / (
                    111320.0 * max(0.2, _math.cos(_math.radians(lat)))
                )
                batch.add_spawn(
                    eid=eid,
                    sid=_hex_id((eid, "inc"), 11),
                    pid=_pick_species(r, ev),
                    cp=_pick_cp(r, ev),
                    lat=dl,
                    lng=dn,
                    nearby_dist=15.0,
                )

        # Lures
        if proc_spawns:
            for lf, lm in lured.items():
                pos = fort_pos.get(lf)
                if not pos:
                    continue
                try:
                    c_id = s2sphere.CellId.from_lat_lng(
                        s2sphere.LatLng.from_degrees(pos[0], pos[1])
                    ).parent(15).id()
                except Exception:
                    c_id = None
                if c_id != cid:
                    continue

                n = _cfg.get("boosts", "lure_extra_spawns", cast=int)
                for k in range(n):
                    r = _random.Random(
                        (hash(lf) ^ (_win * 0x9E3779B1) ^ (k * 0x2545F491)) & 0x7FFFFFFF
                    )
                    eid = (hash(lf) ^ 0x1D4E ^ (k * 0x9E3779B1) ^ (_win * 0x85EBCA6B)) & (
                        (1 << 62) - 1
                    )
                    if _world.is_despawned(eid):
                        continue
                    ang = 2 * _math.pi * k / max(1, n) + r.uniform(-0.4, 0.4)
                    dist = 8.0 + r.random() * 22.0
                    dl = pos[0] + (dist * _math.cos(ang)) / 111320.0
                    dn = pos[1] + (dist * _math.sin(ang)) / (
                        111320.0 * max(0.2, _math.cos(_math.radians(pos[0])))
                    )
                    batch.add_spawn(
                        eid=eid,
                        sid=_hex_id((eid, "lure"), 11),
                        pid=_pick_species(r, ev),
                        cp=_pick_cp(r, ev),
                        lat=dl,
                        lng=dn,
                        nearby_dist=12.0,
                    )

        # Raid bonus spawns
        if cid == player_cell:
            for b in _world.bonus_spawns(_world.current().username):
                if _world.is_despawned(b["eid"]):
                    continue
                bsid = _hex_id((b["eid"], "raid"), 11)
                batch.add_spawn(
                    eid=b["eid"],
                    sid=bsid,
                    pid=b["pid"],
                    cp=b["cp"],
                    lat=b["lat"],
                    lng=b["lng"],
                    nearby_dist=5.0,
                    expire_override=b["expires_ms"],
                )

        spawned += len(batch.wild)
        w.message(
            1,
            build_map_cell(
                cid,
                now,
                batch.catch,
                batch.forts,
                batch.wild,
                spawn_points=batch.spawns,
                nearby=batch.nearby,
            ),
        )

    w.uint(2, 1).uint(3, 1)
    tag = "real fix -> spawns at player" if have_fix else "NO-GPS-FIX (0,0)"
    print(
        f"   [map] {len(cell_ids)} req cells, {len(cells)} sent; "
        f"player ({lat:.5f},{lng:.5f}) [{tag}]; "
        f"{spawned} mons, {forts_n} stops/gyms",
        flush=True,
    )
    return w.to_bytes()


_GAME_MASTER = None

def build_download_item_templates_response(templates=None) -> bytes:
    # SERVE_GAME_MASTER=1 -> serve the full 2016 game master (game_master.bin). The
    # client loads+applies it but then boot-loops on the asset layer (wants the real
    # CDN asset bundles we don't host). Default OFF -> minimal templates so the client
    # finishes loading and reaches the playable MAP (trainer at your location).
    global _GAME_MASTER
    if os.environ.get("SERVE_GAME_MASTER") == "1":
        if _GAME_MASTER is None:
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "game_master.bin")
            try:
                with open(path, "rb") as fh:
                    _GAME_MASTER = fh.read()
            except OSError:
                _GAME_MASTER = b""
        if _GAME_MASTER:
            # Override timestamp_ms (field 3, last-wins) so the served master's version
            # always equals TEMPLATES_TS from DOWNLOAD_REMOTE_CONFIG_VERSION regardless of
            # what's baked into game_master.bin -> lets us bump TEMPLATES_TS to force a
            # re-download without regenerating the .bin.
            return _GAME_MASTER + pb.Writer().uint(3, TEMPLATES_TS).to_bytes()
    w = pb.Writer().uint(1, 1)                          # success
    for t in (templates or [build_item_template("PRIVATE_SERVER_0001")]):
        w.message(2, t)
    return w.uint(3, TEMPLATES_TS).to_bytes()


def build_download_remote_config_version_response() -> bytes:
    # DownloadRemoteConfigVersionResponse { result=1 SUCCESS,
    #   item_templates_timestamp_ms=2, asset_digest_timestamp_ms=3 }
    # asset_digest_timestamp_ms MUST equal the digest file's own timestamp (a
    # microsecond value, e.g. 1467338276561000) -- not a millisecond clock and not an
    # invented constant. If it doesn't match, the client never treats the digest as
    # current and keeps re-fetching it instead of using the bundles.
    return (pb.Writer()
            .uint(1, 1)                 # result = SUCCESS
            .uint(2, TEMPLATES_TS)      # item templates: ordinary ms
            .uint(3, digest_timestamp() or ASSET_TS)
            .to_bytes())


def build_download_settings_response() -> bytes:
    # DownloadSettingsResponse { error=1, hash=2, settings=3 GlobalSettings }
    # GlobalSettings { fort_settings=2, map_settings=3, level_settings=4,
    #                  inventory_settings=5, minimum_client_version=6 }
    #
    # These field numbers were previously GUESSED and were WRONG: map_settings was
    # written into slot 2 (fort_settings) and a bare string into slot 5
    # (inventory_settings). Consequences, both observed live:
    #   * FortSettings.interaction_range_meters never arrived -> defaulted to 0
    #     -> PokeStops render but CANNOT BE SPUN at any distance.
    #   * MapSettings.pokemon_visible_range never arrived -> defaulted to 0
    #     -> wild Pokemon are never drawn.
    # Values below are the genuine 2016 ones taken from maierfelix/POGOServer.
    fort_settings = (pb.Writer()
                     .double(1, 40.25098039215686)      # interaction_range_meters
                     .int_(2, 10)                       # max_total_deployed_pokemon
                     .int_(3, 1)                        # max_player_deployed_pokemon
                     .double(4, 8.062745098039215)      # deploy_stamina_multiplier
                     .double(5, 0.0)                    # deploy_attack_multiplier
                     .double(6, 1000.0156862745098)     # far_interaction_range_meters
                     .to_bytes())
    map_settings = (pb.Writer()
                    .double(1, 70.00196078431372)       # pokemon_visible_range
                    .double(2, 751.0156862745098)       # poke_nav_range_meters
                    .double(3, 50.25098039215686)       # encounter_range_meters
                    .float_(4, 10.007843017578125)      # get_map_objects_min_refresh_seconds
                    .float_(5, 11.01568603515625)       # get_map_objects_max_refresh_seconds
                    .float_(6, 10.007843017578125)      # get_map_objects_min_distance_meters
                    .string(7, "")                      # google_maps_api_key (ours: none)
                    .to_bytes())
    inventory_settings = (pb.Writer()
                          .int_(1, 1000)                # max_pokemon
                          .int_(2, 1000)                # max_bag_items
                          .int_(3, 250)                 # base_pokemon
                          .int_(4, 350)                 # base_bag_items
                          .int_(5, 9)                   # base_eggs
                          .to_bytes())
    settings = (pb.Writer()
                .message(2, fort_settings)
                .message(3, map_settings)
                .message(5, inventory_settings)
                .string(6, "0.29.0")                    # minimum_client_version
                .to_bytes())
    return (pb.Writer()
            .string(2, SETTINGS_HASH)   # hash
            .message(3, settings)       # settings
            .to_bytes())


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
