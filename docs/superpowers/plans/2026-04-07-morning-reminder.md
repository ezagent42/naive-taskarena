# Morning Task Reminder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a configurable daily morning reminder that DMs each task assignee their pending tasks via Feishu, and handles the completion flow (doc link submission → task marked complete).

**Architecture:** Extend `Config` with a `ReminderConfig` dataclass; extend `feishu.py` to return assignees from `list_tasks` and accept `receive_id_type` in `send_message`; add `_check_morning_reminders` to the scheduler's 30s polling loop; update `.claude/CLAUDE.md` with reply-handling instructions.

**Tech Stack:** Python 3.14, lark-oapi SDK, zoneinfo (stdlib), pytest-asyncio, uv

---

## File Map

| File | Action | What changes |
|------|--------|--------------|
| `src/taskarena/config.py` | Modify | Add `ReminderConfig` dataclass; load `reminders` block from yaml |
| `src/taskarena/feishu.py` | Modify | `send_message` gains `receive_id_type`; `list_tasks` returns `assignees` |
| `src/taskarena/tools.py` | Modify | `reply` tool schema and dispatch gain optional `receive_id_type` |
| `src/taskarena/scheduler.py` | Modify | Add `_check_morning_reminders` + `_send_morning_reminders` |
| `.claude/CLAUDE.md` | Modify | Add completion reply handling instructions |
| `tests/test_config.py` | Modify | Tests for `ReminderConfig` loading |
| `tests/test_feishu.py` | Modify | Tests for `list_tasks` assignees + `send_message` receive_id_type |
| `tests/test_tools.py` | Modify | Tests for `reply` tool with `receive_id_type` |
| `tests/test_scheduler.py` | Modify | Tests for morning reminder logic |

---

## SDK Facts (verified from .venv source)

- `TaskSummary.members: List[Member]` — list of task members
- `Member.id: str` — the user's open_id directly (not nested)
- `Member.role: str` — `"assignee"` or `"follower"`
- `TaskSummary.completed_at: int` — 0 = not completed, unix ms timestamp = completed

---

## Task 1: Add ReminderConfig to config.py

**Files:**
- Modify: `src/taskarena/config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_config.py`:

```python
import os
from unittest import mock
from taskarena.config import Config, ReminderConfig


@mock.patch.dict(os.environ, {"FEISHU_APP_ID": "test_id", "FEISHU_APP_SECRET": "test_secret"})
def test_config_load():
    config = Config.load()
    assert config.app_id == "test_id"
    assert config.app_secret == "test_secret"
    assert config.log_level == "INFO"


@mock.patch.dict(os.environ, {"FEISHU_APP_ID": "id", "FEISHU_APP_SECRET": "secret"})
def test_config_reminders_absent_by_default():
    config = Config.load()
    assert config.reminders is None


@mock.patch.dict(os.environ, {"FEISHU_APP_ID": "id", "FEISHU_APP_SECRET": "secret"})
def test_config_reminders_loaded_from_yaml(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".taskarena").mkdir()
    (tmp_path / ".taskarena" / "config.yaml").write_text(
        "reminders:\n  morning_time: '08:30'\n  timezone: 'Asia/Tokyo'\n  tasklists:\n    - 'abc123'\n"
    )
    config = Config.load()
    assert config.reminders is not None
    assert config.reminders.morning_time == "08:30"
    assert config.reminders.timezone == "Asia/Tokyo"
    assert config.reminders.tasklists == ["abc123"]


@mock.patch.dict(os.environ, {"FEISHU_APP_ID": "id", "FEISHU_APP_SECRET": "secret"})
def test_config_reminders_defaults(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".taskarena").mkdir()
    (tmp_path / ".taskarena" / "config.yaml").write_text("reminders: {}\n")
    config = Config.load()
    assert config.reminders.morning_time == "09:00"
    assert config.reminders.timezone == "Asia/Shanghai"
    assert config.reminders.tasklists == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_config.py -v
```

Expected: `test_config_reminders_absent_by_default` passes (reminders is None by accident), others FAIL with `ImportError: cannot import name 'ReminderConfig'`

- [ ] **Step 3: Implement ReminderConfig in config.py**

