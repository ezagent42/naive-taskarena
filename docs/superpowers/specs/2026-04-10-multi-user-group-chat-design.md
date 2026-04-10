# Multi-User Session Isolation & Group Chat Support

**Date:** 2026-04-10
**Status:** Approved
**Scope:** Path 1 — single Claude Code process, no architectural rewrite

---

## Background

TaskArena currently forwards all Feishu events (private messages, task updates) into a single Claude Code conversation as channel notifications. All users share one context window with no session isolation.

**Core problems:**
1. Task attribution errors — Claude may use the wrong `open_id` when assigning tasks, especially when multiple users are interacting concurrently (3–5 users, medium frequency)
2. No group chat support — group @ mentions are not detected or routed
3. No proactive push to group chats — reminders and scheduled prompts only reach DMs

**Out of scope (Path 2, future):** Per-user Claude API sessions backed by SQLite conversation history.

---

## Design

### 1. Session Key & Structured Actor Context

Every channel notification must carry a complete actor block so Claude never needs to infer user identity from conversation history.

**Session key rules (computed in `events.py`):**
- Private message (`chat_type=p2p`) → `session_key = open_id`
- Group message (`chat_type=group`) → `session_key = chat_id`

**Notification format (before → after):**

Before:
```xml
<channel source="taskarena" type="user_message" user="张三" chat_id="oc_xxx">content</channel>
```

After:
```xml
<channel source="taskarena" type="user_message"
  chat_type="p2p"
  open_id="ou_abc"
  user="张三"
  chat_id="oc_xxx"
  message_id="om_yyy"
  session_key="ou_abc">content</channel>
```

All existing notification types (`task_event`, `morning_reminder_sent`, etc.) remain unchanged — only `user_message` notifications get the new fields.

### 2. Group Chat Support

#### Detection

`events.py` checks for bot @ mention before forwarding group messages:

```python
mentions = getattr(message, "mentions", [])
bot_mentioned = any(
    getattr(m.id, "open_id", None) == config.bot_open_id
    for m in (mentions or [])
)
if not bot_mentioned:
    return  # ignore — bot not mentioned
```

Group messages that do mention the bot are forwarded with `chat_type="group"`, `session_key=chat_id`.

#### Configuration (`config.yaml`)

```yaml
bot_open_id: "ou_bot_xxx"        # bot's own open_id, set manually once

reminders:
  morning_time: "09:00"
  timezone: "Asia/Shanghai"
  group_chat_ids:                 # groups to receive proactive pushes
    - "oc_group_yyy"
```

#### Proactive push (`scheduler.py`)

Morning reminders and scheduled prompts are sent to each configured `group_chat_id` in addition to individual DMs:

```python
for chat_id in cfg.group_chat_ids:
    await feishu.send_message(chat_id, message, receive_id_type="chat_id")
```

### 3. Reply Routing

`reply` tool behavior is unchanged. Claude must always use `message_id` from the triggering notification — Feishu automatically routes the reply to the correct chat (DM or group). Claude must never construct a `chat_id` from memory.

### 4. CLAUDE.md Rules (hardened)

Two new explicit rules added to `.claude/CLAUDE.md`:

**Rule 1 — Actor identity:**
> All tool calls involving user identity (`assignee_ids`, `open_id`-typed fields) must use the `open_id` from the current notification. Never infer identity from conversation history.

**Rule 2 — Reply routing:**
> Always reply using `message_id` from the triggering notification. Never construct or recall a `chat_id` for replies.

**Rule 3 — Task assignment scenarios:**
- Self-claim ("assign to me"): use `open_id` from current notification directly
- Manager assigns to others ("assign X to 张三"): call `search_users` first, confirm the resolved `open_id` with the requester before calling `assign_task`

---

## Files Changed

| File | Change |
|---|---|
| `src/taskarena/events.py` | Add `open_id`, `chat_type`, `session_key` to `user_message` notifications; detect group @ mentions using `bot_open_id` |
| `src/taskarena/config.py` | Add `bot_open_id` field; add `group_chat_ids` to `RemindersConfig` |
| `src/taskarena/scheduler.py` | Push morning reminders and scheduled prompts to `group_chat_ids` |
| `.claude/CLAUDE.md` | Add actor identity rule, reply routing rule, assignment scenario rules |

**Not changed:** `channel.py`, `tools.py`, `feishu.py`, `channel_format.py`

---

## What This Does Not Solve

- **Deep context contamination**: 5+ concurrent users in long multi-turn flows can still confuse Claude's context window. The structured `open_id` reduces frequency but does not eliminate the risk.
- **Conversation persistence across restarts**: Claude's context is lost on restart. Per-user history requires Path 2 (SQLite + Claude API).
- **Group member isolation**: Group messages are keyed by `chat_id` (shared group context). Per-member isolation inside a group (`{chat_id}:{open_id}`) is not implemented.

These limitations are acceptable for a team of 3–5 concurrent users at medium interaction frequency. Revisit when Path 2 is funded.

---

## Testing

- Unit tests for `session_key` computation (p2p → `open_id`, group → `chat_id`)
- Unit test for group @ mention detection (mentioned / not mentioned / missing `bot_open_id`)
- Unit tests for `group_chat_ids` push in scheduler
- Manual end-to-end: two users simultaneously claim different tasks, verify correct assignment
