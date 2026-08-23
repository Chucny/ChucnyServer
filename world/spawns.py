"""Transient spawn, despawn, lure, and bonus-spawn state."""
import time

from world.player import _lock, take_item


SPAWNS = {}                        # transient
DESPAWNED = {}                     # encounter_id -> expiry_ms
FORT_MODIFIERS = {}                # fort_id -> {item, expires_ms, by}
BONUS_SPAWNS = {}                  # username -> [ {eid,pid,cp,lat,lng,expires_ms} ]
_MAX_SPAWNS = 4000


def add_fort_modifier(fort_id, item_id, minutes, by):
    """Attach a Lure to a PokeStop."""
    now = int(time.time() * 1000)
    with _lock:
        cur = FORT_MODIFIERS.get(fort_id)
        if cur and cur.get("expires_ms", 0) > now:
            return 2, None
    if not take_item(int(item_id), 1):
        return 4, None
    mod = {"item": int(item_id), "expires_ms": now + int(minutes * 60000), "by": by}
    with _lock:
        FORT_MODIFIERS[fort_id] = mod
    return 1, dict(mod)


def fort_modifier(fort_id):
    now = int(time.time() * 1000)
    with _lock:
        m = FORT_MODIFIERS.get(fort_id)
        if not m:
            return None
        if m.get("expires_ms", 0) <= now:
            FORT_MODIFIERS.pop(fort_id, None)
            return None
        return dict(m)


def lured_forts():
    now = int(time.time() * 1000)
    with _lock:
        for fid in [
            k for k, m in FORT_MODIFIERS.items() if m.get("expires_ms", 0) <= now
        ]:
            FORT_MODIFIERS.pop(fid, None)
        return {k: dict(v) for k, v in FORT_MODIFIERS.items()}


def remember_spawn(encounter_id, pokemon_id, lat, lng, cp, spawn_id, expires_ms):
    with _lock:
        if len(SPAWNS) >= _MAX_SPAWNS:
            for k in sorted(SPAWNS, key=lambda k: SPAWNS[k]["expires_ms"])[: _MAX_SPAWNS // 2]:
                SPAWNS.pop(k, None)
        SPAWNS[encounter_id] = {
            "pokemon_id": pokemon_id,
            "lat": lat,
            "lng": lng,
            "cp": cp,
            "spawn_id": spawn_id,
            "expires_ms": expires_ms,
        }


def get_spawn(encounter_id):
    with _lock:
        s = SPAWNS.get(encounter_id)
        return dict(s) if s else None


def remove_spawn(encounter_id):
    with _lock:
        SPAWNS.pop(encounter_id, None)


def mark_despawned(encounter_id, until_ms):
    with _lock:
        DESPAWNED[encounter_id] = until_ms
        if len(DESPAWNED) > 5000:
            now = int(time.time() * 1000)
            for k in [k for k, v in DESPAWNED.items() if v < now]:
                DESPAWNED.pop(k, None)


def is_despawned(encounter_id):
    with _lock:
        exp = DESPAWNED.get(encounter_id)
        if exp is None:
            return False
        if exp < int(time.time() * 1000):
            DESPAWNED.pop(encounter_id, None)
            return False
        return True


def add_bonus_spawn(username, eid, pid, cp, lat, lng, expires_ms):
    """A one-off wild Pokemon placed for ONE trainer."""
    with _lock:
        lst = BONUS_SPAWNS.setdefault(username, [])
        lst.append(
            {
                "eid": eid,
                "pid": pid,
                "cp": cp,
                "lat": lat,
                "lng": lng,
                "expires_ms": expires_ms,
            }
        )
        del lst[:-10]


def bonus_spawns(username):
    now = int(time.time() * 1000)
    with _lock:
        lst = [b for b in BONUS_SPAWNS.get(username, []) if b["expires_ms"] > now]
        BONUS_SPAWNS[username] = lst
        return [dict(b) for b in lst]


def drop_bonus_spawn(username, eid):
    with _lock:
        lst = BONUS_SPAWNS.get(username, [])
        BONUS_SPAWNS[username] = [b for b in lst if b["eid"] != eid]
