import json
from pathlib import Path
import unittest

import tempfile
from unittest.mock import patch

import pb
import protocol
import rpc
import world

class BadgeTemplateExtractionTest(unittest.TestCase):
    def test_extracts_only_badge_templates(self):
        badge_body = pb.Writer().uint(1, 7).uint(2, 100).to_bytes()
        badge = pb.Writer().string(1, "BADGE_CAPTURE_TOTAL").message(9, badge_body).to_bytes()
        pokemon = pb.Writer().string(1, "V0001_POKEMON_BULBASAUR").message(2, b"\x08\x01").to_bytes()
        game_master = pb.Writer().message(2, badge).message(2, pokemon).to_bytes()

        self.assertEqual(protocol.extract_badge_templates(game_master),
                         {"BADGE_CAPTURE_TOTAL": badge_body})

    def test_uses_first_nonempty_length_delimited_badge_body(self):
        first_body = pb.Writer().uint(1, 7).to_bytes()
        later_body = pb.Writer().uint(1, 100).to_bytes()
        badge = (pb.Writer().string(1, "BADGE_CAPTURE_TOTAL")
                 .message(9, first_body)
                 .message(2, later_body)
                 .to_bytes())

        self.assertEqual(protocol.extract_badge_templates(pb.Writer().message(2, badge).to_bytes()),
                         {"BADGE_CAPTURE_TOTAL": first_body})

    def test_checked_in_fixture_matches_local_game_master(self):
        fixture_path = Path(__file__).parent / "fixtures" / "badges" / "game_master_badges_0.29.0.json"
        fixture = json.loads(fixture_path.read_text())
        with open(Path(__file__).parent / "game_master.bin", "rb") as game_master:
            actual = {template_id: body.hex()
                      for template_id, body in protocol.extract_badge_templates(game_master.read()).items()}

        self.assertEqual(fixture, actual)



class TypeBadgeMetadataTest(unittest.TestCase):
    def test_game_master_type_fields_map_to_fixture_badges(self):
        pokemon = (pb.Writer().string(1, "V0001_POKEMON_BULBASAUR")
                   .message(2, pb.Writer().uint(1, 1).uint(4, 12).uint(5, 4).to_bytes())
                   .to_bytes())

        self.assertEqual(
            world.type_badges_from_game_master(pb.Writer().message(2, pokemon).to_bytes()),
            {1: ("BADGE_TYPE_GRASS", "BADGE_TYPE_POISON")},
        )


class BadgeProgressTest(unittest.TestCase):
    def setUp(self):
        self.saves = tempfile.TemporaryDirectory()
        self.saves_dir = patch.object(world, "SAVES_DIR", self.saves.name)
        self.saves_dir.start()
        world._players.clear()
        if hasattr(world._current, "player"):
            delattr(world._current, "player")
        self.gyms_file = patch.object(world, "GYMS_FILE", str(Path(self.saves.name) / "gyms.json"))
        self.gyms_file.start()
        world.GYMS.clear()
        world.BATTLES.clear()
        self.addCleanup(world.GYMS.clear)
        self.addCleanup(world.BATTLES.clear)
        self.addCleanup(self.gyms_file.stop)
        self.addCleanup(world._players.clear)
        self.addCleanup(self.saves_dir.stop)
        self.addCleanup(self.saves.cleanup)

    def test_decodes_badge_type_rank_and_packed_thresholds(self):
        capture = world.BADGE_DEFINITIONS["BADGE_CAPTURE_TOTAL"]

        self.assertEqual(capture["type"], 3)
        self.assertEqual(capture["max_rank"], 4)
        self.assertEqual(capture["thresholds"], (30, 500, 2000))

    def test_crossing_thresholds_queues_each_new_level_once(self):
        player = world.use("badges")

        world.record_badge_progress("BADGE_CAPTURE_TOTAL", 30)
        world.record_badge_progress("BADGE_CAPTURE_TOTAL", 0)
        world.record_badge_progress("BADGE_CAPTURE_TOTAL", 1970)

        self.assertEqual(player.BADGE_PROGRESS["BADGE_CAPTURE_TOTAL"], 2000)
        self.assertEqual(player.BADGE_LEVELS["BADGE_CAPTURE_TOTAL"], 3)
        self.assertEqual(player.BADGE_PENDING, [3, 3, 3])

    def test_progress_and_pending_levels_survive_reload(self):
        world.use("badges")
        world.record_badge_progress("BADGE_CAPTURE_TOTAL", 500)
        world._players.clear()
        if hasattr(world._current, "player"):
            delattr(world._current, "player")

        player = world.use("badges")

        self.assertEqual(player.BADGE_PROGRESS, {"BADGE_CAPTURE_TOTAL": 500})
        self.assertEqual(player.BADGE_LEVELS, {"BADGE_CAPTURE_TOTAL": 2})
        self.assertEqual(player.BADGE_PENDING, [3, 3])

    def test_reload_discards_negative_badge_state(self):
        path = Path(self.saves.name) / "badges.json"
        path.write_text(json.dumps({
            "badge_progress": {"BADGE_CAPTURE_TOTAL": -1, "other": 2},
            "badge_levels": {"BADGE_CAPTURE_TOTAL": -1, "other": 2},
            "badge_pending": [-1, "3", 4],
        }))

        player = world.use("badges")

        self.assertEqual(player.BADGE_PROGRESS, {"other": 2})
        self.assertEqual(player.BADGE_LEVELS, {"other": 2})
        self.assertEqual(player.BADGE_PENDING, [3, 4])