Replace `src/taskarena/config.py` with:

```python
import os
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Any, Optional

import yaml
from dotenv import load_dotenv


@dataclass
class ReminderConfig:
    morning_time: str = "09:00"
    timezone: str = "Asia/Shanghai"
    tasklists: List[str] = field(default_factory=list)


@dataclass
class Config:
    app_id: str
    app_secret: str
    tasklists: List[Dict[str, str]] = field(default_factory=list)
    allowed_users: List[str] = field(default_factory=list)
    schedules: List[Dict[str, Any]] = field(default_factory=list)
    users: Dict[str, str] = field(default_factory=dict)
    log_level: str = "INFO"
    reminders: Optional[ReminderConfig] = None

    @classmethod
    def load(cls) -> "Config":
        # 1. Load .env for credentials
        load_dotenv()
        app_id = os.getenv("FEISHU_APP_ID")
        app_secret = os.getenv("FEISHU_APP_SECRET")
        log_level = os.getenv("TASKARENA_LOG_LEVEL", "INFO")

        if not app_id or not app_secret:
            raise ValueError(
                "FEISHU_APP_ID and FEISHU_APP_SECRET must be set in .env or environment variables. "
                "Run 'uv run taskarena init' first."
            )

        # 2. Load runtime config from .taskarena/config.yaml
        config_path = Path(".taskarena/config.yaml")
        tasklists = []
        allowed_users = []
        schedules = []
        reminders = None

        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
                tasklists = data.get("tasklists", [])

                access = data.get("access", {})
                if isinstance(access, dict):
                    allowed_users = access.get("allowed_users", [])

                schedules = data.get("schedules", [])

                reminders_data = data.get("reminders")
                if reminders_data is not None:
                    rd = reminders_data if isinstance(reminders_data, dict) else {}
                    reminders = ReminderConfig(
                        morning_time=rd.get("morning_time", "09:00"),
                        timezone=rd.get("timezone", "Asia/Shanghai"),
                        tasklists=rd.get("tasklists", []),
                    )

        # 3. Load users cache
        users_path = Path(".taskarena/users.json")
        users = {}
        if users_path.exists():
            try:
                with open(users_path, "r", encoding="utf-8") as f:
                    users = json.load(f)
            except json.JSONDecodeError:
                pass

        return cls(
            app_id=app_id,
            app_secret=app_secret,
            tasklists=tasklists,
            allowed_users=allowed_users,
            schedules=schedules,
            users=users,
            log_level=log_level,
            reminders=reminders,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_config.py -v
```

Expected: all 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/taskarena/config.py tests/test_config.py
git commit -m "feat: add ReminderConfig to Config for morning reminder support"
```

---

## Task 2: Extend feishu.py — assignees in list_tasks + receive_id_type in send_message

**Files:**
- Modify: `src/taskarena/feishu.py`
- Modify: `tests/test_feishu.py`

- [ ] **Step 1: Write failing tests**

Replace `tests/test_feishu.py` with:

```python
import importlib
from unittest import mock


def test_feishu_module_imports():
    module = importlib.import_module("taskarena.feishu")
    assert module is not None


def test_runtime_modules_import():
    for module_name in [
        "taskarena.tools",
        "taskarena.channel",
        "taskarena.events",
        "taskarena.scheduler",
        "taskarena.__main__",
    ]:
        assert importlib.import_module(module_name) is not None


def test_list_tasks_includes_assignees():
    """list_tasks returns assignees field with open_ids of members with role='assignee'."""
    from taskarena import feishu
    from lark_oapi.api.task.v2.model.task_summary import TaskSummary
    from lark_oapi.api.task.v2.model.member import Member

    assignee = Member()
    assignee.id = "ou_abc"
    assignee.role = "assignee"

    follower = Member()
    follower.id = "ou_def"
    follower.role = "follower"

    task = TaskSummary()
    task.guid = "task-001"
    task.summary = "Fix the bug"
    task.completed_at = 0
    task.members = [assignee, follower]

    mock_response = mock.MagicMock()
    mock_response.success.return_value = True
    mock_response.data.items = [task]

    mock_client = mock.MagicMock()
    mock_client.task.v2.tasklist.atasks = mock.AsyncMock(return_value=mock_response)

    with mock.patch.object(feishu, "get_client", return_value=mock_client):
        import asyncio
        result = asyncio.run(feishu.list_tasks("tasklist-001"))

    assert result["tasks"][0]["assignees"] == ["ou_abc"]
    assert result["tasks"][0]["is_completed"] is False


