#!/usr/bin/env python3
"""Query Antigravity CLI/IDE state, sqlite database, history, and transcripts to emit usage stats."""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import glob
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any


def default_base_dir() -> Path:
    return Path(os.environ.get("ANTIGRAVITY_DATA_DIR") or os.path.expanduser("~/.gemini/antigravity-cli"))


def expand_path(value: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(value))).resolve()


def date_string(value: dt.date) -> str:
    return value.strftime("%Y-%m-%d")


def sanitize_plain_text(val: Any, max_len: int = 250) -> str:
    """Sanitize arbitrary strings to safe plain-text by stripping control chars and truncating."""
    if val is None:
        return ""
    text = str(val)
    # Remove null bytes and non-printable control characters
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", text)
    # Collapse whitespace and newlines to a single space
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_len]


def recent_date_strings() -> list[str]:
    today = dt.datetime.now().date()
    return [date_string(today - dt.timedelta(days=offset)) for offset in range(6, -1, -1)]


def local_date_from_timestamp(value: Any) -> str:
    if value is None:
        return date_string(dt.datetime.now().date())
    if isinstance(value, (int, float)):
        try:
            # Check if timestamp is in milliseconds (epoch ms)
            seconds = float(value) / 1000.0 if float(value) > 10_000_000_000 else float(value)
            return date_string(dt.datetime.fromtimestamp(seconds).date())
        except Exception:
            return date_string(dt.datetime.now().date())
    raw = str(value).strip()
    if not raw:
        return date_string(dt.datetime.now().date())
    try:
        parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone()
        return date_string(parsed.date())
    except Exception:
        pass
    try:
        clean = raw.split(".")[0]
        parsed = dt.datetime.fromisoformat(clean)
        return date_string(parsed.date())
    except Exception:
        return date_string(dt.datetime.now().date())


def empty_result() -> dict[str, Any]:
    recent_dates = recent_date_strings()
    return {
        "schemaVersion": 1,
        "id": "antigravity",
        "name": "Antigravity",
        "ready": False,
        "active": False,
        "activeStatus": "Idle",
        "hasActiveSession": False,
        "hasLocalStats": False,
        "tierLabel": "Google DeepMind",
        "currentModel": "Gemini 3.7 Flash",
        "todayPrompts": 0,
        "todaySessions": 0,
        "todaySteps": 0,
        "todayTotalTokens": 0,
        "todayTokensByModel": {},
        "recentDays": [{"date": day, "messageCount": 0, "prompts": 0, "steps": 0} for day in recent_dates],
        "totalPrompts": 0,
        "totalSessions": 0,
        "totalSteps": 0,
        "activeSessions": [],
        "recentSessions": [],
        "toolUsage": {},
        "modelUsage": {},
        "modelList": [],
        "quotaGroups": [],
        "limits": [],
        "recentWorkspaces": [],
        "updatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "usageStatusText": "No Antigravity data found",
        "authHelpText": "Run `agy` to start a session."
    }


