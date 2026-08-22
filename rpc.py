"""
RPC endpoint — pgorelease.nianticlabs.com/plfe/rpc

Milestone 1: get the player logged in and onto the map.
  - Decode + log the RequestEnvelope (so we can verify the real client's exact
    field layout against protocol.py's constants).
  - First call to /plfe/rpc  -> status 53 REDIRECT to an api_url on the same
    host (the documented bootstrap handshake).
  - Calls to the redirected url -> status 2 OK, with an auth_ticket and one
    return per request. GET_PLAYER gets a real PlayerData (nickname=username,
    tutorial complete). Every other request gets an empty response for now;
    that is enough to clear the login/handshake. We flesh them out next.

api_url stays on pgorelease.nianticlabs.com so the client keeps hitting a host
our DNS redirect + TLS cert already cover.
"""
import os
import struct
import threading
import time

import pb
import protocol as P

API_HOST = "pgorelease.nianticlabs.com"
API_PATH = "/plfe/0/rpc"          # any non-bootstrap path works
ASSET_BASE_URL = f"https://{API_HOST}/asset"   # where GET_DOWNLOAD_URLS points
_dump_budget = [8]                 # verbosely dump the first N envelopes
_last_loc = [0.0, 0.0]            # last non-zero player location we've seen
_last_user = [None]               # last trainer to make a request (for /shop)
_teleport_lock = threading.Lock()
_teleports = {}


def set_teleport(username: str, lat: float, lng: float) -> None:
    with _teleport_lock:
        _teleports[username] = (lat, lng)


def map_position(username: str, lat: float, lng: float) -> tuple[float, float]:
    with _teleport_lock:
        return _teleports.get(username, (lat, lng))


def teleports() -> dict[str, tuple[float, float]]:
    with _teleport_lock:
        return dict(_teleports)


def _envelope_latlng(fields):
    la = pb.get(fields, P.RE_LATITUDE, pb.WT_64)
    lo = pb.get(fields, P.RE_LONGITUDE, pb.WT_64)
    if la is None or lo is None:
        return None
    return (struct.unpack("<d", struct.pack("<Q", la))[0],
            struct.unpack("<d", struct.pack("<Q", lo))[0])


def capture_request(request_type: int, message: bytes, log) -> None:
    if os.environ.get("CAPTURE_RPC_REQUESTS") == "1":
        payload = "<redacted>" if request_type == P.RT.SET_AVATAR else message.hex()
        log(f"[capture] type={request_type} name={P.rt_name(request_type)} "
            f"message={payload}\n")