class BadgeEventAndResponseTest(BadgeProgressTest):
    def test_capture_and_new_pokedex_entries_record_fixture_badges(self):
        player = world.use("badges")

        for index in range(30):
            world.add_caught(index + 1, index % 5 + 1, 10)
            world.pokedex_caught(index % 5 + 1)

        self.assertEqual(player.BADGE_PROGRESS["BADGE_CAPTURE_TOTAL"], 30)
        self.assertEqual(player.BADGE_PROGRESS["BADGE_POKEDEX_ENTRIES"], 5)
        self.assertCountEqual(player.BADGE_PENDING, [
            world.BADGE_DEFINITIONS[key]["type"]
            for key in ("BADGE_CAPTURE_TOTAL", "BADGE_POKEDEX_ENTRIES",
                        "BADGE_TYPE_GRASS", "BADGE_TYPE_POISON", "BADGE_TYPE_FIRE")
        ])

    def test_pokestop_visits_record_fixture_badge(self):
        player = world.use("badges")

        for _ in range(100):
            world.bump("poke_stop_visits")

        self.assertEqual(player.BADGE_PROGRESS["BADGE_POKESTOPS_VISITED"], 100)
        self.assertEqual(player.BADGE_PENDING, [8])

    def test_sub_kilometre_steps_accumulate_to_travel_badge(self):
        player = world.use("badges")

        for step in range(101):
            world.add_distance(step * 100.1 / 111320.0, 0.0)

        self.assertGreaterEqual(player.BADGE_PROGRESS["BADGE_TRAVEL_KM"], 10)
        self.assertEqual(player.BADGE_PENDING, [1])

    def test_catching_pikachu_records_pikachu_badge(self):
        player = world.use("badges")

        world.add_caught(25, 25, 10)
        self.assertEqual(player.BADGE_PROGRESS["BADGE_PIKACHU"], 1)


    def test_catch_credits_each_distinct_species_type_once(self):
        player = world.use("badges")
        with patch.object(world, "_TYPE_BADGES", {
            1: ("BADGE_TYPE_GRASS", "BADGE_TYPE_POISON"),
            2: ("BADGE_TYPE_WATER", "BADGE_TYPE_WATER"),
        }):
            world.add_caught(1, 1, 10)
            world.add_caught(2, 2, 10)

        self.assertEqual(player.BADGE_PROGRESS["BADGE_TYPE_GRASS"], 1)
        self.assertEqual(player.BADGE_PROGRESS["BADGE_TYPE_POISON"], 1)
        self.assertEqual(player.BADGE_PROGRESS["BADGE_TYPE_WATER"], 1)

    def test_choosing_pikachu_starter_records_pikachu_badge(self):
        player = world.use("badges")

        world.add_tutorial_starter(25)

        self.assertEqual(player.BADGE_PROGRESS["BADGE_PIKACHU"], 1)

    def test_evolution_only_records_badge_after_successful_mutation(self):
        player = world.use("badges")

        self.assertEqual(pb.get(pb.decode(protocol.build_evolve_response(999)), 1), 2)
        self.assertNotIn("BADGE_EVOLVED_TOTAL", player.BADGE_PROGRESS)

        pokemon_id, info = next(
            (pokemon_id, info) for pokemon_id, info in protocol._evo_table().items()
            if info["evolves_to"]
        )
        world.add_caught(1, pokemon_id, 10)
        world.add_candy(info["family"], info["candy"] or 25)

        self.assertEqual(pb.get(pb.decode(protocol.build_evolve_response(1)), 1), 1)
        self.assertEqual(player.BADGE_PROGRESS["BADGE_EVOLVED_TOTAL"], 1)

    def test_hatching_records_badge_after_egg_is_mutated(self):
        player = world.use("badges")
        egg = world.give_egg(2)
        status, _ = world.use_incubator("incubator-unlimited", egg["uid"])
        self.assertEqual(status, 1)
        player.STATS["km_walked"] = 2

        self.assertEqual(len(world.check_hatches(lambda _: (1, 10))), 1)
        self.assertEqual(player.BADGE_PROGRESS["BADGE_HATCHED_TOTAL"], 1)

    def test_winning_attack_battle_records_attack_badge(self):
        self._win_battle(defender_team=2)

        self.assertEqual(world.current().BADGE_PROGRESS["BADGE_BATTLE_ATTACK_WON"], 1)
        self.assertNotIn("BADGE_BATTLE_TRAINING_WON", world.current().BADGE_PROGRESS)

    def test_winning_training_battle_records_training_badge(self):
        self._win_battle(defender_team=1)

        self.assertEqual(world.current().BADGE_PROGRESS["BADGE_BATTLE_TRAINING_WON"], 1)
        self.assertNotIn("BADGE_BATTLE_ATTACK_WON", world.current().BADGE_PROGRESS)

    def _win_battle(self, defender_team):
        world.use("badges")
        self.assertEqual(world.set_team(1)[0], 1)
        world.add_caught(1, 1, 100)
        world.GYMS["gym"] = [{
            "uid": 2, "pokemon_id": 4, "cp": 100, "team": defender_team,
            "trainer": "rival", "owner": "rival",
        }]
        started = pb.decode(protocol.build_start_gym_battle_response("gym", [1], 2, 1))
        self.assertEqual(pb.get(started, 1), 1)
        battle_id = pb.get(started, 4, pb.WT_LEN).decode()
        world.BATTLES[battle_id]["def_hp"] = 1

        won = pb.decode(protocol.build_attack_gym_response(
            "gym", battle_id, [{"type": protocol.BA_ATTACK, "start": 2, "duration": 1}], 3))
        log = pb.decode(pb.get(won, 2, pb.WT_LEN))
        self.assertEqual(pb.get(log, 1), protocol.BS_VICTORY)

    def test_check_awarded_badges_returns_and_drains_only_pending_ids(self):
        player = world.use("badges")
        player.BADGE_PENDING[:] = [3, 2]
        player.save()

        response = rpc._build_returns(
            [(protocol.RT.CHECK_AWARDED_BADGES, b"")], "badges", lambda _: None)[0]

        self.assertEqual(pb.get(pb.decode(response), 1, pb.WT_VARINT), 1)
        self.assertEqual(pb.get_all(pb.decode(response), 2), [3, 2])
        self.assertEqual(player.BADGE_PENDING, [])
        empty = rpc._build_returns(
            [(protocol.RT.CHECK_AWARDED_BADGES, b"")], "badges", lambda _: None)[0]
        self.assertEqual(pb.get_all(pb.decode(empty), 2), [])
