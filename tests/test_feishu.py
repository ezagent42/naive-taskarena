import importlib
from unittest import mock


def test_feishu_module_imports():
    module = importlib.import_module("taskarena.feishu")
    assert module is not None


def test_runtime_modules_import():
    for module_name in [
        "taskarena.tools",
        "taskarena.channel",
        "taskarena.events",
        "taskarena.scheduler",
        "taskarena.__main__",
    ]:
        assert importlib.import_module(module_name) is not None


def test_list_tasks_includes_assignees():
    """list_tasks returns assignees field with open_ids of members with role='assignee'."""
    from taskarena import feishu
    from lark_oapi.api.task.v2.model.task_summary import TaskSummary
    from lark_oapi.api.task.v2.model.member import Member

    assignee = Member()
    assignee.id = "ou_abc"
    assignee.role = "assignee"

    follower = Member()
    follower.id = "ou_def"
    follower.role = "follower"

    task = TaskSummary()
    task.guid = "task-001"
    task.summary = "Fix the bug"
    task.completed_at = 0
    task.members = [assignee, follower]

    mock_response = mock.MagicMock()
    mock_response.success.return_value = True
    mock_response.data.items = [task]

    mock_client = mock.MagicMock()
    mock_client.task.v2.tasklist.atasks = mock.AsyncMock(return_value=mock_response)

    with mock.patch.object(feishu, "get_client", return_value=mock_client):
        import asyncio
        result = asyncio.run(feishu.list_tasks("tasklist-001"))

    assert result["tasks"][0]["assignees"] == ["ou_abc"]
    assert result["tasks"][0]["is_completed"] is False


def test_send_message_passes_receive_id_type():
    """send_message forwards receive_id_type to the Feishu API."""
    from taskarena import feishu

    mock_response = mock.MagicMock()
    mock_response.success.return_value = True
    mock_response.data.message_id = "msg-001"

    captured_request = {}

    async def capture_create(req):
        captured_request["req"] = req
        return mock_response

    mock_client = mock.MagicMock()
    mock_client.im.v1.message.acreate = capture_create

    with mock.patch.object(feishu, "get_client", return_value=mock_client):
        import asyncio
        asyncio.run(feishu.send_message("ou_abc", "hello", receive_id_type="open_id"))

    req = captured_request["req"]
    # The receive_id_type is set on the request builder
    assert req.receive_id_type == "open_id"
