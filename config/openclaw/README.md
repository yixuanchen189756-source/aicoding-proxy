# OpenClaw Proxy Configuration

Language / 语言: English | [简体中文](README.zh-CN.md)

This folder contains the OpenClaw-specific integration assets for RL trace
collection.

OpenClaw is handled separately from the shared profile core. Use
`proxy/openclaw_proxy.py` for OpenClaw because OpenClaw has its own gateway,
instance registration, and internal-message patterns.

## Directory Layout

```text
config/openclaw/
  extensions/
    rl-training-headers/
      Injects RL headers and registers the OpenClaw gateway with the proxy.

    task-commands/
      Provides the clear_memory tool used by the /clear-memory skill.

  skills/
    clear-memory/
      User-invocable skill that calls clear_memory.

  workspace/
    markdown_templates/
      Template markdown files used to reset OpenClaw workspace memory.
```

## Runtime Components

### OpenClaw Proxy

Start the OpenClaw-specific proxy from `proxy/`:

```bash
python openclaw_proxy.py
```

`openclaw_proxy.py` is the actual OpenClaw proxy service. It reads the top-level
`openclaw` block from `proxy/config.yaml` for its listener port, upstream
backend, and trace directory.

By default, the current OpenClaw proxy listens on:

```text
http://0.0.0.0:8908
```

Set `OPENAI_PROXY_PORT` if you want a different port:

```bash
OPENAI_PROXY_PORT=8908 python openclaw_proxy.py
```

The preferred persistent configuration is the top-level `openclaw` block in
`proxy/config.yaml`:

```yaml
openclaw:
  port: 8908
  backend: "GLM-5-FP8"
  session_dir: "traces/openclaw"
```

Important environment variables:

```text
VLLM_BASE_URL
  Optional override for the upstream backend base URL. Prefer configuring the
  backend in proxy/config.yaml.

VLLM_MODEL_NAME
  Optional override for the model name sent to the upstream backend.

VLLM_API_KEY
  Optional override for the upstream API key.

OPENAI_PROXY_PORT
  Optional port override for openclaw_proxy.py. Prefer configuring
  openclaw.port in proxy/config.yaml.

OPENAI_PROXY_TRACE=1
  Print request/response trace summaries to stderr.

OPENAI_PROXY_SESSION_FOLDER
  Root directory for per-session trace folders. Each session is written as
  <session_id>/task_<i>.json. If this is unset, the proxy uses openclaw.session_dir
  from proxy/config.yaml; if that is also unset, it uses the current working
  directory.
```

The OpenClaw proxy also persists gateway metadata near the script:

```text
gateway_tokens.json
gateway_instances.json
```

Those files contain runtime registration information and should not be treated
as portable source files.

### OpenClaw Client Gateway Requirements

The OpenClaw client must expose its local gateway chat-completions endpoint.
Without this endpoint, `openclaw_proxy.py` can receive normal model requests but
cannot send the task-completion `/clear-memory` request back into OpenClaw.

In the OpenClaw state/config file, normally `openclaw.json`, enable the local
LAN gateway, token auth, and the HTTP OpenAI chat-completions endpoint:

```json
{
  "gateway": {
    "mode": "local",
    "bind": "lan",
    "auth": {
      "mode": "token",
      "token": "<token>"
    },
    "http": {
      "endpoints": {
        "chatCompletions": {
          "enabled": true
        }
      }
    },
    "dangerouslyAllowHostHeaderOriginFallback": true,
    "dangerouslyDisableDeviceAuth": true
  }
}
```

The token should be the same gateway token that the `rl-training-headers`
extension can read from OpenClaw state or from `OPENCLAW_GATEWAY_TOKEN`. The
`bind: "lan"` setting is needed when the proxy reaches OpenClaw through the
host's LAN or tailnet address instead of loopback.

### rl-training-headers Extension

Path:

```text
config/openclaw/extensions/rl-training-headers/
```

Purpose:

- inject `X-Session-Id`
- inject `X-Turn-Type`
- inject `X-Instance-Id`
- register the OpenClaw gateway URL/token with `openclaw_proxy.py`

