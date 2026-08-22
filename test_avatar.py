import io
import unittest
from unittest.mock import patch

import rpc
import pb
import protocol as P



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
