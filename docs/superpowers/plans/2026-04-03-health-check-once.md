# Health Check One-Shot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Suppress repeated health alert notifications — fire at most once per silence period, reset when a real Feishu event arrives.

**Architecture:** Add a single boolean flag `_health_alerted` to `FeishuEventListener`. Gate the health notification on this flag. Reset it inside `_remember_event` whenever a real event is processed.

**Tech Stack:** Python asyncio, pytest-asyncio, `unittest.mock`

---

### Task 1: Add `_health_alerted` flag and one-shot logic to `FeishuEventListener`

**Files:**
- Modify: `src/taskarena/events.py`
- Test: `tests/test_events.py` (create new)

---

- [ ] **Step 1: Write the failing test for "alert fires once, then silences"**

Create `tests/test_events.py`:

```python
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
```

- [ ] **Step 2: Run to confirm they fail**

```bash
uv run pytest tests/test_events.py -v
```

Expected: `AttributeError: 'FeishuEventListener' object has no attribute '_check_health'`

- [ ] **Step 3: Implement the changes in `events.py`**

In `__init__`, add the flag (after `self._last_event_at = time.time()`):

```python
self._health_alerted: bool = False
```

Extract the health check into its own method `_check_health` and gate it on the flag. Add reset in `_remember_event`.

Replace the health-check block inside `run` (lines 72–81) and add `_check_health`:

```python
    async def run(self) -> None:
        loop = asyncio.get_running_loop()

        def schedule(coro: Awaitable[None]) -> None:
            loop.call_soon_threadsafe(asyncio.create_task, coro)

        builder = EventDispatcherHandler.builder("", "", lark.LogLevel.INFO)
        handler = builder \
            .register_p2_im_message_receive_v1(lambda event: schedule(self._handle_im_message(event))) \
            .register_p2_task_task_update_tenant_v1(lambda event: schedule(self._handle_task_update(event))) \
            .register_p2_task_task_comment_updated_v1(lambda event: schedule(self._handle_task_comment(event))) \
            .build()

        self._ws_client = lark.ws.Client(
            self.config.app_id,
            self.config.app_secret,
            event_handler=handler,
            log_level=getattr(lark.LogLevel, self.config.log_level, lark.LogLevel.INFO),
        )

        self._thread = threading.Thread(target=self._ws_client.start, name="taskarena-feishu-ws", daemon=True)
        self._thread.start()

        while not self._stop_event.is_set():
            await asyncio.sleep(30)
            if self._thread and not self._thread.is_alive():
                await self.notifier(
                    build_channel_xml(
                        "WebSocket listener stopped unexpectedly. Events may be missed.",
                        source="taskarena",
                        type="health",
                        status="degraded",
                    )
                )
                break

            await self._check_health()

    async def _check_health(self) -> None:
        if time.time() - self._last_event_at > 300 and not self._health_alerted:
            await self.notifier(
                build_channel_xml(
                    "WebSocket has not received events for 5+ minutes.",
                    source="taskarena",
                    type="health",
                    status="degraded",
                )
            )
            self._health_alerted = True
```

In `_remember_event`, add the reset right after the `self._last_event_at = time.time()` line:

```python
        self._last_event_at = time.time()
        self._health_alerted = False
        return True
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
uv run pytest tests/test_events.py -v
```

Expected:
```
tests/test_events.py::test_health_alert_fires_only_once_during_silence PASSED
tests/test_events.py::test_health_alert_resets_after_real_event PASSED
tests/test_events.py::test_health_alert_does_not_fire_when_recent_events PASSED
```

- [ ] **Step 5: Run the full test suite to check for regressions**

```bash
uv run pytest tests/ -v
```

Expected: all existing tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/taskarena/events.py tests/test_events.py
git commit -m "fix: health alert fires once per silence period, resets on new events"
```