def test_send_message_passes_receive_id_type():
    """send_message forwards receive_id_type to the Feishu API."""
    from taskarena import feishu

    mock_response = mock.MagicMock()
    mock_response.success.return_value = True
    mock_response.data.message_id = "msg-001"

    mock_client = mock.MagicMock()
    mock_client.im.v1.message.acreate = mock.AsyncMock(return_value=mock_response)

    captured_request = {}

    async def capture_create(req):
        captured_request["req"] = req
        return mock_response

    mock_client.im.v1.message.acreate = capture_create

    with mock.patch.object(feishu, "get_client", return_value=mock_client):
        import asyncio
        asyncio.run(feishu.send_message("ou_abc", "hello", receive_id_type="open_id"))

    req = captured_request["req"]
    # The receive_id_type is set on the request builder
    assert req._receive_id_type == "open_id"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_feishu.py -v
```

Expected: `test_list_tasks_includes_assignees` FAIL (no `assignees` key), `test_send_message_passes_receive_id_type` FAIL (no `receive_id_type` param)

- [ ] **Step 3: Update feishu.py**

Update `send_message` signature and body (lines 40-62 in existing file):

```python
async def send_message(chat_id: str, content: str, msg_type: str = "text", receive_id_type: str = "chat_id") -> dict:
    """Send a message to a chat or user."""
    client = get_client()

    if msg_type == "text":
        content_str = json.dumps({"text": content}, ensure_ascii=False)
    else:
        content_str = content

    request = CreateMessageRequest.builder() \
        .receive_id_type(receive_id_type) \
        .request_body(CreateMessageRequestBody.builder()
            .receive_id(chat_id)
            .msg_type(msg_type)
            .content(content_str)
            .build()) \
        .build()

    response = await client.im.v1.message.acreate(request)
    if not response.success():
        raise Exception(f"Feishu API error (send_message): code {response.code}, msg {response.msg}")

    return {"message_id": response.data.message_id}
```

Update the `list_tasks` function body (the `tasks.append(...)` block):

```python
    tasks = []
    if response.data and response.data.items:
        for item in response.data.items:
            is_completed = bool(item.completed_at and item.completed_at != "0")
            if completed is not None and is_completed != completed:
                continue

            assignees = [
                m.id for m in (item.members or [])
                if m.role == "assignee" and m.id
            ]
            tasks.append({
                "task_id": item.guid,
                "summary": item.summary,
                "is_completed": is_completed,
                "assignees": assignees,
            })

    return {"tasks": tasks, "total": len(tasks)}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_feishu.py -v
```

Expected: all 4 tests PASS

Note: `test_send_message_passes_receive_id_type` inspects `req._receive_id_type`. If the lark SDK stores it under a different attribute name, update the assertion to match. Check with:
```bash
uv run python -c "from lark_oapi.api.im.v1 import CreateMessageRequest; r = CreateMessageRequest.builder().receive_id_type('open_id').build(); print(vars(r))"
```

- [ ] **Step 5: Commit**

```bash
git add src/taskarena/feishu.py tests/test_feishu.py
git commit -m "feat: list_tasks returns assignees; send_message accepts receive_id_type"
```

---

## Task 3: Add receive_id_type to reply tool in tools.py

**Files:**
- Modify: `src/taskarena/tools.py`
- Modify: `tests/test_tools.py`

- [ ] **Step 1: Write failing tests**

Replace `tests/test_tools.py` with:

```python
import asyncio
from unittest import mock
import pytest
from taskarena.tools import list_tools, call_tool


def test_reply_tool_has_receive_id_type_field():
    tools = {t.name: t for t in list_tools()}
    reply = tools["reply"]
    assert "receive_id_type" in reply.inputSchema["properties"]


