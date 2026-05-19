# Claude Code Proxy Configuration

Language / 璇█: English | [绠€浣撲腑鏂嘳(README.zh-CN.md)

Claude Code integration has two moving pieces:

1. The wrapper starts Claude Code with stable run/workspace headers.
2. The hook receives Claude Code's `session_id` and registers it with the proxy.

`ANTHROPIC_BASE_URL` is configured by Claude Code itself. These scripts do not search `.env` files, do not infer alternate settings keys, and do not rewrite the model URL.

## Files

```text
config/claude-code/
  scripts/
    claude_code_rl.sh
    claude_code_rl.bat

  hooks/
    claude_code_session_hook.py
```

## Claude Settings

Configure the Claude Code proxy endpoint in Claude settings:

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "http://100.64.0.132:8906"
  }
}
```

Use the bare proxy base URL. Do not add `/v1`.

## Starting Claude Code

Start Claude Code through the wrapper so model requests carry the run metadata headers.

Linux/macOS:

```bash
sh config/claude-code/scripts/claude_code_rl.sh
```

Windows:

```bat
config\claude-code\scripts\claude_code_rl.bat
```

The wrapper only sets:

```text
CLAUDE_CODE_RUN_ID
CLAUDE_CODE_WORKSPACE_ID
CLAUDE_CODE_WORKSPACE
CLAUDE_CODE_INSTANCE_ID
ANTHROPIC_CUSTOM_HEADERS
```

Claude Code handles `ANTHROPIC_BASE_URL`.

## Hook Settings

Copy `claude_code_session_hook.py` to a stable Claude hook location, for example:

```text
~/.claude/hooks/claude_code_session_hook.py
```

Linux/macOS:

```json
{
  "command": "python3 ~/.claude/hooks/claude_code_session_hook.py"
}
```

Windows:

```json
{
  "command": "python C:\\Users\\PC-M\\.claude\\hooks\\claude_code_session_hook.py",
  "shell": "powershell"
}
```

Linux does not need a `shell` field. Windows should use `"shell": "powershell"`.

The hook uses exactly one proxy source:

```text
ANTHROPIC_BASE_URL
```

It posts session events to:

```text
<ANTHROPIC_BASE_URL>/_agent/session-event
```

## Trace Binding

The wrapper puts `X-Agent-Run-Id` into every model request. The hook posts:

```text
run_id -> session_id
```

The proxy then writes Claude Code traces to:

```text
traces/claude-code/<session_id>.json
```

Hook/run binding metadata is written once per active session:

```text
traces/claude-code/_metadata/<workspace_id>/<session_id>.json
```

If traces fall into `__no_session_id__`, check only these things:

1. Claude Code was started through the wrapper.
2. `ANTHROPIC_BASE_URL` is correct in Claude settings.
3. The hook ran and received a `session_id`.
4. The wrapper's `CLAUDE_CODE_RUN_ID` matches the hook environment.
