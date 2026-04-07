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

        try:
            h, m = cfg.morning_time.split(":")
            target = now.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
        except (ValueError, TypeError):
            log.error("Invalid morning_time format %r in reminders config — expected HH:MM", cfg.morning_time)
            return
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
