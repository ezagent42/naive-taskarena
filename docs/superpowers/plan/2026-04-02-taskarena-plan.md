# TaskArena Implementation Plan

Based on [TaskArena Design Spec](./2026-04-02-taskarena-design.md).

## Phase 1: Project Scaffolding

### Step 1.1: Initialize Python project with uv

- `uv init --name taskarena --package` in the repo root
- Configure `pyproject.toml`:
  - `name = "taskarena"`
  - `python-requires = ">=3.11"`
  - `dependencies`: `lark-oapi>=1.3.0` (minimum for `lark_oapi.ws.Client`), `mcp`, `python-dotenv`, `pyyaml`, `croniter`
  - `[tool.pytest.ini_options]`: `testpaths = ["tests"]`
  - dev dependencies: `pytest`, `pytest-asyncio`
  - `[project.scripts]`: `taskarena = "taskarena.__main__:main"`
- `uv sync` to create lockfile and venv

**Verify:** `uv run taskarena --help` prints usage (stub is fine at this stage).

### Step 1.2: Create project structure and configuration files

Create directories and files:
```
.claude/settings.json
.claude/mcp.json
.claude/CLAUDE.md
.taskarena/config.yaml
.env.example
.gitignore
claude.sh
src/taskarena/__init__.py
src/taskarena/__main__.py
src/taskarena/channel.py
src/taskarena/events.py
src/taskarena/tools.py
src/taskarena/scheduler.py
src/taskarena/config.py
src/taskarena/feishu.py
tests/__init__.py
tests/test_config.py
```

Populate:
- `.env.example`: template with `FEISHU_APP_ID=` and `FEISHU_APP_SECRET=`
- `.gitignore`: `.env`, `.venv/`, `__pycache__/`, `.taskarena/users.json`, `.taskarena/tasklists.json`
- `.claude/mcp.json`: register `taskarena` channel server (see spec for exact JSON)
- `.claude/CLAUDE.md`: project instructions for Claude Code sessions, including:
  - What TaskArena is (Feishu task management bridge)
  - Available MCP tools and when to use each
  - How to respond to channel notifications (task events, user messages, scheduled prompts)
  - Access control: only respond to allowlisted users
  - Reply format: use `reply` tool for Feishu responses, not terminal output
- `.claude/settings.json`: `{"permissions": {"allow": ["mcp__taskarena__*"]}}`
- `claude.sh`: launch script from spec verbatim (make executable with `chmod +x`)
- `.taskarena/config.yaml`: example config with placeholder tasklist ID

**Verify:** `test -x claude.sh` passes. All 18+ files present in `git status`.

### Step 1.3: Symlink lark-skills into .claude/

These skills provide Claude Code (the operator) with Feishu API knowledge during development and interactive sessions. They are NOT runtime dependencies of TaskArena itself.

```bash
mkdir -p .claude/skills && cd .claude/skills && ln -s ~/.agents/skills/lark-* .
```

**Verify:** `.claude/skills/lark-task/SKILL.md` exists and is readable.

### Step 1.4: Set up logging infrastructure

Create a `src/taskarena/log.py` module:
- Configure `logging.basicConfig` with stderr handler
- Format: `[taskarena] {level} {timestamp} {message}`
- Level from `TASKARENA_LOG_LEVEL` env var (default: INFO)
- Redirect `lark-oapi` SDK logger to stderr at WARNING level
- Expose a `get_logger(name)` helper for all modules

**Verify:** `from taskarena.log import get_logger; log = get_logger("test"); log.info("ok")` prints to stderr.

## Phase 2: Config & Feishu Client

### Step 2.1: Implement `config.py`

- Load `.env` via `python-dotenv` (auto-find from cwd upward)
- Load `.taskarena/config.yaml` via `pyyaml`
- Load `users.json` and `tasklists.json` caches
- Expose a `Config` dataclass with:
  - `app_id: str`
  - `app_secret: str`
  - `tasklists: list[dict]`
  - `allowed_users: list[str]`
  - `schedules: list[dict]`
  - `users: dict[str, str]` (open_id → name)
  - `log_level: str` (from `TASKARENA_LOG_LEVEL` env var, default INFO)
