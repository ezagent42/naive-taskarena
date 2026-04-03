# TaskArena Handoff Notes

Date: 2026-04-03

## Context

TaskArena is a Python `uv` project that bridges Feishu (Lark) task management with a Claude/Codex-style MCP channel server.

Primary project references:

- `/Users/daiming/workspace/naive-taskarena/docs/superpowers/specs/2026-04-02-taskarena-design.md`
- `/Users/daiming/workspace/naive-taskarena/docs/superpowers/plan/2026-04-02-taskarena-plan.md`
- `/Users/daiming/workspace/naive-taskarena/AGENTS.md`
- `/Users/daiming/workspace/naive-taskarena/.claude/CLAUDE.md`

## What Was Fixed

### 1. `feishu.py` ImportError resolved

Original blocker:

- `from lark_oapi.api.contact.v3 import SearchUserRequest` failed.

What was confirmed from local SDK source under `.venv`:

- `lark_oapi.api.contact.v3` does **not** export `SearchUserRequest`
- `contact.v3.user` exposes real methods like:
  - `alist(...)`
  - `afind_by_department(...)`
  - `aget(...)`
- There is no `asearch(...)` on `client.contact.v3.user`

Relevant SDK files inspected:

- `.venv/lib/python3.14/site-packages/lark_oapi/api/contact/v3/resource/user.py`
- `.venv/lib/python3.14/site-packages/lark_oapi/api/contact/v3/model/list_user_request.py`
- `.venv/lib/python3.14/site-packages/lark_oapi/api/contact/v3/model/find_by_department_user_request.py`
- `.venv/lib/python3.14/site-packages/lark_oapi/api/contact/v3/model/__init__.py`

Resolution applied:

- Removed the invalid `SearchUserRequest` import from `src/taskarena/feishu.py`
- Reimplemented `search_users(query)` to search against the local `Config.load().users` cache instead of calling a nonexistent SDK API
- Added `list_tasklists()` using real SDK classes:
  - `ListTasklistRequest`
  - `client.task.v2.tasklist.alist(...)`

## Files Added / Updated

### Updated

- `/Users/daiming/workspace/naive-taskarena/src/taskarena/feishu.py`
- `/Users/daiming/workspace/naive-taskarena/src/taskarena/__main__.py`
- `/Users/daiming/workspace/naive-taskarena/src/taskarena/scheduler.py`
- `/Users/daiming/workspace/naive-taskarena/tests/test_feishu.py`

### Added

- `/Users/daiming/workspace/naive-taskarena/src/taskarena/tools.py`
- `/Users/daiming/workspace/naive-taskarena/src/taskarena/channel.py`
- `/Users/daiming/workspace/naive-taskarena/src/taskarena/events.py`
- `/Users/daiming/workspace/naive-taskarena/src/taskarena/channel_format.py`
- `/Users/daiming/workspace/naive-taskarena/docs/superpowers/specs/2026-04-03-taskarena-handoff.md`

## Current Implementation State

### `src/taskarena/feishu.py`

Implemented / present:

- shared `lark_oapi.Client`
- `send_message`
- `send_reply`
- `react_message`
- `create_task`
- `update_task`
- `complete_task`
- `list_tasks`
- `search_users` using local cache
- `list_tasklists`

Important note:

- `search_users()` is currently cache-based, not remote SDK search. This was done because the originally referenced SDK request class did not exist. If true remote search is still required, the next AI must again inspect the installed SDK source instead of guessing.

### `src/taskarena/tools.py`

Implemented MCP tool definitions and dispatch for:

- `reply`
- `react`
- `create_task`
- `update_task`
- `complete_task`
- `list_tasks`
- `search_users`
- `get_config`

### `src/taskarena/channel.py`

Implemented:

- low-level MCP server with tool registration
- `claude/channel` experimental capability declaration
- raw JSON-RPC emission for `notifications/claude/channel`
- startup wiring for tools, event listener, and scheduler

Important implementation detail:

- Standard `mcp.types.ServerNotification` does not include custom `notifications/claude/channel`
- Therefore notifications are emitted by directly writing `JSONRPCNotification` to the stdio write stream

### `src/taskarena/events.py`

Implemented skeleton:

- `lark_oapi.ws.Client`
- `EventDispatcherHandler.builder(...)`
- handlers registered for:
  - `p2.im.message.receive_v1`
  - `p2.task.task.update_tenant_v1`
  - `p2.task.task.comment.updated_v1`
- thread-to-async bridge using `loop.call_soon_threadsafe(asyncio.create_task, ...)`
- basic event dedupe using an LRU-ish `OrderedDict`
- allowlist filtering for IM messages
- basic health notification when listener thread dies or is idle too long

Important note:

- This is still a practical skeleton, not a production-complete listener
- WebSocket shutdown/reconnect control is limited because the SDK is thread/loop driven internally

### `src/taskarena/scheduler.py`

Implemented:

- config-driven schedule loading
- `croniter` next-run calculation
- 30s polling loop
- channel notification emission for scheduled prompts

### `src/taskarena/__main__.py`

Implemented basic CLI skeleton:

- `taskarena channel`
- `taskarena init`
- `taskarena status`
- `taskarena users`
- `taskarena tasklists`

Current CLI behavior:

- `init` writes `.env`, `.taskarena/users.json`, `.taskarena/tasklists.json`, and a starter `.taskarena/config.yaml`
- `status` prints loaded config
- `users` prints cached users or filtered `search_users`
- `tasklists --refresh` calls Feishu and writes `.taskarena/tasklists.json`

