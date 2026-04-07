# TaskArena
TaskArena is a Python-based Claude Code Channel + CLI tool that bridges Feishu (Lark) task management with Claude Code.

## MCP Tools
- `reply`: Send a message to a Feishu chat
- `react`: Add emoji reaction to a message
- `create_task`: Create a task
- `update_task`: Update a task
- `complete_task`: Complete a task
- `list_tasks`: List tasks
- `search_users`: Search organization members
- `get_config`: Return current TaskArena config

## Guidelines
- Respond to channel notifications (task events, user messages, scheduled prompts).
- Only respond to allowlisted users.
- Use the `reply` tool for Feishu responses, do NOT use terminal output.

## 任务完成提醒回复处理

当收到用户的 IM 消息，且内容涉及任务完成时：

1. **消息包含 URL**：
   - 调用 `update_task`，将链接追加到任务描述末尾，格式：`\n完成文档：<url>`
   - 调用 `complete_task` 标记完成
   - 用 `reply` 确认："✅ 任务「{summary}」已标记完成，文档链接已记录。"

2. **消息表达完成但无 URL**（如"完成了"、"做好了"）：
   - 用 `reply` 追问："请提供完成文档链接，我来帮你记录并关闭任务。"

3. **用户有多个未完成任务时**：
   - 若无法从上下文判断是哪个任务，先列出任务让用户确认

提醒消息中已包含 task_id，优先使用消息上下文中的 task_id 定位任务，避免重复调用 list_tasks。
