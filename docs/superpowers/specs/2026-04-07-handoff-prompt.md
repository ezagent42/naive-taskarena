# 接手提示词（2026-04-07）

## 使用方法

清空上下文后，把以下内容粘贴给新会话。

---

## 提示词

我在开发 TaskArena，一个把飞书任务管理与 Claude Code 连接的 MCP server。请读取 memory 文件了解项目状态。

**项目路径：** `/Users/daiming/workspace/naive-taskarena`
**当前分支：** `feature/taskarena-implementation`

### 刚刚完成的事

我们刚完成了「早晨任务提醒」功能（PR #3 已合并）：
- 每天早上向任务负责人发飞书私信，列出未完成任务
- 用户回复完成文档链接 → 自动更新任务描述并标记完成
- 59 个测试全部通过

### 当前状态：等待飞书手动测试结果

我已经完成了飞书手动测试，结果如下：
[在这里填写你的测试结果，比如："全部通过" 或 "发现 xxx 问题"]

### 需要你帮我做的事

[根据测试结果选择：]

**如果测试通过：**
把 `feature/taskarena-implementation` 合并到 `main` 并推送：
```bash
git checkout main
git merge feature/taskarena-implementation
git push origin main
```

**如果发现 bug：**
描述具体问题，帮我修复。

### 飞书手动测试方案（供参考）

| # | 场景 | 预期结果 | 实际结果 |
|---|------|---------|---------|
| 1 | morning_time 设为当前时间，重启 taskarena channel | 飞书收到私信，含任务名和 task_id | 收到 |
| 2 | 等 30 秒 | 不重复发送 | 没有重复消息 |
| 3 | 私信里回复"完成了" | 机器人追问：请提供完成文档链接 | 他没看到上下文，把任务列表里所有任务都列出来，问我完成了哪个。我回答后，他也没有追问我提供链接。 |
| 4 | 回复一个 URL | 机器人确认，任务描述更新，任务标记完成 | 未测试 |
| 5 | 新建任务，再次触发提醒，直接回复含 URL 的消息 | 机器人直接完成，不追问 | 未测试 |

### 关键配置

`.taskarena/config.yaml` 中加入（测试时 morning_time 填当前时间）：
```yaml
reminders:
  morning_time: "HH:MM"
  timezone: "Asia/Shanghai"
```

重启 taskarena channel 后生效。
