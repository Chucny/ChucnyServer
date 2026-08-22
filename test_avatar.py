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
    def test_capture_mode_omits_only_avatar_selection(self):
        with patch.dict("os.environ", {"AVATAR_TUTORIAL_CAPTURE": "1"}, clear=False):
            fields = pb.decode(P.build_player_data("avatar-test"))
        self.assertEqual(list(pb.get_all(fields, P.PD_TUTORIAL)[0]), [0, 2, 3, 4, 5, 6, 7])

    def test_normal_mode_keeps_existing_tutorial_state(self):
        with patch.dict("os.environ", {"AVATAR_TUTORIAL_CAPTURE": "0"}, clear=False):
            fields = pb.decode(P.build_player_data("avatar-test"))
        self.assertEqual(list(pb.get_all(fields, P.PD_TUTORIAL)[0]), [0, 1, 2, 3, 4, 5, 6, 7])


class AvatarOnboardingCaptureTest(unittest.TestCase):
    def test_capture_user_receives_uninitialized_player_data(self):
        env = {
            "AVATAR_ONBOARDING_CAPTURE": "1",
            "AVATAR_ONBOARDING_CAPTURE_USER": "AvatarCapture",
        }
        with patch.dict("os.environ", env, clear=False):
            fields = pb.decode(P.build_player_data("AvatarCapture"))

        self.assertIsNone(pb.get(fields, P.PD_TEAM))
        self.assertEqual(pb.get_all(fields, P.PD_TUTORIAL), [])
        self.assertIsNone(pb.get(fields, P.PD_AVATAR, pb.WT_LEN))

    def test_other_users_keep_the_normal_player_data(self):
        env = {
            "AVATAR_ONBOARDING_CAPTURE": "1",
            "AVATAR_ONBOARDING_CAPTURE_USER": "AvatarCapture",
        }
        with patch.dict("os.environ", env, clear=False):
            fields = pb.decode(P.build_player_data("Trainer"))

        self.assertIsNotNone(pb.get(fields, P.PD_TEAM))
        self.assertEqual(list(pb.get_all(fields, P.PD_TUTORIAL)[0]),
                         [0, 1, 2, 3, 4, 5, 6, 7])
        self.assertIsNotNone(pb.get(fields, P.PD_AVATAR, pb.WT_LEN))


class AvatarOnboardingCompletionTest(unittest.TestCase):
    def test_legal_tutorial_completion_returns_success(self):
        response = P.build_mark_tutorial_complete_response()
        self.assertEqual(pb.get(pb.decode(response), 1), 1)

    def test_only_capture_user_accepts_the_observed_legal_completion(self):
        env = {
            "AVATAR_ONBOARDING_CAPTURE": "1",
            "AVATAR_ONBOARDING_CAPTURE_USER": "Trainer",
        }
        with patch.dict("os.environ", env, clear=False):
            replies = rpc._build_returns(
                [(406, bytes.fromhex("0a01001001"))], "Trainer", lambda _: None)
        self.assertEqual(pb.get(pb.decode(replies[0]), 1), 1)


class AvatarPersistenceTest(unittest.TestCase):
    def test_avatar_slots_survive_save_reload_and_player_data(self):
        player = world.use("avatar-persist-test")
        self.assertTrue(player.set_avatar_slots({3: 5, 6: 1, 7: 2, 9: 2}))
        player.save()

        world._players.clear()
        reloaded = world.use("avatar-persist-test")
        self.assertEqual(reloaded.AVATAR[3], 5)
        self.assertEqual(reloaded.AVATAR[6], 1)
        avatar = pb.get(pb.decode(P.build_player_data("avatar-persist-test")),
                        P.PD_AVATAR, pb.WT_LEN)
        self.assertEqual(pb.get(pb.decode(avatar), 3), 5)

    def test_player_data_uses_named_account_avatar_not_current_account(self):
        alice = world.use("avatar-alice-test")
        self.assertTrue(alice.set_avatar_slots({3: 5}))
        alice.save()
        bob = world.use("avatar-bob-test")
        self.assertTrue(bob.set_avatar_slots({3: 2}))
        bob.save()

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