- Validate required fields; raise clear errors if missing

**Verify:** Unit test — create temp `.env` + `config.yaml`, load Config, assert fields populated.

### Step 2.2: Implement `feishu.py`

- Create a shared `lark_oapi.Client` instance from Config credentials
- Expose helper functions:
  - `send_message(chat_id, content, msg_type="text")` → calls IM send API
  - `send_reply(message_id, content, msg_type="text")` → calls IM reply API
  - `react_message(message_id, emoji_type)` → calls reactions API
  - `create_task(summary, description, due, assignees, tasklist_id)` → calls task create + add to tasklist
  - `update_task(task_id, **fields)` → calls task patch API
  - `complete_task(task_id)` → calls task patch with status=done
  - `list_tasks(tasklist_id, completed)` → calls tasklist tasks list API
  - `search_users(query)` → calls contact search API
- All functions are async, return typed dicts
- Handle lark-oapi error responses; raise descriptive exceptions

**Verify:** Manual test with real `.env` — call `send_message` to yourself, verify receipt in Feishu.

## Phase 3: MCP Channel Server

### Step 3.1: Implement `channel.py` — MCP server skeleton

- Use `mcp` Python SDK to create an MCP server
- Declare capabilities: `claude/channel` (via experimental/vendor-specific capabilities dict — verify exact API in `mcp` SDK docs), `tools`
- Connect over stdio transport
- On startup, initialize event listener and scheduler as async tasks
- Expose a `emit_notification(content, meta)` function that calls `server.notification()` with `notifications/claude/channel`
- Register signal handlers (SIGTERM, SIGINT) for graceful shutdown:
  1. Close WebSocket connection cleanly
  2. Cancel pending scheduled tasks
  3. Flush logs
  4. Exit with code 0

**Note:** The `lark-oapi` WebSocket client uses threading internally. Events from the WS thread must be bridged to the asyncio event loop via `loop.call_soon_threadsafe()` or `asyncio.Queue`.

**Verify:** Start `uv run taskarena channel` and connect with a minimal MCP client script (subprocess + stdin/stdout JSON-RPC). Verify `initialize` handshake succeeds and capabilities include `claude/channel`.

### Step 3.2: Implement `tools.py` — MCP tool definitions

Register tools with the MCP server:

| Tool | Implementation |
|------|---------------|
| `reply` | Calls `feishu.send_message()` or `feishu.send_reply()` depending on whether `message_id` is provided |
| `react` | Calls `feishu.react_message()` |
| `create_task` | Calls `feishu.create_task()` with default tasklist from config |
| `update_task` | Calls `feishu.update_task()` |
| `complete_task` | Calls `feishu.complete_task()` |
| `list_tasks` | Calls `feishu.list_tasks()` |
| `search_users` | Calls `feishu.search_users()` |
| `get_config` | Returns sanitized config (no secrets) |

Each tool:
- Has a JSON Schema for parameters (via MCP tool registration)
- Returns structured JSON result
- Catches exceptions and returns error messages (not stack traces)
- Do NOT add retry logic for Feishu API rate limits — `lark-oapi` SDK handles 429 retries automatically

**Verify:** Load channel in Claude Code, verify `tools/list` returns all 8 tools. Call `get_config` and verify response.

## Phase 4: Event Listener

### Step 4.1: Implement `events.py` — WebSocket event listener

- Use `lark_oapi.ws.Client` to connect via WebSocket
- Register event handlers:
  - `task.task.update_tenant_v1` → parse `obj_type`, extract task details, call `emit_notification`
  - `task.task.comment_updated_v1` → extract comment info, call `emit_notification`
  - `im.message.receive_v1` → check allowlist, extract message content/sender, call `emit_notification`
