import io
import unittest
from unittest.mock import patch

import rpc
import pb
import protocol as P
import world




class AvatarCaptureTest(unittest.TestCase):
    def test_capture_formats_only_inner_request_metadata(self):
        with patch.dict("os.environ", {"CAPTURE_RPC_REQUESTS": "1"}, clear=False):
            output = io.StringIO()
            rpc.capture_request(8, b"\x0a\x02\x10\x01", output.write)

        self.assertEqual(output.getvalue(),
                         "[capture] type=8 name=UNKNOWN_8 message=0a021001\n")
        self.assertNotIn("auth", output.getvalue().lower())
        self.assertNotIn("ticket", output.getvalue().lower())

    def test_capture_redacts_set_avatar_payload(self):
        with patch.dict("os.environ", {"CAPTURE_RPC_REQUESTS": "1"}, clear=False):
            output = io.StringIO()
            rpc.capture_request(P.RT.SET_AVATAR,
                                bytes.fromhex("12081805300138024802"), output.write)

        self.assertEqual(output.getvalue(),
                         "[capture] type=404 name=SET_AVATAR message=<redacted>\n")

    def test_capture_redacts_claim_codename_payload(self):
        with patch.dict("os.environ", {"CAPTURE_RPC_REQUESTS": "1"}, clear=False):
            output = io.StringIO()
            rpc.capture_request(P.RT.CLAIM_CODENAME,
                                bytes.fromhex("0a084d72507572706c65"), output.write)

        self.assertEqual(output.getvalue(),
                         "[capture] type=403 name=CLAIM_CODENAME message=<redacted>\n")

    def test_claim_codename_skips_verbose_envelope_logging(self):
        request = (pb.Writer()
                   .uint(P.REQ_TYPE, P.RT.CLAIM_CODENAME)
                   .message(P.REQ_MESSAGE, bytes.fromhex("0a084d72507572706c65"))
                   .to_bytes())
        envelope = (pb.Writer()
                    .uint(P.RE_STATUS_CODE, 2)
                    .uint(P.RE_REQUEST_ID, 1)
                    .message(P.RE_REQUESTS, request)
                    .to_bytes())
        output = io.StringIO()

        with patch.object(rpc, "_dump_budget", [1]):
            rpc.handle("POST", "/plfe/rpc", {}, {}, envelope, output.write)

        self.assertNotIn("raw RequestEnvelope", output.getvalue())
        self.assertNotIn("MrPurple", output.getvalue())

    def test_capture_mode_skips_envelope_logging(self):
        request = (pb.Writer()
                   .uint(P.REQ_TYPE, 8)
                   .message(P.REQ_MESSAGE, b"\x0a\x02\x10\x01")
                   .to_bytes())
        auth_info = (pb.Writer()
                     .string(P.AI_PROVIDER, "ptc")
                     .message(P.AI_TOKEN,
                              pb.Writer().string(P.AI_TOKEN_CONTENTS, "outer-auth-token"))
                     .to_bytes())
        envelope = (pb.Writer()
                    .uint(P.RE_STATUS_CODE, 2)
                    .uint(P.RE_REQUEST_ID, 1)
                    .message(P.RE_REQUESTS, request)
                    .message(P.RE_AUTH_INFO, auth_info)
                    .to_bytes())
        output = io.StringIO()

        with (patch.dict("os.environ", {"CAPTURE_RPC_REQUESTS": "1"}, clear=False),
              patch.object(rpc, "_dump_budget", [1])):
            rpc.handle("POST", "/plfe/rpc", {}, {}, envelope, output.write)

        log = output.getvalue()
        self.assertIn("[capture] type=8 name=UNKNOWN_8 message=0a021001\n", log)
        self.assertNotIn("raw RequestEnvelope", log)
        self.assertNotIn("outer-auth-token", log)