def _build_returns(reqs, username, log):
    # Everything below reads/writes THIS account's state (saves/<name>.json).
    # Must happen before any world.* call in the request.
    import world
    world.use(username)
    # Bring home any Gym defenders that have served their time and pay the coins.
    # Checked on every batch so it happens while you play, not only on a restart.
    try:
        import world
        for fid, pid, coins in world.collect_gym_returns():
            log(f"   [gym] defender #{pid} came home from {fid[:12]}... "
                f"after {world._defender_minutes():g} min -> +{coins} PokeCoins "
                f"(total {world.COINS})")
    except Exception as e:
        log(f"   [gym] return check failed: {e}")
    returns = []
    for rtype, msg in reqs:
        if rtype == P.RT.GET_PLAYER:
            returns.append(P.build_get_player_response(username))
            log(f"      -> GET_PLAYER answered as {username!r}")
        elif rtype == P.RT.GET_MAP_OBJECTS:
            cells, lat, lng = P.parse_get_map_objects(msg)
            if not lat and not lng:                 # map msg had no fix; use the
                lat, lng = _last_loc                # player's last known location
            lat, lng = map_position(username, lat, lng)
            returns.append(P.build_get_map_objects_response(cells, lat, lng))
            log(f"      -> GET_MAP_OBJECTS: {len(cells)} cells @ ({lat:.5f},{lng:.5f}) + spawns")
        elif rtype == P.RT.GET_INVENTORY:
            returns.append(P.build_get_inventory_response())
            log("      -> GET_INVENTORY answered (stats + balls/potions)")
        elif rtype == P.RT.DOWNLOAD_REMOTE_CONFIG_VERSION:
            returns.append(P.build_download_remote_config_version_response())
            log("      -> DOWNLOAD_REMOTE_CONFIG_VERSION req:\n" + pb.pretty(msg))
        elif rtype == P.RT.DOWNLOAD_SETTINGS:
            returns.append(P.build_download_settings_response())
            log("      -> DOWNLOAD_SETTINGS answered")
        elif rtype == P.RT.GET_ASSET_DIGEST:
            r = P.build_get_asset_digest_response()
            returns.append(r)
            log(f"      -> GET_ASSET_DIGEST served ({len(P._our_bundles())} bundles); req:\n"
                + pb.pretty(msg))
        elif rtype == P.RT.GET_DOWNLOAD_URLS:
            ids = P.parse_get_download_urls(msg)
            returns.append(P.build_get_download_urls_response(ids, ASSET_BASE_URL))
            log(f"      -> GET_DOWNLOAD_URLS for {ids} -> {ASSET_BASE_URL}/...")
        elif rtype == P.RT.DOWNLOAD_ITEM_TEMPLATES:
            r = P.build_download_item_templates_response()
            returns.append(r)
            log(f"      -> DOWNLOAD_ITEM_TEMPLATES served game master ({len(r)} bytes); req:\n"
                + pb.pretty(msg))
        elif rtype == P.RT.FORT_DETAILS:
            fid, flat, flng = P.parse_fort_request(msg)
            returns.append(P.build_fort_details_response(fid, flat, flng))
            log(f"      -> FORT_DETAILS {fid!r}")
        elif rtype == P.RT.GET_GYM_DETAILS:
            fid, glat, glng = P.parse_gym_details(msg)
            import world
            returns.append(P.build_gym_details_response(
                fid, glat or _last_loc[0], glng or _last_loc[1], int(time.time() * 1000)))
            log(f"      -> GET_GYM_DETAILS {fid!r} ({len(world.gym_members(fid))} defenders)")
        elif rtype == P.RT.FORT_DEPLOY_POKEMON:
            fid, uid = P.parse_deploy(msg)
            returns.append(P.build_fort_deploy_response(
                fid, uid, _last_loc[0], _last_loc[1], int(time.time() * 1000)))
            import world
            log(f"      -> FORT_DEPLOY_POKEMON {fid!r} pokemon={uid} "
                f"-> {len(world.gym_members(fid))} at gym")
        elif rtype == P.RT.START_GYM_BATTLE:
            gid, atk_ids, def_id = P.parse_start_gym_battle(msg)
            r = P.build_start_gym_battle_response(gid, atk_ids, def_id,
                                                  int(time.time() * 1000))
            returns.append(r)
            d = pb.decode(r); res = pb.get(d, 1, pb.WT_VARINT)
            bid = pb.get(d, 4, pb.WT_LEN)
            import world
            b = world.BATTLES.get(bid.decode()) if bid else None
            log(f"      -> START_GYM_BATTLE {gid[:12]}... -> " +
                (f"battle_id ISSUED = {bid.decode()!r} ({len(atk_ids)} attackers)"
                 + (f" atk={b['attacker']:#x} vs def={b['defender']:#x}"
                    f"{'  <<< SAME POKEMON!' if b['attacker'] == b['defender'] else ''}"
                    if b else "")
                 if res == 1 and bid else
                 {5: "gym is empty",
                  8: "no eligible attacker (all fainted, or your only Pokemon is "
                     "the one defending this gym)"}.get(res, f"result {res}")))
        elif rtype == P.RT.ATTACK_GYM:
            gid, bid, actions, last_seen = P.parse_attack_gym(msg)
            r = P.build_attack_gym_response(gid, bid, actions,
                                            int(time.time() * 1000), last_seen)
            returns.append(r)
            d = pb.decode(r)
            lg = pb.decode(pb.get(d, 2, pb.WT_LEN) or b"")
            state = pb.get(lg, 1, pb.WT_VARINT)
            rid = pb.get(d, 3, pb.WT_LEN)
            import world
            now = int(time.time() * 1000)
            b = world.BATTLES.get(bid)
            out = [pb.decode(a) for a in pb.get_all(lg, 4) if isinstance(a, bytes)]
            # Actions are replayed at ActionStartMs on the CLIENT's clock, so a
            # positive offset here means we scheduled them in the future and the
            # client will never animate them. These must stay at or below zero.
            offs = [(pb.get(a, 2, pb.WT_VARINT) or 0) - now for a in out]
            log(f"      -> ATTACK_GYM battle_id RECEIVED={bid!r} "
                f"known={b is not None} match={bool(rid) and rid.decode() == bid} "
                f"| in={len(actions)} taps{[a.get('start', 0) - now for a in actions]} "
                f"out={len(out)} actions offset_ms={offs} "
                + (f"| atk={b['attacker']:#x} hp={b['atk_hp']} "
                   f"def={b['defender']:#x} hp={b['def_hp']} " if b else "")
                + "-> " + {1: "battle continues", 2: "VICTORY - gym taken!",
                           3: "your Pokemon fainted"}.get(state, f"state {state}"))
        elif rtype == P.RT.USE_ITEM_XP_BOOST:
            iid = P.parse_use_item_xp_boost(msg)
            r = P.build_use_item_xp_boost_response(iid)
            returns.append(r)
            res = pb.get(pb.decode(r), 1, pb.WT_VARINT)
            log("      -> USE_ITEM_XP_BOOST -> " +
                {1: "Lucky Egg active: double XP", 3: "one is already running",
                 4: "you have none"}.get(res, f"result {res}"))
        elif rtype == P.RT.USE_INCENSE:
            r = P.build_use_incense_response(P.ITEM_INCENSE)
            returns.append(r)
            res = pb.get(pb.decode(r), 1, pb.WT_VARINT)
            log("      -> USE_INCENSE -> " +
                {1: "Incense burning: more Pokemon nearby",
                 2: "one is already burning",
                 3: "you have none"}.get(res, f"result {res}"))
        elif rtype == P.RT.GET_INCENSE_POKEMON:
            returns.append(P.build_get_incense_pokemon_response())
        elif rtype == P.RT.ADD_FORT_MODIFIER:
            iid, fid, mlat, mlng = P.parse_add_fort_modifier(msg)
            r = P.build_add_fort_modifier_response(
                iid, fid, int(time.time() * 1000),
                mlat or _last_loc[0], mlng or _last_loc[1])
            returns.append(r)
            res = pb.get(pb.decode(r), 1, pb.WT_VARINT)
            log(f"      -> ADD_FORT_MODIFIER {fid[:12]}... -> " +
                {1: "Lure attached", 2: "that stop already has one",
                 4: "you have no Lure Modules"}.get(res, f"result {res}"))
        elif rtype == P.RT.USE_ITEM_CAPTURE:
            iid, eid = P.parse_use_item_capture(msg)
            r = P.build_use_item_capture_response(iid, eid)
            returns.append(r)
            ok = pb.get(pb.decode(r), 1, pb.WT_VARINT)
            log(f"      -> USE_ITEM_CAPTURE item={iid} encounter={eid} -> " +
                ("Razz Berry used, next ball is much likelier to hold"
                 if ok else "couldn't use that item"))
        elif rtype == P.RT.SET_AVATAR:
            try:
                outer = pb.decode(msg)
                if (len(outer) != 1 or outer[0]["field"] != 2
                        or outer[0]["wire"] != pb.WT_LEN):
                    raise ValueError
                if pb.Writer().bytes_(2, outer[0]["value"]).to_bytes() != msg:
                    raise ValueError
                slots = {}
                canonical = pb.Writer()
                for field in pb.decode(outer[0]["value"]):
                    slot, value = field["field"], field["value"]
                    if (field["wire"] != pb.WT_VARINT or not 2 <= slot <= 10
                            or not 0 <= value <= 255 or slot in slots):
                        raise ValueError
                    slots[slot] = value
                    canonical.uint(slot, value)
                if (canonical.to_bytes() != outer[0]["value"]
                        or not world.current().set_avatar_slots(slots)):
                    raise ValueError
            except (IndexError, struct.error, ValueError):
                returns.append(b"")
            else:
                world.current().save()
                returns.append(P.build_set_avatar_response())
                log("      -> SET_AVATAR success")
        elif rtype == P.RT.SET_PLAYER_TEAM:
            team = P.parse_set_player_team(msg)
            r = P.build_set_player_team_response(team, username)
            returns.append(r)
            st = pb.get(pb.decode(r), 1, pb.WT_VARINT)
            names = {1: "Mystic (blue)", 2: "Valor (red)", 3: "Instinct (yellow)"}
            log(f"      -> SET_PLAYER_TEAM -> " +
                (f"joined {names.get(team, team)}" if st == 1 else
                 "team was already chosen" if st == 2 else "failed"))
        elif (rtype == P.RT.MARK_TUTORIAL_COMPLETE
              and P.avatar_onboarding_capture(username)
              and msg == bytes.fromhex("0a01001001")):
            returns.append(P.build_mark_tutorial_complete_response())
            log("      -> MARK_TUTORIAL_COMPLETE acknowledged")
        elif rtype == P.RT.ENCOUNTER_TUTORIAL_COMPLETE:
            try:
                fields = pb.decode(msg)
                if (not P.avatar_onboarding_capture(username) or len(fields) != 1
                        or fields[0]["field"] != 1
                        or fields[0]["wire"] != pb.WT_VARINT
                        or fields[0]["value"] not in (1, 4, 7)
                        or pb.Writer().uint(1, fields[0]["value"]).to_bytes() != msg):
                    raise ValueError
            except (IndexError, struct.error, ValueError):
                returns.append(b"")
            else:
                starter = world.add_tutorial_starter(fields[0]["value"])
                caught = world.caught()
                if (len(caught) != 1 or caught[0]["uid"] != starter["uid"]
                        or starter["pokemon_id"] != fields[0]["value"]):
                    returns.append(b"")
                else:
                    returns.append(pb.Writer()
                                   .uint(1, 1)
                                   .message(2, P.build_pokemon_data(
                                       starter["pokemon_id"], starter["uid"], starter["cp"],
                                       extra=starter))
                                   .to_bytes())
                    log(f"      -> ENCOUNTER_TUTORIAL_COMPLETE #{starter['pokemon_id']}")
        elif rtype == P.RT.GET_HATCHED_EGGS:
            import world
            for h in world.check_hatches(P.hatch_species):
                log(f"   [egg] a {h['km']:g} km egg hatched into #{h['pokemon_id']} "
                    f"CP{h['cp']} (+{h['xp']} XP, +{h['candy']} candy, "
                    f"+{h['stardust']} stardust)")
            returns.append(P.build_get_hatched_eggs_response())
        elif rtype == P.RT.USE_ITEM_EGG_INCUBATOR:
            inc_id, egg_uid = P.parse_use_item_egg_incubator(msg)
            r = P.build_use_item_egg_incubator_response(inc_id, egg_uid)
            returns.append(r)
            res = pb.get(pb.decode(r), 1, pb.WT_VARINT)
            log(f"      -> USE_ITEM_EGG_INCUBATOR {inc_id!r} egg={egg_uid} -> " +
                {1: "incubating", 2: "no such incubator", 3: "no such egg",
                 4: "that isn't an egg", 5: "incubator already in use",
                 6: "egg already incubating",
                 7: "incubator has no uses left"}.get(res, f"result {res}"))
        elif rtype in (P.RT.USE_ITEM_POTION, P.RT.USE_ITEM_REVIVE):
            iid, uid = P.parse_use_item(msg)
            revive = rtype == P.RT.USE_ITEM_REVIVE
            r = (P.build_use_item_revive_response(iid, uid) if revive
                 else P.build_use_item_potion_response(iid, uid))
            returns.append(r)
            d = pb.decode(r)
            res = pb.get(d, 1, pb.WT_VARINT)
            hp = pb.get(d, 2, pb.WT_VARINT)
            log(f"      -> {'USE_ITEM_REVIVE' if revive else 'USE_ITEM_POTION'} "
                f"item={iid} pokemon={uid} -> " +
                (f"healed to {hp} HP" if res == 1 else
                 {2: "no such Pokemon", 3: "cannot use it on that Pokemon",
                  4: "it's defending a gym"}.get(res, f"result {res}")))
        elif rtype == P.RT.RELEASE_POKEMON:
            uid = P.parse_pokemon_id(msg)
            r = P.build_release_response(uid)
            returns.append(r)
            res = pb.get(pb.decode(r), 1, pb.WT_VARINT)
            log(f"      -> RELEASE_POKEMON {uid} -> " +
                {1: "transferred (+1 candy)", 2: "REFUSED: it's at a gym",
                 3: "FAILED"}.get(res, str(res)))
        elif rtype == P.RT.UPGRADE_POKEMON:
            uid = P.parse_pokemon_id(msg)
            r = P.build_upgrade_response(uid)
            returns.append(r)
            res = pb.get(pb.decode(r), 1, pb.WT_VARINT)
            log(f"      -> UPGRADE_POKEMON {uid} -> " +
                {1: "powered up", 2: "not found", 3: "not enough candy/stardust",
                 5: "it's at a gym"}.get(res, str(res)))
        elif rtype == P.RT.EVOLVE_POKEMON:
            uid = P.parse_pokemon_id(msg)
            r = P.build_evolve_response(uid)
            returns.append(r)
            d = pb.decode(r); res = pb.get(d, 1, pb.WT_VARINT)
            log(f"      -> EVOLVE_POKEMON {uid} -> " +
                {1: f"evolved! +{pb.get(d,3,pb.WT_VARINT)} xp", 2: "missing",
                 3: "not enough candy", 4: "cannot evolve",
                 5: "it's at a gym"}.get(res, str(res)))
        elif rtype == P.RT.NICKNAME_POKEMON:
            f = pb.decode(msg)
            uid = pb.get(f, 1, pb.WT_64) or 0
            nick = pb.get(f, 2, pb.WT_LEN) or b""
            returns.append(P.build_nickname_response(uid, nick.decode("utf-8", "replace")))
            log(f"      -> NICKNAME_POKEMON {uid} = {nick.decode('utf-8','replace')!r}")
        elif rtype == P.RT.SET_FAVORITE_POKEMON:
            f = pb.decode(msg)
            uid = pb.get(f, 1, pb.WT_64) or pb.get(f, 1, pb.WT_VARINT) or 0
            fav = bool(pb.get(f, 2, pb.WT_VARINT))
            returns.append(P.build_favorite_response(uid, fav))
            log(f"      -> SET_FAVORITE_POKEMON {uid} fav={fav}")
        elif rtype == P.RT.RECYCLE_INVENTORY_ITEM:
            iid, cnt = P.parse_recycle(msg)
            returns.append(P.build_recycle_response(iid, cnt))
            log(f"      -> RECYCLE_INVENTORY_ITEM item={iid} x{cnt} (dropped from bag)")
        elif rtype == P.RT.LEVEL_UP_REWARDS:
            import world
            lvl = P.parse_level_up_rewards(msg) or world.stats()[0]
            already = world.level_claimed(lvl)
            returns.append(P.build_level_up_rewards_response(lvl))
            log(f"      -> LEVEL_UP_REWARDS level {lvl}: "
                + ("AWARDED_ALREADY (no popup)" if already else "SUCCESS, items granted"))
        elif rtype == P.RT.FORT_SEARCH:
            fid, _, _ = P.parse_fort_request(msg)
            returns.append(P.build_fort_search_response(fid, int(time.time() * 1000)))
            log(f"      -> FORT_SEARCH {fid!r} (items added to bag + 50xp, 5m cooldown)")
        elif rtype == P.RT.ENCOUNTER:
            eid = P.parse_encounter(msg)
            returns.append(P.build_encounter_response(eid, int(time.time() * 1000)))
            import world
            s = world.get_spawn(eid)
            log(f"      -> ENCOUNTER {eid} -> " +
                (f"pokemon #{s['pokemon_id']} cp{s['cp']} (catch screen)"
                 if s else "NOT_FOUND (unknown spawn)"))
        elif rtype == P.RT.CATCH_POKEMON:
            eid, ball, hit, reticle, spin = P.parse_catch(msg)
            returns.append(P.build_catch_pokemon_response(
                eid, ball, hit, int(time.time() * 1000), reticle, spin))
            b = P.throw_bonus(reticle, spin)
            st = pb.get(pb.decode(returns[-1]), 1, pb.WT_VARINT)
            log(f"      -> CATCH_POKEMON {eid} ball={ball} hit={hit} "
                f"reticle={reticle:.2f} -> "
                + {1: "CAUGHT", 2: "broke out", 3: "fled",
                   4: "missed"}.get(st, f"status {st}")
                + (f" ({b[1]} throw! +{b[2]} XP)" if b and hit and st == 1 else ""))
        else:
            returns.append(b"")            # placeholder; client tolerates empties
            log(f"      -> {P.rt_name(rtype)} (#{rtype}) empty response")
    return returns


