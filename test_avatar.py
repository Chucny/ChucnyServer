import io
import unittest
from unittest.mock import patch

import rpc


class AvatarCaptureTest(unittest.TestCase):
    def test_capture_formats_only_inner_request_metadata(self):
        with patch.dict("os.environ", {"CAPTURE_RPC_REQUESTS": "1"}, clear=False):
            output = io.StringIO()
            rpc.capture_request(8, b"\x0a\x02\x10\x01", output.write)

        self.assertEqual(output.getvalue(),
                         "[capture] type=8 name=UNKNOWN_8 message=0a021001\n")
        self.assertNotIn("auth", output.getvalue().lower())
        self.assertNotIn("ticket", output.getvalue().lower())