class AvatarTutorialTest(unittest.TestCase):
    def test_configured_account_keeps_full_tutorial_state(self):
        player = world.use("avatar-test")
        player.TEAM = 1
        fields = pb.decode(P.build_player_data("avatar-test"))
        self.assertEqual(list(pb.get_all(fields, P.PD_TUTORIAL)[0]), [0, 1, 2, 3, 4, 5, 6, 7])

    def test_named_player_with_starter_ends_automatic_onboarding(self):
        player = world.use("AvatarCapture")
        player.CODENAME = "AvatarCapture"
        player.CAUGHT = [{"uid": 1, "pokemon_id": 4, "cp": 10}]
        fields = pb.decode(P.build_player_data("AvatarCapture"))

        self.assertIsNotNone(pb.get(fields, P.PD_TEAM))
        self.assertEqual(list(pb.get_all(fields, P.PD_TUTORIAL)[0]),
                         [0, 1, 2, 3, 4, 5, 6, 7])

    def setUp(self):
        import tempfile

        self.saves = tempfile.TemporaryDirectory()
        self.saves_dir = patch.object(world, "SAVES_DIR", self.saves.name)
        self.saves_dir.start()
        world._players.clear()
        if hasattr(world._current, "player"):
            delattr(world._current, "player")
        self.addCleanup(world._players.clear)
        self.addCleanup(self.saves_dir.stop)
        self.addCleanup(self.saves.cleanup)


