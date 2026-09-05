import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from delete_worker import Config, run_once, safe_source


class FakeNavidrome:
    def all_songs(self):
        return [
            {"path": "Artist/Album/one.flac", "userRating": 1},
            {"path": "Artist/Album/unrated.flac"},
        ]

    def liked_songs(self):
        return [{"path": "Artist/Album/liked.flac", "starred": "now"}]


class WorkerSmokeTest(unittest.TestCase):
    def config(self, root: Path, *, dry_run: bool = False) -> Config:
        return Config(root, "http://navidrome", "u", "p", True, 1, True, dry_run, 0)

    def test_moves_rating_and_liked_but_not_unrated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            album = root / "Artist/Album"
            album.mkdir(parents=True)
            for name in ("one.flac", "unrated.flac", "liked.flac"):
                (album / name).write_bytes(b"audio")

            moved, skipped = run_once(self.config(root), FakeNavidrome())

            self.assertEqual((moved, skipped), (2, 0))
            self.assertTrue((root / ".trash/Artist/Album/one.flac").is_file())
            self.assertTrue((root / ".trash/Artist/Album/liked.flac").is_file())
            self.assertTrue((album / "unrated.flac").is_file())

    def test_rejects_paths_outside_media_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertIsNone(safe_source(root, "../outside.flac"))
            self.assertIsNone(safe_source(root, "/etc/passwd"))

    def test_environment_defaults_are_safe(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
            "MEDIA_PATH": tmp,
            "NAVIDROME_URL": "http://navidrome",
            "NAVIDROME_USER": "user",
            "NAVIDROME_PASSWORD": "password",
        }, clear=True):
            config = Config.from_env()
            self.assertFalse(config.delete_by_rating)
            self.assertFalse(config.delete_liked)
            self.assertTrue(config.dry_run)
            self.assertEqual(config.max_rating, 1)


if __name__ == "__main__":
    unittest.main()
