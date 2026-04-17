"""
Morning Reminder Lifecycle Test

Simulates the complete flow:
  1. Config loads reminders section correctly
  2. Scheduler fires at morning_time and sends DMs to assignees
  3. Each assignee DM contains the right task info
  4. Assignees not in allowed_users are skipped
  5. Tasks without assignees are skipped
  6. feishu.update_task + complete_task are available for the completion flow
  7. reply tool with receive_id_type="open_id" works end-to-end through call_tool
"""
from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from taskarena.config import Config, ReminderConfig
from taskarena.scheduler import TaskArenaScheduler
from taskarena import feishu
from taskarena.tools import call_tool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _config_with_reminders(tmp_path: Path, yaml_content: str) -> Config:
    (tmp_path / ".taskarena").mkdir(exist_ok=True)
    (tmp_path / ".taskarena" / "config.yaml").write_text(yaml_content)
    with mock.patch.dict(os.environ, {"FEISHU_APP_ID": "id", "FEISHU_APP_SECRET": "secret"}):
        import os as _os
        old_cwd = _os.getcwd()
        _os.chdir(tmp_path)
        try:
            return Config.load()
        finally:
            _os.chdir(old_cwd)


# ---------------------------------------------------------------------------
# Phase 1: Config loading
# ---------------------------------------------------------------------------

def test_lifecycle_config_loads_reminders(tmp_path):
    """Config correctly loads the reminders block from YAML."""
    config = _config_with_reminders(tmp_path, """\
reminders:
  morning_time: "08:00"
  timezone: "Asia/Shanghai"
  tasklists:
    - "tl-abc"
""")
    assert config.reminders is not None
    assert config.reminders.morning_time == "08:00"
    assert config.reminders.timezone == "Asia/Shanghai"
    assert config.reminders.tasklists == ["tl-abc"]


def test_lifecycle_config_no_reminders_disables_feature(tmp_path):
    """Without a reminders block, the feature is disabled."""
    config = _config_with_reminders(tmp_path, "tasklists: []\n")
    assert config.reminders is None


# ---------------------------------------------------------------------------
# Phase 2: Scheduler fires and sends DMs
# ---------------------------------------------------------------------------

MOCK_TASKS = {
    "tasks": [
        {
            "task_id": "task-001",
            "summary": "完成飞书集成",
            "is_completed": False,
            "assignees": ["ou_alice"],
        },
        {
            "task_id": "task-002",
            "summary": "写单元测试",
            "is_completed": False,
            "assignees": ["ou_alice", "ou_bob"],
        },
        {
            "task_id": "task-003",
            "summary": "无负责人任务",
            "is_completed": False,
            "assignees": [],
        },
        {
            "task_id": "task-004",
            "summary": "外部用户任务",
            "is_completed": False,
            "assignees": ["ou_external"],  # not in allowed_users
        },
    ],
    "total": 4,
}


@pytest.mark.asyncio
async def test_lifecycle_scheduler_sends_dm_to_each_assignee():
    """Scheduler sends one DM per assignee (grouping multiple tasks)."""
    config = Config(
        app_id="test",
        app_secret="test",
        tasklists=[{"id": "tl-001", "name": "Main"}],
        allowed_users=["ou_alice", "ou_bob"],
        reminders=ReminderConfig(
            morning_time="00:00",  # already past
            timezone="UTC",
        ),
    )
    scheduler = TaskArenaScheduler(config, mock.AsyncMock())

    sent_dms: list[tuple[str, str]] = []  # (open_id, message)

    async def mock_send_message(open_id, message, receive_id_type="chat_id"):
        sent_dms.append((open_id, message))
        return {"message_id": f"msg-{open_id}"}

    with mock.patch("taskarena.scheduler.feishu") as mock_feishu:
        mock_feishu.list_tasks = mock.AsyncMock(return_value=MOCK_TASKS)
        mock_feishu.send_message = mock_send_message

        await scheduler._check_morning_reminders()

    # Two DMs sent: one to ou_alice, one to ou_bob
    assert len(sent_dms) == 2
    recipients = {dm[0] for dm in sent_dms}
    assert recipients == {"ou_alice", "ou_bob"}

    # ou_external was skipped (not in allowed_users)
    # unassigned task-003 was skipped


@pytest.mark.asyncio
async def test_lifecycle_dm_content_lists_all_user_tasks():
    """ou_alice's DM lists both her tasks."""
    config = Config(
        app_id="test",
        app_secret="test",
        tasklists=[{"id": "tl-001", "name": "Main"}],
        allowed_users=["ou_alice", "ou_bob"],
        reminders=ReminderConfig(morning_time="00:00", timezone="UTC"),
    )
    scheduler = TaskArenaScheduler(config, mock.AsyncMock())

    alice_message = None

    async def mock_send_message(open_id, message, receive_id_type="chat_id"):
        nonlocal alice_message
        if open_id == "ou_alice":
            alice_message = message
        return {"message_id": "m1"}

    with mock.patch("taskarena.scheduler.feishu") as mock_feishu:
        mock_feishu.list_tasks = mock.AsyncMock(return_value=MOCK_TASKS)
        mock_feishu.send_message = mock_send_message
        await scheduler._check_morning_reminders()

    assert alice_message is not None
    # Both her tasks appear in the message
    assert "完成飞书集成" in alice_message
    assert "task-001" in alice_message
    assert "写单元测试" in alice_message
    assert "task-002" in alice_message