class AvatarOnboardingCaptureTest(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.saves = tempfile.TemporaryDirectory()
        self.saves_dir = patch.object(world, "SAVES_DIR", self.saves.name)
        self.saves_dir.start()
        world._players.clear()
        if hasattr(world._current, "player"):
            delattr(world._current, "player")
        self.addCleanup(world._players.clear)
        self.addCleanup(self.saves_dir.stop)
        self.addCleanup(self.saves.cleanup)

    def test_new_account_receives_uninitialized_player_data(self):
        fields = pb.decode(P.build_player_data("AvatarCapture"))

        self.assertIsNone(pb.get(fields, P.PD_TEAM))
        self.assertEqual(pb.get_all(fields, P.PD_TUTORIAL), [])
        self.assertIsNone(pb.get(fields, P.PD_AVATAR, pb.WT_LEN))

    def test_configured_user_keeps_the_normal_player_data(self):
        player = world.use("Trainer")
        player.TEAM = 1
        fields = pb.decode(P.build_player_data("Trainer"))

        self.assertIsNotNone(pb.get(fields, P.PD_TEAM))
        self.assertEqual(list(pb.get_all(fields, P.PD_TUTORIAL)[0]),
                         [0, 1, 2, 3, 4, 5, 6, 7])
        self.assertIsNotNone(pb.get(fields, P.PD_AVATAR, pb.WT_LEN))


class AvatarOnboardingCompletionTest(unittest.TestCase):
    def test_legal_tutorial_completion_returns_success(self):
        response = P.build_mark_tutorial_complete_response()
        self.assertEqual(pb.get(pb.decode(response), 1), 1)

    def setUp(self):
        import tempfile

        self.saves = tempfile.TemporaryDirectory()
        self.saves_dir = patch.object(world, "SAVES_DIR", self.saves.name)
        self.saves_dir.start()
        world._players.clear()
        if hasattr(world._current, "player"):
            delattr(world._current, "player")
        self.addCleanup(world._players.clear)
        self.addCleanup(self.saves_dir.stop)
        self.addCleanup(self.saves.cleanup)

    def test_only_capture_user_accepts_the_observed_legal_completion(self):
        env = {
            "AVATAR_ONBOARDING_CAPTURE": "1",
            "AVATAR_ONBOARDING_CAPTURE_USER": "Trainer",
        }
        with patch.dict("os.environ", env, clear=False):
            replies = rpc._build_returns(
                [(406, bytes.fromhex("0a01001001"))], "Trainer", lambda _: None)
        self.assertEqual(pb.get(pb.decode(replies[0]), 1), 1)


class ClaimCodenameRpcTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.saves = tempfile.TemporaryDirectory()
        self.saves_dir = patch.object(world, "SAVES_DIR", self.saves.name)
        self.saves_dir.start()
        world._players.clear()
        self.addCleanup(world._players.clear)
        self.addCleanup(self.saves_dir.stop)
        self.addCleanup(self.saves.cleanup)
        self.env = {
            "AVATAR_ONBOARDING_CAPTURE": "1",
            "AVATAR_ONBOARDING_CAPTURE_USER": "AvatarCapture",
        }

    def _claim(self, username, body):
        with patch.dict("os.environ", self.env, clear=False):
            return rpc._build_returns([(403, body)], username, lambda _: None)

    def test_observed_name_returns_success_and_persists_display_name(self):
        reply = self._claim("AvatarCapture", bytes.fromhex("0a084d72507572706c65"))[0]

        fields = pb.decode(reply)
        self.assertEqual(pb.get(fields, 1, pb.WT_LEN), b"MrPurple")
        self.assertEqual(pb.get(fields, 3, pb.WT_VARINT), 1)
        self.assertEqual(pb.get(fields, 4, pb.WT_VARINT), 1)
        self.assertIsNone(pb.get(fields, 5, pb.WT_LEN))
        self.assertEqual(world.current().username, "AvatarCapture")
        self.assertEqual(world.current().CODENAME, "MrPurple")

        world._players.clear()
        reloaded = world.use("AvatarCapture")
        self.assertEqual(reloaded.username, "AvatarCapture")
        self.assertEqual(reloaded.CODENAME, "MrPurple")
        player_data = pb.decode(P.build_player_data("AvatarCapture"))
        self.assertEqual(pb.get(player_data, P.PD_USERNAME, pb.WT_LEN), b"MrPurple")

    def test_invalid_or_non_capture_claims_leave_existing_player_unchanged(self):
        player = world.use("AvatarCapture")
        before = player.snapshot()
        for body in (b"", b"\x0a", bytes.fromhex("0a024161"), bytes.fromhex("0a03412141")):
            with self.subTest(body=body.hex()):
                self.assertEqual(self._claim("AvatarCapture", body), [b""])
                self.assertEqual(player.snapshot(), before)

        other = world.use("OtherTrainer")
        other.TEAM = 1
        other_before = other.snapshot()
        self.assertEqual(self._claim("OtherTrainer", bytes.fromhex("0a084d72507572706c65")),
                         [b""])
        self.assertEqual(other.snapshot(), other_before)



class TutorialStarterRpcTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.saves = tempfile.TemporaryDirectory()
        self.saves_dir = patch.object(world, "SAVES_DIR", self.saves.name)
        self.saves_dir.start()
        world._players.clear()
        self.addCleanup(world._players.clear)
        self.addCleanup(self.saves_dir.stop)
        self.addCleanup(self.saves.cleanup)
        self.env = {
            "AVATAR_ONBOARDING_CAPTURE": "1",
            "AVATAR_ONBOARDING_CAPTURE_USER": "TutorialStarter",
        }

    def _select(self, username, body):
        with patch.dict("os.environ", self.env, clear=False):
            return rpc._build_returns([(127, body)], username, lambda _: None)

    def test_observed_charmander_selection_returns_and_stores_one_starter(self):
        reply = self._select("TutorialStarter", bytes.fromhex("0804"))[0]

        response = pb.decode(reply)
        self.assertEqual(pb.get(response, 1), 1)
        pokemon = pb.decode(pb.get(response, 2, pb.WT_LEN))
        stored = world.current().CAUGHT
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["pokemon_id"], 4)
        self.assertEqual(pb.get(pokemon, 2), 4)
        self.assertEqual(pb.get(pokemon, 1, pb.WT_64), stored[0]["uid"])

    def test_repeat_selection_returns_the_existing_starter_without_duplicate(self):
        first = self._select("TutorialStarter", bytes.fromhex("0804"))[0]
        second = self._select("TutorialStarter", bytes.fromhex("0804"))[0]
        first_response = pb.decode(first)
        self.assertEqual(pb.get(first_response, 1), 1)
        first_pokemon = pb.decode(pb.get(first_response, 2, pb.WT_LEN))
        second_pokemon = pb.decode(pb.get(pb.decode(second), 2, pb.WT_LEN))
        self.assertEqual(len(world.current().CAUGHT), 1)
        self.assertEqual(pb.get(second_pokemon, 1, pb.WT_64),
                         pb.get(first_pokemon, 1, pb.WT_64))

    def test_invalid_or_malformed_selection_leaves_existing_account_unchanged(self):
        self._select("TutorialStarter", bytes.fromhex("0804"))
        before = list(world.current().CAUGHT)

        for body in (bytes.fromhex("0802"), b"", b"\x08", bytes.fromhex("08041000")):
            with self.subTest(body=body.hex()):
                self.assertEqual(self._select("TutorialStarter", body), [b""])
                self.assertEqual(world.current().CAUGHT, before)

    def test_non_capture_user_selection_is_empty_and_does_not_create_a_starter(self):
        world.use("OtherTrainer").TEAM = 1
        self.assertEqual(self._select("OtherTrainer", bytes.fromhex("0804")), [b""])
        self.assertEqual(world.current().CAUGHT, [])

    def test_existing_unrelated_pokemon_rejects_selection_without_mutation(self):
        player = world.use("TutorialStarter")
        world.add_caught(world.new_uid(25), 25, 100)
