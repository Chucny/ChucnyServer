import http.client
import json
import threading
import unittest
from http.server import ThreadingHTTPServer

import admin
import rpc
import world


class TeleportTest(unittest.TestCase):
    def setUp(self):
        self.alice = "teleport-test-alice"
        self.bob = "teleport-test-bob"
        world.use(self.alice)
        world.use(self.bob)
        getattr(rpc, "_teleports", {}).clear()

    def tearDown(self):
        getattr(rpc, "_teleports", {}).clear()

    def test_forced_position_is_isolated_and_beats_later_gps(self):
        self.assertTrue(hasattr(rpc, "set_teleport"))
        rpc.set_teleport(self.alice, -23.55052, -46.63331)

        self.assertEqual(rpc.map_position(self.alice, 1.0, 2.0),
                         (-23.55052, -46.63331))
        self.assertEqual(rpc.map_position(self.bob, 1.0, 2.0), (1.0, 2.0))
        self.assertEqual(rpc.map_position(self.alice, 3.0, 4.0),
                         (-23.55052, -46.63331))

    def test_teleport_route_validates_and_sets_position(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), admin._Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            for body in (
                {"player": "missing", "lat": 0, "lng": 0},
                {"player": self.alice, "lat": 91, "lng": 0},
                {"player": self.alice, "lat": 0, "lng": float("inf")},
            ):
                conn = http.client.HTTPConnection("127.0.0.1", port)
                conn.request("POST", "/api/teleport", json.dumps(body),
                             {"Content-Type": "application/json"})
                response = conn.getresponse()
                self.assertEqual(response.status, 400)
                self.assertFalse(json.loads(response.read())["ok"])

            conn = http.client.HTTPConnection("127.0.0.1", port)
            conn.request("POST", "/api/teleport", json.dumps(
                {"player": self.alice, "lat": -23.55052, "lng": -46.63331}),
                {"Content-Type": "application/json"})
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(json.loads(response.read()), {
                "ok": True, "player": self.alice,
                "lat": -23.55052, "lng": -46.63331})
            self.assertEqual(rpc.teleports()[self.alice], (-23.55052, -46.63331))
        finally:
            server.shutdown()
            thread.join()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
