# Antigravity Usage for Omarchy

Antigravity active session monitor, prompt metrics, tool telemetry, and 7-day usage stats in the Omarchy top bar.

![preview](preview.png)

## Features

- **Live Status & Pulse**: Visual status indicator (pulsing green/blue dot) in the Omarchy bar showing when an Antigravity agent is active, working, or idle.
- **Today & Totals with Live Quota & Model Breakdown**:
  - Top summary cards: Prompts today, steps today, and all-time totals.
  - **Live Quota Limits Bar Graphs**: Real-time quota buckets fetched directly from `agy /usage` (Gemini Models weekly/5h limits, Claude & GPT models weekly/5h limits) with dynamic countdown reset timers, remaining percentage, and health-based color transitions.
  - **Model Usage Breakdown Bar Graphs**: Visual volume and activity share bars for all active models (Gemini Flash/Pro, Claude Sonnet/Opus, etc.) with prompt and step counters.
- **7-Day Activity Chart**: Visual bar chart of prompt volume over the last 7 days with date headers.
- **Tool Telemetry Breakdown**: Live counter of tool calls (`run_command`, `write_to_file`, `replace_file_content`, `view_file`, `grep_search`, `find_by_name`, `subagents`, etc.).
- **Active & Recent Sessions**: Preview of current tasks, workspace names, step progress, and session status.
- **Fast Smart Caching**: Sub-second responsiveness using an intelligent cache for `agy /usage` with on-demand `--force` refresh.
- **Dual Omarchy Integration**:
  1. Standalone Bar Widget with rich QML popup modal (`jesseburlamaque.antigravity-usage`).
  2. Native Omarchy Agents panel collector (`bin/omarchy-agent-usage-antigravity`).

## Requirements

- Python 3 (standard library: `sqlite3`, `json`, `datetime`, `pathlib`, `collections`, `subprocess`, `shutil`)
- Google Antigravity (`agy` CLI / IDE) with local session data in `~/.gemini/antigravity-cli`
- Omarchy Shell / Quickshell

## Installation

```sh
omarchy plugin add https://github.com/BoeyCorp/antigravity-usage.git --enable
omarchy restart shell
```

### (Optional) Native `omarchy.agents` Panel Integration

To also include Antigravity as a tab inside Omarchy's built-in Agents panel:

```sh
mkdir -p ~/.local/bin
ln -sf ~/.config/omarchy/plugins/jesseburlamaque.antigravity-usage/bin/omarchy-agent-usage-antigravity ~/.local/bin/omarchy-agent-usage-antigravity
```

## Update

```sh
omarchy plugin update jesseburlamaque.antigravity-usage --yes
omarchy restart shell
```

## Removal

To remove the plugin from Omarchy:

```sh
omarchy plugin remove jesseburlamaque.antigravity-usage
omarchy restart shell
```

If you configured the optional Agents panel integration:

```sh
rm -f ~/.local/bin/omarchy-agent-usage-antigravity
```

## Interactions

- **Left Click**: Open/close popup panel with stats, charts, and recent sessions.
- **Middle Click**: Force immediate refresh of telemetry and quota data.
- **Right Click**: Open in-popup settings view.
- **Keyboard Shortcuts** (when popup is open):
  - `1`–`5`: Quick-resume the corresponding recent session directly in your terminal.
  - `n`: Start a brand-new `agy` session in your terminal.
  - `r`: Force refresh live quota and usage data.
  - `s`: Toggle between Stats and Settings view.
  - `q` or `Esc`: Close popup.
- **Session Management**:
  - **Quick Resume**: Click any session card or press its `[1]`–`[5]` numeric shortcut to open it in terminal (`agy --conversation <id>`).
  - **Kill Active Process**: Hover over an active session and click the red `` button to terminate the session process cleanly (`SIGTERM`).
  - **Expand / Collapse**: Click "Show all sessions" to view up to 10 recent sessions with workspace pill tags.

## Features

- **Status Bar Icon & Live Badge**: Color-coded pulse dot indicating session status (green = active/working, blue = waiting for input) and optional prompt counter badge.
- **Adaptive Polling**: Auto-scales refresh frequency from 60s idle down to 3s when an active session is working, then returns to 60s when idle.
- **Exact Reset Times**: Displays both relative countdowns (e.g. `2h 15m`) and exact local wall-clock reset times (e.g. `04:15 AM`).
- **Desktop Quota Alerts**: Proactive desktop notification alerts when any quota bucket drops below 15% remaining (with intelligent 2-hour per-bucket rate-limiting).
- **System-Wide Agent Usage Integration**: Fully compatible with Omarchy's `omarchy-agent-usage-antigravity` provider contract (`--limits-only`).

## Configuration

Configuration lives in `~/.config/omarchy/shell.json`.

| Key | Type | Default | Description |
|---|---|---|---|
| `refreshIntervalSec` | integer (10–1800) | `60` | Telemetry refresh rate in seconds (adaptive to 3s while active) |
| `showBadge` | boolean | `true` | Show prompt count badge in the bar widget |

## License

MIT © BoeyCorp (Forked and enhanced from original by Jesse Burlamaque)
