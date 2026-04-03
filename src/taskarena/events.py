from __future__ import annotations

import asyncio
import json
import threading
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from typing import Any

import lark_oapi as lark
from lark_oapi.api.im.v1.model.p2_im_message_receive_v1 import P2ImMessageReceiveV1
from lark_oapi.api.task.v1.model.p2_task_task_comment_updated_v1 import P2TaskTaskCommentUpdatedV1
from lark_oapi.api.task.v1.model.p2_task_task_update_tenant_v1 import P2TaskTaskUpdateTenantV1
from lark_oapi.event.dispatcher_handler import EventDispatcherHandler

from .channel_format import build_channel_xml
from .config import Config
from .log import get_logger

log = get_logger("events")

Notifier = Callable[..., Awaitable[None]]


class FeishuEventListener:
    def __init__(self, config: Config, notifier: Notifier) -> None:
        self.config = config
        self.notifier = notifier
        self._stop_event = asyncio.Event()
        self._last_event_at = time.time()
        self._event_ids: OrderedDict[str, None] = OrderedDict()
        self._thread: threading.Thread | None = None
        self._ws_client: lark.ws.Client | None = None

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

            if time.time() - self._last_event_at > 300:
                await self.notifier(
                    build_channel_xml(
                        "WebSocket has not received events for 5+ minutes.",
                        source="taskarena",
                        type="health",
                        status="degraded",
                    )
                )
                self._last_event_at = time.time()

    async def stop(self) -> None:
        self._stop_event.set()

    def _remember_event(self, event_id: str | None) -> bool:
        if not event_id:
            return True
        if event_id in self._event_ids:
            return False
        self._event_ids[event_id] = None
        self._event_ids.move_to_end(event_id)
        while len(self._event_ids) > 1000:
            self._event_ids.popitem(last=False)
        self._last_event_at = time.time()
        return True

    async def _handle_im_message(self, event: P2ImMessageReceiveV1) -> None:
        if not self._remember_event(getattr(event.header, "event_id", None)):
            return

        sender = getattr(getattr(event.event, "sender", None), "sender_id", None)
        open_id = getattr(sender, "open_id", None)
        if self.config.allowed_users and open_id not in self.config.allowed_users:
            log.debug("Dropping message from non-allowlisted user: %s", open_id)
            return

        message = getattr(event.event, "message", None)
        content = _extract_message_text(getattr(message, "content", None))
        user_name = self.config.users.get(open_id or "", open_id or "unknown")
        xml = build_channel_xml(
            content,
            source="taskarena",
            type="user_message",
            chat_id=getattr(message, "chat_id", None),
            message_id=getattr(message, "message_id", None),
            user=user_name,
        )
        await self.notifier(xml)

    async def _handle_task_update(self, event: P2TaskTaskUpdateTenantV1) -> None:
        if not self._remember_event(getattr(event.header, "event_id", None)):
            return

        evt = event.event
        actor_names = []
        uid_list_obj = getattr(evt, "user_id_list", None)
        user_id_entries = getattr(uid_list_obj, "user_id_list", None) or []
        for uid in user_id_entries:
            open_id = getattr(uid, "open_id", None)
            if open_id:
                actor_names.append(self.config.users.get(open_id, open_id))

        xml = build_channel_xml(
            f"任务 {evt.task_id} 收到更新事件。",
            source="taskarena",
            type="task_event",
            event_type=getattr(evt, "event_type", None),
            obj_type=getattr(evt, "object_type", None),
            task_id=getattr(evt, "task_id", None),
            assignees=",".join(actor_names) if actor_names else None,
        )
        await self.notifier(xml)

    async def _handle_task_comment(self, event: P2TaskTaskCommentUpdatedV1) -> None:
        if not self._remember_event(getattr(event.header, "event_id", None)):
            return

        evt = event.event
        xml = build_channel_xml(
            f"任务 {evt.task_id} 的评论已更新。",
            source="taskarena",
            type="task_event",
            event_type="comment_updated",
            obj_type=getattr(evt, "obj_type", None),
            task_id=getattr(evt, "task_id", None),
            comment_id=getattr(evt, "comment_id", None),
        )
        await self.notifier(xml)


def _extract_message_text(raw_content: str | None) -> str:
    if not raw_content:
        return ""
    try:
        payload = json.loads(raw_content)
    except json.JSONDecodeError:
        return raw_content
    if isinstance(payload, dict):
        return str(payload.get("text") or payload.get("content") or raw_content)
    return raw_content
