"""World state facade; player state lives in :mod:`world.player`."""
import importlib
import json
import math
import os
import sys
import time
import types

import pb
import settings as _cfg

__path__ = [os.path.join(os.path.dirname(__file__), "world")]
player = importlib.import_module(__name__ + ".player")

from world.player import (
    BADGE_DEFINITIONS, DEFAULT_AVATAR, ITEM_GREAT_BALL, ITEM_POKE_BALL,
    ITEM_POTION, ITEM_RAZZ_BERRY, ITEM_REVIVE, LEVEL_XP, Player, _current,
    _fresh_uid, _hash_pw, _load_badge_counters, _load_badge_pending, _lock,
    _players, _record_type_badges, _safe_name, _unpack_badge_thresholds,
    account_names, accounts, acting_as, add_candy, add_coins, add_item,
    add_stardust, avatar_for, bag_count, bag_full, bag_items, candy,
    check_login, codename_for, current, drain_badge_pending, has_password,
    level_bounds, level_for_xp, new_uid, onboarding_needed, record_badge_progress,
    room_in_bag, save, set_password, spend, spend_coins, take_item, team_for,
    type_badges_from_game_master, use,
)

HERE = player.HERE
SAVE_FILE = player.SAVE_FILE
SAVES_DIR = player.SAVES_DIR
GYMS_FILE = os.path.join(HERE, "gyms.json")
RAID_FILE = os.path.join(HERE, "raid.json")
_TYPE_BADGES = player._TYPE_BADGES


# ==============================================================================
# Player Leveling, XP, Claims & Stats
# ==============================================================================

def stats():
    p = current()
    with _lock:
        return p.LEVEL, p.XP


def add_xp(n):
    p = current()
    n = int(n) * xp_multiplier()          # Lucky Egg
    with _lock:
        p.XP += n
        p.LEVEL = level_for_xp(p.XP)
    p.save()
    return p.XP


def bump(counter, n=1):
    p = current()
    with _lock:
        if counter in p.STATS:
            p.STATS[counter] += n
    p.save()
    if counter == "poke_stop_visits":
        record_badge_progress("BADGE_POKESTOPS_VISITED", n)


def level_claimed(level):
    with _lock:
        return int(level) in current().CLAIMED_LEVELS


def claim_level(level):
    p = current()
    with _lock:
        if int(level) not in p.CLAIMED_LEVELS:
            p.CLAIMED_LEVELS.append(int(level))
    p.save()


# ==============================================================================
# Pokemon Collection & Storage Operations
# ==============================================================================

def add_caught(uid, pokemon_id, cp):
    p = current()
    with _lock:
        p.DELETED.pop(int(uid), None)     # never report a live Pokemon as deleted
        p.CAUGHT.append(
            {
                "uid": uid,
                "pokemon_id": pokemon_id,
                "cp": cp,
                "caught_ms": int(time.time() * 1000),
            }
        )
        p.STATS["pokemons_captured"] += 1
        p.STATS["pokeballs_thrown"] += 1
        p.STATS["unique_pokedex_entries"] = len({c["pokemon_id"] for c in p.CAUGHT})
        n = len(p.CAUGHT)
    p.save()
    record_badge_progress("BADGE_CAPTURE_TOTAL", 1)
    if int(pokemon_id) == 25:
        record_badge_progress("BADGE_PIKACHU", 1)
    _record_type_badges(pokemon_id)
    return n


def add_tutorial_starter(pokemon_id, cp=10):
    """Persist one selected starter, or return the account's existing Pokémon."""
    p = current()
    with _lock:
        if p.CAUGHT:
            return dict(p.CAUGHT[0])
        uid = new_uid(pokemon_id)
        starter = {
            "uid": uid,
            "pokemon_id": pokemon_id,
            "cp": cp,
            "caught_ms": int(time.time() * 1000),
        }
        p.CAUGHT.append(starter)
        p.STATS["pokemons_captured"] += 1
        p.STATS["unique_pokedex_entries"] = 1
        entry = p.POKEDEX.setdefault(int(pokemon_id), [0, 0])
        entry[1] += 1
        entry[0] = max(entry[0], entry[1])
    p.save()
    record_badge_progress("BADGE_CAPTURE_TOTAL", 1)
    if int(pokemon_id) == 25:
        record_badge_progress("BADGE_PIKACHU", 1)
    record_badge_progress("BADGE_POKEDEX_ENTRIES", 1)
    return dict(starter)


