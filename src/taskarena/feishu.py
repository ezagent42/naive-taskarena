import json
import time
from datetime import datetime, timezone
import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest, CreateMessageRequestBody,
    ReplyMessageRequest, ReplyMessageRequestBody,
    CreateMessageReactionRequest, CreateMessageReactionRequestBody,
)
from lark_oapi.api.im.v1.model.emoji import Emoji
from lark_oapi.api.task.v2 import (
    CreateTaskRequest, InputTask,
    PatchTaskRequest,
    TasksTasklistRequest,
    AddTasklistTaskRequest,
    ListTasklistRequest,
    AddMembersTaskRequest,
    GetTaskRequest,
)
from lark_oapi.api.task.v2.model import Due, Member, Start
from lark_oapi.api.task.v2.model.add_tasklist_task_request_body import AddTasklistTaskRequestBody
from lark_oapi.api.task.v2.model.patch_task_request_body import PatchTaskRequestBody
from lark_oapi.api.task.v2.model.add_members_task_request_body import AddMembersTaskRequestBody

from .config import Config
from .log import get_logger

log = get_logger("feishu")


def _due_from_date(due_date: str) -> Due:
    """Convert YYYY-MM-DD string to a Feishu Due object (all-day, end of day UTC ms timestamp)."""
    dt = datetime.strptime(due_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    timestamp_ms = str(int(dt.timestamp() * 1000))
    return Due.builder().timestamp(timestamp_ms).is_all_day(True).build()


def _start_from_date(start_date: str) -> Start:
    """Convert YYYY-MM-DD string to a Feishu Start object (all-day)."""
    dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    timestamp_ms = str(int(dt.timestamp() * 1000))
    return Start.builder().timestamp(timestamp_ms).is_all_day(True).build()

_client = None

def get_client() -> lark.Client:
    """Returns a singleton lark_oapi.Client instance initialized from Config."""
    global _client
    if _client is None:
        cfg = Config.load()
        # Setup logging level based on config
        level = getattr(lark.LogLevel, cfg.log_level, lark.LogLevel.INFO)
        _client = lark.Client.builder() \
            .app_id(cfg.app_id) \
            .app_secret(cfg.app_secret) \
            .log_level(level) \
            .build()
    return _client

async def send_message(chat_id: str, content: str, msg_type: str = "text", receive_id_type: str = "chat_id") -> dict:
    """Send a message to a chat or user."""
    client = get_client()

    if msg_type == "text":
        content_str = json.dumps({"text": content}, ensure_ascii=False)
    else:
        content_str = content  # Assume it's already a valid JSON string for other types

    request = CreateMessageRequest.builder() \
        .receive_id_type(receive_id_type) \
        .request_body(CreateMessageRequestBody.builder()
            .receive_id(chat_id)
            .msg_type(msg_type)
            .content(content_str)
            .build()) \
        .build()

    response = await client.im.v1.message.acreate(request)
    if not response.success():
        raise Exception(f"Feishu API error (send_message): code {response.code}, msg {response.msg}")

    return {"message_id": response.data.message_id}

async def send_reply(message_id: str, content: str, msg_type: str = "text") -> dict:
    """Reply to a specific message."""
    client = get_client()
    
    if msg_type == "text":
        content_str = json.dumps({"text": content}, ensure_ascii=False)
    else:
        content_str = content

    request = ReplyMessageRequest.builder() \
        .message_id(message_id) \
        .request_body(ReplyMessageRequestBody.builder()
            .msg_type(msg_type)
            .content(content_str)
            .build()) \
        .build()

    response = await client.im.v1.message.areply(request)
    if not response.success():
        raise Exception(f"Feishu API error (send_reply): code {response.code}, msg {response.msg}")
    
    return {"message_id": response.data.message_id}

async def react_message(message_id: str, emoji_type: str) -> dict:
    """Add an emoji reaction to a message."""
    client = get_client()
    request = CreateMessageReactionRequest.builder() \
        .message_id(message_id) \
        .request_body(CreateMessageReactionRequestBody.builder()
            .reaction_type(Emoji.builder().emoji_type(emoji_type).build())
            .build()) \
        .build()
        
    response = await client.im.v1.message_reaction.acreate(request)
    if not response.success():
        raise Exception(f"Feishu API error (react_message): code {response.code}, msg {response.msg}")
    return {"success": True}

async def create_task(summary: str, description: str = None, due_date: str = None, assignees: list = None, tasklist_id: str = None) -> dict:
    """Create a task and optionally add it to a tasklist."""
    client = get_client()

    task_builder = InputTask.builder().summary(summary)
    if description:
        task_builder.description(description)
    if due_date:
        task_builder.due(_due_from_date(due_date))

    request = CreateTaskRequest.builder() \
        .user_id_type("open_id") \
        .request_body(task_builder.build()) \
        .build()

    response = await client.task.v2.task.acreate(request)
    if not response.success():
        raise Exception(f"Feishu API error (create_task): code {response.code}, msg {response.msg}")
    
    task_guid = response.data.task.guid
    
    if tasklist_id:
        add_req = AddTasklistTaskRequest.builder()
        add_req.task_guid(task_guid)
        add_req.user_id_type("open_id")
        add_req.request_body(
            AddTasklistTaskRequestBody.builder().tasklist_guid(tasklist_id).build()
        )
        add_resp = await client.task.v2.task.aadd_tasklist(add_req.build())
        if not add_resp.success():
            log.warning("Task %s created, but failed to add to tasklist %s: %s", task_guid, tasklist_id, add_resp.msg)

    return {"task_id": task_guid, "summary": response.data.task.summary}

async def update_task(task_id: str, summary: str = None, description: str = None, due_date: str = None, start_date: str = None) -> dict:
    """Update task attributes."""
    client = get_client()

    task_builder = InputTask.builder()
    update_fields = []
    if summary:
        task_builder.summary(summary)
        update_fields.append("summary")
    if description is not None:
        task_builder.description(description)
        update_fields.append("description")
    if due_date:
        task_builder.due(_due_from_date(due_date))
        update_fields.append("due")
    if start_date:
        task_builder.start(_start_from_date(start_date))
        update_fields.append("start")
    body = PatchTaskRequestBody.builder() \
        .task(task_builder.build()) \
        .update_fields(update_fields) \
        .build()

    request = PatchTaskRequest.builder() \
        .task_guid(task_id) \
        .user_id_type("open_id") \
        .request_body(body) \
        .build()

    response = await client.task.v2.task.apatch(request)
    if not response.success():
        raise Exception(f"Feishu API error (update_task): code {response.code}, msg {response.msg}")

    return {"task_id": task_id, "success": True}


async def add_task_members(task_id: str, assignee_ids: list) -> dict:
    """Add assignees to a task and return task context (summary, due_date)."""
    client = get_client()
    members = [
        Member.builder().id(uid).type("user").role("assignee").build()
        for uid in assignee_ids
    ]
    body = AddMembersTaskRequestBody.builder().members(members).build()
    request = AddMembersTaskRequest.builder() \
        .task_guid(task_id) \
        .user_id_type("open_id") \
        .request_body(body) \
        .build()
    response = await client.task.v2.task.aadd_members(request)
    if not response.success():
        raise Exception(f"Feishu API error (add_task_members): code {response.code}, msg {response.msg}")

    # Fetch task context so Claude can decide whether to ask about start date
    due_date = None
    summary = None
    try:
        get_req = GetTaskRequest.builder() \
            .task_guid(task_id) \
            .user_id_type("open_id") \
            .build()
        get_resp = await client.task.v2.task.aget(get_req)
        if get_resp.success() and get_resp.data and get_resp.data.task:
            task = get_resp.data.task
            summary = task.summary
            if task.due and task.due.timestamp:
                ts_ms = int(task.due.timestamp)
                due_date = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    except Exception:
        log.warning("Failed to fetch task context after assign (task_id=%s)", task_id)

    return {"task_id": task_id, "summary": summary, "due_date": due_date}


async def complete_task(task_id: str) -> dict:
    """Mark a task as complete."""
    client = get_client()

    # Feishu Task V2 uses completed_at timestamp (milliseconds)
    current_time_ms = str(int(time.time() * 1000))

    body = PatchTaskRequestBody.builder() \
        .task(InputTask.builder().completed_at(current_time_ms).build()) \
        .update_fields(["completed_at"]) \
        .build()

    request = PatchTaskRequest.builder() \
        .task_guid(task_id) \
        .user_id_type("open_id") \
        .request_body(body) \
        .build()

    response = await client.task.v2.task.apatch(request)
    if not response.success():
        raise Exception(f"Feishu API error (complete_task): code {response.code}, msg {response.msg}")

    return {"task_id": task_id, "status": "completed"}

async def list_tasks(tasklist_id: str, completed: bool = None, assignee_id: str = None) -> dict:
    """List tasks in a tasklist."""
    client = get_client()
    
    request = TasksTasklistRequest.builder() \
        .tasklist_guid(tasklist_id) \
        .page_size(50) \
        .user_id_type("open_id") \
        .build()

    response = await client.task.v2.tasklist.atasks(request)
    if not response.success():
        raise Exception(f"Feishu API error (list_tasks): code {response.code}, msg {response.msg}")
    
    tasks = []
    if response.data and response.data.items:
        for item in response.data.items:
            # items are TaskSummary objects directly (no .task wrapper)
            # completed_at may be int 0 or string "0" for incomplete; nonzero/non-"0" = completed
            is_completed = bool(item.completed_at and item.completed_at != "0")
            if completed is not None and is_completed != completed:
                continue

            assignees = [
                m.id for m in (item.members or [])
                if m.role == "assignee" and m.id
            ]
            if assignee_id and assignee_id not in assignees:
                continue
            tasks.append({
                "task_id": item.guid,
                "summary": item.summary,
                "is_completed": is_completed,
                "assignees": assignees,
            })

    return {"tasks": tasks, "total": len(tasks)}


async def list_tasklists() -> dict:
    """List visible tasklists for the current app credentials."""
    client = get_client()
    request = ListTasklistRequest.builder() \
        .page_size(50) \
        .user_id_type("open_id") \
        .build()

    response = await client.task.v2.tasklist.alist(request)
    if not response.success():
        raise Exception(f"Feishu API error (list_tasklists): code {response.code}, msg {response.msg}")

    tasklists = []
    if response.data and response.data.items:
        for item in response.data.items:
            tasklists.append({
                "id": item.guid,
                "name": item.name,
                "url": item.url,
            })

    return {"tasklists": tasklists}

async def search_users(query: str) -> dict:
    """Search organization members from the local users cache."""
    cfg = Config.load()
    normalized_query = query.strip().casefold()

    if not normalized_query:
        return {"users": []}

    users = []
    for open_id, name in cfg.users.items():
        if not isinstance(name, str):
            continue
        if normalized_query not in name.casefold() and normalized_query not in open_id.casefold():
            continue
        users.append({
            "open_id": open_id,
            "name": name,
            "department_ids": [],
        })

    users.sort(key=lambda item: item["name"])
    return {"users": users[:20]}
