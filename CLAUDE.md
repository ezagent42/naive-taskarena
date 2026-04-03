# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Does

TaskArena is a Python MCP server that bridges Feishu (Lark) task management with Claude Code. It runs as a background channel process that forwards Feishu task events and user messages to Claude Code as channel notifications, and exposes MCP tools so Claude can respond back through Feishu APIs.

The typical runtime is via `./claude.sh`, which launches a tmux session running both Claude Code and `taskarena channel` (the MCP server) together.

## Commands

```bash
# Install dependencies
uv sync

# Run all tests
uv run pytest tests/

# Run a single test file
uv run pytest tests/test_config.py

# Start the MCP server (connects to Claude Code via stdio)
uv run taskarena channel

# CLI management commands
uv run taskarena init              # Interactive setup: writes .env and .taskarena/
uv run taskarena status            # Print loaded config
uv run taskarena users [--query TEXT]
uv run taskarena tasklists [--refresh]
```

## Architecture

```
Feishu WebSocket ──► events.py ──► channel.py (MCP server) ──► Claude Code
                                        │
                        scheduler.py ──►│  (cron triggers)
                                        │
Claude Code ──► tools.py ──► feishu.py ──► Feishu REST APIs
```

**Key modules:**

- `channel.py` — MCP server using `mcp.server.lowlevel.Server`. Registers tools, starts background tasks (event listener + scheduler), emits `notifications/claude/channel` JSON-RPC notifications to Claude Code.
- `events.py` — Long-lived WebSocket client (`lark_oapi.ws.Client`) that handles task updates, task comments, and IM messages. Bridges the WebSocket thread to asyncio via `loop.call_soon_threadsafe()`. Deduplicates events with an LRU dict (1000 entries). Drops IM messages from non-allowlisted users.
- `scheduler.py` — 30-second polling loop using `croniter`. Reads `config.schedules` from config and fires channel notifications when a cron expression triggers.
- `tools.py` — Defines 8 MCP tools with JSON Schema validation and dispatches to `feishu.py`.
- `feishu.py` — Async wrappers around `lark-oapi` SDK for messaging and task operations. `search_users()` searches the local cache (not a remote API — the SDK doesn't expose that endpoint).
- `config.py` — Loads credentials from `.env`, then `.taskarena/config.yaml` (tasklists, allowed_users, schedules), then `.taskarena/users.json` (open_id → name cache).
- `channel_format.py` — Formats channel notification payloads as XML.

## Configuration

Runtime config lives outside the repo:
- `.env` — `FEISHU_APP_ID`, `FEISHU_APP_SECRET`, `TASKARENA_LOG_LEVEL`
- `.taskarena/config.yaml` — tasklists (id + name), allowed_users (open_ids), schedules (name, cron, prompt, timezone)
- `.taskarena/users.json` — cached user directory (populated by `taskarena users --refresh` or manually)

## MCP Channel Protocol

`channel.py` uses an experimental `claude/channel` capability. Notifications are sent as raw `JSONRPCNotification` with method `notifications/claude/channel` — this is not a standard MCP notification type. The `.claude/CLAUDE.md` file contains the bot's runtime instructions (how Claude should behave when running as the TaskArena bot).
