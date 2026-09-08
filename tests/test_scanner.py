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
    read_configured_model,
    compute_bucket_forecast,
    update_quota_snapshots,
    format_hours_duration,
    parse_transcripts,
)


import datetime as dt
import json
import unittest


class TestAntigravityScanner(unittest.TestCase):
    def test_sanitize_plain_text(self):
        self.assertEqual(sanitize_plain_text("hello\x00 world\t"), "hello world")
        self.assertEqual(sanitize_plain_text(None), "")
        self.assertEqual(sanitize_plain_text("   spaced   out   "), "spaced out")

    def test_read_configured_model(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pdir = Path(tmpdir)
            # Default fallback when no settings file exists
            self.assertEqual(read_configured_model(pdir), "Gemini 3.8 Flash (High)")

            # Reads model from settings.json
            settings_file = pdir / "settings.json"
            settings_file.write_text(json.dumps({"model": "Claude Opus 4.6 (Thinking)"}))
            self.assertEqual(read_configured_model(pdir), "Claude Opus 4.6 (Thinking)")

    def test_format_hours_duration(self):
        self.assertEqual(format_hours_duration(0.5), "30m")
        self.assertEqual(format_hours_duration(2.5), "2.5h")
        self.assertEqual(format_hours_duration(26.0), "1d 2h")

    def test_compute_bucket_forecast(self):
        now_dt = dt.datetime.now(dt.timezone.utc)
        reset_in_5h = (now_dt + dt.timedelta(hours=5)).isoformat().replace("+00:00", "Z")

        # Stable / idle: burn rate ~ 0
        burn_txt, fc_txt, status = compute_bucket_forecast(90.0, 0.0, reset_in_5h)
        self.assertEqual(status, "stable")
        self.assertEqual(fc_txt, "Paced to reset")

        # Safe pace: 80% remaining, burning 2%/h for 5h -> 70% left at reset
        burn_txt, fc_txt, status = compute_bucket_forecast(80.0, 2.0, reset_in_5h)
        self.assertEqual(status, "safe")
        self.assertIn("On pace", fc_txt)
        self.assertEqual(burn_txt, "2.0%/h")

        # Warning / tight pace: 20% remaining, burning 2%/h for 5h -> 10% left at reset (<15%)
        burn_txt, fc_txt, status = compute_bucket_forecast(20.0, 2.0, reset_in_5h)
        self.assertEqual(status, "warning")
        self.assertIn("Tight pace", fc_txt)

        # Critical: 20% remaining, burning 10%/h for 5h -> depletes in 2.0h before 5h reset
        burn_txt, fc_txt, status = compute_bucket_forecast(20.0, 10.0, reset_in_5h)
        self.assertEqual(status, "critical")
        self.assertIn("Depletes in ~2.0h (before reset)", fc_txt)

    def test_update_quota_snapshots(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pdir = Path(tmpdir)
            groups = [
                {
                    "name": "Gemini Models",
                    "buckets": [
                        {"id": "gemini-5h", "remaining_fraction": 0.90}
                    ]
                }
            ]
            rates = update_quota_snapshots(pdir, groups)
            # First snapshot establishes baseline
            self.assertIn("gemini-5h", rates)
            self.assertEqual(rates["gemini-5h"], 0.0)

            snap_file = pdir / "cache" / "quota_snapshots.json"
            self.assertTrue(snap_file.exists())

    def test_transcript_caching(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pdir = Path(tmpdir)
            brain_dir = pdir / "brain"
            tpath = brain_dir / "conv1" / ".system_generated" / "logs" / "transcript.jsonl"
            tpath.parent.mkdir(parents=True, exist_ok=True)
            tpath.write_text(json.dumps({
                "type": "USER_INPUT",
                "created_at": "2026-09-08T01:00:00Z",
                "tool_calls": [{"name": "run_command"}]
            }) + "\n")

            # First parse: builds cache
            tools1, models1, list1, latest1 = parse_transcripts(brain_dir, "2026-09-08", ["2026-09-08"], base_dir=pdir)
            self.assertEqual(tools1["run_command"], 1)

            cache_file = pdir / "cache" / "transcript_stats_cache.json"
            self.assertTrue(cache_file.exists())

            # Second parse: reads from cache
            tools2, models2, list2, latest2 = parse_transcripts(brain_dir, "2026-09-08", ["2026-09-08"], base_dir=pdir)
            self.assertEqual(tools2["run_command"], 1)

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
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            cache_dir = base_dir / "cache"
            cache_dir.mkdir(parents=True)
            mock_quota = {
                "groups": [
                    {
                        "name": "Gemini Models",
                        "buckets": [
                            {
                                "id": "gemini-weekly",
                                "name": "Weekly Limit Remaining",
                                "remaining_fraction": 0.85,
                                "reset_time": "2026-09-11T02:24:22Z"
                            }
                        ]
                    }
                ]
            }
            (cache_dir / "quota_usage_cache.json").write_text(json.dumps(mock_quota))

            data = scan(base_dir, force=False)

            self.assertEqual(data["schemaVersion"], 1)
            self.assertEqual(data["id"], "antigravity")
            self.assertIn("activeStatus", data)
            self.assertIn("todayPrompts", data)
            self.assertIn("recentSessions", data)
            self.assertIsInstance(data["recentSessions"], list)
            self.assertIn("limits", data)
            self.assertIsInstance(data["limits"], list)
            self.assertIn("currentModel", data)
            self.assertEqual(data["currentModel"], "Gemini 3.8 Flash (High)")
            self.assertTrue(len(data["limits"]) > 0)
            self.assertIn("burnRatePerHour", data["limits"][0])
            self.assertIn("forecastText", data["limits"][0])
            self.assertIn("forecastStatus", data["limits"][0])


if __name__ == "__main__":
    unittest.main()
