import tempfile
import unittest
from pathlib import Path

from compressor.store import Store


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "store.json"
        self.store = Store(self.path)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_persist_roundtrip(self) -> None:
        self.store.update_user(42, preset="ultra", ask_each=False, username="ada")
        self.store.record_job(42, 1_000_000, 400_000)
        again = Store(self.path)
        user = again.get_user(42)
        self.assertEqual(user.preset, "ultra")
        self.assertFalse(user.ask_each)
        self.assertEqual(user.videos, 1)
        self.assertEqual(user.bytes_saved, 600_000)
        stats = again.stats()
        self.assertEqual(stats.videos, 1)
        self.assertEqual(stats.users, 1)

    def test_ban(self) -> None:
        self.store.set_banned(7, True)
        self.assertTrue(Store(self.path).get_user(7).banned)

    def test_unknown_preset_falls_back(self) -> None:
        self.path.write_text(
            '{"users":[{"user_id":1,"preset":"nope","ask_each":true}]}',
            encoding="utf-8",
        )
        user = Store(self.path).get_user(1)
        self.assertEqual(user.preset, "medium")


if __name__ == "__main__":
    unittest.main()
