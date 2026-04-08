# Assign Start Date Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After a user claims a task, Claude checks the task's due date and asks when they plan to start if the due date is absent or more than 7 days away; when the user answers, Claude sets the start date via `update_task`.

**Architecture:** Two backend changes (enrich `assign_task` response with task context; add `start_date` to `update_task`) plus a `.claude/CLAUDE.md` instruction update. No new tools or files needed.

**Tech Stack:** Python, lark-oapi Task V2 SDK (`GetTaskRequest`, `Start` model), pytest-asyncio, unittest.mock

---

### Task 1: Add `start_date` to `update_task`

**Files:**
- Modify: `src/taskarena/feishu.py:148-178`
- Modify: `src/taskarena/tools.py:57-67`
- Modify: `tests/test_morning_reminder_lifecycle.py:243-248`
- Test: `tests/test_tools.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_tools.py`:

```python
@pytest.mark.asyncio
async def test_update_task_with_start_date():
    mock_response = {"task_id": "task-001", "success": True}
    with mock.patch.object(feishu, "update_task", new=mock.AsyncMock(return_value=mock_response)) as m:
        result = await call_tool("update_task", {
            "task_id": "task-001",
            "start_date": "2026-04-15",
        })
    assert result == mock_response
    m.assert_called_once_with(
        task_id="task-001",
        summary=None,
        description=None,
        due_date=None,
        start_date="2026-04-15",
    )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_tools.py::test_update_task_with_start_date -v
```

Expected: FAIL — `update_task` called without `start_date` kwarg.

- [ ] **Step 3: Add `start_date` to `update_task` schema in `tools.py`**

In `TOOLS` list, update the `update_task` tool:

```python
_tool(
    "update_task",
    "Update a Feishu task.",
    {
        "task_id": {"type": "string"},
        "summary": {"type": "string"},
        "description": {"type": "string"},
        "due_date": {"type": "string", "description": "Due date in YYYY-MM-DD format"},
        "start_date": {"type": "string", "description": "Start date in YYYY-MM-DD format"},
    },
    ["task_id"],
),
```

In `call_tool`, update the `update_task` branch:

```python
if name == "update_task":
    return await feishu.update_task(
        task_id=args["task_id"],
        summary=args.get("summary"),
        description=args.get("description"),
        due_date=args.get("due_date"),
        start_date=args.get("start_date"),
    )
```

- [ ] **Step 4: Add `start_date` support to `feishu.update_task`**

Add `Start` to imports at top of `feishu.py`:

```python
from lark_oapi.api.task.v2.model import Due, Member, Start
```

Add helper below `_due_from_date`:

```python
def _start_from_date(start_date: str) -> Start:
    """Convert YYYY-MM-DD string to a Feishu Start object (all-day)."""
    dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    timestamp_ms = str(int(dt.timestamp() * 1000))
    return Start.builder().timestamp(timestamp_ms).is_all_day(True).build()
```

Update `update_task` signature and body:

```python
async def update_task(task_id: str, summary: str = None, description: str = None, due_date: str = None, start_date: str = None) -> dict:
    """Update task attributes."""
    client = get_client()

    task_builder = InputTask.builder()
    update_fields = []
    if summary:
        task_builder.summary(summary)
        update_fields.append("summary")
    if description is not None:
        task_builder.description(description)
        update_fields.append("description")
    if due_date:
        task_builder.due(_due_from_date(due_date))
        update_fields.append("due")
    if start_date:
        task_builder.start(_start_from_date(start_date))
        update_fields.append("start")

    body = PatchTaskRequestBody.builder() \
        .task(task_builder.build()) \
        .update_fields(update_fields) \
        .build()

    request = PatchTaskRequest.builder() \
        .task_guid(task_id) \
        .user_id_type("open_id") \
        .request_body(body) \
        .build()

    response = await client.task.v2.task.apatch(request)
    if not response.success():
        raise Exception(f"Feishu API error (update_task): code {response.code}, msg {response.msg}")

    return {"task_id": task_id, "success": True}
```

- [ ] **Step 5: Fix the existing lifecycle test** (it now needs `start_date=None`)

In `tests/test_morning_reminder_lifecycle.py`, update the assertion:

```python
m.assert_called_once_with(
    task_id="task-001",
    summary=None,
    description="原始描述\n完成文档：https://docs.example.com/result",
    due_date=None,
    start_date=None,
)
```

- [ ] **Step 6: Run all tests**

```bash
uv run pytest tests/ -v
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/taskarena/feishu.py src/taskarena/tools.py tests/test_tools.py tests/test_morning_reminder_lifecycle.py
git commit -m "feat: add start_date support to update_task"
```

---

### Task 2: Enrich `assign_task` response with task context

**Files:**
- Modify: `src/taskarena/feishu.py` (`add_task_members` function)
- Test: `tests/test_tools.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_tools.py`:

```python
@pytest.mark.asyncio
async def test_assign_task_returns_task_context():
    """assign_task should return summary and due_date from the task."""
    mock_response = {
        "task_id": "task-001",
        "summary": "Fix login bug",
        "due_date": "2026-04-20",
    }
    with mock.patch.object(feishu, "add_task_members", new=mock.AsyncMock(return_value=mock_response)) as m:
        result = await call_tool("assign_task", {
            "task_id": "task-001",
            "assignee_ids": ["ou_abc123"],
        })
    assert result["summary"] == "Fix login bug"
    assert result["due_date"] == "2026-04-20"


@pytest.mark.asyncio
async def test_assign_task_returns_null_due_date_when_absent():
    """assign_task returns due_date=None when task has no due date."""
    mock_response = {
        "task_id": "task-001",
        "summary": "Fix login bug",
        "due_date": None,
    }
    with mock.patch.object(feishu, "add_task_members", new=mock.AsyncMock(return_value=mock_response)) as m:
        result = await call_tool("assign_task", {
            "task_id": "task-001",
            "assignee_ids": ["ou_abc123"],
        })
    assert result["due_date"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_tools.py::test_assign_task_returns_task_context tests/test_tools.py::test_assign_task_returns_null_due_date_when_absent -v
```

Expected: FAIL — `add_task_members` currently returns `{"task_id", "success": True}`.

- [ ] **Step 3: Add GET task after add_members in `feishu.add_task_members`**

Add `GetTaskRequest` to imports:

```python
from lark_oapi.api.task.v2 import (
    CreateTaskRequest, InputTask,
    PatchTaskRequest,
    TasksTasklistRequest,
    AddTasklistTaskRequest,
    ListTasklistRequest,
    AddMembersTaskRequest,
    GetTaskRequest,
)
```

Replace `add_task_members` with:

```python
async def add_task_members(task_id: str, assignee_ids: list) -> dict:
    """Add assignees to a task and return task context (summary, due_date)."""
    client = get_client()
    members = [
        Member.builder().id(uid).type("user").role("assignee").build()
        for uid in assignee_ids
    ]
    body = AddMembersTaskRequestBody.builder().members(members).build()
    request = AddMembersTaskRequest.builder() \
        .task_guid(task_id) \
        .user_id_type("open_id") \
        .request_body(body) \
        .build()
    response = await client.task.v2.task.aadd_members(request)
    if not response.success():
        raise Exception(f"Feishu API error (add_task_members): code {response.code}, msg {response.msg}")

    # Fetch task context so Claude can decide whether to ask about start date
    due_date = None
    summary = None
    try:
        get_req = GetTaskRequest.builder() \
            .task_guid(task_id) \
            .user_id_type("open_id") \
            .build()
        get_resp = await client.task.v2.task.aget(get_req)
        if get_resp.success() and get_resp.data and get_resp.data.task:
            task = get_resp.data.task
            summary = task.summary
            if task.due and task.due.timestamp:
                ts_ms = int(task.due.timestamp)
                due_date = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    except Exception:
        log.warning("Failed to fetch task context after assign (task_id=%s)", task_id)

    return {"task_id": task_id, "summary": summary, "due_date": due_date}
```

- [ ] **Step 4: Run all tests**

```bash
uv run pytest tests/ -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/taskarena/feishu.py tests/test_tools.py
git commit -m "feat: enrich assign_task response with summary and due_date"
```

---

### Task 3: Update bot instructions in `.claude/CLAUDE.md`

**Files:**
- Modify: `.claude/CLAUDE.md`

No code tests for this task — it's a prompt instruction change.

- [ ] **Step 1: Replace the "认领任务" section**

Replace the existing section:

```markdown
## 认领任务

当用户说"我要认领任务X"、"把任务X分配给我"等，调用 `assign_task` 并传入用户自己的 `open_id`：

```
assign_task(task_id=<task_id>, assignee_ids=[<发送者的 open_id>])
```

如果用户想认领多个任务，对每个任务分别调用一次 `update_task`。
```

With:

```markdown
## 认领任务

当用户说"我要认领任务X"、"把任务X分配给我"等，对每个任务调用 `assign_task`：

```
assign_task(task_id=<task_id>, assignee_ids=[<发送者的 open_id>])
```

`assign_task` 返回 `{ task_id, summary, due_date }`。认领后检查 `due_date`：

- **`due_date` 为 null，或距今超过 7 天**：用 `reply` 追问："已认领「{summary}」！你计划什么时候开始？"
- **`due_date` 在 7 天内**：直接回复认领成功，不追问。

认领多个任务时，合并成一条追问："已认领以下任务，你计划什么时候开始？\n1. 任务A\n2. 任务B"

### 用户回复开始时间

用户回复后，解析日期（"明天"→明天的日期，"下周一"→下周一的日期，"4月15日"→2026-04-15），
然后对每个任务调用：

```
update_task(task_id=<task_id>, start_date="YYYY-MM-DD")
```

随后用 `reply` 确认："已将开始时间设为 {date}，加油！"

**模糊日期**（如"下周"）：解析为该周一，先 reply 确认"我理解为 {date}，对吗？"，等用户确认后再写入。

**用户不确定**（"不知道"、"再说"）：reply "好的，确定后告诉我。" 不调用 `update_task`。
```

- [ ] **Step 2: Verify the section renders correctly**

```bash
cat .claude/CLAUDE.md
```

Visual check: confirm the section is correct and no leftover text from the old version.

- [ ] **Step 3: Commit**

```bash
git add .claude/CLAUDE.md
git commit -m "docs: instruct Claude to ask about start date after task claim"
```