def caught():
    with _lock:
        return list(current().CAUGHT)


def get_caught(uid):
    with _lock:
        for c in current().CAUGHT:
            if c["uid"] == uid:
                return dict(c)
    return None


def update_caught(uid, **fields):
    p = current()
    with _lock:
        for c in p.CAUGHT:
            if c["uid"] == uid:
                c.update(fields)
                out = dict(c)
                break
        else:
            return None
    p.save()
    return out


def release(uid):
    if is_deployed(uid):
        return False, "deployed"
    p = current()
    with _lock:
        for i, c in enumerate(p.CAUGHT):
            if c["uid"] == uid:
                p.CAUGHT.pop(i)
                break
        else:
            return False, "not found"
        p.DELETED[int(uid)] = int(time.time() * 1000)
    p.save()
    return True, "ok"


def recent_deletions(max_age_ms=1800000):
    """Pokemon removed recently, so the inventory delta can keep confirming the deletion."""
    p = current()
    cutoff = int(time.time() * 1000) - max_age_ms
    with _lock:
        stale = [u for u, ts in p.DELETED.items() if ts < cutoff]
        for u in stale:
            p.DELETED.pop(u, None)
        return sorted(p.DELETED.items())


def pokemon_full():
    p = current()
    return len(p.CAUGHT) + len(p.EGGS) >= p.MAX_POKEMON


def buy_storage(kind):
    p = current()
    step = _cfg.get(
        "storage",
        "pokemon_upgrade_step" if kind == "pokemon" else "items_upgrade_step",
        cast=int,
    )
    cost = _cfg.get(
        "storage",
        "pokemon_upgrade_cost" if kind == "pokemon" else "items_upgrade_cost",
        cast=int,
    )
    cap = _cfg.get(
        "storage",
        "max_pokemon_limit" if kind == "pokemon" else "max_items_limit",
        cast=int,
    )
    with _lock:
        cur = p.MAX_POKEMON if kind == "pokemon" else p.MAX_ITEMS
        if cur + step > cap:
            return False, f"already at the maximum ({cap})", cur
        if p.COINS < cost:
            return False, f"need {cost} PokeCoins, you have {p.COINS}", cur
        p.COINS -= cost
        if kind == "pokemon":
            p.MAX_POKEMON = cur + step
            new = p.MAX_POKEMON
        else:
            p.MAX_ITEMS = cur + step
            new = p.MAX_ITEMS
    p.save()
    return True, f"+{step} space for {cost} coins", new


def storage():
    p = current()
    with _lock:
        return {
            "max_pokemon": p.MAX_POKEMON,
            "max_items": p.MAX_ITEMS,
            "pokemon_used": len(p.CAUGHT),
            "items_used": sum(p.BAG.values()),
            "coins": p.COINS,
            "stardust": p.STARDUST,
        }


# ==============================================================================
# Pokédex Mechanics
# ==============================================================================

def pokedex_saw(pokemon_id):
    p = current()
    with _lock:
        e = p.POKEDEX.setdefault(int(pokemon_id), [0, 0])
        e[0] += 1
    p.save()


def pokedex_caught(pokemon_id):
    p = current()
    with _lock:
        e = p.POKEDEX.setdefault(int(pokemon_id), [0, 0])
        new_entry = e[1] == 0
        e[1] += 1
        if e[0] < e[1]:
            e[0] = e[1]          # caught implies seen
    p.save()
    if new_entry:
        record_badge_progress("BADGE_POKEDEX_ENTRIES", 1)


def pokedex():
    with _lock:
        return sorted((pid, v[0], v[1]) for pid, v in current().POKEDEX.items())


# ==============================================================================
# Eggs, Incubation & Walking Mechanics
# ==============================================================================

def km_walked():
    return float(current().STATS.get("km_walked", 0.0) or 0.0)