Unlike OpenCode, OpenClaw does not provide the same native `chat.headers` hook.
This extension uses OpenClaw lifecycle events and a narrow `globalThis.fetch`
patch:

```text
before_prompt_build
  -> compute pending headers from session/trigger
  -> patched fetch injects headers into the next POST
agent_end
  -> clear pending headers
```

The extension also registers a service startup hook and retries registration on
`before_prompt_build` if startup registration did not complete.

### task-commands Extension

Path:

```text
config/openclaw/extensions/task-commands/
```

Purpose:

- registers a `clear_memory` tool
- resets workspace markdown files from `workspace/markdown_templates`
- clears existing `.md` workspace files that do not have a matching template

### clear-memory Skill

Path:

```text
config/openclaw/skills/clear-memory/SKILL.md
```

User command:

```text
/clear-memory
```

This command directly invokes `clear_memory`. It is intentionally destructive
within the OpenClaw workspace markdown files, so use it only when the current
workspace memory should be reset from templates.

## Header Semantics

### X-Session-Id

Format:

```text
<openclaw-session-id>
```

The extension uses OpenClaw's `ctx.sessionId` as the trace session ID. Do not
use `ctx.sessionKey` for trace grouping: OpenClaw may create separate
`dashboard` and `openai` session keys for the same visible conversation or for
internal requests such as `/clear-memory`.

This keeps all user-facing tasks from the same OpenClaw conversation in one
trace folder while still allowing the proxy to split that folder into
`task_<i>.json` files.

### X-Turn-Type

| Value | Meaning |
| --- | --- |
| `main` | User-facing interaction. |
| `side` | Background or maintenance activity. |

The extension classifies these triggers as `side`:

```text
heartbeat
memory
cron
```

Everything else is `main`.

### X-Instance-Id

Identifies the OpenClaw instance. This lets the proxy keep gateway registrations
and traces separate when multiple OpenClaw instances call the same proxy.

The plugin derives this from the OpenClaw gateway URL origin:

```text
http://100.64.0.70:18789/v1/chat/completions -> 100.64.0.70_18789
```

Manual `instanceId` values are ignored so stale names such as `pc-m-main` do not
become registry keys.

### X-Agent-Workspace

Contains the workspace path when the plugin can resolve it. The plugin first
uses workspace data from the OpenClaw prompt context when available, then falls
back to the current process working directory.

## Extension Configuration

`rl-training-headers/openclaw.plugin.json` defines these options:

| Option | Default | Description |
| --- | --- | --- |
| `sessionIdHeader` | `X-Session-Id` | Header name for session ID. |
| `turnTypeHeader` | `X-Turn-Type` | Header name for turn type. |
| `instanceIdHeader` | `X-Instance-Id` | Header name for instance ID. |
| `workspaceHeader` | `X-Agent-Workspace` | Header name for the workspace path. |
| `instanceId` | ignored | Legacy option accepted by the schema but ignored by the plugin. |
| `proxyRegisterUrl` | ignored | Legacy option accepted by the schema but ignored by the plugin. |
| `gatewayUrl` | Required | OpenClaw gateway URL. |
| `gatewayToken` | read from OpenClaw state when possible | Gateway auth token. |
| `gatewayPort` | `18789` | Local OpenClaw gateway port. |
| `registerOnStart` | `true` | Whether to register at service start. |

Environment variable fallbacks:

```text
OPENCLAW_STATE_DIR
OPENCLAW_GATEWAY_PORT
OPENCLAW_GATEWAY_URL
OPENCLAW_GATEWAY_TOKEN
OPENCLAW_INSTANCE_ID
OPENCLAW_WORKSPACE_DIR
```

The OpenClaw client has one source of truth for the proxy address: the active
model provider `baseUrl` in OpenClaw's own config, for example:

```text
models.providers.vllm.baseUrl = http://100.64.0.132:8908/v1
```

The plugin reads the default model provider from OpenClaw state, removes the
trailing `/v1`, and derives:

```text
http://100.64.0.132:8908/register-instance
```

Do not configure a separate `proxyRegisterUrl`; stale values are ignored to
avoid drift between chat completions and registration.

The extension tries to read the gateway token from:

```text
<OPENCLAW_STATE_DIR>/openclaw.json
%USERPROFILE%\.openclaw\openclaw.json
$HOME/.openclaw/openclaw.json
```

## Installing the Extensions

Copy the extension folders into the OpenClaw extension location used by your
installation. A typical Windows layout is:

```text
<user-home>/.openclaw/extensions/rl-training-headers
<user-home>/.openclaw/extensions/task-commands
```

Copy the skill:

```text
<user-home>/.openclaw/skills/clear-memory
```

Copy or merge workspace templates:

```text
<user-home>/.openclaw/workspace/markdown_templates
```

After copying, restart OpenClaw or reload its extensions.

## Proxy Registration Flow

The intended flow is:

```text
OpenClaw starts
  -> rl-training-headers extension loads
  -> extension resolves gateway URL/token/instance ID
  -> extension POSTs registration to openclaw_proxy.py
  -> proxy stores gateway_instances.json
  -> later LLM requests carry X-Instance-Id and X-Session-Id
  -> proxy writes traces by session/task and detects task completion
  -> each completed task triggers one /clear-memory request to the gateway
  -> proxy can route/attribute requests for that instance
```

Trace files are stored under:

```text
traces/openclaw/<session_id>/task_1.json
traces/openclaw/<session_id>/task_2.json
```

The current `task_<i>.json` file is updated as the turn evolves. When the proxy
detects that a task is complete, the next user-facing task advances to the next
task file.

This is intentional: OpenClaw traces are split by task, not only by session.
After a task is complete, the proxy notifies the OpenClaw gateway to run
`/clear-memory`. That command resets the configured workspace memory files from
templates, so the next task begins with a clean slate while still staying under
the same session folder when the user continues the session.

OpenClaw may create additional internal `openai` session contexts while handling
the `/clear-memory` request. Those requests are skipped by the trace writer and
should not become the session folder for the user-facing conversation.

Registration payload shape:

```json
{
  "instance_id": "DESKTOP-123",
  "gateway_url": "http://<openclaw-gateway-host>:18789/v1/chat/completions",
  "gateway_token": "<token>",
  "gateway_port": "18789",
  "source": "rl-training-headers",
  "reason": "service_start",
  "updated_at": "2026-05-14T00:00:00.000Z"
}
```

## Logs

The extension writes best-effort logs to:

```text
<OPENCLAW_STATE_DIR>/logs/rl-training-headers.log
```

or to the default OpenClaw state directory if `OPENCLAW_STATE_DIR` is not set.

Useful messages:

- `module loaded`
- `resolved config ...`
- `service start hook fired`
- `registering gateway instance`
- `registered gateway instance`
- `before_prompt_build seq=... sessionId=... sessionKey=...`
- `fetch POST applying headers seq=... target=... xSession=...`
- `agent_end clearing pending headers seq=...`

## Validation

1. Start `openclaw_proxy.py`.
2. Start OpenClaw with the extension installed.
3. Check extension logs for gateway registration.
4. Send a normal OpenClaw prompt.
5. Confirm the model request includes:

```text
X-Session-Id
X-Turn-Type
X-Instance-Id
```

6. Confirm the proxy writes a trace for the session.

## Troubleshooting

If registration fails:

- verify the active OpenClaw model provider `baseUrl`
- verify `openclaw_proxy.py` is running
- verify the gateway token exists in OpenClaw state or is set through
  `OPENCLAW_GATEWAY_TOKEN`
- check `rl-training-headers.log`

If headers are missing:

- confirm `before_prompt_build` appears in the extension log
- confirm the LLM request is a `POST`
- confirm another extension is not replacing request headers after this one

If `/clear-memory` fails:

- confirm `task-commands` is installed and loaded
- confirm `workspace/markdown_templates` exists
- confirm OpenClaw can write to its workspace directory
