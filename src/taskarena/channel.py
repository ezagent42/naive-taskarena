from __future__ import annotations

import asyncio
import json
import signal
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any

import anyio
import mcp.types as types
from anyio.streams.memory import MemoryObjectSendStream
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.shared.message import SessionMessage

from .config import Config
from .events import FeishuEventListener
from .log import get_logger
from .scheduler import TaskArenaScheduler
from .tools import call_tool, list_tools

log = get_logger("channel")


@dataclass
class ChannelNotifier:
    write_stream: MemoryObjectSendStream[SessionMessage]
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def emit(self, content: str, **meta: Any) -> None:
        payload = {"content": content}
        if meta:
            payload["meta"] = meta

        notification = types.JSONRPCNotification(
            jsonrpc="2.0",
            method="notifications/claude/channel",
            params=payload,
        )
        try:
            async with self.lock:
                await self.write_stream.send(SessionMessage(message=types.JSONRPCMessage(notification)))
            log.debug("Channel notification sent: %s", content[:80])
        except Exception:
            log.warning("Failed to send channel notification: %s", content[:80], exc_info=True)


def create_server() -> Server:
    server: Server = Server("taskarena", instructions="Feishu task management bridge for Claude Code.")

    @server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        return list_tools()

    @server.call_tool(validate_input=True)
    async def handle_call_tool(name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
        return await call_tool(name, arguments)

    return server


async def run_channel_server() -> None:
    server = create_server()

    async with stdio_server() as (read_stream, write_stream):
        notifier = ChannelNotifier(write_stream=write_stream)
        stop_event = asyncio.Event()

        def _request_stop(*_: object) -> None:
            stop_event.set()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            with suppress(NotImplementedError):
                loop.add_signal_handler(sig, _request_stop)

        async def _run_background(factory: Callable[[], Awaitable[None]]) -> None:
            try:
                await factory()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Background task failed")

        event_listener = FeishuEventListener(Config.load(), notifier.emit)
        scheduler = TaskArenaScheduler(Config.load(), notifier.emit)

        async def _run_server() -> None:
            await server.run(
                read_stream,
                write_stream,
                InitializationOptions(
                    server_name="taskarena",
                    server_version="0.1.0",
                    capabilities=server.get_capabilities(
                        notification_options=NotificationOptions(),
                        experimental_capabilities={"claude/channel": {}},
                    ),
                    instructions="TaskArena exposes Feishu task tools and channel notifications.",
                ),
            )
            # stdin closed (Claude exited) — trigger graceful shutdown
            stop_event.set()

        async with anyio.create_task_group() as tg:
            tg.start_soon(_run_server)
            tg.start_soon(_run_background, event_listener.run)
            tg.start_soon(_run_background, scheduler.run)

            await stop_event.wait()
            await event_listener.stop()
            await scheduler.stop()
            tg.cancel_scope.cancel()


def main() -> None:
    asyncio.run(run_channel_server())
