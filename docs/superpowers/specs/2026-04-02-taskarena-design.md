# TaskArena Design Spec

## Overview

TaskArena is a Python-based Claude Code Channel + CLI tool that bridges Feishu (Lark) task management with Claude Code. It monitors Feishu task events and user messages via WebSocket, pushes them into a Claude Code session as channel notifications, and lets Claude respond back through Feishu.

## Goals

1. Real-time task event monitoring — detect task changes in Feishu tasklists and push to Claude Code
2. Interactive bot — users can DM the Feishu bot, messages route to Claude Code, Claude responds via Feishu
3. Scheduled analysis — periodic triggers for Claude to analyze/organize tasks
4. CLI management — `uv run taskarena` for configuration, status checks, manual operations

## Non-Goals

- Replacing Feishu's native task UI
- Multi-tenant / SaaS deployment (single-org, single-user setup)
- Implementing low-level Feishu API wrappers — delegate to `lark-oapi` SDK

## Architecture

### System Diagram

```
┌─────────────────────────────────────────────────┐
│  Claude Code Session                             │
│  (loads TaskArena channel as sole MCP server)    │
│                                                  │
│  <channel source="taskarena" type="task_event">  │
│    Task X added to tasklist Y                    │
│  </channel>                                      │
│                                                  │
│  <channel source="taskarena" type="user_message" │
│    chat_id="oc_xxx" user="林懿伦">                │
│    请帮我创建一个测试任务                           │
│  </channel>                                      │
│                                                  │
│  Claude → calls reply tool → Feishu reply        │
│  Claude → calls create_task tool → create task   │
│  Claude → calls list_tasks tool → query tasks    │
└──────────────┬───────────────────────────────────┘
               │ stdio (MCP)
               ▼
┌──────────────────────────┐
│  TaskArena Channel       │
│  (Python MCP Server)     │
│  All Feishu ops via      │
│  lark-oapi Python SDK    │
│                          │
│  ┌────────────────────┐  │
│  │ Event Listener     │  │
│  │ lark-oapi SDK      │  │
│  │ WebSocket          │  │
│  │ - task events      │  │
│  │ - im messages      │  │
│  └────────────────────┘  │
│  ┌────────────────────┐  │
│  │ MCP Tools          │  │
│  │ reply, react,      │  │
│  │ create/update/     │  │
│  │ complete/list task,│  │
│  │ search_users,      │  │
│  │ get_config         │  │
│  └────────────────────┘  │
│  ┌────────────────────┐  │
│  │ Scheduler          │  │
│  │ - daily digest     │  │
│  │ - custom cron      │  │
│  └────────────────────┘  │
└──────────────────────────┘
```

### Components

#### 1. MCP Channel Server (`channel.py`)

The core MCP server that Claude Code spawns as a subprocess over stdio.

- Declares `claude/channel` capability so Claude Code registers a notification listener
- Declares `tools` capability for reply/react tools
- On startup, initializes the event listener and scheduler as async tasks
- Emits `notifications/claude/channel` when events arrive

#### 2. Event Listener (`events.py`)

Uses `lark-oapi` Python SDK (`lark_oapi.ws.Client`) to establish WebSocket long-connection to Feishu.

**Subscribed events:**
- `task.task.update_tenant_v1` — catch-all task event; disambiguate via `obj_type` field:
  - 1: task details changed (title, description, due date)
  - 2: collaborators modified
  - 3: followers modified
  - 4: reminders changed
  - 5: task completed
  - 6: task reopened
  - 7: task deleted
- `task.task.comment_updated_v1` — task comment changes
- `im.message.receive_v1` — user DMs the bot

Note: Feishu only delivers task events for tasks created by the subscribing application. Tasks created via Feishu client or other apps will not trigger events. This is a known platform limitation.

**Event processing:**
- Task events: extract task_id, event_type, obj_type, user info → format as channel notification with structured metadata
- IM messages: extract chat_id, message content, sender → format as channel notification
- Deduplication: track recent event_ids (LRU cache, 1000 entries) to avoid processing duplicates

