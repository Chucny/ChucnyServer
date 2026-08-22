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
