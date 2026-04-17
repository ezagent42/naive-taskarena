# Multi-User Session Isolation & Group Chat Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add structured actor context to all user_message notifications, support group chat @ mentions, push morning reminders to group chats, and harden CLAUDE.md rules to prevent task attribution errors.

**Architecture:** `config.py` gains `bot_open_id` and `group_chat_ids`; `events.py` enriches user_message notifications with `open_id`/`chat_type`/`session_key` and filters group messages by bot @ mention; `scheduler.py` pushes morning reminders to group chats; `.claude/CLAUDE.md` adds three hardened rules.

**Tech Stack:** Python, lark-oapi, pytest, existing project patterns (dataclasses, build_channel_xml, feishu.send_message)

---

## File Map

| File | Change |
|---|---|
| `src/taskarena/config.py` | Add `bot_open_id: str \| None` to `Config`; add `group_chat_ids: list[str]` to `ReminderConfig` |
| `src/taskarena/events.py` | Enrich `user_message` notifications; filter group messages by bot @ mention |
| `src/taskarena/scheduler.py` | Push morning reminders to `group_chat_ids` |
| `.claude/CLAUDE.md` | Add actor identity, reply routing, and assignment rules |
| `tests/test_config.py` | Tests for new config fields |
| `tests/test_events.py` | Tests for enriched notification format and group @ detection |
| `tests/test_scheduler.py` | Test for group chat push |

---

### Task 1: Config — add `bot_open_id` and `group_chat_ids`

**Files:**
- Modify: `src/taskarena/config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_config.py`:

```python
@mock.patch.dict(os.environ, {"FEISHU_APP_ID": "id", "FEISHU_APP_SECRET": "secret"})
def test_config_bot_open_id_loaded(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".taskarena").mkdir()
    (tmp_path / ".taskarena" / "config.yaml").write_text(
        "bot_open_id: 'ou_bot_abc'\n"
    )
    config = Config.load()
    assert config.bot_open_id == "ou_bot_abc"


@mock.patch.dict(os.environ, {"FEISHU_APP_ID": "id", "FEISHU_APP_SECRET": "secret"})
def test_config_bot_open_id_absent_by_default(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = Config.load()
    assert config.bot_open_id is None


@mock.patch.dict(os.environ, {"FEISHU_APP_ID": "id", "FEISHU_APP_SECRET": "secret"})
def test_config_reminders_group_chat_ids(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".taskarena").mkdir()
    (tmp_path / ".taskarena" / "config.yaml").write_text(
        "reminders:\n  group_chat_ids:\n    - 'oc_group_1'\n    - 'oc_group_2'\n"
    )
    config = Config.load()
    assert config.reminders is not None
    assert config.reminders.group_chat_ids == ["oc_group_1", "oc_group_2"]


@mock.patch.dict(os.environ, {"FEISHU_APP_ID": "id", "FEISHU_APP_SECRET": "secret"})
def test_config_reminders_group_chat_ids_default_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".taskarena").mkdir()
    (tmp_path / ".taskarena" / "config.yaml").write_text("reminders: {}\n")
    config = Config.load()
    assert config.reminders.group_chat_ids == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_config.py::test_config_bot_open_id_loaded tests/test_config.py::test_config_bot_open_id_absent_by_default tests/test_config.py::test_config_reminders_group_chat_ids tests/test_config.py::test_config_reminders_group_chat_ids_default_empty -v
```

Expected: FAIL — `Config` has no `bot_open_id`, `ReminderConfig` has no `group_chat_ids`

- [ ] **Step 3: Update `ReminderConfig` and `Config`**

In `src/taskarena/config.py`, update `ReminderConfig`:

```python
@dataclass
class ReminderConfig:
    morning_time: str = "09:00"
    timezone: str = "Asia/Shanghai"
    tasklists: List[str] = field(default_factory=list)
    group_chat_ids: List[str] = field(default_factory=list)
```

Add `bot_open_id` to `Config`:

```python
@dataclass
class Config:
    app_id: str
    app_secret: str
    tasklists: List[Dict[str, str]] = field(default_factory=list)
    allowed_users: List[str] = field(default_factory=list)
    schedules: List[Dict[str, Any]] = field(default_factory=list)
    users: Dict[str, str] = field(default_factory=dict)
    log_level: str = "INFO"
    reminders: Optional[ReminderConfig] = None
    bot_open_id: Optional[str] = None
```

In `Config.load()`, inside the `if config_path.exists():` block, add after reading `schedules`:

```python
bot_open_id = data.get("bot_open_id")
```

