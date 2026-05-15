# Claude Code Proxy Configuration

Language / 语言: English | [简体中文](README.zh-CN.md)

This folder contains the Claude Code hook used by the proxy to bind Claude Code
session IDs to model requests.

Claude Code is different from OpenCode and Hermes:

- model requests are Anthropic Messages API requests
- the current session ID is not naturally available as an HTTP header
- session lifecycle information is available through Claude Code hooks

The integration therefore uses two channels:

1. **HTTP headers on every model request** identify the current run/workspace.
2. **Session hooks** report Claude Code `session_id` events to the proxy.

The proxy joins those two streams using `X-Agent-Run-Id`.

## Files

```text
config/claude-code/
  scripts/
    claude_code_rl.bat
      Windows launcher. Generates the run/workspace metadata, sets Claude
      Code's proxy environment variables and request headers, then starts
      Claude Code.

    claude_code_rl.sh
      Linux/macOS launcher with the same behavior as the Windows launcher.

  hooks/
    claude_code_session_hook.bat
      Windows wrapper. Creates the log directory, records basic diagnostics,
      and invokes the Python hook.

    claude_code_session_hook.py
      Reads the JSON hook payload from stdin and POSTs it to
      /_agent/session-event on the Claude Code proxy port.
```

## Starting Claude Code

Claude Code must be started from one of the wrapper scripts in `scripts/`.
Do not start `claude`, `claude-js`, or another Claude Code binary directly when
you want it to interact with this proxy.

Windows:

```bat
config\claude-code\scripts\claude_code_rl.bat
```

Linux/macOS:

```bash
sh config/claude-code/scripts/claude_code_rl.sh
```

Both wrappers accept `--claude-bin` if the Claude Code executable has a custom
name or path:

```bash
sh config/claude-code/scripts/claude_code_rl.sh --claude-bin claude -- --help
```

The wrapper is the component that creates `CLAUDE_CODE_RUN_ID`,
`CLAUDE_CODE_WORKSPACE_ID`, `CLAUDE_CODE_WORKSPACE`, `CLAUDE_CODE_INSTANCE_ID`,
`ANTHROPIC_BASE_URL`, `CLAUDE_CODE_SESSION_EVENT_URL`, and
`ANTHROPIC_CUSTOM_HEADERS` before Claude Code starts. Claude Code then sends
those headers on model requests, while the hook reports Claude Code's
`session_id` on lifecycle events. The proxy joins the two streams with
`X-Agent-Run-Id`.

If Claude Code is launched directly, the hook may still receive a `session_id`,
but model requests will not have the matching run header. In that state the
proxy cannot reliably associate requests with the active Claude Code session,
and trajectories can fall back to `__no_session_id__` or the wrong session.

## Proxy Endpoint

Claude Code should send model requests to the Claude Code profile:

```text
http://<proxy-host>:8906/v1/messages
```

In Claude Code environment terms:

```text
ANTHROPIC_BASE_URL=http://<proxy-host>:8906/v1
```

The hook posts session events to:

```text
http://<proxy-host>:8906/_agent/session-event
```

The hook script defaults to `http://127.0.0.1:8906/_agent/session-event`. If the
proxy runs on another host, set `CLAUDE_CODE_SESSION_EVENT_URL` instead of
editing the script.

## Required Request Headers

Claude Code model requests must carry these headers:

| Header | Purpose |
| --- | --- |
| `X-Agent-Name` | Static value, usually `claude-code`. |
| `X-Agent-Run-Id` | Stable ID for one Claude Code process/workspace run. |
| `X-Agent-Workspace-Id` | Stable sanitized workspace ID. |
| `X-Agent-Workspace` | Human-readable workspace path. |
| `X-Instance-Id` | Machine or instance name. |

`X-Agent-Run-Id` is the key field. The hook stores:

```text
run_id -> active_session_id
```

Then every LLM request carrying the same `X-Agent-Run-Id` can be written to the
correct session trajectory.

## Header Format

Use newline-separated custom headers. Do not use comma-separated headers.

Good:

```text
ANTHROPIC_CUSTOM_HEADERS=X-Agent-Name: claude-code
X-Agent-Run-Id: ccrun_ws_abc123_machine_123456
X-Agent-Workspace-Id: ws_abc123
X-Agent-Workspace: <workspace-path>
X-Instance-Id: DESKTOP-123
```

Bad:

```text
ANTHROPIC_CUSTOM_HEADERS=X-Agent-Name: claude-code,X-Agent-Run-Id: ...
```

Comma-separated values can be sent by Claude Code as one malformed
`x-agent-name` header instead of separate headers.

## Environment Variables

The wrapper script must set:

```text
ANTHROPIC_BASE_URL=http://<proxy-host>:8906/v1
ANTHROPIC_CUSTOM_HEADERS=<newline-separated headers>
CLAUDE_CODE_RUN_ID=<same value as X-Agent-Run-Id>
CLAUDE_CODE_WORKSPACE_ID=<same value as X-Agent-Workspace-Id>
CLAUDE_CODE_WORKSPACE=<workspace path>
CLAUDE_CODE_INSTANCE_ID=<machine or instance id>
CLAUDE_CODE_SESSION_EVENT_URL=http://<proxy-host>:8906/_agent/session-event
```

