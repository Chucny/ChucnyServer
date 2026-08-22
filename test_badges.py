import json
from pathlib import Path
import unittest

import pb
import protocol


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
                 .message(2, first_body)
                 .message(9, later_body)
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
