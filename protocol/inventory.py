"""Inventory protocol builders and parsers."""
import math as _math
import random as _random
import time

import pb
import world
from protocol.player import build_pokemon_data, current_hp, max_hp

try:
    import gamedata as _gd
except ImportError:  # pragma: no cover
    _gd = None

# ------------------------------------------------------------- GET_INVENTORY
# (VERIFIED field numbers, POGOProtos 2016 layout:
#  GetInventoryResponse{success=1, inventory_delta=2}
#  InventoryDelta{original_ts=1, new_ts=2, inventory_items=3}
#  InventoryItem{modified_ts=1, deleted_item_key=2, inventory_item_data=3}
#  InventoryItemData{pokemon_data=1, item=2, pokedex_entry=3, player_stats=4, ...}
#  Item{item_id=1, count=2, unseen=3}   PlayerStats{level=1, xp=2, prev=3, next=4})
# Returning a real (non-empty) inventory clears the client's perpetual "syncing"
# spinner, which otherwise suppresses the live map (Pokemon/PokeStops).
ITEM_POKE_BALL = 1
ITEM_GREAT_BALL = 2
ITEM_POTION = 101
ITEM_REVIVE = 201
ITEM_ULTRA_BALL = 3
ITEM_RAZZ_BERRY = 701


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
