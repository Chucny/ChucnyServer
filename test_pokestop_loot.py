import json
import random
import http.client
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import admin
import pb
import settings
import world
from protocol import map as map_proto


class PokestopLootSettingsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.settings_file = Path(self.tmp.name) / "settings.json"
        self.settings_patch = patch.object(
            settings, "SETTINGS_FILE", str(self.settings_file)
        )
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)
        self.addCleanup(self.tmp.cleanup)
        settings._cache.update(data=None, mtime=None, checked=0.0)

    def _write_settings(self, pokestops=None):
        doc = {"_readme": []}
        for section, vals in settings.DEFAULTS.items():
            doc[section] = dict(vals)
        if pokestops is not None:
            doc["pokestops"] = pokestops
        self.settings_file.write_text(json.dumps(doc), encoding="utf-8")
        settings._cache.update(data=None, mtime=None, checked=0.0)

    def test_default_loot_reproduces_current_items(self):
        self.assertEqual(
            [(e["item"], e["chance"], e["min"], e["max"])
             for e in settings.DEFAULT_POKESTOP_LOOT],
            [
                (1, 1.0, 1, 3),      # Poke Ball, always 1-3
                (101, 1.0, 1, 2),    # Potion, always 1-2
                (201, 1.0, 1, 1),    # Revive, always 1
                (2, 0.30, 1, 2),     # Great Ball, 30%
                (3, 0.10, 1, 1),     # Ultra Ball, 10%
                (701, 0.35, 1, 2),   # Razz Berry, 35%
            ],
        )

    def test_absent_loot_migrates_to_default(self):
        # An existing install's settings.json predates the loot key.
        self._write_settings(pokestops={
            k: v for k, v in settings.DEFAULTS["pokestops"].items() if k != "loot"
        })
        self.assertEqual(
            settings.all()["pokestops"]["loot"], settings.DEFAULT_POKESTOP_LOOT
        )

    def test_invalid_loot_falls_back_to_default(self):
        self._write_settings(pokestops={
            **settings.DEFAULTS["pokestops"],
            "loot": [{"item": 9999, "chance": 1.0, "min": 1, "max": 1}],
        })
        self.assertEqual(
            settings.all()["pokestops"]["loot"], settings.DEFAULT_POKESTOP_LOOT
        )

    def test_validation_accepts_only_giveable_entries(self):
        good = [{"item": 2, "chance": 0.5, "min": 1, "max": 2}]
        self.assertEqual(settings.validated_pokestop_loot(good), good)
        for bad in [
            [{"item": 9999, "chance": 0.5, "min": 1, "max": 2}],   # not GIVEABLE
            [{"item": 1, "chance": 1.5, "min": 1, "max": 2}],      # chance > 1
            [{"item": 1, "chance": -0.1, "min": 1, "max": 2}],     # chance < 0
            [{"item": 1, "chance": 0.5, "min": 0, "max": 2}],      # min < 1
            [{"item": 1, "chance": 0.5, "min": 3, "max": 2}],      # min > max
            [{"item": 1, "chance": 0.5}],                           # missing keys
            [{"item": "x", "chance": 0.5, "min": 1, "max": 2}],    # bad id type
            [{"chance": 0.5, "min": 1, "max": 2}],                  # no item
            "not a list",
            [],
        ]:
            self.assertEqual(
                settings.validated_pokestop_loot(bad),
                settings.DEFAULT_POKESTOP_LOOT,
                msg=repr(bad),
            )

    def test_roll_is_deterministic(self):
        self._write_settings()
        self.assertEqual(
            settings.roll_pokestop_loot(random.Random(1234)),
            settings.roll_pokestop_loot(random.Random(1234)),
        )

    def test_roll_honours_chance_and_bounds(self):
        self._write_settings()
        rng = random.Random(7)
        for _ in range(200):
            counts = {}
            for iid, cnt in settings.roll_pokestop_loot(rng):
                counts[iid] = counts.get(iid, 0) + cnt
            # chance-1.0 entries always drop, within their min/max
            self.assertGreaterEqual(counts.get(1, 0), 1)
            self.assertLessEqual(counts.get(1, 0), 3)
            self.assertGreaterEqual(counts.get(101, 0), 1)
            self.assertLessEqual(counts.get(101, 0), 2)
            self.assertGreaterEqual(counts.get(201, 0), 1)

    def test_zero_chance_never_drops(self):
        self._write_settings(pokestops={
            **settings.DEFAULTS["pokestops"],
            "loot": [
                {"item": 1, "chance": 0.0, "min": 1, "max": 3},
                {"item": 101, "chance": 1.0, "min": 2, "max": 2},
            ],
        })
        rng = random.Random(3)
        for _ in range(50):
            self.assertEqual(settings.roll_pokestop_loot(rng), [(101, 2)])


