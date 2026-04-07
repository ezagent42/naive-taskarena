from __future__ import annotations

import asyncio
import os
from datetime import date, datetime, timedelta
from unittest import mock

import pytest

from taskarena.scheduler import TaskArenaScheduler
from taskarena.config import Config, ReminderConfig


def _make_config(schedules: list) -> Config:
    return Config(
        app_id="test",
        app_secret="test",
        schedules=schedules,
    )


@pytest.mark.asyncio
async def test_scheduler_fires_overdue_schedule():
    notifications = []

    async def notifier(content: str, **_: object) -> None:
        notifications.append(content)

    # Use a cron that ran 2 minutes ago — scheduler should fire it immediately
    two_min_ago = datetime.now().astimezone() - timedelta(minutes=2)
    # Build a cron that matches "two minutes ago" — use minute/hour that is now past
    # Simpler: patch _prime_next_runs to set next_run in the past
    config = _make_config([
        {"name": "test-job", "cron": "* * * * *", "prompt": "do the thing"},
    ])
    scheduler = TaskArenaScheduler(config, notifier)

    # Force next_run to be in the past so _tick fires immediately
    scheduler._next_run["test-job"] = two_min_ago

    await scheduler._tick()

    assert len(notifications) == 1
    assert "do the thing" in notifications[0]


@pytest.mark.asyncio
async def test_scheduler_does_not_fire_future_schedule():
    notifications = []

    async def notifier(content: str, **_: object) -> None:
        notifications.append(content)

    config = _make_config([
        {"name": "future-job", "cron": "* * * * *", "prompt": "future"},
    ])
    scheduler = TaskArenaScheduler(config, notifier)

    # Force next_run to be 1 hour in the future
    scheduler._next_run["future-job"] = datetime.now().astimezone() + timedelta(hours=1)

    await scheduler._tick()

    assert notifications == []


@pytest.mark.asyncio
async def test_scheduler_skips_incomplete_schedule():
    notifications = []

    async def notifier(content: str, **_: object) -> None:
        notifications.append(content)

    # Schedule missing 'prompt'
    config = _make_config([
        {"name": "bad-job", "cron": "* * * * *"},
    ])
    scheduler = TaskArenaScheduler(config, notifier)
    scheduler._next_run["bad-job"] = datetime.now().astimezone() - timedelta(minutes=1)

    await scheduler._tick()
    assert notifications == []


@pytest.mark.asyncio
async def test_scheduler_primes_next_runs():
    config = _make_config([
        {"name": "job1", "cron": "0 9 * * *", "prompt": "morning"},
        {"name": "job2", "cron": "0 18 * * *", "prompt": "evening"},
    ])
    scheduler = TaskArenaScheduler(config, lambda *a, **k: None)
    scheduler._prime_next_runs()

    assert "job1" in scheduler._next_run
    assert "job2" in scheduler._next_run
    now = datetime.now().astimezone()
    assert scheduler._next_run["job1"] > now
    assert scheduler._next_run["job2"] > now


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
        assert "Fix bug" in call_kwargs.args[1]


@pytest.mark.asyncio
async def test_morning_reminder_fires_only_once_per_day():
    config = _make_config_with_reminders(morning_time="00:00")
    scheduler = TaskArenaScheduler(config, None)

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


@pytest.mark.asyncio
async def test_morning_reminder_skips_users_not_in_allowed_users():
    config = _make_config_with_reminders(morning_time="00:00")
    # Only ou_alice and ou_bob are in allowed_users (from _make_config_with_reminders)
    scheduler = TaskArenaScheduler(config, None)

    mock_tasks = {
        "tasks": [
            {"task_id": "t-1", "summary": "Task for charlie", "is_completed": False, "assignees": ["ou_charlie"]},
        ],
        "total": 1,
    }

    with mock.patch("taskarena.scheduler.feishu") as mock_feishu:
        mock_feishu.list_tasks = mock.AsyncMock(return_value=mock_tasks)
        mock_feishu.send_message = mock.AsyncMock()

        await scheduler._check_morning_reminders()

        mock_feishu.send_message.assert_not_called()
