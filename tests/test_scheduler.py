from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta
from unittest import mock

import pytest

from taskarena.scheduler import TaskArenaScheduler
from taskarena.config import Config


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
    from datetime import datetime, timedelta
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
