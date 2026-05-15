# Claude Code 代理配置

语言 / Language: [English](README.md) | 简体中文

本目录包含 Claude Code 的启动 wrapper 和 hook。代理用它们把 Claude Code
的模型请求绑定到 Claude Code 自己的 `session_id`。

Claude Code 和 OpenCode、Hermes 不同：

- 模型请求使用 Anthropic Messages API。
- 当前 `session_id` 不会自然出现在 HTTP header 里。
- session 生命周期信息可以通过 Claude Code hooks 获取。

因此集成使用两条通道：

1. **每个模型请求上的 HTTP headers** 标识当前 run/workspace。
2. **Session hooks** 把 Claude Code 的 `session_id` 事件上报给代理。

代理通过 `X-Agent-Run-Id` 把这两条流关联起来。

## 文件

```text
config/claude-code/
  scripts/
    claude_code_rl.bat
      Windows 启动 wrapper。生成 run/workspace metadata，设置 Claude Code
      的代理环境变量和请求 header，然后启动 Claude Code。

    claude_code_rl.sh
      Linux/macOS 启动 wrapper，行为与 Windows wrapper 相同。

  hooks/
    claude_code_session_hook.bat
      Windows hook wrapper。创建日志目录，记录基础诊断信息，并调用
      Python hook。

    claude_code_session_hook.py
      从 stdin 读取 JSON hook payload，并 POST 到 Claude Code 代理端口的
      /_agent/session-event。
```

## 启动 Claude Code

Claude Code 必须从 `scripts/` 里的 wrapper 脚本启动。需要让它接入这个
代理时，不要直接运行 `claude`、`claude-js` 或其他 Claude Code 二进制。

Windows：

```bat
config\claude-code\scripts\claude_code_rl.bat
```

Linux/macOS：

```bash
sh config/claude-code/scripts/claude_code_rl.sh
```

如果 Claude Code 可执行文件使用了自定义名称或路径，两个 wrapper 都支持
`--claude-bin`：

```bash
sh config/claude-code/scripts/claude_code_rl.sh --claude-bin claude -- --help
```

wrapper 会在 Claude Code 启动前创建 `CLAUDE_CODE_RUN_ID`、
`CLAUDE_CODE_WORKSPACE_ID`、`CLAUDE_CODE_WORKSPACE`、
`CLAUDE_CODE_INSTANCE_ID`、`ANTHROPIC_BASE_URL`、
`CLAUDE_CODE_SESSION_EVENT_URL` 和 `ANTHROPIC_CUSTOM_HEADERS`。Claude Code
会把这些 header 发送到模型请求里；hook 则会在生命周期事件中上报 Claude
Code 的 `session_id`。代理通过 `X-Agent-Run-Id` 把这两条流关联起来。

如果直接启动 Claude Code，hook 可能仍然能收到 `session_id`，但模型请求
不会有匹配的 run header。此时代理无法可靠地把请求关联到当前 Claude Code
session，轨迹可能会落到 `__no_session_id__` 或错误的 session 下。

## 代理端点

Claude Code 的模型请求应发送到 Claude Code profile：

```text
http://<proxy-host>:8906/v1/messages
```

在 Claude Code 环境变量中：

```text
ANTHROPIC_BASE_URL=http://<proxy-host>:8906/v1
```

hook 会把 session 事件 POST 到：

```text
http://<proxy-host>:8906/_agent/session-event
```

hook 脚本默认使用 `http://127.0.0.1:8906/_agent/session-event`。如果代理运行
在其他主机上，请设置 `CLAUDE_CODE_SESSION_EVENT_URL`，不要直接改脚本。

## 必需请求头

Claude Code 模型请求必须携带这些 header：

| Header | 用途 |
| --- | --- |
| `X-Agent-Name` | 静态值，通常是 `claude-code`。 |
| `X-Agent-Run-Id` | 一个 Claude Code 进程/workspace run 的稳定 ID。 |
| `X-Agent-Workspace-Id` | 稳定且已清洗的 workspace ID。 |
| `X-Agent-Workspace` | 便于阅读的 workspace 路径。 |
| `X-Instance-Id` | 机器或实例名称。 |

`X-Agent-Run-Id` 是关键字段。hook 会存储：

```text
run_id -> active_session_id
```

之后每个携带相同 `X-Agent-Run-Id` 的 LLM 请求都会写入正确的 session 轨迹。

## Header 格式

使用换行分隔的自定义 header。不要使用逗号分隔。

正确：

```text
ANTHROPIC_CUSTOM_HEADERS=X-Agent-Name: claude-code
X-Agent-Run-Id: ccrun_ws_abc123_machine_123456
X-Agent-Workspace-Id: ws_abc123
X-Agent-Workspace: <workspace-path>
X-Instance-Id: DESKTOP-123
```

错误：

```text
ANTHROPIC_CUSTOM_HEADERS=X-Agent-Name: claude-code,X-Agent-Run-Id: ...
```

逗号分隔可能会被 Claude Code 当成一个畸形的 `x-agent-name` header，而不是
多个独立 header。

## 环境变量

wrapper 脚本必须设置：

```text
ANTHROPIC_BASE_URL=http://<proxy-host>:8906/v1
ANTHROPIC_CUSTOM_HEADERS=<newline-separated headers>
CLAUDE_CODE_RUN_ID=<same value as X-Agent-Run-Id>
CLAUDE_CODE_WORKSPACE_ID=<same value as X-Agent-Workspace-Id>
CLAUDE_CODE_WORKSPACE=<workspace path>
CLAUDE_CODE_INSTANCE_ID=<machine or instance id>
CLAUDE_CODE_SESSION_EVENT_URL=http://<proxy-host>:8906/_agent/session-event
```

