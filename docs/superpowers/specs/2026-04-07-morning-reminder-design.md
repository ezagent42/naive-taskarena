# Morning Task Reminder Design

Date: 2026-04-07

## Overview

Add a morning reminder feature that sends a daily Feishu private message (DM) to each task assignee listing their in-progress tasks. When the assignee replies, Claude handles the completion flow: detecting a URL triggers task completion with doc link recorded; saying "done" prompts Claude to ask for the link.

## Architecture & Data Flow

```
Each day at morning_time (within ~30s)
        │
        ▼
scheduler.py: _check_morning_reminders()
        │  Per tasklist: list_tasks(completed=False)
        │  Filter: assignee in allowed_users
        │  Group by assignee
        │
        ▼
feishu.py: send_message(open_id, content, receive_id_type="open_id")
        │  One DM per assignee, listing all their pending tasks
        │  Message includes task name + task_id for each task
        │
        ▼
Assignee replies → events.py captures IM message
        │  Channel notification pushed to Claude (chat_id, message_id, user, content)
        │
        ▼
Claude decides:
  ├── Reply contains URL → update_task (append link to description) + complete_task + reply confirm
  ├── Reply says "done" (no URL) → reply asking for doc link
  └── Multiple tasks unclear → list tasks and ask which one
```

## Configuration

New `reminders` block in `.taskarena/config.yaml`:

```yaml
reminders:
  morning_time: "09:00"   # HH:MM, local time
  timezone: "Asia/Shanghai"
  tasklists:              # optional — omit to use global tasklists; list of tasklist IDs
    - "xxx"
```

- If `reminders` is absent, the feature is disabled entirely.
- `morning_time` is a threshold: scheduler triggers once per day when `now >= morning_time`.
- On restart after `morning_time`, the reminder fires immediately (useful for testing; acceptable production behavior since it compensates for downtime).

## Config Model Changes (`config.py`)

```python
@dataclass
class ReminderConfig:
    morning_time: str = "09:00"
    timezone: str = "Asia/Shanghai"
    tasklists: list[str] = field(default_factory=list)  # empty = use global tasklists

@dataclass
class Config:
    ...
    reminders: ReminderConfig | None = None
```

## feishu.py Changes

### 1. `send_message` — add `receive_id_type` parameter

```python
async def send_message(
    chat_id: str,
    content: str,
    msg_type: str = "text",
    receive_id_type: str = "chat_id",  # pass "open_id" for DMs
) -> dict:
```

### 2. `list_tasks` — include assignees in return value

`TaskSummary.members` contains assignees. Field names must be verified from SDK source at implementation time (`.venv/lib/python3.14/site-packages/lark_oapi/api/task/v2/model/`).

Expected output per task:

```python
{
    "task_id": item.guid,
    "summary": item.summary,
    "is_completed": is_completed,
    "assignees": ["ou_xxx", "ou_yyy"],  # open_ids of members with role == "assignee"
}
```

## scheduler.py Changes

Add `_last_reminder_date: date | None = None` to `TaskArenaScheduler`.

New method `_check_morning_reminders()`:

```python
async def _check_morning_reminders(self) -> None:
    cfg = self.config.reminders
    if not cfg:
        return

    now = datetime.now(ZoneInfo(cfg.timezone))
    today = now.date()

    if self._last_reminder_date == today:
        return

    target = now.replace(
        hour=int(cfg.morning_time.split(":")[0]),
        minute=int(cfg.morning_time.split(":")[1]),
        second=0, microsecond=0,
    )
    if now < target:
        return

    self._last_reminder_date = today
    await self._send_morning_reminders()
```

`_send_morning_reminders()` logic:
1. Determine tasklists: `cfg.tasklists` if set, else `self.config.tasklists`
2. For each tasklist: call `feishu.list_tasks(tasklist_id, completed=False)`
3. Filter tasks where `assignees` is non-empty and at least one assignee is in `allowed_users`
4. Group tasks by assignee open_id
5. For each assignee: send one DM listing all their pending tasks with task names and task_ids
6. Use `feishu.send_message(open_id, content, receive_id_type="open_id")`

Call `_check_morning_reminders()` inside the existing 30-second polling loop.

### DM message format (example)

```
早上好！你有以下未完成的任务需要关注：

1. MacBook开发 (task_id: abc123)
2. TaskArena 第一个任务 (task_id: def456)

如有完成，请回复完成文档链接，我来帮你记录并关闭任务。
```

## Claude Bot Behavior (`.claude/CLAUDE.md`)

Add section:

```markdown
## 任务完成提醒回复处理

当收到用户的 IM 消息，且内容涉及任务完成时：

1. **消息包含 URL**：
   - 调用 `update_task`，将链接追加到任务描述末尾，格式：`\n完成文档：<url>`
   - 调用 `complete_task` 标记完成
   - 用 `reply` 确认："✅ 任务「{summary}」已标记完成，文档链接已记录。"

2. **消息表达完成但无 URL**（如"完成了"、"做好了"）：
   - 用 `reply` 追问："请提供完成文档链接，我来帮你记录并关闭任务。"

3. **用户有多个未完成任务时**：
   - 若无法从上下文判断是哪个任务，先列出任务让用户确认

提醒消息中已包含 task_id，优先使用消息上下文中的 task_id 定位任务，避免重复调用 list_tasks。
```

## tools.py Changes

`reply` tool's `chat_id` is currently required when `message_id` is absent. For DM replies triggered by reminders, `chat_id` will be the user's open_id — no change to tool schema needed, but `send_message` must accept `receive_id_type`.

Update `call_tool` in `tools.py` to pass `receive_id_type` from args if provided:

```python
if name == "reply":
    ...
    return await feishu.send_message(
        chat_id=args["chat_id"],
        content=message,
        msg_type=msg_type,
        receive_id_type=args.get("receive_id_type", "chat_id"),
    )
```

And add `receive_id_type` to the `reply` tool schema as an optional field.

## Error Handling

- If `list_tasks` fails for a tasklist, log the error and skip that tasklist (don't abort other reminders).
- If `send_message` to a specific user fails, log and continue to the next user.
- If assignee open_id is not in the users cache, still send the DM (open_id is sufficient for the API).

## Testing

- Unit test: `_check_morning_reminders` does not fire before `morning_time`
- Unit test: fires exactly once per day, resets on next day
- Unit test: fires immediately on restart after `morning_time`
- Unit test: `list_tasks` returns `assignees` field correctly
- Unit test: `send_message` passes correct `receive_id_type` to Feishu API
- Integration: manual test by setting `morning_time` to current time + 1 minute

## Files Changed

| File | Change |
|------|--------|
| `src/taskarena/config.py` | Add `ReminderConfig` dataclass, add `reminders` field to `Config` |
| `src/taskarena/feishu.py` | Add `receive_id_type` to `send_message`; add `assignees` to `list_tasks` return |
| `src/taskarena/scheduler.py` | Add `_check_morning_reminders` + `_send_morning_reminders` |
| `src/taskarena/tools.py` | Add `receive_id_type` to `reply` tool schema and dispatch |
| `.claude/CLAUDE.md` | Add completion reply handling instructions |
| `.taskarena/config.yaml` | Add `reminders` block (user-managed, not in repo) |
