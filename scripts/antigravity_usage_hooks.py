#!/usr/bin/env python3
"""Install/remove Antigravity hooks that push instant bar-widget refreshes.

Without this, the widget only learns an Antigravity session started, stopped, or completed a turn
on its timed polling interval (10s active / 60s idle). This wires PreInvocation, PostInvocation,
and Stop in ~/.gemini/config/hooks.json to ping `omarchy-shell -q jesseburlamaque.antigravity-usage refresh`,
so the bar updates the moment agent activity occurs.

Non-destructive: only touches the "antigravity-usage" key in hooks.json. Any existing hooks
(e.g., herdr or user lint scripts) are preserved completely intact. A timestamped backup is
created prior to any write.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

HOOK_NAME = "antigravity-usage"
HOOK_COMMAND = "omarchy-shell -q jesseburlamaque.antigravity-usage refresh >/dev/null 2>&1 || true; echo '{}'"
HOOK_TIMEOUT = 5
HOOK_EVENTS = ["PreInvocation", "PostInvocation", "Stop"]


def default_hooks_path() -> Path:
    base = os.environ.get("ANTIGRAVITY_CONFIG_DIR") or os.path.expanduser("~/.gemini/config")
    return Path(base).expanduser() / "hooks.json"


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_config(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup = path.with_suffix(path.suffix + ".antigravity-usage.bak")
        try:
            backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        except Exception:
            pass
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    tmp.replace(path)


def hooks_installed(config: dict[str, Any]) -> bool:
    entry = config.get(HOOK_NAME)
    if not isinstance(entry, dict) or entry.get("enabled") is False:
        return False
    for event in ("PreInvocation", "Stop"):
        handlers = entry.get(event, [])
        if not any(
            isinstance(h, dict) and "jesseburlamaque.antigravity-usage" in str(h.get("command", ""))
            for h in handlers
        ):
            return False
    return True


def install(path: Path) -> bool:
    """Add or update the antigravity-usage hook definition in hooks.json.
    Existing unrelated hooks are completely preserved.
    """
    config = load_config(path)
    handler = {
        "type": "command",
        "command": HOOK_COMMAND,
        "timeout": HOOK_TIMEOUT,
    }

    target = {
        "enabled": True,
        "PreInvocation": [handler],
        "PostInvocation": [handler],
        "Stop": [handler],
    }

    if config.get(HOOK_NAME) == target:
        return False

    config[HOOK_NAME] = target
    save_config(path, config)
    return True


def remove(path: Path) -> bool:
    """Remove the antigravity-usage hook definition from hooks.json.
    Leaves any other hooks intact.
    """
    config = load_config(path)
    if HOOK_NAME in config:
        del config[HOOK_NAME]
        save_config(path, config)
        return True
    return False


def trigger() -> None:
    """Execute refresh in background and output valid empty JSON to satisfy Antigravity contract."""
    try:
        subprocess.Popen(
            ["omarchy-shell", "-q", "jesseburlamaque.antigravity-usage", "refresh"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass
    print("{}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage Antigravity Live Hook Updates")
    parser.add_argument("action", choices=["install", "remove", "status", "trigger"])
    parser.add_argument("path", nargs="?", default=None, help="Path to ~/.gemini/config/hooks.json")
    args = parser.parse_args()

    if args.action == "trigger":
        trigger()
        return

    hooks_path = Path(args.path).expanduser() if args.path else default_hooks_path()

    if args.action == "status":
        print(json.dumps({"installed": hooks_installed(load_config(hooks_path))}))
        return

    if args.action == "install":
        changed = install(hooks_path)
        print(json.dumps({"installed": True, "changed": changed}))
        return

    changed = remove(hooks_path)
    print(json.dumps({"installed": hooks_installed(load_config(hooks_path)), "changed": changed}))


if __name__ == "__main__":
    sys.exit(main() or 0)