def add_distance(lat, lng):
    """Accumulate real walked distance from successive GPS fixes."""
    p = current()
    prev = p.LAST_POS
    p.LAST_POS = (lat, lng)
    if not prev:
        return 0.0
    dlat = (lat - prev[0]) * 111320.0
    dlng = (lng - prev[1]) * 111320.0 * math.cos(math.radians((lat + prev[0]) / 2.0))
    metres = math.hypot(dlat, dlng)
    lo = _cfg.get("eggs", "min_step_m", cast=float)
    hi = _cfg.get("eggs", "max_step_m", cast=float)
    if metres < lo or metres > hi:
        return 0.0
    with _lock:
        p.STATS["km_walked"] = km_walked() + metres / 1000.0
    record_badge_progress("BADGE_TRAVEL_KM", metres / 1000.0)
    return metres


def eggs():
    with _lock:
        return [dict(e) for e in current().EGGS]


def incubators():
    with _lock:
        return [dict(i) for i in current().INCUBATORS]


def give_egg(target_km):
    """A new egg from a PokeStop. Returns None if the egg bag is full."""
    p = current()
    with _lock:
        if len(p.EGGS) >= _cfg.get("eggs", "max_eggs", cast=int):
            return None
        uid = _fresh_uid(
            {c["uid"] for c in p.CAUGHT}
            | {e["uid"] for e in p.EGGS}
            | set(p.DELETED)
        )
        egg = {
            "uid": uid,
            "target_km": float(target_km),
            "start_km": 0.0,
            "incubator": "",
        }
        p.EGGS.append(egg)
    p.save()
    return dict(egg)


def use_incubator(incubator_id, egg_uid):
    """Put an egg in an incubator."""
    p = current()
    with _lock:
        inc = next((i for i in p.INCUBATORS if i["id"] == incubator_id), None)
        if inc is None:
            return 2, None
        egg = next((e for e in p.EGGS if e["uid"] == egg_uid), None)
        if egg is None:
            return (4, None) if any(c["uid"] == egg_uid for c in p.CAUGHT) else (3, None)
        if inc.get("egg"):
            return 5, None
        if egg.get("incubator"):
            return 6, None
        if inc.get("uses", -1) == 0:
            return 7, None
        start = km_walked()
        egg["start_km"] = start
        egg["incubator"] = incubator_id
        inc.update(egg=egg_uid, start_km=start, target_km=start + egg["target_km"])
    p.save()
    return 1, dict(inc)


def check_hatches(pick_species):
    """Hatch any egg that has covered its distance."""
    p = current()
    done = []
    with _lock:
        walked = km_walked()
        for egg in list(p.EGGS):
            if not egg.get("incubator"):
                continue
            if walked - egg["start_km"] < egg["target_km"]:
                continue
            tier = egg["target_km"]
            pid, cp = pick_species(tier)
            uid = _fresh_uid(
                {c["uid"] for c in p.CAUGHT}
                | {e["uid"] for e in p.EGGS}
                | set(p.DELETED)
            )
            p.CAUGHT.append(
                {
                    "uid": uid,
                    "pokemon_id": pid,
                    "cp": cp,
                    "caught_ms": int(time.time() * 1000),
                }
            )
            p.EGGS.remove(egg)
            for i in p.INCUBATORS:
                if i["id"] == egg["incubator"]:
                    i.update(egg=0, start_km=0.0, target_km=0.0)
                    if i.get("uses", -1) > 0:
                        i["uses"] -= 1
            xp = int(tier) * 100
            candy = 2 + int(tier)
            dust = int(tier) * 100
            rec = {
                "uid": uid,
                "pokemon_id": pid,
                "cp": cp,
                "km": tier,
                "xp": xp,
                "candy": candy,
                "stardust": dust,
                "egg_uid": egg["uid"],
            }
            p.HATCHED.append(rec)
            done.append(rec)
    if done:
        p.save()
        record_badge_progress("BADGE_HATCHED_TOTAL", len(done))
    return done


def drain_hatched():
    """Hand the client the eggs that hatched since it last asked."""
    p = current()
    with _lock:
        out, p.HATCHED = list(p.HATCHED), []
    if out:
        p.save()
    return out


# ==============================================================================
# Temporary Buffs, Items & Fort Modifiers
# ==============================================================================

def apply_item(item_id, minutes):
    """Start a Lucky Egg / Incense."""
    p = current()
    now = int(time.time() * 1000)
    with _lock:
        p.APPLIED = [a for a in p.APPLIED if a.get("expires_ms", 0) > now]
        if any(a["item"] == int(item_id) for a in p.APPLIED):
            return 2, None
    if not take_item(int(item_id), 1):
        return 3, None
    entry = {
        "item": int(item_id),
        "applied_ms": now,
        "expires_ms": now + int(minutes * 60000),
    }
    with _lock:
        p.APPLIED.append(entry)
    p.save()
    return 1, dict(entry)