def test_reply_tool_passes_receive_id_type_to_feishu():
    from taskarena import feishu

    mock_result = {"message_id": "msg-001"}
    with mock.patch.object(feishu, "send_message", new=mock.AsyncMock(return_value=mock_result)) as m:
        asyncio.run(call_tool("reply", {
            "chat_id": "ou_abc",
            "message": "hello",
            "receive_id_type": "open_id",
        }))
        m.assert_called_once_with(
            chat_id="ou_abc",
            content="hello",
            msg_type="text",
            receive_id_type="open_id",
        )


def test_reply_tool_defaults_receive_id_type_to_chat_id():
    from taskarena import feishu

    mock_result = {"message_id": "msg-002"}
    with mock.patch.object(feishu, "send_message", new=mock.AsyncMock(return_value=mock_result)) as m:
        asyncio.run(call_tool("reply", {
            "chat_id": "chat_abc",
            "message": "hi",
        }))
        _, kwargs = m.call_args
        assert kwargs.get("receive_id_type", "chat_id") == "chat_id"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_tools.py -v
```

Expected: all 3 tests FAIL

- [ ] **Step 3: Update tools.py**

In the `TOOLS` list, update the `reply` tool definition to add `receive_id_type`:

```python
_tool(
    "reply",
    "Send a reply to a Feishu chat or reply to a specific Feishu message.",
    {
        "chat_id": {"type": "string"},
        "message": {"type": "string"},
        "message_id": {"type": "string"},
        "msg_type": {"type": "string", "default": "text"},
        "receive_id_type": {"type": "string", "default": "chat_id"},
    },
    ["message"],
),
```

In `call_tool`, update the `reply` branch:

```python
    if name == "reply":
        message = args["message"]
        msg_type = args.get("msg_type", "text")
        message_id = args.get("message_id")
        receive_id_type = args.get("receive_id_type", "chat_id")
        if message_id:
            return await feishu.send_reply(message_id=message_id, content=message, msg_type=msg_type)
        return await feishu.send_message(
            chat_id=args["chat_id"],
            content=message,
            msg_type=msg_type,
            receive_id_type=receive_id_type,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_tools.py -v
```

Expected: all 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/taskarena/tools.py tests/test_tools.py
git commit -m "feat: reply tool accepts receive_id_type for sending DMs by open_id"
```

---

## Task 4: Add morning reminder to scheduler.py

**Files:**
- Modify: `src/taskarena/scheduler.py`
- Modify: `tests/test_scheduler.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_scheduler.py`:

```python
from datetime import date
from zoneinfo import ZoneInfo
from taskarena.config import ReminderConfig


def _make_config_with_reminders(morning_time: str = "09:00", tasklists=None) -> Config:
    return Config(
        app_id="test",
        app_secret="test",
        tasklists=[{"id": "tl-001", "name": "Main"}],
        allowed_users=["ou_alice", "ou_bob"],
        reminders=ReminderConfig(
            morning_time=morning_time,
            timezone="UTC",
            tasklists=tasklists or [],
        ),
    )


@pytest.mark.asyncio
async def test_morning_reminder_does_not_fire_before_time():
    dms_sent = []

    async def notifier(content, **_):
        dms_sent.append(content)

    config = _make_config_with_reminders(morning_time="23:59")
    scheduler = TaskArenaScheduler(config, notifier)

    await scheduler._check_morning_reminders()

    assert dms_sent == []


@pytest.mark.asyncio
async def test_morning_reminder_fires_after_time():
    dms_sent = []

    async def notifier(content, **_):
        dms_sent.append(content)

    config = _make_config_with_reminders(morning_time="00:00")
    scheduler = TaskArenaScheduler(config, notifier)

    mock_tasks = {
        "tasks": [
            {"task_id": "t-1", "summary": "Fix bug", "is_completed": False, "assignees": ["ou_alice"]},
        ],
        "total": 1,
    }

    with mock.patch("taskarena.scheduler.feishu") as mock_feishu:
        mock_feishu.list_tasks = mock.AsyncMock(return_value=mock_tasks)
        mock_feishu.send_message = mock.AsyncMock(return_value={"message_id": "m1"})

        await scheduler._check_morning_reminders()

        mock_feishu.send_message.assert_called_once()
        call_kwargs = mock_feishu.send_message.call_args
        assert call_kwargs.kwargs.get("receive_id_type") == "open_id"
        assert "Fix bug" in call_kwargs.kwargs.get("content", "") or "Fix bug" in str(call_kwargs)


@pytest.mark.asyncio
async def test_morning_reminder_fires_only_once_per_day():
    dms_sent = []

    async def notifier(content, **_):
        dms_sent.append(content)

    config = _make_config_with_reminders(morning_time="00:00")
    scheduler = TaskArenaScheduler(config, notifier)

    with mock.patch("taskarena.scheduler.feishu") as mock_feishu:
        mock_feishu.list_tasks = mock.AsyncMock(return_value={"tasks": [], "total": 0})
        mock_feishu.send_message = mock.AsyncMock(return_value={"message_id": "m1"})

        await scheduler._check_morning_reminders()
        await scheduler._check_morning_reminders()  # second call — should be skipped

        # list_tasks called once, not twice
        assert mock_feishu.list_tasks.call_count == 1


@pytest.mark.asyncio
async def test_morning_reminder_skips_tasks_without_assignees():
    config = _make_config_with_reminders(morning_time="00:00")
    scheduler = TaskArenaScheduler(config, None)

    mock_tasks = {
        "tasks": [
            {"task_id": "t-1", "summary": "Unassigned task", "is_completed": False, "assignees": []},
        ],
        "total": 1,
    }

    with mock.patch("taskarena.scheduler.feishu") as mock_feishu:
        mock_feishu.list_tasks = mock.AsyncMock(return_value=mock_tasks)
        mock_feishu.send_message = mock.AsyncMock()

        await scheduler._check_morning_reminders()

        mock_feishu.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_morning_reminder_disabled_when_no_reminders_config():
    config = Config(app_id="test", app_secret="test")
    scheduler = TaskArenaScheduler(config, None)

    with mock.patch("taskarena.scheduler.feishu") as mock_feishu:
        mock_feishu.list_tasks = mock.AsyncMock()

        await scheduler._check_morning_reminders()

        mock_feishu.list_tasks.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_scheduler.py -v
```

Expected: new tests FAIL with `AttributeError: '_check_morning_reminders' not found`

- [ ] **Step 3: Implement morning reminder in scheduler.py**

Replace `src/taskarena/scheduler.py` with:

```python
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import date, datetime
from zoneinfo import ZoneInfo

from croniter import croniter

from . import feishu
from .channel_format import build_channel_xml
from .config import Config
from .log import get_logger

log = get_logger("scheduler")

Notifier = Callable[..., Awaitable[None]]


class TaskArenaScheduler:
    def __init__(self, config: Config, notifier: Notifier) -> None:
        self.config = config
        self.notifier = notifier
        self._stop_event = asyncio.Event()
        self._next_run: dict[str, datetime] = {}
        self._last_reminder_date: date | None = None

    async def run(self) -> None:
        self._prime_next_runs()
        while not self._stop_event.is_set():
            await self._tick()
            await self._check_morning_reminders()
            await asyncio.sleep(30)

    async def stop(self) -> None:
        self._stop_event.set()

    def _prime_next_runs(self) -> None:
        for schedule in self.config.schedules:
            name = schedule.get("name")
            cron = schedule.get("cron")
            if not name or not cron:
                continue
            now = self._now(schedule)
            self._next_run[name] = croniter(cron, now).get_next(datetime)

    async def _tick(self) -> None:
        for schedule in self.config.schedules:
            name = schedule.get("name")
            cron = schedule.get("cron")
            prompt = schedule.get("prompt")
            if not name or not cron or not prompt:
                continue

            now = self._now(schedule)
            next_run = self._next_run.get(name)
            if next_run is None:
                next_run = croniter(cron, now).get_next(datetime)
                self._next_run[name] = next_run

            if now >= next_run:
                await self.notifier(build_channel_xml(prompt, source="taskarena", type="scheduled", schedule=name))
                self._next_run[name] = croniter(cron, now).get_next(datetime)
                log.info("Schedule %s fired", name)

    def _now(self, schedule: dict) -> datetime:
        timezone_name = schedule.get("timezone")
        if timezone_name:
            return datetime.now(ZoneInfo(timezone_name))
        return datetime.now().astimezone()

    async def _check_morning_reminders(self) -> None:
        cfg = self.config.reminders
        if not cfg:
            return

        now = datetime.now(ZoneInfo(cfg.timezone))
        today = now.date()

        if self._last_reminder_date == today:
            return

        h, m = cfg.morning_time.split(":")
        target = now.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
        if now < target:
            return

        self._last_reminder_date = today
        await self._send_morning_reminders()

    async def _send_morning_reminders(self) -> None:
        cfg = self.config.reminders
        if not cfg:
            return

        tasklist_ids = cfg.tasklists if cfg.tasklists else [tl["id"] for tl in self.config.tasklists]

        # Collect tasks per assignee: {open_id: [(task_id, summary), ...]}
        assignee_tasks: dict[str, list[tuple[str, str]]] = {}

        for tasklist_id in tasklist_ids:
            try:
                result = await feishu.list_tasks(tasklist_id, completed=False)
            except Exception:
                log.exception("Failed to list tasks for tasklist %s", tasklist_id)
                continue

            for task in result.get("tasks", []):
                for open_id in task.get("assignees", []):
                    if self.config.allowed_users and open_id not in self.config.allowed_users:
                        continue
                    assignee_tasks.setdefault(open_id, []).append(
                        (task["task_id"], task["summary"])
                    )

        for open_id, tasks in assignee_tasks.items():
            task_lines = "\n".join(
                f"{i+1}. {summary} (task_id: {task_id})"
                for i, (task_id, summary) in enumerate(tasks)
            )
            message = (
                f"早上好！你有以下未完成的任务需要关注：\n\n{task_lines}\n\n"
                "如有完成，请回复完成文档链接，我来帮你记录并关闭任务。"
            )
            try:
                await feishu.send_message(open_id, message, receive_id_type="open_id")
                log.info("Morning reminder sent to %s (%d tasks)", open_id, len(tasks))
            except Exception:
                log.exception("Failed to send morning reminder to %s", open_id)
```

- [ ] **Step 4: Run all scheduler tests to verify they pass**

```bash
uv run pytest tests/test_scheduler.py -v
```

Expected: all tests PASS (including original 4 + new 5)

- [ ] **Step 5: Commit**

```bash
git add src/taskarena/scheduler.py tests/test_scheduler.py
git commit -m "feat: add morning reminder — daily DM to task assignees with pending tasks"
```

---

## Task 5: Update .claude/CLAUDE.md with completion reply instructions

**Files:**
- Modify: `.claude/CLAUDE.md`

- [ ] **Step 1: Add completion reply section**

Append the following to `.claude/CLAUDE.md`:

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

- [ ] **Step 2: Commit**

```bash
git add .claude/CLAUDE.md
git commit -m "docs: add completion reply handling instructions to bot CLAUDE.md"
```

---

## Task 6: Run full test suite

- [ ] **Step 1: Run all tests**

```bash
uv run pytest tests/ -v
```

Expected: all tests PASS

- [ ] **Step 2: Verify imports are clean**

```bash
uv run python -c "from taskarena.scheduler import TaskArenaScheduler; from taskarena.config import ReminderConfig; print('imports ok')"
```

Expected: `imports ok`

- [ ] **Step 3: Manual smoke test (optional)**

Set `morning_time` in `.taskarena/config.yaml` to a time 1 minute from now, restart the channel server, and confirm the DM arrives in Feishu.

---

## Self-Review Notes

- **Spec coverage**: All 5 spec sections covered: config ✓, feishu.py ✓, tools.py ✓, scheduler ✓, CLAUDE.md ✓
- **No placeholders**: All code is complete with no TBD/TODO
- **Type consistency**: `ReminderConfig.tasklists: List[str]` used consistently in Tasks 1, 4; `receive_id_type: str` used consistently in Tasks 2, 3, 4
- **SDK facts**: `Member.id` is a plain `str` (open_id directly) — confirmed from `.venv` source. Not `Member.id.open_id`.
- **completed_at**: Already fixed in previous session (`bool(item.completed_at and item.completed_at != "0")`). No additional change needed.
