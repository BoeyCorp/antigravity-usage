#!/usr/bin/env python3
"""Unit tests for antigravity_usage_hooks."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from antigravity_usage_hooks import (
    HOOK_COMMAND,
    HOOK_NAME,
    hooks_installed,
    install,
    load_config,
    remove,
)


class TestAntigravityUsageHooks(unittest.TestCase):
    def test_install_on_missing_config_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "hooks.json"
            self.assertFalse(path.exists())

            changed = install(path)
            self.assertTrue(changed)
            self.assertTrue(path.exists())

            config = load_config(path)
            self.assertTrue(hooks_installed(config))
            self.assertIn(HOOK_NAME, config)
            self.assertIn("PreInvocation", config[HOOK_NAME])
            self.assertIn("Stop", config[HOOK_NAME])

    def test_install_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "hooks.json"
            self.assertTrue(install(path))
            self.assertFalse(install(path), "second install should be a no-op")

            config = load_config(path)
            self.assertTrue(hooks_installed(config))

    def test_install_preserves_existing_unrelated_hooks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "hooks.json"
            path.write_text(json.dumps({
                "herdr": {
                    "PreInvocation": [
                        {
                            "type": "command",
                            "command": "bash /some/path/herdr.sh session",
                            "timeout": 10
                        }
                    ]
                }
            }))

            changed = install(path)
            self.assertTrue(changed)

            config = load_config(path)
            self.assertTrue(hooks_installed(config))
            # Check herdr is preserved
            self.assertIn("herdr", config)
            self.assertEqual(config["herdr"]["PreInvocation"][0]["command"], "bash /some/path/herdr.sh session")

    def test_remove_uninstalls_hooks_and_preserves_unrelated(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "hooks.json"
            path.write_text(json.dumps({
                "herdr": {
                    "PreInvocation": [
                        {
                            "type": "command",
                            "command": "bash /some/path/herdr.sh session",
                            "timeout": 10
                        }
                    ]
                }
            }))

            install(path)
            self.assertTrue(hooks_installed(load_config(path)))

            changed = remove(path)
            self.assertTrue(changed)

            config = load_config(path)
            self.assertFalse(hooks_installed(config))
            self.assertNotIn(HOOK_NAME, config)
            self.assertIn("herdr", config)

    def test_remove_on_empty_or_missing_returns_false(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "hooks.json"
            self.assertFalse(remove(path))


if __name__ == "__main__":
    unittest.main()