def handle(method, path, query, headers, body, log):
    # Asset bundle download: the client GETs the URL we returned from
    # GET_DOWNLOAD_URLS (https://pgorelease.nianticlabs.com/asset/pm0001).
    if method == "GET" and path.startswith("/asset/"):
        asset_id = path[len("/asset/"):]
        fp = P.bundle_path(asset_id)
        if fp:
            data = open(fp, "rb").read()
            log(f"[asset] SERVING {asset_id} ({len(data)} bytes) to client")
            return 200, {"Content-Type": "application/octet-stream"}, data
        log(f"[asset] 404 unknown asset {asset_id!r}")
        return 404, {"Content-Type": "text/plain"}, b"no such asset"

    # PokeStop / Gym photos: files the user dropped in photos/ next to the server,
    # referenced from FortDetailsResponse.image_urls.
    if method == "GET" and path.startswith("/fortimg/"):
        name = os.path.basename(path[len("/fortimg/"):])
        if name == P.DEFAULT_FORT_IMAGE:            # built-in placeholder photo
            data = P.default_fort_png()
            return 200, {"Content-Type": "image/png"}, data
        fp = os.path.join(P.PHOTO_DIR, name)
        if name and os.path.isfile(fp):
            data = open(fp, "rb").read()
            ext = os.path.splitext(name)[1].lower()
            ctype = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                     ".gif": "image/gif", ".webp": "image/webp"}.get(ext, "image/jpeg")
            log(f"[photo] SERVING {name} ({len(data)} bytes)")
            return 200, {"Content-Type": ctype}, data
        log(f"[photo] 404 {name!r} (put it in the photos/ folder)")
        return 404, {"Content-Type": "text/plain"}, b"no such photo"

    if method != "POST" or not body:
        return 405, {"Content-Type": "text/plain"}, b"method not allowed"

    request_id, reqs, fields = P.parse_request_envelope(body)
    for rtype, message in reqs:
        capture_request(rtype, message, log)
    username = P.resolve_username(fields) or "Trainer"
    _last_user[0] = username

    # track the player's reported location (envelope #7/#8); remember last good
    ll = _envelope_latlng(fields)
    if ll and (abs(ll[0]) > 1e-6 or abs(ll[1]) > 1e-6):
        _last_loc[0], _last_loc[1] = ll
        try:
            import world as _w
            _w.use(username)
            _w.add_distance(ll[0], ll[1])
        except Exception:
            pass
        log(f"[loc] player at {ll[0]:.5f},{ll[1]:.5f}")

    if os.environ.get("CAPTURE_RPC_REQUESTS") != "1":
        if _dump_budget[0] > 0:
            _dump_budget[0] -= 1
            import pb
            log(f"[rpc] {path}  request_id={request_id}  username={username!r}  "
                f"requests={[P.rt_name(t) for t, _ in reqs]}")
            log("[rpc] ---- raw RequestEnvelope ----\n" + pb.pretty(body))
            log("[rpc] -------------------------------")
        else:
            log(f"[rpc] {path}  reqs={[P.rt_name(t) for t, _ in reqs]}  user={username!r}")

    # Bootstrap handshake: tell the client which host to use from now on.
    if path == "/plfe/rpc":
        env = P.build_response_envelope(
            status_code=P.STATUS_REDIRECT,
            request_id=request_id,
            api_url=f"{API_HOST}{API_PATH}",
        )
        log(f"[rpc] -> 53 REDIRECT to {API_HOST}{API_PATH}")
        return 200, {"Content-Type": "application/binary"}, env

    # Normal handling.
    returns = _build_returns(reqs, username, log)
    env = P.build_response_envelope(
        status_code=P.STATUS_OK,
        request_id=request_id,
        returns=returns,
        api_url=f"{API_HOST}{API_PATH}",
        auth_ticket=P.build_auth_ticket(username),
    )
    log(f"[rpc] -> 2 OK ({len(returns)} returns)")
    return 200, {"Content-Type": "application/binary"}, env
