# Health Check One-Shot Design

**Date:** 2026-04-03
**Status:** Approved

## Problem

`FeishuEventListener` fires a `health/degraded` channel notification every 5 minutes whenever no Feishu WebSocket events have been received. This causes Claude Code to wake up and process the notification repeatedly — all night, all weekend — consuming tokens even when there is nothing actionable to do.

## Goal

Reduce unnecessary token consumption by suppressing repeated health alerts when the WebSocket is simply quiet (no Feishu activity), without hiding genuine connection failures.

## Design

### Approach: One-Shot Alert with Auto-Reset

Add a single boolean flag `_health_alerted` to `FeishuEventListener`. Once a health alert is sent, the flag prevents further alerts until a real Feishu event resets it.

**Invariant:** Claude Code receives at most one health alert per "silence period." When events resume, the flag resets so the next silence period can alert again.

### Changes to `events.py`

1. **`__init__`** — add `self._health_alerted: bool = False`

2. **`_remember_event`** — reset the flag when a real event is seen:
   ```python
   self._health_alerted = False
   ```

3. **Health check in `run` loop** — gate on the flag; remove the `_last_event_at` reset that was causing re-fire:
   ```python
   if time.time() - self._last_event_at > 300 and not self._health_alerted:
       await self.notifier(...)
       self._health_alerted = True
       # _last_event_at is NOT reset here — it stays stale until a real event arrives
   ```

### Thread Safety

All accesses to `_health_alerted` occur within the asyncio event loop (the health check loop and the `_handle_*` coroutines are all scheduled on the same loop). No additional synchronization needed.

### No Config Changes

This optimization requires no changes to `.taskarena/config.yaml` or `.env`. Zero user configuration.

## Out of Scope

- Working-hours suppression (not needed given the one-shot approach)
- Exponential backoff (over-engineered for this use case)
- Changes to the scheduler or any other component