- Deduplication: maintain an LRU dict of recent `event_id`s (max 1000)
- For task events, enrich notification with structured metadata (task_id, obj_type, status, assignees)
- For IM messages, resolve sender open_id to name using users cache
- Log all events at DEBUG level

**Verify:** 
1. Start channel, create a task in Feishu → verify channel notification appears in Claude session
2. Send a DM to the bot → verify channel notification appears with correct user name and content

### Step 4.2: Connection health monitoring

- Track last successful event timestamp
- If no events received for >5 minutes AND WebSocket reports disconnected, emit a health warning notification:
  ```xml
  <channel source="taskarena" type="health" status="degraded">
    WebSocket disconnected for 5+ minutes. Events may be missed.
  </channel>
  ```
- Log reconnection attempts at WARNING level

**Verify:** Kill network briefly, verify warning notification emits after timeout.

## Phase 5: Scheduler

### Step 5.1: Implement `scheduler.py`

- Parse cron expressions from config using `croniter`
- Use `asyncio.sleep` loop to check for due schedules every 30 seconds (note: schedules may fire up to 30s late; acceptable for daily/weekly triggers)
- When a schedule fires, emit channel notification:
  ```xml
  <channel source="taskarena" type="scheduled" schedule="daily_digest">
    {configured prompt text}
  </channel>
  ```
- Support `timezone` field per schedule (default: system local via `zoneinfo`)
- Track last fire time per schedule to avoid double-firing on restart

**Verify:** Set a schedule 1 minute from now, verify notification fires in Claude session.

## Phase 6: CLI

### Step 6.1: Implement `__main__.py` — CLI entry point

Use `argparse` (no external dep) with subcommands:

- `taskarena channel` — Start MCP channel server (call `channel.main()`)
- `taskarena init` — Interactive setup:
  1. Prompt for `FEISHU_APP_ID` and `FEISHU_APP_SECRET`, write to `.env`
  2. Create `.taskarena/` directory
  3. Fetch org members via SDK, write to `users.json`
  4. Fetch tasklists via SDK, write to `tasklists.json`
  5. Generate default `config.yaml` with all users in allowlist and first tasklist
- `taskarena status` — Print current config, check WebSocket connectivity, show cache stats
- `taskarena users` — Fetch and display org members, update `users.json`
- `taskarena tasklists` — Fetch and display tasklists, update `tasklists.json`

**Verify:** Run `uv run taskarena init` with real credentials, verify `.env` and `.taskarena/` populated correctly. Run `uv run taskarena status` and verify output.

## Phase 7: Integration Testing

### Step 7.1: End-to-end test

1. Run `uv run taskarena init` to set up the project
2. Run `./claude.sh` to start Claude Code with TaskArena channel
3. Test task event flow:
   - Create a task in Feishu → verify Claude receives notification
   - Ask Claude to create a task via `create_task` tool → verify task appears in Feishu
4. Test IM flow:
   - DM the bot: "请帮我创建一个测试任务" → verify Claude receives, processes, and replies
5. Test scheduled flow:
   - Set a schedule 1 minute out, verify Claude receives prompt and acts on it

### Step 7.2: Edge cases

- Send DM from non-allowlisted user → verify silently dropped
- Disconnect network briefly → verify health warning and auto-reconnect
- Malformed event payload → verify logged and skipped
- Call `reply` tool with invalid chat_id → verify error message returned to Claude

## Implementation Order Summary

| Phase | Steps | Dependencies |
|-------|-------|-------------|
| 1. Scaffolding | 1.1, 1.2, 1.3, 1.4 | None |
| 2. Config & Client | 2.1, 2.2 | Phase 1 |
| 3. MCP Channel | 3.1, 3.2 | Phase 2 |
| 4. Events | 4.1, 4.2 | Phase 3 |
| 5. Scheduler | 5.1 | Phase 3 |
| 6. CLI | 6.1 | Phase 2 |
| 7. Integration | 7.1, 7.2 | All above |

Phases 4, 5, 6 can be worked on in parallel after Phase 3 is complete. They have no cross-dependencies and can be assigned to independent agents if using parallel execution.
