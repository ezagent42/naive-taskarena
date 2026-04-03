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