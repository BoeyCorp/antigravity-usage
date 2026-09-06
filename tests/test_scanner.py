#!/usr/bin/env python3
"""Smoke and unit tests for antigravity_usage_scanner."""

import fcntl
import os
import sys
import tempfile
from pathlib import Path

# Add scripts directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from antigravity_usage_scanner import (
    parse_presence,
    check_session_working,
    scan,
    default_base_dir,
    sanitize_plain_text,
)


import unittest


class TestAntigravityScanner(unittest.TestCase):
    def test_sanitize_plain_text(self):
        self.assertEqual(sanitize_plain_text("hello\x00 world\t"), "hello world")
        self.assertEqual(sanitize_plain_text(None), "")
        self.assertEqual(sanitize_plain_text("   spaced   out   "), "spaced out")

    def test_presence_flock_detection(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pdir = Path(tmpdir)
            lock_held = pdir / "held_session.lock"
            lock_stale = pdir / "stale_session.lock"

            lock_held.touch()
            lock_stale.touch()

            # Hold lock on lock_held
            f = open(lock_held, "rb")
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

            active = parse_presence(pdir, prune_stale=False)
            self.assertIn("held_session", active)
            self.assertNotIn("stale_session", active)

            # Release and verify it becomes inactive
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            f.close()

            active_after = parse_presence(pdir, prune_stale=False)
            self.assertNotIn("held_session", active_after)

    def test_concurrent_presence_detection(self):
        """Verify concurrent multi-monitor scans do not cause false active sessions on stale lock files."""
        import concurrent.futures
        with tempfile.TemporaryDirectory() as tmpdir:
            pdir = Path(tmpdir)
            lock_held = pdir / "active_real.lock"
            lock_held.touch()
            # Create several stale lock files
            for i in range(10):
                (pdir / f"stale_{i}.lock").touch()

            # Hold exclusive lock on the one real active session
            f = open(lock_held, "rb")
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

            try:
                def run_check():
                    return parse_presence(pdir, prune_stale=False)

                # Simulate 8 concurrent monitor/widget threads checking presence simultaneously
                with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
                    futures = [ex.submit(run_check) for _ in range(20)]
                    for fut in futures:
                        res = fut.result()
                        self.assertEqual(res, {"active_real"}, "Concurrent presence checks must not falsely report stale locks as active")
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                f.close()

    def test_scan_contract(self):
        base_dir = default_base_dir()
        data = scan(base_dir)

        self.assertEqual(data["schemaVersion"], 1)
        self.assertEqual(data["id"], "antigravity")
        self.assertIn("activeStatus", data)
        self.assertIn("todayPrompts", data)
        self.assertIn("recentSessions", data)
        self.assertIsInstance(data["recentSessions"], list)
        self.assertIn("limits", data)
        self.assertIsInstance(data["limits"], list)


if __name__ == "__main__":
    unittest.main()