@pytest.mark.asyncio
async def test_lifecycle_dm_uses_open_id_receive_type():
    """DMs are sent with receive_id_type='open_id' (not 'chat_id')."""
    config = Config(
        app_id="test",
        app_secret="test",
        tasklists=[{"id": "tl-001", "name": "Main"}],
        allowed_users=["ou_alice"],
        reminders=ReminderConfig(morning_time="00:00", timezone="UTC"),
    )
    scheduler = TaskArenaScheduler(config, mock.AsyncMock())

    tasks = {"tasks": [{"task_id": "t1", "summary": "Task", "is_completed": False, "assignees": ["ou_alice"]}], "total": 1}

    with mock.patch("taskarena.scheduler.feishu") as mock_feishu:
        mock_feishu.list_tasks = mock.AsyncMock(return_value=tasks)
        mock_feishu.send_message = mock.AsyncMock(return_value={"message_id": "m1"})
        await scheduler._check_morning_reminders()

    call = mock_feishu.send_message.call_args
    assert call.args[0] == "ou_alice"          # first positional arg is open_id
    assert call.kwargs.get("receive_id_type") == "open_id"


# ---------------------------------------------------------------------------
# Phase 3: Completion flow — reply tool sends DM back to user
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_lifecycle_reply_tool_can_send_dm_by_open_id():
    """
    When Claude calls reply with receive_id_type='open_id', it sends a DM
    directly to the user (not a group chat). This simulates Claude's response
    after an assignee replies to the morning reminder.
    """
    mock_response = {"message_id": "reply-001"}

    with mock.patch.object(feishu, "send_message", new=mock.AsyncMock(return_value=mock_response)) as m:
        result = await call_tool("reply", {
            "chat_id": "ou_alice",
            "message": "✅ 任务「完成飞书集成」已标记完成，文档链接已记录。",
            "receive_id_type": "open_id",
        })

    assert result == mock_response
    m.assert_called_once_with(
        chat_id="ou_alice",
        content="✅ 任务「完成飞书集成」已标记完成，文档链接已记录。",
        msg_type="text",
        receive_id_type="open_id",
    )


@pytest.mark.asyncio
async def test_lifecycle_update_task_appends_completion_doc():
    """
    update_task is available for Claude to append a completion doc link
    to the task description.
    """
    mock_response = {"task_id": "task-001", "success": True}

    with mock.patch.object(feishu, "update_task", new=mock.AsyncMock(return_value=mock_response)) as m:
        result = await call_tool("update_task", {
            "task_id": "task-001",
            "description": "原始描述\n完成文档：https://docs.example.com/result",
        })

    assert result == mock_response
    m.assert_called_once_with(
        task_id="task-001",
        summary=None,
        description="原始描述\n完成文档：https://docs.example.com/result",
        due_date=None,
        start_date=None,
    )


@pytest.mark.asyncio
async def test_lifecycle_complete_task_marks_done():
    """complete_task is available for Claude to mark a task as done."""
    mock_response = {"task_id": "task-001", "status": "completed"}

    with mock.patch.object(feishu, "complete_task", new=mock.AsyncMock(return_value=mock_response)) as m:
        result = await call_tool("complete_task", {"task_id": "task-001"})

    assert result == mock_response
    m.assert_called_once_with(task_id="task-001")


# ---------------------------------------------------------------------------
# Phase 4: Edge cases
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_lifecycle_malformed_morning_time_does_not_crash():
    """A bad morning_time logs an error and returns gracefully."""
    config = Config(
        app_id="test",
        app_secret="test",
        reminders=ReminderConfig(morning_time="9am", timezone="UTC"),
    )
    scheduler = TaskArenaScheduler(config, mock.AsyncMock())

    with mock.patch("taskarena.scheduler.feishu") as mock_feishu:
        mock_feishu.list_tasks = mock.AsyncMock()
        # Should not raise
        await scheduler._check_morning_reminders()
        mock_feishu.list_tasks.assert_not_called()


@pytest.mark.asyncio
async def test_lifecycle_list_tasks_failure_is_handled():
    """A feishu API failure for one tasklist does not abort other tasklists."""
    config = Config(
        app_id="test",
        app_secret="test",
        tasklists=[{"id": "tl-fail", "name": "Fail"}, {"id": "tl-ok", "name": "OK"}],
        allowed_users=["ou_alice"],
        reminders=ReminderConfig(morning_time="00:00", timezone="UTC"),
    )
    scheduler = TaskArenaScheduler(config, mock.AsyncMock())

    ok_tasks = {"tasks": [{"task_id": "t1", "summary": "OK task", "is_completed": False, "assignees": ["ou_alice"]}], "total": 1}

    async def list_tasks_side_effect(tasklist_id, completed=None):
        if tasklist_id == "tl-fail":
            raise RuntimeError("Feishu API error")
        return ok_tasks

    with mock.patch("taskarena.scheduler.feishu") as mock_feishu:
        mock_feishu.list_tasks = list_tasks_side_effect
        mock_feishu.send_message = mock.AsyncMock(return_value={"message_id": "m1"})
        await scheduler._check_morning_reminders()

    # DM still sent for the successful tasklist
    mock_feishu.send_message.assert_called_once()