你可以在调用 wrapper 前预先定义这些变量，以覆盖 wrapper 支持覆盖的生成值；
关键要求是 Claude Code 在启动前继承一组一致的环境变量。

可选：

```text
CLAUDE_CODE_HOOK_LOG=<writable-log-path>
CLAUDE_CODE_HOOK_PYTHON=python
```

hook 使用环境变量里的 `CLAUDE_CODE_RUN_ID`，以及 Claude Code hook payload
里的 `session_id`。

## Session 生命周期

Claude Code 可以在不重启的情况下切换 session：

- `/new` 创建新 session。
- `/clear` 启动一个新上下文。
- `/resume` 切换到已有 session。
- 启动参数可以直接打开已有 session。

每次 Claude Code 发出 session hook 事件时，hook 都会把最新 session ID 上报
给代理。代理会更新当前 run ID 对应的 active mapping。

这意味着代理不需要用单独的 `run_id` 目录保存真实对话轨迹。`run_id` 只是
绑定 key：

```text
模型请求上的 X-Agent-Run-Id
  -> proxy registry
  -> active Claude Code session_id
  -> traces/claude-code/<workspace_id>/<session_id>/trajectory.json
```

调试 metadata 也会写入：

```text
traces/claude-code/<workspace_id>/runs/<run_id>.json
traces/claude-code/<workspace_id>/<session_id>/metadata.json
```

## 安装 Hook

把 hook 文件夹复制到稳定位置，例如：

```text
<user-home>/.claude/hooks/
```

预期结构：

```text
<user-home>/.claude/hooks/claude_code_session_hook.bat
<user-home>/.claude/hooks/claude_code_session_hook.py
```

Windows 上请配置 Claude Code 通过 PowerShell 运行 `.bat` hook。否则某些安装
会默认尝试使用 `bash`，而 Windows 上可能没有它。

示例 command：

```json
{
  "command": "<user-home>\\.claude\\hooks\\claude_code_session_hook.bat",
  "shell": "powershell"
}
```

把这个 command 放到用于 session startup 或 resume 的 Claude Code hook 事件
下。`SessionStart` 如果能可靠触发，是首选。`UserPromptSubmit` 也可以作为
fallback，但会发送更多注册请求。

不同 Claude Code 版本的 `settings.json` 结构可能不同。关键要求是：

- hook 能从 stdin 收到 Claude Code 的 JSON event。
- hook 进程继承 `CLAUDE_CODE_RUN_ID`。
- Windows 中 command 指向 `claude_code_session_hook.bat`。
- Windows 配置包含 `"shell": "powershell"`。

## Linux/macOS Hook 用法

Python hook 跨平台。Linux 或 macOS 上，可以在 Claude Code hook settings 中
直接调用 Python 脚本：

```json
{
  "command": "python3 ~/.claude/hooks/claude_code_session_hook.py"
}
```

如果需要 debug logs，请把 `CLAUDE_CODE_HOOK_LOG` 设置成可写路径：

```bash
export CLAUDE_CODE_HOOK_LOG="$HOME/.claude/logs/rl-session-hook.log"
```

## Hook 日志

hook 默认把诊断信息写到：

```text
<hook-directory>/claude_code_session_hook.log
```

如果设置了 `CLAUDE_CODE_HOOK_LOG`，则写入该路径。

有用的日志项：

- `hook invoked`
- `stdin read`
- `event parsed`
- `environment snapshot`
- `POST prepared`
- `POST success`
- `POST failed`

hook 是 best-effort。失败会记录日志，但 hook 会以 `0` 退出，避免影响
Claude Code。

## 手动 Session Event 测试

```bash
curl -X POST http://<proxy-host>:8906/_agent/session-event \
  -H "Content-Type: application/json" \
  -d '{"agent_name":"claude-code","run_id":"test-run","workspace_id":"test-workspace","workspace":"<workspace-path>","session_id":"test-session","hook_event_name":"SessionStart"}'
```

预期响应：

```json
{
  "ok": true,
  "run_id": "test-run",
  "active_session_id": "test-session",
  "workspace_id": "test-workspace"
}
```

## 轨迹行为

Claude Code 轨迹写入前会被规范化：

- 跳过标题生成请求。
- 保留 assistant 的 `<think>...</think>` 文本。
- 把 `<system-reminder>...</system-reminder>` 块按时间顺序拆成 `system`
  messages。
- 用户可见文本仍保留为 `user` message。

输出路径：

```text
traces/claude-code/<workspace_id>/<session_id>/trajectory.json
```

## 排查问题

如果轨迹进入 `__unknown_workspace__/__no_session_id__`：

1. 确认模型请求包含 `X-Agent-Run-Id`。
2. 确认 hook 日志显示 `POST success`。
3. 确认 hook payload 包含 `session_id`。
4. 确认 `CLAUDE_CODE_RUN_ID` 和 `X-Agent-Run-Id` 完全一致。
5. 确认 hook POST 到 `http://<proxy-host>:8906/_agent/session-event`。

如果 Windows 中 hook 没有产生日志：

- 检查配置的 `command` 路径。
- 加上 `"shell": "powershell"`。
- 确认日志目录可写。
- 从 PowerShell 手动运行一次 `.bat`。

如果自定义 header 变成一个畸形 header：

- 把 `ANTHROPIC_CUSTOM_HEADERS` 改成换行分隔。
- 从设置这些环境变量的环境里重启 Claude Code。
