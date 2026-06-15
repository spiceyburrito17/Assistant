"""Tests for v2 config and logger path consistency."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from torn_hud_v2.config import HudConfig
from torn_hud_v2.constants import DEFAULT_SESSION_CSV_PATH


class ConfigTests(unittest.TestCase):
    def test_defaults_use_shared_csv_path(self) -> None:
        config = HudConfig()
        self.assertEqual(config.session_csv_path, DEFAULT_SESSION_CSV_PATH)

    def test_loads_config_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "v2.json"
            path.write_text(
                json.dumps(
                    {
                        "ws_port": 9001,
                        "session_csv_path": "debug_captures/custom_v2.csv",
                    }
                ),
                encoding="utf-8",
            )
            config = HudConfig.load(path)
            self.assertEqual(config.ws_port, 9001)
            self.assertEqual(config.session_csv_path, "debug_captures/custom_v2.csv")


if __name__ == "__main__":
    unittest.main()