You may predefine these variables before invoking the wrapper to override the
generated values where the wrapper supports it, but the important requirement is
that Claude Code inherits one consistent environment before it starts.

Optional:

```text
CLAUDE_CODE_HOOK_LOG=<writable-log-path>
CLAUDE_CODE_HOOK_PYTHON=python
```

The hook uses `CLAUDE_CODE_RUN_ID` from the environment and `session_id` from
Claude Code's hook payload.

## Session Lifecycle

Claude Code can change sessions without restarting:

- `/new` creates a new session
- `/clear` starts a fresh context
- `/resume` switches to an existing session
- startup arguments can open an existing session directly

Every time Claude Code emits a session hook event, the hook posts the latest
session ID to the proxy. The proxy updates the active mapping for the current
run ID.

This means the proxy does not need a separate `run_id` directory for actual
conversation traces. `run_id` is only the binding key:

```text
X-Agent-Run-Id on model request
  -> proxy registry
  -> active Claude Code session_id
  -> traces/claude-code/<workspace_id>/<session_id>/trajectory.json
```

Metadata is also stored for debugging:

```text
traces/claude-code/<workspace_id>/runs/<run_id>.json
traces/claude-code/<workspace_id>/<session_id>/metadata.json
```

## Hook Installation

Copy the hook folder to a stable location, for example:

```text
<user-home>/.claude/hooks/
```

Expected layout:

```text
<user-home>/.claude/hooks/claude_code_session_hook.bat
<user-home>/.claude/hooks/claude_code_session_hook.py
```

On Windows, configure Claude Code to run the `.bat` hook through PowerShell.
Without an explicit shell, some installations try to use `bash`, which may not
exist on Windows.

Example command value:

```json
{
  "command": "<user-home>\\.claude\\hooks\\claude_code_session_hook.bat",
  "shell": "powershell"
}
```

Place that command under the Claude Code hook event you use for session startup
or resume. `SessionStart` is preferred when it fires reliably in your Claude
Code version. `UserPromptSubmit` also works as a fallback, but it sends more
registration requests than necessary.

The exact `settings.json` shape may vary by Claude Code version. The important
requirements are:

- the hook receives Claude Code's JSON event on stdin
- the hook process inherits `CLAUDE_CODE_RUN_ID`
- the command points to `claude_code_session_hook.bat` on Windows
- Windows settings include `"shell": "powershell"`

## Linux/macOS Hook Usage

The Python hook is cross-platform. On Linux or macOS, call the Python script
directly from Claude Code hook settings:

```json
{
  "command": "python3 ~/.claude/hooks/claude_code_session_hook.py"
}
```

Set `CLAUDE_CODE_HOOK_LOG` to a writable path if you want debug logs:

```bash
export CLAUDE_CODE_HOOK_LOG="$HOME/.claude/logs/rl-session-hook.log"
```

## Hook Logging

The hook writes diagnostics to:

```text
<hook-directory>/claude_code_session_hook.log
```

or to `CLAUDE_CODE_HOOK_LOG` if set.

Useful log entries:

- `hook invoked`
- `stdin read`
- `event parsed`
- `environment snapshot`
- `POST prepared`
- `POST success`
- `POST failed`

Hooks are best-effort. Failures are logged but the hook exits with `0` so it
does not break Claude Code.

## Manual Session Event Test

```bash
curl -X POST http://<proxy-host>:8906/_agent/session-event \
  -H "Content-Type: application/json" \
  -d '{"agent_name":"claude-code","run_id":"test-run","workspace_id":"test-workspace","workspace":"<workspace-path>","session_id":"test-session","hook_event_name":"SessionStart"}'
```

Expected response:

```json
{
  "ok": true,
  "run_id": "test-run",
  "active_session_id": "test-session",
  "workspace_id": "test-workspace"
}
```

## Trajectory Behavior

Claude Code trajectories are normalized before writing:

- title-generation requests are skipped
- assistant `<think>...</think>` text is preserved
- `<system-reminder>...</system-reminder>` blocks are separated into
  chronological `system` messages
- user-visible text remains a `user` message

The output path is:

```text
traces/claude-code/<workspace_id>/<session_id>/trajectory.json
```

## Troubleshooting

If trajectories go to `__unknown_workspace__/__no_session_id__`:

1. Confirm the model request contains `X-Agent-Run-Id`.
2. Confirm the hook log shows `POST success`.
3. Confirm the hook payload includes `session_id`.
4. Confirm `CLAUDE_CODE_RUN_ID` exactly matches `X-Agent-Run-Id`.
5. Confirm the hook posts to `http://<proxy-host>:8906/_agent/session-event`.

If the hook produces no logs on Windows:

- check the configured `command` path
- include `"shell": "powershell"`
- ensure the log directory is writable
- run the `.bat` manually once from PowerShell

If custom headers arrive as one malformed header:

- change `ANTHROPIC_CUSTOM_HEADERS` to newline-separated headers
- restart Claude Code from the environment that sets those variables