def parse_history_file(history_path: Path, recent_dates: list[str]) -> tuple[dict[str, int], int, list[dict[str, Any]], Counter]:
    daily_prompts = {day: 0 for day in recent_dates}
    total_prompts = 0
    recent_prompts: list[dict[str, Any]] = []
    workspace_counter: Counter = Counter()

    if not history_path.exists():
        return daily_prompts, total_prompts, recent_prompts, workspace_counter

    try:
        with open(history_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    total_prompts += 1
                    ts = entry.get("timestamp")
                    day = local_date_from_timestamp(ts)
                    if day in daily_prompts:
                        daily_prompts[day] += 1
                    
                    ws = sanitize_plain_text(entry.get("workspace") or "", 300)
                    if ws:
                        workspace_counter[ws] += 1

                    recent_prompts.append({
                        "display": sanitize_plain_text(entry.get("display", ""), 200),
                        "workspace": ws,
                        "conversationId": sanitize_plain_text(entry.get("conversationId", ""), 100),
                        "type": sanitize_plain_text(entry.get("type", "prompt"), 50),
                        "timestamp": ts or 0,
                        "date": day
                    })
                except Exception:
                    continue
    except Exception:
        pass

    return daily_prompts, total_prompts, recent_prompts, workspace_counter


def parse_presence(presence_dir: Path) -> set[str]:
    """Return set of conversation IDs whose presence locks are actively held by running processes."""
    active_ids = set()
    if not presence_dir.exists():
        return active_ids

    for p in presence_dir.glob("*.lock"):
        cid = sanitize_plain_text(p.stem, 100)
        if not cid:
            continue
        try:
            with open(p, "rb") as f:
                try:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    # Succeeded in acquiring exclusive lock: no active process holds it (stale file)
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                except (BlockingIOError, PermissionError, OSError):
                    # Lock is actively held by a running agy process!
                    active_ids.add(cid)
        except Exception:
            pass
    return active_ids


def check_session_working(cid: str, base_dir: Path) -> bool:
    """Check whether a session is actively executing/thinking or waiting for user input."""
    # 1. Check sqlite database steps status
    db_path = base_dir / "conversations" / f"{cid}.db"
    if db_path.exists():
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=0.3)
            cur = conn.cursor()
            cur.execute("SELECT status FROM steps ORDER BY idx DESC LIMIT 1")
            row = cur.fetchone()
            conn.close()
            if row and row[0] == 2:  # Status 2 = in progress / running
                return True
        except Exception:
            pass

    # 2. Check transcript.jsonl tail
    tpath = base_dir / "brain" / cid / ".system_generated" / "logs" / "transcript.jsonl"
    if tpath.exists():
        try:
            with open(tpath, "rb") as f:
                f.seek(max(0, tpath.stat().st_size - 4096))
                lines = f.readlines()
                if lines:
                    last_line = lines[-1].decode("utf-8", errors="replace").strip()
                    if not last_line and len(lines) > 1:
                        last_line = lines[-2].decode("utf-8", errors="replace").strip()
                    if last_line:
                        data = json.loads(last_line)
                        step_type = data.get("type", "")
                        if step_type in ("USER_INPUT", "GENERIC"):
                            return True
                        if step_type == "PLANNER_RESPONSE" and data.get("tool_calls"):
                            return True
        except Exception:
            pass

    return False