class AvatarPersistenceTest(unittest.TestCase):
    def test_avatar_slots_survive_save_reload_and_player_data(self):
        player = world.use("avatar-persist-test")
        self.assertTrue(player.set_avatar_slots({3: 5, 6: 1, 7: 2, 9: 2}))
        player.save()

        world._players.clear()
        reloaded = world.use("avatar-persist-test")
        reloaded.TEAM = 1
        self.assertEqual(reloaded.AVATAR[3], 5)
        self.assertEqual(reloaded.AVATAR[6], 1)
        avatar = pb.get(pb.decode(P.build_player_data("avatar-persist-test")),
                        P.PD_AVATAR, pb.WT_LEN)
        self.assertEqual(pb.get(pb.decode(avatar), 3), 5)

    def test_player_data_uses_named_account_avatar_not_current_account(self):
        alice = world.use("avatar-alice-test")
        self.assertTrue(alice.set_avatar_slots({3: 5}))
        alice.save()
        alice.TEAM = 1
        bob = world.use("avatar-bob-test")
        self.assertTrue(bob.set_avatar_slots({3: 2}))
        bob.save()
        bob.TEAM = 1

        avatar = pb.get(pb.decode(P.build_player_data("avatar-alice-test")),
                        P.PD_AVATAR, pb.WT_LEN)
        self.assertEqual(pb.get(pb.decode(avatar), 3), 5)
    def test_rejected_avatar_slots_leave_saved_avatar_unchanged(self):
        player = world.use("avatar-reject-test")
        before = dict(player.AVATAR)
        self.assertFalse(player.set_avatar_slots({11: 1}))
        self.assertEqual(player.AVATAR, before)


