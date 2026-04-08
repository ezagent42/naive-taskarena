from __future__ import annotations

from typing import Any

import mcp.types as types

from .config import Config
from . import feishu


def _tool(name: str, description: str, properties: dict[str, Any], required: list[str] | None = None) -> types.Tool:
    return types.Tool(
        name=name,
        description=description,
        inputSchema={
            "type": "object",
            "properties": properties,
            "required": required or [],
            "additionalProperties": False,
        },
    )


TOOLS: list[types.Tool] = [
    _tool(
        "reply",
        "Send a reply to a Feishu chat or reply to a specific Feishu message.",
        {
            "chat_id": {"type": "string"},
            "message": {"type": "string"},
            "message_id": {"type": "string"},
            "msg_type": {"type": "string", "default": "text"},
            "receive_id_type": {"type": "string", "default": "chat_id", "enum": ["chat_id", "open_id", "user_id", "union_id"]},
        },
        ["message"],
    ),
    _tool(
        "react",
        "Add an emoji reaction to a Feishu message.",
        {
            "message_id": {"type": "string"},
            "emoji_type": {"type": "string"},
        },
        ["message_id", "emoji_type"],
    ),
    _tool(
        "create_task",
        "Create a Feishu task in the default or specified tasklist.",
        {
            "summary": {"type": "string"},
            "description": {"type": "string"},
            "due_date": {"type": "string", "description": "Due date in YYYY-MM-DD format"},
            "tasklist_id": {"type": "string"},
        },
        ["summary"],
    ),
    _tool(
        "update_task",
        "Update a Feishu task.",
        {
            "task_id": {"type": "string"},
            "summary": {"type": "string"},
            "description": {"type": "string"},
            "due_date": {"type": "string", "description": "Due date in YYYY-MM-DD format"},
            "start_date": {"type": "string", "description": "Start date in YYYY-MM-DD format"},
        },
        ["task_id"],
    ),
    _tool(
        "assign_task",
        "Add assignees to a Feishu task. Use this when a user wants to claim or be assigned to a task.",
        {
            "task_id": {"type": "string"},
            "assignee_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of assignee open_ids to add",
            },
        },
        ["task_id", "assignee_ids"],
    ),
    _tool(
        "complete_task",
        "Mark a Feishu task as completed.",
        {"task_id": {"type": "string"}},
        ["task_id"],
    ),
    _tool(
        "list_tasks",
        "List tasks from a Feishu tasklist. Use assignee_id to filter tasks assigned to a specific user.",
        {
            "tasklist_id": {"type": "string"},
            "completed": {"type": "boolean"},
            "assignee_id": {"type": "string", "description": "Filter by assignee open_id"},
        },
    ),
    _tool(
        "search_users",
        "Search organization users from the local TaskArena user cache.",
        {"query": {"type": "string"}},
        ["query"],
    ),
    _tool(
        "get_config",
        "Return sanitized TaskArena configuration.",
        {},
    ),
]


def list_tools() -> list[types.Tool]:
    return TOOLS


def _sanitize_config(config: Config) -> dict[str, Any]:
    return {
        "tasklists": config.tasklists,
        "allowed_users": config.allowed_users,
        "schedules": config.schedules,
        "users_count": len(config.users),
        "log_level": config.log_level,
    }


async def call_tool(name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    args = arguments or {}

    if name == "reply":
        message = args["message"]
        msg_type = args.get("msg_type", "text")
        message_id = args.get("message_id")
        receive_id_type = args.get("receive_id_type", "chat_id")
        if message_id:
            return await feishu.send_reply(message_id=message_id, content=message, msg_type=msg_type)
        return await feishu.send_message(
            chat_id=args["chat_id"],
            content=message,
            msg_type=msg_type,
            receive_id_type=receive_id_type,
        )

    if name == "react":
        return await feishu.react_message(message_id=args["message_id"], emoji_type=args["emoji_type"])

    if name == "create_task":
        config = Config.load()
        tasklist_id = args.get("tasklist_id") or (config.tasklists[0]["id"] if config.tasklists else None)
        return await feishu.create_task(
            summary=args["summary"],
            description=args.get("description"),
            due_date=args.get("due_date"),
            tasklist_id=tasklist_id,
        )

    if name == "update_task":
        return await feishu.update_task(
            task_id=args["task_id"],
            summary=args.get("summary"),
            description=args.get("description"),
            due_date=args.get("due_date"),
            start_date=args.get("start_date"),
        )

    if name == "assign_task":
        return await feishu.add_task_members(
            task_id=args["task_id"],
            assignee_ids=args["assignee_ids"],
        )

    if name == "complete_task":
        return await feishu.complete_task(task_id=args["task_id"])

    if name == "list_tasks":
        config = Config.load()
        tasklist_id = args.get("tasklist_id") or (config.tasklists[0]["id"] if config.tasklists else None)
        if not tasklist_id:
            raise ValueError("No tasklist_id provided and no default tasklist configured.")
        return await feishu.list_tasks(
            tasklist_id=tasklist_id,
            completed=args.get("completed"),
            assignee_id=args.get("assignee_id"),
        )

    if name == "search_users":
        return await feishu.search_users(query=args["query"])

    if name == "get_config":
        return _sanitize_config(Config.load())

    raise ValueError(f"Unknown tool: {name}")
