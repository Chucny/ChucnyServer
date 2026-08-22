import json
from pathlib import Path
import unittest

import tempfile
from unittest.mock import patch

import pb
import protocol
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


class BadgeProgressTest(unittest.TestCase):
    def setUp(self):
        self.saves = tempfile.TemporaryDirectory()
        self.saves_dir = patch.object(world, "SAVES_DIR", self.saves.name)
        self.saves_dir.start()
        world._players.clear()
        if hasattr(world._current, "player"):
            delattr(world._current, "player")
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
