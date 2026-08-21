#!/usr/bin/env python3
"""Query Antigravity CLI/IDE state, sqlite database, history, and transcripts to emit usage stats."""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import re
import sqlite3
import sys
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
    active_ids = set()
    if not presence_dir.exists():
        return active_ids

    try:
        for p in presence_dir.glob("*.lock"):
            conv_id = sanitize_plain_text(p.stem, 100)
            if conv_id:
                active_ids.add(conv_id)
    except Exception:
        pass
    return active_ids


def parse_transcripts(brain_dir: Path) -> tuple[Counter, dict[str, dict[str, Any]], str]:
    tool_counter: Counter = Counter()
    models_stats: dict[str, dict[str, Any]] = {}
    latest_model = "Gemini 3.7 Flash"

    if not brain_dir.exists():
        return tool_counter, models_stats, latest_model

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
                                "sessions": set()
                            }

                        models_stats[current_model]["steps"] += 1
                        if step.get("type") == "USER_INPUT":
                            models_stats[current_model]["prompts"] += 1
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
    for m, data in sorted(models_stats.items(), key=lambda item: item[1]["prompts"] + item[1]["steps"], reverse=True):
        clean_model_name = sanitize_plain_text(m, 80)
        formatted_models[clean_model_name] = {
            "name": clean_model_name,
            "prompts": data["prompts"],
            "steps": data["steps"],
            "sessions": len(data["sessions"]),
            "inputTokens": 0,
            "outputTokens": 0
        }

    return tool_counter, formatted_models, latest_model


def scan(base_dir: Path) -> dict[str, Any]:
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

    # 3. Parse Transcripts for Tool Calls & Models
    tool_counter, model_usage_dict, latest_model = parse_transcripts(brain_dir)

    # 4. Query SQLite DB for Sessions
    all_sessions: list[dict[str, Any]] = []
    active_sessions: list[dict[str, Any]] = []
    total_db_sessions = 0
    total_db_steps = 0
    today_db_steps = 0
    today_db_sessions = 0
    has_active_session = False
    active_status = "Idle"

    if db_path.exists():
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True, timeout=5)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT conversation_id, title, preview, step_count, last_modified_time,
                       workspace_uris, status, agent_name, parent_conversation_id,
                       nesting_depth, not_fully_idle, killed, last_user_input_time
                FROM conversation_summaries
                ORDER BY last_modified_time DESC
            """)

            for row in cursor:
                total_db_sessions += 1
                c_id = row["conversation_id"]
                step_count = int(row["step_count"] or 0)
                total_db_steps += step_count
                last_mod = row["last_modified_time"] or ""
                mod_day = local_date_from_timestamp(last_mod)

                if mod_day == today_str:
                    today_db_steps += step_count
                    today_db_sessions += 1

                is_active = (c_id in active_lock_ids) or bool(row["not_fully_idle"])
                if is_active:
                    has_active_session = True
                    if bool(row["not_fully_idle"]):
                        active_status = "Working"
                    elif active_status != "Working":
                        active_status = "Waiting"

                ws_raw = row["workspace_uris"] or ""
                workspace = ""
                try:
                    if ws_raw.startswith("["):
                        ws_list = json.loads(ws_raw)
                        workspace = ws_list[0] if ws_list else ""
                    else:
                        workspace = ws_raw
                except Exception:
                    workspace = ws_raw

                clean_cid = sanitize_plain_text(c_id, 100)
                clean_title = sanitize_plain_text(row["title"] or (f"Session {clean_cid[:8]}" if clean_cid else "Session"), 150)
                clean_preview = sanitize_plain_text(row["preview"] or "", 250)
                clean_ws = sanitize_plain_text(workspace, 300)
                clean_ws_name = sanitize_plain_text(Path(workspace).name if workspace else "", 100)
                clean_status = sanitize_plain_text("active" if is_active else (row["status"] or "idle"), 40)
                clean_agent_name = sanitize_plain_text(row["agent_name"] or "Antigravity", 80)

                session_item = {
                    "conversationId": clean_cid,
                    "title": clean_title,
                    "preview": clean_preview,
                    "stepCount": step_count,
                    "lastModified": last_mod,
                    "date": mod_day,
                    "workspace": clean_ws,
                    "workspaceName": clean_ws_name,
                    "status": clean_status,
                    "agentName": clean_agent_name,
                    "notFullyIdle": bool(row["not_fully_idle"]),
                    "killed": bool(row["killed"]),
                    "isActive": is_active
                }

                all_sessions.append(session_item)
                if is_active:
                    active_sessions.append(session_item)

            conn.close()
        except Exception:
            pass

    if len(active_lock_ids) > 0:
        has_active_session = True
        if active_status == "Idle":
            active_status = "Waiting"

    # 5. Build recent days breakdown
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

    # 6. Calculate Limits and Reset Windows by Model Group
    now_utc = dt.datetime.now(dt.timezone.utc)
    
    # Reset timestamps
    next_midnight_utc = (now_utc + dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    daily_reset_iso = next_midnight_utc.isoformat()
    session_5h_iso = (now_utc + dt.timedelta(hours=5)).isoformat()

    # Aggregate prompts per model group
    group_prompts = {"flash": 0, "thinking": 0, "claude": 0}
    for m_name, m_data in model_usage_dict.items():
        m_lower = m_name.lower()
        p_cnt = int(m_data.get("prompts", 0))
        if "claude" in m_lower:
            group_prompts["claude"] += p_cnt
        elif "high" in m_lower or "thinking" in m_lower or "pro" in m_lower:
            group_prompts["thinking"] += p_cnt
        else:
            group_prompts["flash"] += p_cnt

    flash_allowance = 200
    thinking_allowance = 100
    claude_allowance = 50

    limits = [
        {
            "group": "flash",
            "groupName": "Gemini Flash Series",
            "title": "Flash Models Quota",
            "icon": "",
            "color": "#38BDF8",
            "used": group_prompts["flash"],
            "allowance": flash_allowance,
            "percent": min(1.0, round(group_prompts["flash"] / max(1, flash_allowance), 3)),
            "resetsAt": daily_reset_iso
        },
        {
            "group": "thinking",
            "groupName": "Gemini Thinking Series",
            "title": "Thinking Models Quota",
            "icon": "",
            "color": "#A855F7",
            "used": group_prompts["thinking"],
            "allowance": thinking_allowance,
            "percent": min(1.0, round(group_prompts["thinking"] / max(1, thinking_allowance), 3)),
            "resetsAt": daily_reset_iso
        },
        {
            "group": "claude",
            "groupName": "Claude Series",
            "title": "Claude 5h Session Window",
            "icon": "",
            "color": "#D97757",
            "used": group_prompts["claude"],
            "allowance": claude_allowance,
            "percent": min(1.0, round(group_prompts["claude"] / max(1, claude_allowance), 3)),
            "resetsAt": session_5h_iso
        }
    ]

    # 7. Workspaces list (sorted by frequency)
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
    args = parser.parse_args()

    base_dir = expand_path(args.path) if args.path else default_base_dir()
    result = scan(base_dir)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