## Verified Commands

These succeeded:

- `uv run python -c "import src.taskarena.feishu"`
- `uv run python -c "import src.taskarena.feishu, taskarena.channel, taskarena.tools, taskarena.events, taskarena.scheduler, taskarena.__main__; print('all imports ok')"`
- `uv run pytest tests/test_feishu.py`
- `uv run python -c "from taskarena.channel import create_server; from mcp.server.lowlevel import NotificationOptions; s=create_server(); caps=s.get_capabilities(NotificationOptions(), {'claude/channel': {}}); print(caps.model_dump(exclude_none=True))"`

Observed capabilities output:

```python
{'experimental': {'claude/channel': {}}, 'tools': {'listChanged': False}}
```

Parser sanity check also succeeded:

- `uv run python -c "from taskarena.__main__ import build_parser; print(build_parser().parse_args(['status']))"`

## Test Status

Current tests:

- `/Users/daiming/workspace/naive-taskarena/tests/test_feishu.py`

What they cover:

- `taskarena.feishu` imports successfully
- core runtime modules import successfully

Current result:

- `2 passed`

## Known Environment Issue

In this sandbox, these commands failed due to `uv` runtime issues outside the Python app itself:

- `uv run taskarena --help`
- `uv run taskarena status`
- `env UV_CACHE_DIR=.uv-cache uv run taskarena --help`
- `env UV_CACHE_DIR=.uv-cache uv run python -m taskarena --help`

Observed failure:

- `uv` panics in Rust with `system-configuration` / `Attempted to create a NULL object`

Interpretation:

- This appears to be an environment/sandbox/runtime issue with `uv`, not a Python traceback from TaskArena
- Module imports and pytest are still working, so code-level verification should continue using `uv run python -c "..."` where possible

## Important SDK Facts Learned

### MCP package

Inspected package under:

- `.venv/lib/python3.14/site-packages/mcp`

Important findings:

- Low-level server API is in `mcp.server.lowlevel.server.Server`
- stdio transport is in `mcp.server.stdio.stdio_server`
- custom channel notifications are not part of `ServerNotification`
- sending `notifications/claude/channel` requires writing a raw `JSONRPCNotification`

### Feishu event SDK

Inspected package under:

- `.venv/lib/python3.14/site-packages/lark_oapi/ws`
- `.venv/lib/python3.14/site-packages/lark_oapi/event`

Important findings:

- `lark_oapi.ws.Client` accepts an `EventDispatcherHandler`
- `EventDispatcherHandler.builder("", "", level)` can register handlers directly
- real registration methods confirmed:
  - `register_p2_im_message_receive_v1`
  - `register_p2_task_task_update_tenant_v1`
  - `register_p2_task_task_comment_updated_v1`

Relevant model files:

- `.venv/lib/python3.14/site-packages/lark_oapi/api/im/v1/model/p2_im_message_receive_v1.py`
- `.venv/lib/python3.14/site-packages/lark_oapi/api/task/v1/model/p2_task_task_update_tenant_v1.py`
- `.venv/lib/python3.14/site-packages/lark_oapi/api/task/v1/model/p2_task_task_comment_updated_v1.py`

## What Still Needs Work

### High priority

1. Harden `events.py`
   - verify event field names against real Feishu payloads
   - improve shutdown behavior
   - enrich task notifications with actual task data if needed
   - verify allowlist behavior end-to-end

2. Improve CLI completeness
   - `init` should fetch and cache real users/tasklists
   - `users` should support refresh from Feishu
   - `tasklists` should support refresh and local display cleanly
   - `status` should show connection/cache health

3. Add more tests
   - tool dispatch tests
   - scheduler behavior tests
   - parser tests
   - config/cache roundtrip tests

4. Validate MCP handshake end-to-end
   - run `uv run taskarena channel`
   - connect with a tiny stdio MCP client
   - confirm `initialize`, `tools/list`, and custom notifications work

### Medium priority

5. Revisit `search_users()`
   - if the product requires true organization search instead of cache-only search, inspect the installed SDK again and/or Feishu API docs
   - do not guess class names

6. Sanitize / stabilize repo state
   - there are many untracked files and some `.DS_Store` files in `git status`
   - do not delete user-owned changes blindly

## Suggested Next Commands

Use these as safe starting points:

```bash
uv run python -c "import src.taskarena.feishu"
uv run python -c "import taskarena.channel, taskarena.tools, taskarena.events, taskarena.scheduler, taskarena.__main__"
uv run pytest tests/test_feishu.py
uv run python -c "from taskarena.channel import create_server; from mcp.server.lowlevel import NotificationOptions; s=create_server(); print(s.get_capabilities(NotificationOptions(), {'claude/channel': {}}).model_dump(exclude_none=True))"
```

If working on SDK details, inspect local installed source first:

```bash
rg -n "register_p2_im_message_receive_v1|register_p2_task_task_update_tenant_v1|register_p2_task_task_comment_updated_v1" .venv/lib/python3.14/site-packages/lark_oapi/event/dispatcher_handler.py
sed -n '1,260p' .venv/lib/python3.14/site-packages/lark_oapi/api/contact/v3/resource/user.py
sed -n '1,260p' .venv/lib/python3.14/site-packages/lark_oapi/ws/client.py
```

## Handoff Summary

The immediate `ImportError` blocker is fixed. The core modules for Phase 3-5 now exist and import cleanly. The next AI should focus on hardening behavior and completing CLI/data refresh flows, not on re-solving the original `SearchUserRequest` issue.