**Access control:**
- IM messages: filter by allowlist of user open_ids (from `.taskarena/config.yaml`); drop non-allowlisted users silently
- Task events: always pass through (task events come from the app's own tasks, already scoped)

#### 3. MCP Tools (`tools.py`)

Tools exposed to Claude via MCP `tools/list` and `tools/call`:

| Tool | Parameters | Description |
|------|-----------|-------------|
| `reply` | `chat_id`, `message`, `message_id` (optional, for reply-in-thread) | Send a text/markdown message to a Feishu chat |
| `react` | `message_id`, `emoji_type` | Add emoji reaction to a message |
| `create_task` | `summary`, `description` (optional), `due` (optional), `assignees` (optional) | Create a task and add to the monitored tasklist |
| `update_task` | `task_id`, `summary` (optional), `description` (optional), `due` (optional) | Update task attributes |
| `complete_task` | `task_id` | Mark a task as complete |
| `list_tasks` | `tasklist_id` (optional, defaults to configured), `completed` (optional) | List tasks in a tasklist |
| `search_users` | `query` | Search organization members by name |
| `get_config` | — | Return current TaskArena config (monitored tasklists, schedule, etc.) |

All Feishu operations go through `lark-oapi` Python SDK. No external Node.js MCP dependency.

#### 4. Scheduler (`scheduler.py`)

Triggers periodic channel notifications to prompt Claude for analysis.

- Uses `asyncio` scheduler (no external dependency)
- Default: daily digest at a configurable time (e.g., 09:00)
- User-configurable via `.taskarena/config.yaml`:
  ```yaml
  schedules:
    - name: daily_digest
      cron: "0 9 * * *"
      prompt: "请分析 TaskArena@H2OS 清单中的任务状态，总结进展并识别风险"
    - name: weekly_review
      cron: "0 10 * * 1"
      prompt: "请对本周任务完成情况做周报总结"
  ```
- Each trigger emits a channel notification with `type="scheduled"` and the configured prompt

#### 5. Config (`config.py`)

Loads configuration from multiple sources:

- `.env` — Feishu app credentials:
  ```
  FEISHU_APP_ID=cli_xxxxx
  FEISHU_APP_SECRET=xxxxx
  ```
- `.taskarena/config.yaml` — runtime config:
  ```yaml
  tasklists:
    - id: "1aa48004-be58-4496-93c0-99bc65b78e12"
      name: "TaskArena@H2OS"
  
  access:
    allowed_users:
      - ou_832e83d21231eb56ced18ff8d8931ba8  # 林懿伦
      # ... other users
  
  schedules:
    - name: daily_digest
      cron: "0 9 * * *"
      prompt: "请分析任务清单状态"
  ```
- `.taskarena/users.json` — cached user info (name → open_id mapping)
- `.taskarena/tasklists.json` — cached tasklist info

#### 6. CLI (`__main__.py`)

Entry point: `uv run taskarena <command>`

| Command | Description |
|---------|-------------|
| `taskarena channel` | Start MCP channel server (called by Claude Code) |
| `taskarena init` | Interactive setup: configure .env, create .taskarena/, populate users/tasklists |
| `taskarena status` | Show current config, connection status, recent events |
| `taskarena users` | List/refresh organization members |
| `taskarena tasklists` | List/refresh tasklists |

### Channel Notification Format

**Task event:**
```xml
<channel source="taskarena" type="task_event" event_type="update" obj_type="5" task_id="bf6c2b30-..." assignees="林懿伦" status="completed">
  任务「测试任务」已被标记为完成（操作人：林懿伦）
</channel>
```

**User message:**
```xml
<channel source="taskarena" type="user_message" chat_id="oc_xxx" message_id="om_xxx" user="林懿伦">
  请帮我创建一个测试任务
</channel>
```

**Scheduled trigger:**
```xml
<channel source="taskarena" type="scheduled" schedule="daily_digest">
  请分析 TaskArena@H2OS 清单中的任务状态，总结进展并识别风险
</channel>
```

## Project Structure

```
naive-taskarena/
├── .env                          # FEISHU_APP_ID, FEISHU_APP_SECRET
├── .env.example                  # Template
├── .gitignore
├── .claude/
│   ├── settings.json             # Claude Code settings
│   ├── mcp.json                  # Register taskarena channel
│   └── CLAUDE.md                 # Project-specific instructions for Claude
├── .taskarena/
│   ├── config.yaml               # Tasklist IDs, schedules, access control
│   ├── users.json                # Cached org members
│   └── tasklists.json            # Cached tasklist info
├── claude.sh                     # Launch script (tmux + claude with channel)
├── pyproject.toml                # uv project: name=taskarena
├── docs/
│   └── superpowers/
│       └── specs/
│           └── 2026-04-02-taskarena-design.md
└── src/
    └── taskarena/
        ├── __init__.py
        ├── __main__.py           # CLI entry (uv run taskarena)
        ├── channel.py            # MCP channel server (stdio)
        ├── events.py             # Feishu event listener (lark-oapi WebSocket)
        ├── tools.py              # MCP tools (reply, react, task CRUD, search_users, get_config)
        ├── scheduler.py          # Cron-like scheduled notifications
        ├── config.py             # .env + .taskarena/ config loading
        └── feishu.py             # lark-oapi client wrapper (shared SDK client instance)
```

## Dependencies

**Python (pyproject.toml):**
- `lark-oapi` — Feishu/Lark Python SDK (WebSocket events, API calls)
- `mcp` — Model Context Protocol Python SDK
- `python-dotenv` — Load .env
- `pyyaml` — Parse config.yaml
- `croniter` — Parse cron expressions for scheduler

## Startup Flow

### `claude.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Load .env into environment
if [[ -f .env ]]; then
  set -a; source .env; set +a
else
  echo "ERROR: .env not found. Run 'uv run taskarena init' first." >&2
  exit 1
fi

# Session name
SESSION="taskarena"

# Reattach if session exists
if tmux has-session -t "$SESSION" 2>/dev/null; then
  exec tmux attach -t "$SESSION"
fi

# Start new tmux session with Claude Code + TaskArena channel
# Note: TaskArena loads .env via python-dotenv internally, so tmux env inheritance is not required.
# We source .env in this script only for any shell-level tooling that may need it.
tmux new-session -d -s "$SESSION" \
  "cd $SCRIPT_DIR && claude --dangerously-load-development-channels server:taskarena"
exec tmux attach -t "$SESSION"
```

### `.claude/mcp.json`

TaskArena is the sole MCP server. It loads credentials from `.env` via `python-dotenv` at startup.

```json
{
  "mcpServers": {
    "taskarena": {
      "command": "uv",
      "args": ["run", "taskarena", "channel"]
    }
  }
}
### Internal Startup Sequence

1. Claude Code starts, spawns `uv run taskarena channel` as MCP subprocess
2. `channel.py` initializes MCP server over stdio
3. `config.py` loads `.env` (credentials) + `.taskarena/config.yaml` (runtime config)
4. `events.py` establishes WebSocket connection to Feishu using `lark-oapi`
5. `scheduler.py` starts async scheduler for periodic triggers
6. System is ready — events flow in, Claude processes, replies flow out

## Error Handling

- **WebSocket disconnect**: `lark-oapi` SDK handles auto-reconnect. If connection fails for >5 minutes, emit a channel notification to alert Claude/user. Feishu does not replay missed events during disconnection — this is a known gap.
- **Invalid events**: Log to stderr and skip; never crash the channel
- **MCP communication errors**: Log to stderr (stdout is reserved for MCP JSON-RPC)
- **Missing config**: `taskarena init` guides user through setup; `taskarena channel` exits with clear error if `.env` is missing
- **Rate limiting**: Feishu APIs have rate limits (~50-100 req/min per app). `lark-oapi` SDK retries on 429 automatically. Tools should not add additional retry logic.

## Graceful Shutdown

When Claude Code terminates the MCP subprocess (user closes session, Ctrl+C):
1. Close the WebSocket connection cleanly
2. Cancel pending scheduled tasks
3. Flush any pending logs
4. Exit with code 0

## Logging

- All logs go to stderr (stdout reserved for MCP JSON-RPC)
- Default log level: INFO
- Configurable via `TASKARENA_LOG_LEVEL` environment variable (DEBUG, INFO, WARNING, ERROR)
- Format: `[taskarena] {level} {timestamp} {message}`

## Security

- `.env` is gitignored (contains app_secret)
- Access control allowlist for inbound IM messages (prevent unauthorized users from triggering Claude)
- Task events are not filtered by allowlist (they are scoped to the app's own tasks)
- All SDK logs go to stderr to avoid corrupting MCP stdio protocol

## Scheduler Timezone

Cron expressions in `config.yaml` use the system's local timezone by default. Override with a `timezone` field:
```yaml
schedules:
  - name: daily_digest
    cron: "0 9 * * *"
    timezone: "Asia/Shanghai"
    prompt: "请分析任务清单状态"
```

## Cache Strategy

- `users.json` and `tasklists.json` are populated by `taskarena init` and refreshed by `taskarena users` / `taskarena tasklists`
- During channel runtime, caches are read-only (no automatic refresh)
- If a message arrives from an unknown user (not in cache), the event still passes through with the raw `open_id`; the human-readable name will show as the ID
- No TTL — caches are explicitly refreshed via CLI commands
