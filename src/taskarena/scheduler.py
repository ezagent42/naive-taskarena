from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from croniter import croniter

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

    async def run(self) -> None:
        self._prime_next_runs()
        while not self._stop_event.is_set():
            await self._tick()
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
