"""Asset and template protocol builders."""
import json
import os

import pb

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
_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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
    """Every pm#### bundle on disk that also has a genuine digest entry, with the
    REAL metadata (version/checksum/size/key). asset_id is kept == bundle_name so
    the existing /asset/<id> download path resolves straight to the file on disk;
    the client treats asset_id opaquely (crypto uses the per-entry key, not the id)."""
    digest = _load_real_digest()
    plain = _plain_manifest() if PLAIN_ASSETS else {}
    out = []
    if os.path.isdir(ASSETS_DIR):
        for fn in sorted(os.listdir(ASSETS_DIR)):
            if not fn.startswith("pm") or fn not in digest:
                continue
            m = digest[fn]
            if fn in plain:
                # decrypted bytes -> no key, our own size + CRC32
                out.append({"asset_id": fn, "bundle_name": fn, "version": m["version"],
                            "checksum": plain[fn]["crc32"], "size": plain[fn]["size"],
                            "key": b""})
                continue
            checksum = m["checksum"]
            if CRC_FIX:
                # The client's load path is decrypt -> ValidateBundle(CRC32) -> create.
                # The genuine digest checksum is NOT zlib-CRC32 of the decrypted bundle
                # (verified: no standard CRC variant matches), so if the client computes
                # a plain CRC32 it will call every bundle corrupt and silently drop the
                # model -- which is exactly what we see (bundle cached on device, nothing
                # rendered). Advertise the CRC32 we actually measure instead.
                pc = _plain_manifest().get(fn)
                if pc:
                    checksum = pc["crc32"]
            out.append({"asset_id": m["asset_id"], "bundle_name": fn,
                        "version": m["version"], "checksum": checksum,
                        "size": m["size"], "key": m["key"]})
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