class PokestopSpinTest(unittest.TestCase):
    def setUp(self):
        self.saves = tempfile.TemporaryDirectory()
        self.saves_dir = patch.object(world, "SAVES_DIR", self.saves.name)
        self.saves_dir.start()
        world._players.clear()
        if hasattr(world._current, "player"):
            delattr(world._current, "player")
        self.settings_file = Path(self.saves.name) / "settings.json"
        self.settings_patch = patch.object(
            settings, "SETTINGS_FILE", str(self.settings_file)
        )
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)
        self.addCleanup(world._players.clear)
        self.addCleanup(self.saves_dir.stop)
        self.addCleanup(self.saves.cleanup)
        self._write_settings()
        world.use("spinner")

    def _write_settings(self, pokestops=None):
        doc = {"_readme": []}
        for section, vals in settings.DEFAULTS.items():
            doc[section] = dict(vals)
        if pokestops is not None:
            doc["pokestops"] = pokestops
        doc["eggs"]["drop_chance"] = 0.0   # keep spins item-only for counting
        self.settings_file.write_text(json.dumps(doc), encoding="utf-8")
        settings._cache.update(data=None, mtime=None, checked=0.0)

    def _spin(self, fid="stop.11", now_ms=1_000_000):
        before = dict(world.current().BAG)
        resp = map_proto.build_fort_search_response(fid, now_ms)
        return resp, before, dict(world.current().BAG)

    def _result(self, resp):
        return pb.get(pb.decode(resp), 1, pb.WT_VARINT)

    def _awarded(self, before, after):
        return sum(after.values()) - sum(before.values())

    def test_spin_caps_at_max_items_per_spin(self):
        # Three guaranteed 3-item entries roll 9, capped back to 5.
        self._write_settings(pokestops={
            **settings.DEFAULTS["pokestops"],
            "min_items_per_spin": 5,
            "max_items_per_spin": 5,
            "loot": [
                {"item": 1, "chance": 1.0, "min": 3, "max": 3},
                {"item": 101, "chance": 1.0, "min": 3, "max": 3},
                {"item": 201, "chance": 1.0, "min": 3, "max": 3},
            ],
        })
        resp, before, after = self._spin()
        self.assertEqual(self._result(resp), 1)          # SUCCESS
        self.assertEqual(self._awarded(before, after), 5)

    def test_spin_floors_at_min_items_per_spin(self):
        # An all-0%-chance table rolls empty; the floor tops it up to 5 Poke Balls.
        self._write_settings(pokestops={
            **settings.DEFAULTS["pokestops"],
            "min_items_per_spin": 5,
            "max_items_per_spin": 8,
            "loot": [{"item": 1, "chance": 0.0, "min": 1, "max": 3}],
        })
        resp, before, after = self._spin()
        self.assertEqual(self._result(resp), 1)          # SUCCESS
        self.assertEqual(self._awarded(before, after), 5)
        self.assertEqual(after.get(1, 0) - before.get(1, 0), 5)   # all Poke Balls

    def test_spin_trimmed_to_bag_capacity(self):
        p = world.current()
        p.MAX_ITEMS = world.bag_count() + 3             # room for exactly 3
        self._write_settings()                          # default table, floor 5
        resp, before, after = self._spin()
        self.assertEqual(self._result(resp), 1)          # SUCCESS
        self.assertEqual(self._awarded(before, after), 3)

    def test_spin_rejects_when_bag_full(self):
        world.current().MAX_ITEMS = world.bag_count()    # zero room
        resp, before, after = self._spin()
        self.assertEqual(self._result(resp), 4)          # INVENTORY_FULL
        self.assertEqual(before, after)

    def test_spin_preserves_cooldown_and_xp(self):
        xp_before = world.stats()[1]
        resp1, before, after = self._spin("stop.11", 5_000_000)
        self.assertEqual(self._result(resp1), 1)          # SUCCESS
        self.assertEqual(world.stats()[1] - xp_before, 50)  # xp_per_spin
class PokestopLootApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.settings_file = Path(self.tmp.name) / "settings.json"
        self.settings_patch = patch.object(
            settings, "SETTINGS_FILE", str(self.settings_file))
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)
        self.addCleanup(self.tmp.cleanup)
        self._write_settings()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), admin._Handler)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(self.server.shutdown)
        self.port = self.server.server_address[1]

    def _write_settings(self, pokestops=None):
        doc = {"_readme": []}
        for section, vals in settings.DEFAULTS.items():
            doc[section] = dict(vals)
        if pokestops is not None:
            doc["pokestops"] = pokestops
        self.settings_file.write_text(json.dumps(doc), encoding="utf-8")
        settings._cache.update(data=None, mtime=None, checked=0.0)

    def _request(self, method, path, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        payload = json.dumps(body) if body is not None else None
        headers = {"Content-Type": "application/json"} if body is not None else {}
        conn.request(method, path, payload, headers)
        resp = conn.getresponse()
        data = json.loads(resp.read())
        conn.close()
        return resp.status, data

    def _on_disk(self):
        return json.loads(self.settings_file.read_text(encoding="utf-8"))

    def test_world_exposes_effective_loot_table(self):
        status, data = self._request("GET", "/api/world")
        self.assertEqual(status, 200)
        self.assertEqual(data["loot"], settings.all()["pokestops"]["loot"])

    def test_post_persists_valid_loot_table(self):
        table = [
            {"item": 1, "chance": 1.0, "min": 1, "max": 3},
            {"item": 2, "chance": 0.5, "min": 1, "max": 2},
        ]
        status, data = self._request("POST", "/api/pokestop-loot", {"loot": table})
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["loot"], table)
        self.assertEqual(self._on_disk()["pokestops"]["loot"], table)
        self.assertEqual(self._request("GET", "/api/world")[1]["loot"], table)

    def test_post_rejects_invalid_loot_without_writing(self):
        before = self.settings_file.read_text(encoding="utf-8")
        for bad in (
            [{"item": 9999, "chance": 0.5, "min": 1, "max": 2}],  # not GIVEABLE
            [{"item": 1, "chance": 1.5, "min": 1, "max": 2}],     # chance > 1
            [{"item": 1, "chance": 0.5, "min": 3, "max": 2}],     # min > max
            [{"item": 1, "chance": 0.5}],                         # missing keys
            [],
            "not a list",
            None,
        ):
            status, data = self._request(
                "POST", "/api/pokestop-loot", {"loot": bad})
            self.assertEqual(status, 400, msg=repr(bad))
            self.assertFalse(data["ok"])
            self.assertEqual(self.settings_file.read_text(encoding="utf-8"), before)
        self.assertEqual(
            self._request("GET", "/api/world")[1]["loot"],
            settings.DEFAULT_POKESTOP_LOOT)


if __name__ == "__main__":
    unittest.main()


if __name__ == "__main__":
    unittest.main()
