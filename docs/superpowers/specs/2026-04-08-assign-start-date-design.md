# Assign Task — Post-Claim Start Date Interaction

**Date:** 2026-04-08
**Status:** Approved

## Overview

After a user claims a task, Claude checks the task's due date and conditionally asks when the user plans to start. If the user replies with a date, Claude sets it as the task's start date via `update_task`.

## Data Flow

```
User: "我认领任务X"
  → assign_task(task_id, assignee_ids)
      → 飞书 add_members API
      → 飞书 GET task API（fetch due_date）
      → returns { task_id, summary, due_date }
  → Claude checks:
      - No due_date OR due_date > 7 days away → reply "已认领！你计划什么时候开始？"
      - Otherwise → reply "已认领！" (no follow-up)

User replies: "明天" / "下周一" / "4月15日"
  → update_task(task_id, start_date="YYYY-MM-DD")
      → 飞书 PATCH task（update_fields=["start"]）
  → reply "已将开始时间设为 XX，加油！"
```

## Code Changes

### `feishu.py`

- `add_task_members`: after `aadd_members`, call GET task to fetch due date. Return `{ task_id, summary, due_date }` where `due_date` is `"YYYY-MM-DD"` string or `null`.
- `update_task`: add `start_date: str = None` parameter. Construct `Start` object (same structure as `Due`). Append `"start"` to `update_fields`.

### `tools.py`

- `update_task` schema: add `start_date` field (`"YYYY-MM-DD"` format).

### `.claude/CLAUDE.md`

Add rules to the "认领任务" section:
- After `assign_task` returns, check `due_date` in response.
- If `due_date` is null or more than 7 days from today → ask "你计划什么时候开始这个任务？"
- When user replies with a date → parse to `YYYY-MM-DD`, call `update_task(task_id, start_date=...)`, reply confirmation.
- If user is ambiguous (e.g., "下周") → interpret as that Monday, confirm before writing.

## Edge Cases

| Situation | Handling |
|-----------|----------|
| User says "不确定" or doesn't reply | Reply "好的，确定后告诉我", do not set start date |
| Ambiguous date ("下周") | Interpret as that Monday, ask "我理解为 XX，对吗？" before writing |
| GET task fails after assign | Ignore silently, claim succeeds, no follow-up question |
| Multiple tasks claimed at once | Evaluate each task separately; combine into one follow-up message |
| start_date is in the past | Accept as-is (may be backdating) |

## What Is Not Changing

- `assign_task` tool signature (no new input parameters)
- Task claiming flow otherwise unchanged
- No new MCP tools
