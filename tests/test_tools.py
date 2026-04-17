from __future__ import annotations

import os
from unittest import mock

import pytest

from taskarena.tools import list_tools, call_tool
from taskarena import feishu


def test_list_tools_returns_all_eight():
    tools = list_tools()
    names = {t.name for t in tools}
    assert names == {"reply", "react", "create_task", "update_task", "complete_task", "list_tasks", "assign_task", "search_users", "get_config"}


def test_list_tools_have_input_schemas():
    for tool in list_tools():
        assert tool.inputSchema is not None
        assert tool.inputSchema["type"] == "object"


@pytest.mark.asyncio
@mock.patch.dict(os.environ, {"FEISHU_APP_ID": "test", "FEISHU_APP_SECRET": "test"})
async def test_call_tool_reply_with_message_id():
    with mock.patch("taskarena.tools.feishu.send_reply", return_value={"message_id": "mid123"}) as m:
        result = await call_tool("reply", {"message": "hello", "message_id": "mid123"})
    m.assert_called_once_with(message_id="mid123", content="hello", msg_type="text")
    assert result["message_id"] == "mid123"


@pytest.mark.asyncio
@mock.patch.dict(os.environ, {"FEISHU_APP_ID": "test", "FEISHU_APP_SECRET": "test"})
async def test_call_tool_reply_with_chat_id():
    with mock.patch("taskarena.tools.feishu.send_message", return_value={"message_id": "mid456"}) as m:
        result = await call_tool("reply", {"message": "hello", "chat_id": "cid789"})
    m.assert_called_once_with(chat_id="cid789", content="hello", msg_type="text", receive_id_type="chat_id")
    assert result["message_id"] == "mid456"


@pytest.mark.asyncio
@mock.patch.dict(os.environ, {"FEISHU_APP_ID": "test", "FEISHU_APP_SECRET": "test"})
async def test_call_tool_react():
    with mock.patch("taskarena.tools.feishu.react_message", return_value={"success": True}) as m:
        result = await call_tool("react", {"message_id": "mid1", "emoji_type": "THUMBSUP"})
    m.assert_called_once_with(message_id="mid1", emoji_type="THUMBSUP")
    assert result["success"] is True


@pytest.mark.asyncio
@mock.patch.dict(os.environ, {"FEISHU_APP_ID": "test", "FEISHU_APP_SECRET": "test"})
async def test_call_tool_complete_task():
    with mock.patch("taskarena.tools.feishu.complete_task", return_value={"task_id": "t1", "status": "completed"}) as m:
        result = await call_tool("complete_task", {"task_id": "t1"})
    m.assert_called_once_with(task_id="t1")
    assert result["status"] == "completed"


@pytest.mark.asyncio
@mock.patch.dict(os.environ, {"FEISHU_APP_ID": "test", "FEISHU_APP_SECRET": "test"})
async def test_call_tool_search_users():
    with mock.patch("taskarena.tools.feishu.search_users", return_value={"users": []}) as m:
        result = await call_tool("search_users", {"query": "Alice"})
    m.assert_called_once_with(query="Alice")
    assert "users" in result


@pytest.mark.asyncio
@mock.patch.dict(os.environ, {"FEISHU_APP_ID": "test", "FEISHU_APP_SECRET": "test"})
async def test_call_tool_get_config():
    result = await call_tool("get_config", {})
    assert "tasklists" in result
    assert "allowed_users" in result
    assert "app_id" not in result
    assert "app_secret" not in result


@pytest.mark.asyncio
async def test_call_tool_unknown_raises():
    with pytest.raises(ValueError, match="Unknown tool"):
        await call_tool("nonexistent_tool", {})


@pytest.mark.asyncio
async def test_update_task_with_start_date():
    mock_response = {"task_id": "task-001", "success": True}
    with mock.patch.object(feishu, "update_task", new=mock.AsyncMock(return_value=mock_response)) as m:
        result = await call_tool("update_task", {
            "task_id": "task-001",
            "start_date": "2026-04-15",
        })
    assert result == mock_response
    m.assert_called_once_with(
        task_id="task-001",
        summary=None,
        description=None,
        due_date=None,
        start_date="2026-04-15",
    )


def test_reply_tool_has_receive_id_type_field():
    tools = {t.name: t for t in list_tools()}
    reply = tools["reply"]
    assert "receive_id_type" in reply.inputSchema["properties"]


@pytest.mark.asyncio
@mock.patch.dict(os.environ, {"FEISHU_APP_ID": "test", "FEISHU_APP_SECRET": "test"})
async def test_reply_tool_passes_receive_id_type_to_feishu():
    with mock.patch("taskarena.tools.feishu.send_message", return_value={"message_id": "msg-001"}) as m:
        result = await call_tool("reply", {
            "chat_id": "ou_abc",
            "message": "hello",
            "receive_id_type": "open_id",
        })
        m.assert_called_once_with(
            chat_id="ou_abc",
            content="hello",
            msg_type="text",
            receive_id_type="open_id",
        )
        assert result["message_id"] == "msg-001"


@pytest.mark.asyncio
@mock.patch.dict(os.environ, {"FEISHU_APP_ID": "test", "FEISHU_APP_SECRET": "test"})
async def test_reply_tool_defaults_receive_id_type_to_chat_id():
    with mock.patch("taskarena.tools.feishu.send_message", return_value={"message_id": "msg-002"}) as m:
        result = await call_tool("reply", {
            "chat_id": "chat_abc",
            "message": "hi",
        })
        m.assert_called_once_with(
            chat_id="chat_abc",
            content="hi",
            msg_type="text",
            receive_id_type="chat_id",
        )
        assert result["message_id"] == "msg-002"


@pytest.mark.asyncio
@mock.patch.dict(os.environ, {"FEISHU_APP_ID": "test", "FEISHU_APP_SECRET": "test"})
async def test_assign_task_returns_task_context():
    """assign_task should return summary and due_date from the task."""
    mock_response = {
        "task_id": "task-001",
        "summary": "Fix login bug",
        "due_date": "2026-04-20",
    }
    with mock.patch.object(feishu, "add_task_members", new=mock.AsyncMock(return_value=mock_response)) as m:
        result = await call_tool("assign_task", {
            "task_id": "task-001",
            "assignee_ids": ["ou_abc123"],
        })
    assert result["summary"] == "Fix login bug"
    assert result["due_date"] == "2026-04-20"


@pytest.mark.asyncio
@mock.patch.dict(os.environ, {"FEISHU_APP_ID": "test", "FEISHU_APP_SECRET": "test"})
async def test_assign_task_returns_null_due_date_when_absent():
    """assign_task returns due_date=None when task has no due date."""
    mock_response = {
        "task_id": "task-001",
        "summary": "Fix login bug",
        "due_date": None,
    }
    with mock.patch.object(feishu, "add_task_members", new=mock.AsyncMock(return_value=mock_response)) as m:
        result = await call_tool("assign_task", {
            "task_id": "task-001",
            "assignee_ids": ["ou_abc123"],
        })
    assert result["due_date"] is None