class SetAvatarRpcTest(unittest.TestCase):
    REQUEST = bytes.fromhex("12081805300138024802")

    def test_set_avatar_updates_only_active_player_and_returns_success(self):
        world.use("avatar-rpc-other")
        other_before = dict(world.current().AVATAR)

        replies = rpc._build_returns([(404, self.REQUEST)], "avatar-rpc-active",
                                     lambda _: None)

        self.assertEqual(pb.get(pb.decode(replies[0]), 1), 1)
        self.assertEqual(world.current().AVATAR[3], 5)
        self.assertEqual(world.current().AVATAR[6], 1)
        self.assertEqual(world.use("avatar-rpc-other").AVATAR, other_before)

    def test_set_avatar_rejects_malformed_body_without_mutation(self):
        world.use("avatar-rpc-malformed")
        before = dict(world.current().AVATAR)

        replies = rpc._build_returns([(404, b"\x12\x01\x5a")],
                                     "avatar-rpc-malformed", lambda _: None)

        self.assertEqual(replies, [b""])
        self.assertEqual(world.current().AVATAR, before)

    def test_set_avatar_rejects_invalid_slot_wire_and_value_without_mutation(self):
        cases = (
            b"\x12\x02\x12\x00",              # slot 2, length-delimited
            b"\x12\x03\x18\x80\x02",          # slot 3, value 256
            b"\x12\x02\x58\x01",              # unsupported slot 11
            b"\x12\x02\x18\x05\x13",          # malformed trailing group
        )
        for body in cases:
            with self.subTest(body=body.hex()):
                world.use("avatar-rpc-invalid")
                before = dict(world.current().AVATAR)

                replies = rpc._build_returns([(404, body)], "avatar-rpc-invalid",
                                             lambda _: None)

                self.assertEqual(replies, [b""])
                self.assertEqual(world.current().AVATAR, before)

    def test_set_avatar_rejects_truncated_fixed_width_outer_body(self):
        world.use("avatar-rpc-truncated")
        before = dict(world.current().AVATAR)

        replies = rpc._build_returns([(404, b"\x11")],
                                     "avatar-rpc-truncated", lambda _: None)

        self.assertEqual(replies, [b""])
        self.assertEqual(world.current().AVATAR, before)


class _HalfRandom:
    def random(self):
        return 0.5


class TutorialCatchGuaranteeTest(unittest.TestCase):
    def setUp(self):
        self.player = world.Player("tutorial-catch-test")
        self.current_player = patch.object(world, "current", return_value=self.player)
        self.current_player.start()
        self.save_player = patch.object(world.Player, "save")
        self.save_player.start()
        self.addCleanup(self.save_player.stop)
        self.addCleanup(self.current_player.stop)

    def _remember_spawn(self, encounter_id):
        world.remember_spawn(encounter_id, 25, 0.0, 0.0, 100, 1, 2_000_000)
        self.addCleanup(world.remove_spawn, encounter_id)
        self.addCleanup(world.DESPAWNED.pop, encounter_id, None)
        self.addCleanup(world.BONUS_SPAWNS.pop, self.player.username, None)

    def _catch_with_zero_chance(self, encounter_id):
        with (patch.object(P, "catch_chance", return_value=0.0),
              patch.object(P._random, "Random", return_value=_HalfRandom())):
            return P.build_catch_pokemon_response(
                encounter_id, P.ITEM_POKE_BALL, True, 1_000_000)

    def test_first_valid_hit_succeeds_at_zero_capture_probability(self):
        encounter_id = 9_001
        self._remember_spawn(encounter_id)
        balls_before = self.player.BAG[P.ITEM_POKE_BALL]

        response = self._catch_with_zero_chance(encounter_id)

        self.assertEqual(pb.get(pb.decode(response), 1), 1)
        self.assertEqual(self.player.BAG[P.ITEM_POKE_BALL], balls_before - 1)
        self.assertEqual(self.player.STATS["pokemons_captured"], 1)

    def test_later_hit_escapes_at_zero_capture_probability(self):
        first_encounter_id = 9_002
        self._remember_spawn(first_encounter_id)
        self.assertEqual(pb.get(pb.decode(
            self._catch_with_zero_chance(first_encounter_id)), 1), 1)

        later_encounter_id = 9_003
        self._remember_spawn(later_encounter_id)
        response = self._catch_with_zero_chance(later_encounter_id)

        self.assertEqual(pb.get(pb.decode(response), 1), 2)
