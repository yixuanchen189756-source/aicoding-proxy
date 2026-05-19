# Claude Code 代理配置

语言 / Language: [English](README.md) | 简体中文

Claude Code 集成只有两个部分：

1. wrapper 启动 Claude Code，并设置稳定的 run/workspace headers。
2. hook 接收 Claude Code 的 `session_id`，并注册到代理。

`ANTHROPIC_BASE_URL` 由 Claude Code 自己的 settings 配置。这些脚本不会读取 `.env`，不会猜其他配置 key，也不会改写模型地址。

## 文件

```text
config/claude-code/
  scripts/
    claude_code_rl.sh
    claude_code_rl.bat

  hooks/
    claude_code_session_hook.py
```

## Claude Settings

在 Claude settings 中配置代理地址：

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "http://100.64.0.132:8906"
  }
}
```

使用裸 base URL，不要加 `/v1`。

## 启动 Claude Code

通过 wrapper 启动 Claude Code，这样模型请求会带上 run metadata headers。

Linux/macOS：

```bash
sh config/claude-code/scripts/claude_code_rl.sh
```

Windows：

```bat
config\claude-code\scripts\claude_code_rl.bat
```

wrapper 只设置：

```text
CLAUDE_CODE_RUN_ID
CLAUDE_CODE_WORKSPACE_ID
CLAUDE_CODE_WORKSPACE
CLAUDE_CODE_INSTANCE_ID
ANTHROPIC_CUSTOM_HEADERS
```

`ANTHROPIC_BASE_URL` 由 Claude Code 处理。

## Hook Settings

把 `claude_code_session_hook.py` 复制到稳定的 Claude hook 位置，例如：

```text
~/.claude/hooks/claude_code_session_hook.py
```

Linux/macOS：

```json
{
  "command": "python3 ~/.claude/hooks/claude_code_session_hook.py"
}
```

Windows：

```json
{
  "command": "python C:\\Users\\PC-M\\.claude\\hooks\\claude_code_session_hook.py",
  "shell": "powershell"
}
```

Linux 不需要 `shell` 字段。Windows 应该使用 `"shell": "powershell"`。

hook 只使用一个代理来源：

```text
ANTHROPIC_BASE_URL
```

它把 session event POST 到：

```text
<ANTHROPIC_BASE_URL>/_agent/session-event
```

## 轨迹绑定

wrapper 会把 `X-Agent-Run-Id` 放进每个模型请求。hook 上报：

```text
run_id -> session_id
```

代理随后把 Claude Code 轨迹写入：

```text
traces/claude-code/<session_id>.json
```

如果轨迹落到 `__no_session_id__`，只检查这些点：

1. Claude Code 是否通过 wrapper 启动。
2. Claude settings 里的 `ANTHROPIC_BASE_URL` 是否正确。
3. hook 是否运行并收到 `session_id`。
4. wrapper 的 `CLAUDE_CODE_RUN_ID` 是否和 hook 环境一致。
