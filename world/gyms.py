"""Shared gym, raid, and battle state."""
import json
import os
import time

import settings as _cfg
from world.player import HERE, SAVE_FILE, _lock, current, get_caught


GYMS_FILE = os.path.join(HERE, "gyms.json")
RAID_FILE = os.path.join(HERE, "raid.json")
GYMS = {}                          # fort_id -> [{uid, pokemon_id, cp, trainer, team}]
BATTLES = {}                       # battle_id -> live battle state
RAID = {"on": False, "pokemon_id": 150, "cp": 3000, "trainer": "raid"}


def load_raid():
    try:
        with open(RAID_FILE, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        RAID.update({
            "on": bool(d.get("on", False)),
            "pokemon_id": int(d.get("pokemon_id", 150) or 150),
            "cp": int(d.get("cp", 3000) or 3000),
            "trainer": str(d.get("trainer", "raid") or "raid"),
        })
    except (OSError, ValueError, TypeError):
        pass
    return dict(RAID)


def save_raid():
    try:
        tmp = RAID_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(RAID, fh, indent=1)
        os.replace(tmp, RAID_FILE)
    except OSError:
        pass


def set_raid(on=None, pokemon_id=None, cp=None, trainer=None):
    """Turn raid mode on/off."""
    sent_home = 0
    with _lock:
        if on is not None:
            RAID["on"] = bool(on)
        if pokemon_id is not None:
            RAID["pokemon_id"] = max(1, min(151, int(pokemon_id)))
        if cp is not None:
            RAID["cp"] = max(10, min(9999, int(cp)))
        if trainer is not None:
            RAID["trainer"] = str(trainer)[:16] or "raid"
        if RAID["on"]:
            sent_home = sum(len(v) for v in GYMS.values())
            GYMS.clear()
    save_gyms()
    save_raid()
    return dict(RAID), sent_home


def raid():
    with _lock:
        return dict(RAID)


def _raid_member(fort_id):
    uid = (abs(hash(("raid", fort_id))) & 0x3FFFFFFFFFFFFFFF) | 1
    return {
        "uid": uid,
        "pokemon_id": int(RAID["pokemon_id"]),
        "cp": int(RAID["cp"]),
        "trainer": RAID.get("trainer", "raid"),
        "team": 0,
        "raid": True,
        "deployed_ms": int(time.time() * 1000),
    }


def is_raid_uid(fort_id, uid):
    return RAID["on"] and _raid_member(fort_id)["uid"] == uid


def _defender_minutes():
    return _cfg.get("gyms", "defender_minutes", env="DEFENDER_MINUTES", cast=float)


def _defender_coins():
    return _cfg.get("gyms", "defender_coins", env="DEFENDER_COINS", cast=int)


def _max_defenders():
    return _cfg.get("gyms", "max_defenders", cast=int)


def save_gyms():
    try:
        tmp = GYMS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"gyms": GYMS}, fh, indent=1)
        os.replace(tmp, GYMS_FILE)
    except OSError:
        pass


def load_gyms():
    try:
        with open(GYMS_FILE, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        GYMS.clear()
        GYMS.update(
            {k: v for k, v in (d.get("gyms") or {}).items() if isinstance(v, list)}
        )
        return True
    except (OSError, ValueError):
        pass
    try:                       # migrate gyms out of old single-player save
        with open(SAVE_FILE, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        GYMS.update(
            {k: v for k, v in (d.get("gyms") or {}).items() if isinstance(v, list)}
        )
        if GYMS:
            save_gyms()
    except (OSError, ValueError):
        pass
    return False


def my_team():
    """The team this trainer picked in game."""
    t = current().TEAM
    return t if t else _cfg.get("gyms", "team", env="TEAM", cast=int)


def set_team(team):
    """SetPlayerTeam."""
    p = current()
    with _lock:
        if p.TEAM:
            return 2, p.TEAM
        p.TEAM = max(1, min(3, int(team)))
        out = p.TEAM
    p.save()
    return 1, out


def gym_members(fort_id):
    with _lock:
        if RAID["on"]:
            return [_raid_member(fort_id)]
        return list(GYMS.get(fort_id, []))


def gym_team(fort_id):
    """Which team holds this gym (0 = neutral/white)."""
    ms = gym_members(fort_id)
    return ms[0].get("team", 0) if ms else 0


def is_deployed(uid):
    with _lock:
        return any(m["uid"] == uid for ms in GYMS.values() for m in ms)


def deploy(fort_id, uid, trainer=None, team=None):
    p = current()
    trainer = trainer or p.username
    team = team if team is not None else my_team()
    c = get_caught(uid)
    if not c:
        return False, "unknown pokemon"
    with _lock:
        members = GYMS.setdefault(fort_id, [])
        if members and members[0].get("team", team) != team:
            return False, "held by another team"
        if any(m["uid"] == uid for m in members):
            return False, "already deployed"
        if len(members) >= _max_defenders():
            return False, "gym full"
        members.append({
            "uid": uid,
            "pokemon_id": c["pokemon_id"],
            "cp": c["cp"],
            "trainer": trainer,
            "team": team,
            "owner": p.username,
            "deployed_ms": int(time.time() * 1000),
        })
    save_gyms()
    return True, "ok"


def recall(fort_id, uid):
    with _lock:
        members = GYMS.get(fort_id, [])
        n = len(members)
        GYMS[fort_id] = [m for m in members if m["uid"] != uid]
        changed = n != len(GYMS[fort_id])
        if not GYMS[fort_id]:
            GYMS.pop(fort_id, None)
    save_gyms()
    return changed


def clear_gym(fort_id):
    """Every defender is knocked out -- the gym goes neutral."""
    with _lock:
        GYMS.pop(fort_id, None)
    save_gyms()


def gym_guard(fort_id):
    ms = gym_members(fort_id)
    if not ms:
        return None
    best = max(ms, key=lambda m: m.get("cp", 0))
    return best["pokemon_id"], best["cp"], 500 * len(ms)


def collect_gym_returns():
    """Bring home any Pokemon that has served its shift and pay its coins."""
    now = int(time.time() * 1000)
    cutoff = _defender_minutes() * 60_000
    coins = _defender_coins()
    faint = _cfg.get("pokemon", "faint_after_gym", cast=bool)
    returned = []
    with _lock:
        for fid in list(GYMS):
            keep = []
            for m in GYMS.get(fid, []):
                dep = m.get("deployed_ms")
                if dep is None:
                    m["deployed_ms"] = now
                    keep.append(m)
                elif now - dep >= cutoff:
                    returned.append((fid, m["pokemon_id"], coins, m.get("owner"), m["uid"]))
                else:
                    keep.append(m)
            if keep:
                GYMS[fid] = keep
            else:
                GYMS.pop(fid, None)
    mine = []
    if returned:
        save_gyms()
        me = current()
        for fid, pid, c, owner, uid in returned:
            if owner and owner != me.username:
                continue
            with _lock:
                me.COINS += c
                if faint:
                    for pk in me.CAUGHT:
                        if pk["uid"] == uid:
                            pk["stamina"] = 0
                            break
            mine.append((fid, pid, c))
        if mine:
            me.save()
    return mine


def time_left(fort_id, uid):
    for m in gym_members(fort_id):
        if m["uid"] == uid:
            dep = m.get("deployed_ms") or 0
            return max(0, int(_defender_minutes() * 60 - (time.time() - dep / 1000)))
    return 0