def applied_items():
    p = current()
    now = int(time.time() * 1000)
    with _lock:
        p.APPLIED = [a for a in p.APPLIED if a.get("expires_ms", 0) > now]
        return [dict(a) for a in p.APPLIED]


def item_active(item_id):
    return any(a["item"] == int(item_id) for a in applied_items())


def xp_multiplier():
    """A Lucky Egg doubles everything you earn while it burns."""
    return 2 if item_active(301) else 1


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


def use_berry(encounter_id, mult):
    """Remember that a berry is in effect for this encounter."""
    current().BERRIES[int(encounter_id)] = float(mult)


def berry_mult(encounter_id, consume=False):
    p = current()
    m = p.BERRIES.get(int(encounter_id), 1.0)
    if consume:
        p.BERRIES.pop(int(encounter_id), None)
    return m


# ==============================================================================
# Shared World State Data & Spawns
# ==============================================================================

GYMS = {}                          # fort_id -> [{uid, pokemon_id, cp, trainer, team}]
BATTLES = {}                       # battle_id -> live battle state
SPAWNS = {}                        # transient
DESPAWNED = {}                     # encounter_id -> expiry_ms
FORT_MODIFIERS = {}                # fort_id -> {item, expires_ms, by}
RAID = {"on": False, "pokemon_id": 150, "cp": 3000, "trainer": "raid"}
BONUS_SPAWNS = {}                  # username -> [ {eid,pid,cp,lat,lng,expires_ms} ]
_MAX_SPAWNS = 4000


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


# ==============================================================================
# Shared Raids & Bonus Spawns
# ==============================================================================

def load_raid():
    global RAID
    try:
        with open(RAID_FILE, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        RAID.update(
            {
                "on": bool(d.get("on", False)),
                "pokemon_id": int(d.get("pokemon_id", 150) or 150),
                "cp": int(d.get("cp", 3000) or 3000),
                "trainer": str(d.get("trainer", "raid") or "raid"),
            }
        )
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


# ==============================================================================
# Shared Gyms Operations
# ==============================================================================

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
        members.append(
            {
                "uid": uid,
                "pokemon_id": c["pokemon_id"],
                "cp": c["cp"],
                "trainer": trainer,
                "team": team,
                "owner": p.username,
                "deployed_ms": int(time.time() * 1000),
            }
        )
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
                    returned.append(
                        (fid, m["pokemon_id"], coins, m.get("owner"), m["uid"])
                    )
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


# ==============================================================================
# Initialization
# ==============================================================================

load_gyms()
load_raid()


class _WorldFacade(types.ModuleType):
    _player_exports = {
        "HERE", "SAVE_FILE", "SAVES_DIR", "Player", "_current", "_players",
        "_TYPE_BADGES", "current", "use",
        "save", "record_badge_progress", "drain_badge_pending", "accounts",
        "account_names", "acting_as", "onboarding_needed", "check_login",
        "set_password", "has_password", "add_item", "take_item", "bag_items",
        "bag_count", "bag_full", "room_in_bag", "add_coins", "spend_coins",
        "add_stardust", "candy", "add_candy", "spend", "avatar_for",
        "codename_for", "team_for", "new_uid", "level_for_xp", "level_bounds",
        "type_badges_from_game_master",
    }
    _player_dynamic = {
        "BAG", "CAUGHT", "CANDY", "STARDUST", "XP", "LEVEL", "COINS",
        "DELETED", "POKEDEX", "EGGS", "INCUBATORS", "HATCHED", "TEAM",
        "BERRIES", "APPLIED", "MAX_POKEMON", "MAX_ITEMS", "CLAIMED_LEVELS",
        "STATS", "BADGE_PROGRESS", "BADGE_LEVELS", "BADGE_PENDING",
    }

    def __getattr__(self, name):
        if name in self._player_dynamic:
            return getattr(player, name)
        raise AttributeError(name)

    def __setattr__(self, name, value):
        if name in self._player_exports:
            setattr(player, name, value)
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _WorldFacade
