"""Gym battle protocol builders and parsers."""
import hashlib as _hashlib
import struct as _struct

import pb
import settings as _cfg
import world
from protocol.player import (_gd, _hp_for, build_player_avatar, build_pokemon_data,
                             move_timing, moves_for)

def _hex_id(seed, n=32):
    return _hashlib.md5(str(seed).encode()).hexdigest()[:n]

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
    me = _battle_participant(
        atk["pokemon_id"], atk["uid"], atk["cp"], ahp,
        world.codename_for(world.current().username) or world.current().username,
        lvl, world.current().AVATAR)
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

