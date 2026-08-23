"""Player protocol builders and parsers."""
import math as _math
import os
import random as _random
import time

import pb
import settings as _cfg
import world as _world

try:
    import gamedata as _gd
except ImportError:  # pragma: no cover
    _gd = None

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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

# New accounts enter onboarding until they have both a codename and starter.
# Team selection may happen later at a gym, so TEAM=0 alone is not sufficient.
TUTORIAL_COMPLETE = [0, 1, 2, 3, 4, 5, 6, 7]


def tutorial_state():
    return TUTORIAL_COMPLETE


def avatar_onboarding_capture(username: str) -> bool:
    return _world.onboarding_needed(username)



# TeamColor: 0=NEUTRAL, 1=BLUE(Mystic), 2=RED(Valor), 3=YELLOW(Instinct).
def default_gym_team():
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
    team = _world.team_for(username)
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


def build_get_player_profile_response() -> bytes:
    """GetPlayerProfileResponse { result=1, badge=3 repeated }."""
    player = _world.current()
    response = pb.Writer().uint(1, 1)
    for key, progress in player.BADGE_PROGRESS.items():
        definition = _world.BADGE_DEFINITIONS.get(key)
        rank = player.BADGE_LEVELS.get(key, 0)
        if not definition or not (rank or progress):
            continue
        badge = (pb.Writer()
                 .uint(1, definition["type"])
                 .uint(2, rank)
                 .double(5, float(progress))
                 .to_bytes())
        response.message(3, badge)
    return response.to_bytes()


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