def parse_transcripts(brain_dir: Path, today_str: str = "") -> tuple[Counter, dict[str, dict[str, Any]], list[dict[str, Any]], str]:
    tool_counter: Counter = Counter()
    models_stats: dict[str, dict[str, Any]] = {}
    latest_model = "Gemini 3.7 Flash"

    if not brain_dir.exists():
        return tool_counter, models_stats, [], latest_model

    try:
        transcript_files = list(brain_dir.glob("*/.system_generated/logs/transcript.jsonl"))
        transcript_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)

        for p in transcript_files:
            conv_id = sanitize_plain_text(p.parent.parent.parent.name, 100)
            current_model = "Gemini 3.7 Flash"
            try:
                with open(p, "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            step = json.loads(line)
                        except Exception:
                            continue

                        content = step.get("content") or ""
                        created_at = step.get("created_at") or ""
                        step_day = local_date_from_timestamp(created_at)
                        is_today = (step_day == today_str) if today_str else False
                        
                        # Model detection
                        if "Model Selection" in content:
                            match = re.search(r"Model Selection` from .*? to (.+?)\.\s*(?:No need|$)", content)
                            if match:
                                m = sanitize_plain_text(match.group(1).strip().replace("`", ""), 80)
                                if m and len(m) < 60 and not m.lower().startswith("comment"):
                                    current_model = m
                                    if latest_model == "Gemini 3.7 Flash":
                                        latest_model = m

                        if current_model not in models_stats:
                            models_stats[current_model] = {
                                "name": current_model,
                                "prompts": 0,
                                "steps": 0,
                                "todayPrompts": 0,
                                "todaySteps": 0,
                                "sessions": set()
                            }

                        models_stats[current_model]["steps"] += 1
                        if is_today:
                            models_stats[current_model]["todaySteps"] += 1

                        if step.get("type") == "USER_INPUT":
                            models_stats[current_model]["prompts"] += 1
                            if is_today:
                                models_stats[current_model]["todayPrompts"] += 1

                        models_stats[current_model]["sessions"].add(conv_id)

                        # Tool call detection
                        for tc in step.get("tool_calls", []):
                            fn_name = ""
                            if isinstance(tc, dict):
                                fn_name = tc.get("function", {}).get("name") or tc.get("name") or ""
                            fn_name = sanitize_plain_text(fn_name, 80)
                            if fn_name:
                                tool_counter[fn_name] += 1
            except Exception:
                continue
    except Exception:
        pass

    # Convert sets to counts and sort models
    formatted_models: dict[str, dict[str, Any]] = {}
    model_list: list[dict[str, Any]] = []
    total_model_prompts = sum(d["prompts"] for d in models_stats.values()) or 1

    for m, data in sorted(models_stats.items(), key=lambda item: item[1]["prompts"] + item[1]["steps"], reverse=True):
        clean_model_name = sanitize_plain_text(m, 80)
        p_count = data["prompts"]
        s_count = data["steps"]
        share_frac = round(p_count / max(1, total_model_prompts), 4)
        share_pct = round(share_frac * 100, 1)

        m_lower = clean_model_name.lower()
        if "claude" in m_lower:
            m_color = "#D97757"
        elif "gpt" in m_lower:
            m_color = "#10A37F"
        elif "pro" in m_lower or "high" in m_lower:
            m_color = "#A855F7"
        else:
            m_color = "#38BDF8"

        entry = {
            "name": clean_model_name,
            "prompts": p_count,
            "steps": s_count,
            "todayPrompts": data.get("todayPrompts", 0),
            "todaySteps": data.get("todaySteps", 0),
            "sessions": len(data["sessions"]),
            "shareFraction": share_frac,
            "sharePercent": share_pct,
            "color": m_color,
            "inputTokens": 0,
            "outputTokens": 0
        }
        formatted_models[clean_model_name] = entry
        model_list.append(entry)

    return tool_counter, formatted_models, model_list, latest_model


def fetch_agy_usage_quota(base_dir: Path, force: bool = False) -> dict[str, Any]:
    """Fetch real-time quota information via `agy -p /usage --output-format json` with caching."""
    cache_path = base_dir / "cache" / "quota_usage_cache.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Read from cache if fresh and not force-refreshing (TTL: 120s)
    if not force and cache_path.exists():
        try:
            mtime = cache_path.stat().st_mtime
            if time.time() - mtime < 120:
                with open(cache_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict) and "groups" in data:
                        return data
        except Exception:
            pass

    # 2. Query agy CLI directly
    agy_bin = shutil.which("agy") or str(Path.home() / ".local/bin/agy")
    try:
        res = subprocess.run(
            [agy_bin, "-p", "/usage", "--output-format", "json"],
            capture_output=True,
            text=True,
            timeout=12
        )
        if res.returncode == 0 and res.stdout.strip():
            payload = json.loads(res.stdout)
            cmd_data = payload.get("command", {}).get("data", {})
            if isinstance(cmd_data, dict) and "groups" in cmd_data and len(cmd_data["groups"]) > 0:
                try:
                    with open(cache_path, "w", encoding="utf-8") as f:
                        json.dump(cmd_data, f)
                except Exception:
                    pass
                return cmd_data
    except Exception:
        pass

    # 3. Fallback to stale cache if present
    if cache_path.exists():
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and "groups" in data:
                    return data
        except Exception:
            pass

    return {}


def format_quota_groups(raw_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Format agy /usage group and bucket metrics for QML consumption."""
    groups = raw_data.get("groups", [])
    if not groups:
        # Graceful default structure when offline / before first query
        return [
            {
                "name": "Gemini Models",
                "description": "Models within this group: Gemini Flash, Gemini Pro",
                "color": "#38BDF8",
                "buckets": [
                    {
                        "id": "gemini-weekly",
                        "name": "Weekly Limit Remaining",
                        "label": "Weekly Limit",
                        "window": "weekly",
                        "remainingFraction": 1.0,
                        "remainingPercent": 100,
                        "usedPercent": 0,
                        "resetTime": "",
                        "description": "Weekly rolling quota",
                        "color": "#38BDF8"
                    },
                    {
                        "id": "gemini-5h",
                        "name": "Five Hour Limit Remaining",
                        "label": "5-Hour Limit",
                        "window": "5h",
                        "remainingFraction": 1.0,
                        "remainingPercent": 100,
                        "usedPercent": 0,
                        "resetTime": "",
                        "description": "5-hour burst window",
                        "color": "#38BDF8"
                    }
                ]
            },
            {
                "name": "Claude and GPT models",
                "description": "Models within this group: Claude Opus, Claude Sonnet, GPT-OSS",
                "color": "#D97757",
                "buckets": [
                    {
                        "id": "3p-weekly",
                        "name": "Weekly Limit Remaining",
                        "label": "Weekly Limit",
                        "window": "weekly",
                        "remainingFraction": 1.0,
                        "remainingPercent": 100,
                        "usedPercent": 0,
                        "resetTime": "",
                        "description": "Weekly rolling quota",
                        "color": "#D97757"
                    },
                    {
                        "id": "3p-5h",
                        "name": "Five Hour Limit Remaining",
                        "label": "5-Hour Limit",
                        "window": "5h",
                        "remainingFraction": 1.0,
                        "remainingPercent": 100,
                        "usedPercent": 0,
                        "resetTime": "",
                        "description": "5-hour burst window",
                        "color": "#D97757"
                    }
                ]
            }
        ]

    formatted = []
    for g in groups:
        g_name = sanitize_plain_text(g.get("name", "Model Group"), 80)
        is_claude = "claude" in g_name.lower() or "gpt" in g_name.lower()
        g_color = "#D97757" if is_claude else "#38BDF8"

        buckets = []
        for b in g.get("buckets", []):
            b_id = sanitize_plain_text(b.get("id", ""), 50)
            b_name = sanitize_plain_text(b.get("name", "Limit"), 100)
            b_win = sanitize_plain_text(b.get("window", ""), 20)
            rem_frac = float(b.get("remaining_fraction", 1.0))
            rem_frac = min(1.0, max(0.0, rem_frac))
            rem_pct = min(100, max(0, round(rem_frac * 100)))
            used_pct = 100 - rem_pct

            label = "Weekly Limit" if "weekly" in b_win.lower() or "weekly" in b_name.lower() else "5-Hour Limit"

            buckets.append({
                "id": b_id,
                "name": b_name,
                "label": label,
                "window": b_win,
                "remainingFraction": round(rem_frac, 4),
                "remainingPercent": rem_pct,
                "usedPercent": used_pct,
                "resetTime": sanitize_plain_text(b.get("reset_time", ""), 60),
                "description": sanitize_plain_text(b.get("description", ""), 250),
                "color": g_color
            })

        formatted.append({
            "name": g_name,
            "description": sanitize_plain_text(g.get("description", ""), 250),
            "color": g_color,
            "buckets": buckets
        })
    return formatted


def scan(base_dir: Path, force: bool = False) -> dict[str, Any]:
    if not base_dir.exists():
        return empty_result()

    db_path = base_dir / "conversation_summaries.db"
    history_path = base_dir / "history.jsonl"
    presence_dir = base_dir / "presence"
    brain_dir = base_dir / "brain"

    today_date = dt.datetime.now().date()
    today_str = date_string(today_date)
    recent_dates = recent_date_strings()

    # 1. Parse Presence Locks
    active_lock_ids = parse_presence(presence_dir)

    # 2. Parse History JSONL
    daily_prompts, total_prompts_hist, recent_prompts, ws_counter = parse_history_file(history_path, recent_dates)

    # 3. Parse Transcripts for Tool Calls, Models & Model List
    tool_counter, model_usage_dict, model_list, latest_model = parse_transcripts(brain_dir, today_str)

    # 4. Fetch real quota data from agy CLI /usage
    raw_quota = fetch_agy_usage_quota(base_dir, force=force)
    quota_groups = format_quota_groups(raw_quota)

    # 5. Build Unified Session Registry
    conv_map: dict[str, dict[str, Any]] = {}

    # (a) Read history.jsonl for conversation history, workspaces, and user prompts
    if history_path.exists():
        try:
            with open(history_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        e = json.loads(line)
                        cid = sanitize_plain_text(e.get("conversationId") or "", 100)
                        if not cid:
                            continue
                        ts = e.get("timestamp") or 0
                        display = sanitize_plain_text(e.get("display") or "", 250)
                        ws = sanitize_plain_text(e.get("workspace") or "", 300)
                        if cid not in conv_map:
                            conv_map[cid] = {
                                "conversationId": cid,
                                "firstPrompt": display,
                                "lastPrompt": display,
                                "workspace": ws,
                                "timestamp": ts,
                                "stepCount": 0,
                                "agentName": "Antigravity"
                            }
                        else:
                            if display:
                                conv_map[cid]["lastPrompt"] = display
                                if not conv_map[cid].get("firstPrompt"):
                                    conv_map[cid]["firstPrompt"] = display
                            conv_map[cid]["timestamp"] = max(conv_map[cid]["timestamp"], ts)
                            if ws:
                                conv_map[cid]["workspace"] = ws
                    except Exception:
                        continue
        except Exception:
            pass

    # (b) Inspect conversations/*.db for step counts and file modification time
    conv_dir = base_dir / "conversations"
    if conv_dir.exists():
        try:
            for db_file in conv_dir.glob("*.db"):
                cid = sanitize_plain_text(db_file.stem, 100)
                if not cid:
                    continue
                mtime = db_file.stat().st_mtime
                step_count = 0
                try:
                    conn = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True, timeout=0.2)
                    cur = conn.cursor()
                    cur.execute("SELECT count(*) FROM steps")
                    row = cur.fetchone()
                    if row:
                        step_count = int(row[0] or 0)
                    conn.close()
                except Exception:
                    pass

                if cid not in conv_map:
                    conv_map[cid] = {
                        "conversationId": cid,
                        "firstPrompt": f"Session {cid[:8]}",
                        "lastPrompt": "Session",
                        "workspace": "",
                        "timestamp": int(mtime * 1000),
                        "stepCount": step_count,
                        "agentName": "Antigravity"
                    }
                else:
                    conv_map[cid]["stepCount"] = max(conv_map[cid].get("stepCount", 0), step_count)
                conv_map[cid]["mtime"] = max(conv_map[cid].get("timestamp", 0) / 1000.0, mtime)
        except Exception:
            pass

    # (c) Check legacy conversation_summaries.db if it has entries
    if db_path.exists():
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True, timeout=1)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT conversation_id, title, preview, step_count, last_modified_time,
                       workspace_uris, agent_name
                FROM conversation_summaries
            """)
            for row in cursor:
                c_id = sanitize_plain_text(row["conversation_id"], 100)
                if not c_id:
                    continue
                if c_id not in conv_map:
                    conv_map[c_id] = {
                        "conversationId": c_id,
                        "firstPrompt": sanitize_plain_text(row["title"] or f"Session {c_id[:8]}", 150),
                        "lastPrompt": sanitize_plain_text(row["preview"] or "Session", 250),
                        "workspace": sanitize_plain_text(row["workspace_uris"] or "", 300),
                        "timestamp": 0,
                        "stepCount": int(row["step_count"] or 0),
                        "agentName": sanitize_plain_text(row["agent_name"] or "Antigravity", 80)
                    }
                else:
                    if row["title"]:
                        conv_map[c_id]["firstPrompt"] = sanitize_plain_text(row["title"], 150)
                    if row["preview"]:
                        conv_map[c_id]["lastPrompt"] = sanitize_plain_text(row["preview"], 250)
                    if row["agent_name"]:
                        conv_map[c_id]["agentName"] = sanitize_plain_text(row["agent_name"], 80)
            conn.close()
        except Exception:
            pass

    # (d) Ensure active_lock_ids are included
    for cid in active_lock_ids:
        if cid not in conv_map:
            now_ts = int(dt.datetime.now().timestamp() * 1000)
            conv_map[cid] = {
                "conversationId": cid,
                "firstPrompt": f"Session {cid[:8]}",
                "lastPrompt": "Active Session",
                "workspace": "",
                "timestamp": now_ts,
                "mtime": now_ts / 1000.0,
                "stepCount": 0,
                "agentName": "Antigravity"
            }

    # Sort sessions: active sessions first, then most recent modification time
    def session_sort_key(c: dict[str, Any]) -> tuple[int, float]:
        cid = c["conversationId"]
        is_act = 1 if cid in active_lock_ids else 0
        mtime = c.get("mtime") or (c.get("timestamp", 0) / 1000.0)
        return (is_act, mtime)

    sorted_convs = sorted(conv_map.values(), key=session_sort_key, reverse=True)

    all_sessions: list[dict[str, Any]] = []
    active_sessions: list[dict[str, Any]] = []
    any_session_working = False

    for item in sorted_convs:
        cid = item["conversationId"]
        is_active = cid in active_lock_ids
        is_working = False
        if is_active:
            is_working = check_session_working(cid, base_dir)
            if is_working:
                any_session_working = True

        clean_ws = sanitize_plain_text(item.get("workspace", ""), 300)
        ws_name = Path(clean_ws).name if clean_ws else "Workspace"
        mtime_sec = item.get("mtime") or (item.get("timestamp", 0) / 1000.0)
        date_str = local_date_from_timestamp(mtime_sec)
        iso_mod = dt.datetime.fromtimestamp(mtime_sec, tz=dt.timezone.utc).isoformat() if mtime_sec else ""

        first_p = item.get("firstPrompt", "").strip()
        last_p = item.get("lastPrompt", "").strip()
        title = first_p or last_p or f"Session {cid[:8]}"
        preview = last_p or first_p or title
        if len(last_p) < 12 and len(first_p) > len(last_p):
            preview = first_p

        s_item = {
            "conversationId": cid,
            "title": sanitize_plain_text(title, 150),
            "preview": sanitize_plain_text(preview, 250),
            "stepCount": item.get("stepCount", 0),
            "lastModified": iso_mod,
            "date": date_str,
            "workspace": clean_ws,
            "workspaceName": ws_name,
            "status": "active" if is_active else "idle",
            "agentName": item.get("agentName", "Antigravity"),
            "notFullyIdle": is_working,
            "killed": False,
            "isActive": is_active
        }
        all_sessions.append(s_item)
        if is_active:
            active_sessions.append(s_item)

    has_active_session = len(active_lock_ids) > 0
    if has_active_session:
        active_status = "Working" if any_session_working else "Waiting"
    else:
        active_status = "Idle"

    # Step and Session counts from real activity
    today_steps_from_models = sum(m.get("todaySteps", 0) for m in model_list)
    total_steps_from_models = sum(m.get("steps", 0) for m in model_list)
    today_db_steps = today_steps_from_models or sum(s["stepCount"] for s in all_sessions if s["date"] == today_str)
    total_db_steps = total_steps_from_models or sum(s["stepCount"] for s in all_sessions)
    today_db_sessions = len(set(s["conversationId"] for s in all_sessions if s["date"] == today_str)) or (1 if has_active_session else 0)
    total_db_sessions = len(all_sessions)

    # 6. Build recent days breakdown
    recent_days_data = []
    weekly_prompts = 0
    for day in recent_dates:
        p_count = daily_prompts.get(day, 0)
        weekly_prompts += p_count
        recent_days_data.append({
            "date": day,
            "messageCount": p_count,
            "prompts": p_count
        })

    # 7. Convert quota groups into legacy limits array for backward compatibility
    limits = []
    for g in quota_groups:
        for b in g.get("buckets", []):
            limits.append({
                "group": b.get("id", ""),
                "groupName": g.get("name", ""),
                "title": f"{g.get('name', '')} {b.get('label', '')}",
                "icon": "",
                "color": b.get("color", "#38BDF8"),
                "used": b.get("usedPercent", 0),
                "allowance": 100,
                "percent": round(1.0 - b.get("remainingFraction", 1.0), 3),
                "resetsAt": b.get("resetTime", "")
            })

    # 8. Workspaces list (sorted by frequency)
    recent_workspaces = [
        {"path": sanitize_plain_text(ws, 300), "name": sanitize_plain_text(Path(ws).name, 100), "count": count}
        for ws, count in ws_counter.most_common(5)
    ]

    # Tools usage dict
    tools_dict = {sanitize_plain_text(k, 80): v for k, v in tool_counter.most_common(10)}

    clean_latest_model = sanitize_plain_text(latest_model, 80)

    return {
        "schemaVersion": 1,
        "id": "antigravity",
        "name": "Antigravity",
        "ready": True,
        "active": has_active_session,
        "activeStatus": active_status,
        "hasActiveSession": has_active_session,
        "hasLocalStats": True,
        "tierLabel": "Google DeepMind",
        "currentModel": clean_latest_model,
        "todayPrompts": daily_prompts.get(today_str, 0),
        "todaySessions": today_db_sessions or (1 if has_active_session else 0),
        "todaySteps": today_db_steps,
        "todayTotalTokens": 0,
        "todayTokensByModel": {},
        "recentDays": recent_days_data,
        "totalPrompts": total_prompts_hist,
        "totalSessions": total_db_sessions,
        "totalSteps": total_db_steps,
        "activeSessions": active_sessions,
        "recentSessions": all_sessions[:6],
        "toolUsage": tools_dict,
        "modelUsage": model_usage_dict,
        "modelList": model_list,
        "quotaGroups": quota_groups,
        "limits": limits,
        "recentWorkspaces": recent_workspaces,
        "updatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "usageStatusText": f"{active_status} • {clean_latest_model}",
        "authHelpText": ""
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Antigravity Usage Scanner")
    parser.add_argument("path", nargs="?", default=None, help="Path to ~/.gemini/antigravity-cli")
    parser.add_argument("--json", action="store_true", default=True, help="Emit JSON output")
    parser.add_argument("--force", action="store_true", help="Bypass cache and force refresh from agy /usage")
    args = parser.parse_args()

    base_dir = expand_path(args.path) if args.path else default_base_dir()
    result = scan(base_dir, force=args.force)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
