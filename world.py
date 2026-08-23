"""World state facade backed by per-domain state modules."""
import importlib
import math
import os
import sys
import time
import types

import pb
import settings as _cfg

__path__ = [os.path.join(os.path.dirname(__file__), "world")]
player = importlib.import_module(__name__ + ".player")
spawns = importlib.import_module(__name__ + ".spawns")
gyms = importlib.import_module(__name__ + ".gyms")

from world.player import (
    BADGE_DEFINITIONS, DEFAULT_AVATAR, ITEM_GREAT_BALL, ITEM_POKE_BALL,
    ITEM_POTION, ITEM_RAZZ_BERRY, ITEM_REVIVE, LEVEL_XP, Player, _current,
    _fresh_uid, _hash_pw, _load_badge_counters, _load_badge_pending, _lock,
    _players, _record_type_badges, _safe_name, _unpack_badge_thresholds,
    account_names, accounts, acting_as, add_candy, add_coins, add_item,
    add_stardust, avatar_for, bag_count, bag_full, bag_items, candy,
    check_login, codename_for, current, drain_badge_pending, get_caught,
    has_password, level_bounds, level_for_xp, new_uid, onboarding_needed,
    record_badge_progress,
    room_in_bag, resolve_account, save, set_password, spend, spend_coins,
    take_item, team_for, type_badges_from_game_master, use,
)

from world.spawns import (
    BONUS_SPAWNS, DESPAWNED, FORT_MODIFIERS, SPAWNS, _MAX_SPAWNS,
    add_bonus_spawn, add_fort_modifier, bonus_spawns, drop_bonus_spawn,
    fort_modifier, get_spawn, is_despawned, lured_forts, mark_despawned,
    remember_spawn, remove_spawn,
)

from world.gyms import (
    BATTLES, GYMS, GYMS_FILE, RAID, RAID_FILE, _defender_coins,
    _defender_minutes, _max_defenders, _raid_member, clear_gym,
    collect_gym_returns, deploy, gym_guard, gym_members, gym_team,
    is_deployed, is_raid_uid, load_gyms, load_raid, my_team, raid, recall,
    save_gyms, save_raid, set_raid, set_team, time_left,
)

HERE = player.HERE
SAVE_FILE = player.SAVE_FILE
SAVES_DIR = player.SAVES_DIR
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
        "codename_for", "resolve_account", "team_for", "new_uid",
        "level_for_xp", "level_bounds",
        "get_caught", "type_badges_from_game_master",
    }
    _player_dynamic = {
        "BAG", "CAUGHT", "CANDY", "STARDUST", "XP", "LEVEL", "COINS",
        "DELETED", "POKEDEX", "EGGS", "INCUBATORS", "HATCHED", "TEAM",
        "BERRIES", "APPLIED", "MAX_POKEMON", "MAX_ITEMS", "CLAIMED_LEVELS",
        "STATS", "BADGE_PROGRESS", "BADGE_LEVELS", "BADGE_PENDING",
    }
    _spawn_exports = {
        "SPAWNS", "DESPAWNED", "FORT_MODIFIERS", "BONUS_SPAWNS", "_MAX_SPAWNS",
    }
    _gym_exports = {"GYMS", "BATTLES", "RAID", "GYMS_FILE", "RAID_FILE"}


    def __getattr__(self, name):
        if name in self._player_dynamic:
            return getattr(player, name)
        raise AttributeError(name)

    def __setattr__(self, name, value):
        if name in self._player_exports:
            setattr(player, name, value)
        if name == "SAVE_FILE":
            gyms.SAVE_FILE = value
        if name in self._spawn_exports:
            setattr(spawns, name, value)
        if name in self._gym_exports:
            setattr(gyms, name, value)
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _WorldFacade
