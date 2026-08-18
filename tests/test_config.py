import os
import unittest
from unittest.mock import patch

from compressor.config import load_config


class ConfigTests(unittest.TestCase):
    def test_cloud_defaults(self) -> None:
        env = {"BOT_TOKEN": "x"}
        with patch.dict(os.environ, env, clear=True):
            cfg = load_config()
        self.assertFalse(cfg.local_mode)
        self.assertEqual(cfg.download_limit_mb, 20)
        self.assertEqual(cfg.upload_limit_mb, 50)

    def test_local_defaults_are_500(self) -> None:
        env = {
            "BOT_TOKEN": "x",
            "TELEGRAM_LOCAL_API": "true",
            "TELEGRAM_API_URL": "http://127.0.0.1:8081",
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = load_config()
        self.assertTrue(cfg.local_mode)
        self.assertEqual(cfg.download_limit_mb, 500)
        self.assertEqual(cfg.upload_limit_mb, 500)
        self.assertEqual(cfg.max_concurrent_jobs, 1)
        self.assertEqual(cfg.job_timeout_sec, 3600)
        self.assertTrue(cfg.api_base_url.endswith("/bot"))

    def test_explicit_limit_wins(self) -> None:
        env = {
            "BOT_TOKEN": "x",
            "TELEGRAM_LOCAL_API": "true",
            "TELEGRAM_API_URL": "http://127.0.0.1:8081",
            "DOWNLOAD_LIMIT_MB": "400",
            "UPLOAD_LIMIT_MB": "400",
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = load_config()
        self.assertEqual(cfg.download_limit_mb, 400)
        self.assertEqual(cfg.upload_limit_mb, 400)


if __name__ == "__main__":
    unittest.main()
