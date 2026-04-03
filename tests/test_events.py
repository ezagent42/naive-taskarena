from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock, patch

import pytest

from taskarena.config import Config
from taskarena.events import FeishuEventListener


def _make_config() -> Config:
    return Config(app_id="test", app_secret="test")


@pytest.mark.asyncio
async def test_health_alert_fires_only_once_during_silence():
    """Health alert should fire once, then stay silent until a real event resets it."""
    notifications = []

    async def notifier(content: str, **_: object) -> None:
        notifications.append(content)

    listener = FeishuEventListener(_make_config(), notifier)
    # Simulate 6 minutes of silence
    listener._last_event_at = time.time() - 360

    # First check — should fire
    await listener._check_health()
    assert len(notifications) == 1
    assert "degraded" in notifications[0]

    # Second check — should NOT fire again (flag is set)
    await listener._check_health()
    assert len(notifications) == 1  # still 1, not 2


@pytest.mark.asyncio
async def test_health_alert_resets_after_real_event():
    """After a real event is remembered, the flag resets and the next silence can alert again."""
    notifications = []

    async def notifier(content: str, **_: object) -> None:
        notifications.append(content)

    listener = FeishuEventListener(_make_config(), notifier)
    listener._last_event_at = time.time() - 360

    # First silence alert
    await listener._check_health()
    assert len(notifications) == 1

    # A real event arrives — resets the flag
    listener._remember_event("event-abc-123")

    # Silence again
    listener._last_event_at = time.time() - 360
    await listener._check_health()
    assert len(notifications) == 2  # now fires again


@pytest.mark.asyncio
async def test_health_alert_does_not_fire_when_recent_events():
    """No alert when events have arrived within the last 5 minutes."""
    notifications = []

    async def notifier(content: str, **_: object) -> None:
        notifications.append(content)

    listener = FeishuEventListener(_make_config(), notifier)
    # Recent event — 2 minutes ago
    listener._last_event_at = time.time() - 120

    await listener._check_health()
    assert notifications == []