Update the `ReminderConfig` construction to include `group_chat_ids`:

```python
reminders = ReminderConfig(
    morning_time=rd.get("morning_time", "09:00"),
    timezone=rd.get("timezone", "Asia/Shanghai"),
    tasklists=rd.get("tasklists", []),
    group_chat_ids=rd.get("group_chat_ids", []),
)
```

Update the `return cls(...)` call to include `bot_open_id`:

```python
return cls(
    app_id=app_id,
    app_secret=app_secret,
    tasklists=tasklists,
    allowed_users=allowed_users,
    schedules=schedules,
    users=users,
    log_level=log_level,
    reminders=reminders,
    bot_open_id=bot_open_id,
)
```

Note: `bot_open_id` must be declared before `load()` in the function body even when `config_path` does not exist — initialise it to `None` at the top of `load()`:

```python
bot_open_id: Optional[str] = None
```

Add this line right after `reminders = None` near the top of `load()`.

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_config.py -v
```

Expected: all 8 config tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/taskarena/config.py tests/test_config.py
git commit -m "feat: add bot_open_id and group_chat_ids to config"
```

---

### Task 2: events.py — enrich user_message notification format

**Files:**
- Modify: `src/taskarena/events.py`
- Modify: `tests/test_events.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_events.py`:

```python
@pytest.mark.asyncio
async def test_user_message_notification_includes_open_id_and_session_key():
    """user_message notification must carry open_id, chat_type, and session_key."""
    notifications = []

    async def notifier(content: str, **_: object) -> None:
        notifications.append(content)

    from taskarena.config import Config
    config = Config(app_id="test", app_secret="test")
    listener = FeishuEventListener(config, notifier)

    # Build a minimal fake P2 event for a p2p message
    event = MagicMock()
    event.header.event_id = "evt-001"
    event.event.sender.sender_id.open_id = "ou_alice"
    event.event.message.chat_id = "oc_p2p_1"
    event.event.message.message_id = "om_msg_1"
    event.event.message.chat_type = "p2p"
    event.event.message.content = '{"text": "hello"}'
    event.event.message.mentions = []

    await listener._handle_im_message(event)

    assert len(notifications) == 1
    xml = notifications[0]
    assert 'open_id="ou_alice"' in xml
    assert 'chat_type="p2p"' in xml
    assert 'session_key="ou_alice"' in xml
    assert 'message_id="om_msg_1"' in xml


@pytest.mark.asyncio
async def test_group_message_session_key_is_chat_id():
    """For group messages, session_key must be chat_id, not open_id."""
    notifications = []

    async def notifier(content: str, **_: object) -> None:
        notifications.append(content)

    from taskarena.config import Config
    config = Config(app_id="test", app_secret="test", bot_open_id="ou_bot_1")
    listener = FeishuEventListener(config, notifier)

    event = MagicMock()
    event.header.event_id = "evt-002"
    event.event.sender.sender_id.open_id = "ou_alice"
    event.event.message.chat_id = "oc_group_1"
    event.event.message.message_id = "om_msg_2"
    event.event.message.chat_type = "group"
    event.event.message.content = '{"text": "@bot hello"}'

    # Simulate bot being mentioned
    mention = MagicMock()
    mention.id.open_id = "ou_bot_1"
    event.event.message.mentions = [mention]

    await listener._handle_im_message(event)

    assert len(notifications) == 1
    xml = notifications[0]
    assert 'session_key="oc_group_1"' in xml
    assert 'chat_type="group"' in xml
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_events.py::test_user_message_notification_includes_open_id_and_session_key tests/test_events.py::test_group_message_session_key_is_chat_id -v
```

Expected: FAIL — notifications don't contain `open_id` or `session_key` yet

- [ ] **Step 3: Update `_handle_im_message` in `events.py`**

Replace the existing `_handle_im_message` method with:

```python
async def _handle_im_message(self, event: P2ImMessageReceiveV1) -> None:
    event_id = getattr(event.header, "event_id", None)
    if not self._remember_event(event_id):
        log.debug("Duplicate IM event %s, skipping", event_id)
        return

    sender = getattr(getattr(event.event, "sender", None), "sender_id", None)
    open_id = getattr(sender, "open_id", None)
    log.info("IM message received from open_id=%s, event_id=%s", open_id, event_id)

    if self.config.allowed_users and open_id not in self.config.allowed_users:
        log.info("Dropping message from non-allowlisted user: %s", open_id)
        return

    message = getattr(event.event, "message", None)
    chat_type = getattr(message, "chat_type", "p2p") or "p2p"
    chat_id = getattr(message, "chat_id", None)
    is_group = chat_type in ("group", "group_chat")

    if is_group:
        if not self.config.bot_open_id:
            log.debug("Group message received but bot_open_id not configured, skipping")
            return
        mentions = getattr(message, "mentions", None) or []
        bot_mentioned = any(
            getattr(getattr(m, "id", None), "open_id", None) == self.config.bot_open_id
            for m in mentions
        )
        if not bot_mentioned:
            log.debug("Group message does not mention bot, skipping")
            return

    session_key = chat_id if is_group else open_id
    content = _extract_message_text(getattr(message, "content", None))
    user_name = self.config.users.get(open_id or "", open_id or "unknown")
    log.info("Forwarding IM from %s: %s", user_name, content[:50])
    xml = build_channel_xml(
        content,
        source="taskarena",
        type="user_message",
        chat_type=chat_type,
        open_id=open_id,
        user=user_name,
        chat_id=chat_id,
        message_id=getattr(message, "message_id", None),
        session_key=session_key,
    )
    await self.notifier(xml)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_events.py -v
```

Expected: all 5 event tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/taskarena/events.py tests/test_events.py
git commit -m "feat: enrich user_message notification with open_id, chat_type, session_key"
```

---

### Task 3: events.py — group @ mention filtering

**Files:**
- Modify: `tests/test_events.py` (already partially covered; add missing cases)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_events.py`:

```python
@pytest.mark.asyncio
async def test_group_message_without_bot_mention_is_dropped():
    """Group messages that don't @ the bot should not be forwarded."""
    notifications = []

    async def notifier(content: str, **_: object) -> None:
        notifications.append(content)

    from taskarena.config import Config
    config = Config(app_id="test", app_secret="test", bot_open_id="ou_bot_1")
    listener = FeishuEventListener(config, notifier)

    event = MagicMock()
    event.header.event_id = "evt-003"
    event.event.sender.sender_id.open_id = "ou_alice"
    event.event.message.chat_id = "oc_group_1"
    event.event.message.message_id = "om_msg_3"
    event.event.message.chat_type = "group"
    event.event.message.content = '{"text": "general chat message"}'
    event.event.message.mentions = []  # no mentions

    await listener._handle_im_message(event)

    assert notifications == []


@pytest.mark.asyncio
async def test_group_message_dropped_when_bot_open_id_not_configured():
    """Group messages are silently dropped if bot_open_id is not set in config."""
    notifications = []

    async def notifier(content: str, **_: object) -> None:
        notifications.append(content)

    from taskarena.config import Config
    config = Config(app_id="test", app_secret="test")  # no bot_open_id
    listener = FeishuEventListener(config, notifier)

    event = MagicMock()
    event.header.event_id = "evt-004"
    event.event.sender.sender_id.open_id = "ou_alice"
    event.event.message.chat_id = "oc_group_1"
    event.event.message.message_id = "om_msg_4"
    event.event.message.chat_type = "group"
    event.event.message.content = '{"text": "@bot hi"}'
    mention = MagicMock()
    mention.id.open_id = "ou_bot_1"
    event.event.message.mentions = [mention]

    await listener._handle_im_message(event)

    assert notifications == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_events.py::test_group_message_without_bot_mention_is_dropped tests/test_events.py::test_group_message_dropped_when_bot_open_id_not_configured -v
```

Expected: FAIL — group messages are not filtered yet (Task 2 already added the filtering code, so these should actually PASS after Task 2. If they do pass, skip to Step 5.)

> **Note:** If these tests already pass after Task 2 (because the filtering logic was already added), that is expected — the code in Task 2 already includes the group filtering. Verify with `uv run pytest tests/test_events.py -v` and confirm all pass, then commit.

- [ ] **Step 3: Verify all event tests pass**

```bash
uv run pytest tests/test_events.py -v
```

Expected: all 7 event tests PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_events.py
git commit -m "test: add group @ mention filtering tests for events"
```

---

### Task 4: scheduler.py — push morning reminders to group chats

**Files:**
- Modify: `src/taskarena/scheduler.py`
- Modify: `tests/test_scheduler.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_scheduler.py`:

```python
@pytest.mark.asyncio
async def test_morning_reminder_pushes_to_group_chat_ids():
    """Morning reminders are also sent to configured group_chat_ids."""
    from taskarena.config import ReminderConfig
    from unittest.mock import AsyncMock, patch

    notifications = []

    async def notifier(content: str, **_: object) -> None:
        notifications.append(content)

    config = Config(
        app_id="test",
        app_secret="test",
        reminders=ReminderConfig(
            morning_time="09:00",
            timezone="Asia/Shanghai",
            group_chat_ids=["oc_group_1", "oc_group_2"],
        ),
    )
    scheduler = TaskArenaScheduler(config, notifier)

    mock_tasks = {
        "tasks": [
            {"task_id": "t1", "summary": "Fix bug", "assignees": ["ou_alice"], "completed_at": "0"},
        ]
    }

    sent_messages = []

    async def mock_send_message(receive_id, content, receive_id_type="open_id"):
        sent_messages.append({"receive_id": receive_id, "receive_id_type": receive_id_type})

    with patch("taskarena.scheduler.feishu.list_tasks", return_value=mock_tasks), \
         patch("taskarena.scheduler.feishu.send_message", side_effect=mock_send_message):
        scheduler._last_reminder_date = None
        await scheduler._send_morning_reminders()

    group_sends = [m for m in sent_messages if m["receive_id_type"] == "chat_id"]
    assert len(group_sends) == 2
    assert {m["receive_id"] for m in group_sends} == {"oc_group_1", "oc_group_2"}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_scheduler.py::test_morning_reminder_pushes_to_group_chat_ids -v
```

Expected: FAIL — scheduler doesn't push to `group_chat_ids` yet

- [ ] **Step 3: Update `_send_morning_reminders` in `scheduler.py`**

In `src/taskarena/scheduler.py`, inside `_send_morning_reminders`, after the existing per-user loop that sends DMs, add a group push block. Find the section after the `for open_id, tasks in assignee_tasks.items():` loop and add:

```python
        # Push to group chats
        if cfg.group_chat_ids and assignee_tasks:
            # Build a consolidated message listing all users and their tasks
            lines = []
            for open_id, tasks in assignee_tasks.items():
                user_name = self.config.users.get(open_id, open_id)
                for task_id, summary in tasks:
                    lines.append(f"• {user_name}：{summary}")
            group_message = "早上好！今日待完成任务：\n\n" + "\n".join(lines)
            for group_chat_id in cfg.group_chat_ids:
                try:
                    await feishu.send_message(group_chat_id, group_message, receive_id_type="chat_id")
                    log.info("Morning reminder sent to group %s", group_chat_id)
                except Exception:
                    log.exception("Failed to send morning reminder to group %s", group_chat_id)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_scheduler.py -v
```

Expected: all scheduler tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/taskarena/scheduler.py tests/test_scheduler.py
git commit -m "feat: push morning reminders to group_chat_ids"
```

---

### Task 5: CLAUDE.md — hardened rules

**Files:**
- Modify: `.claude/CLAUDE.md`

- [ ] **Step 1: Add the three new rules**

Open `.claude/CLAUDE.md` and add the following section after the existing `## Guidelines` section:

```markdown
## 身份与路由规则（重要）

### Rule 1 — Actor 身份
每条 `user_message` 通知都包含 `open_id` 属性，它是发送者的唯一飞书 ID。
涉及用户身份的所有工具调用（`assignee_ids`、`list_tasks` 的 `assignee_id`、`reply` 的 `receive_id_type=open_id`）**必须**使用当前通知中的 `open_id`。
**禁止**从历史消息或对话上下文中推断用户身份。

### Rule 2 — 回复路由
每条 `user_message` 通知都包含 `message_id` 属性。
**必须**使用 `reply(message_id=<当前通知的 message_id>)` 来回复。
**禁止**自己构造或从记忆中回忆 `chat_id` 来发送回复。
飞书会自动将回复投递到正确的私信或群聊。

### Rule 3 — 任务分配场景
- **自认领**（用户说"我要认领"、"分配给我"）：直接使用当前通知的 `open_id` 作为 `assignee_ids`
- **代分配**（领导说"把任务分配给张三"）：先调用 `search_users` 查找目标用户，向请求者确认解析到的 `open_id`，确认后再调用 `assign_task`
```

- [ ] **Step 2: Verify full test suite still passes**

```bash
uv run pytest tests/ -v
```

Expected: all 65+ tests PASS, no regressions

- [ ] **Step 3: Commit**

```bash
git add .claude/CLAUDE.md
git commit -m "docs: harden CLAUDE.md with actor identity, reply routing, and assignment rules"
```

---

### Task 6: Final integration check

- [ ] **Step 1: Run the full test suite**

```bash
uv run pytest tests/ -v
```

Expected: all tests PASS, output clean (no errors or warnings beyond the known deprecation warning from lark_oapi)

- [ ] **Step 2: Push to PR branch**

```bash
git push
```
