# AI Coding Proxy

Language / 语言: English | [简体中文](README.zh-CN.md)

This directory contains the deployable proxy package for collecting trajectories
from multiple coding agents while routing their LLM requests to configured
upstream model providers.

The project is intentionally small and file-oriented: runtime configuration
lives in `config.yaml`, per-agent hooks/plugins live under `config/`, and the
proxy writes JSON trajectories to disk. Each agent integration uses the lightest
stable extension point available in that client.

## Goals

The proxy is designed to:

- serve several coding-agent clients from one codebase
- route each agent to the correct upstream model backend
- attach stable session/workspace/run metadata to stored trajectories
- keep each agent's trajectories in separate folders for filtering, inspection,
  training, and replay

The proxy does not replace OpenCode, Claude Code, Hermes, or OpenClaw. It sits
between the agents and upstream model providers, preserving normal agent
behavior while adding routing, traceability, and storage.

## Directory Layout

```text
proxy/
  agent_proxy_core.py
    Shared proxy core for OpenCode, Claude Code, and Hermes. The independent
    entrypoint scripts below import this file and select one profile each.

  opencode_proxy.py
  claude_code_proxy.py
  hermes_proxy.py
    Independent single-agent entrypoints for OpenCode, Claude Code, and Hermes.
    Each registers only the routes needed by that coding agent.

  openclaw_proxy.py
    OpenClaw-specific proxy logic. Handles OpenClaw gateway registration,
    instance routing, token registries, OpenClaw internal-message handling, and
    OpenClaw trajectory cleanup. Reads OpenClaw runtime settings from
    config.yaml.

  config.yaml
    Main runtime configuration for model backends, agent profiles, OpenClaw
    runtime settings, authentication, metrics, tracing, and usage storage.

  config/
    opencode/
      OpenCode plugin and documentation.

    claude-code/
      Claude Code hook scripts and documentation.

    hermes/
      Hermes integration documentation.

    openclaw/
      OpenClaw extensions, skills, workspace templates, and documentation.
```

Unless paths in `config.yaml` are absolute, runtime output is written relative to
the process working directory:

```text
traces/
  opencode/
  claude-code/
  hermes/
  openclaw/

usage/
  opencode/
  claude-code/
  hermes/
```

## Proxy Components

### Shared Core and Independent Entrypoints

[agent_proxy_core.py](agent_proxy_core.py) is the shared proxy core for
OpenCode, Claude Code, and Hermes. It is not an entrypoint. Start one of the
independent entrypoint scripts instead:

```bash
python opencode_proxy.py
python claude_code_proxy.py
python hermes_proxy.py
```

Each entrypoint imports `agent_proxy_core.py`, selects exactly one profile from
[config.yaml](config.yaml), and creates an app with only the routes needed by
that coding agent. This keeps the runtime surface small and makes it clear which
process owns which agent.

Current main profiles:

| Agent | Port | Client protocol | Upstream handling | Trace directory |
| --- | ---: | --- | --- | --- |
| OpenCode | `8905` | OpenAI-compatible | Direct OpenAI-format routing | `traces/opencode` |
| Claude Code | `8906` | Anthropic Messages | Anthropic-to-OpenAI conversion when needed | `traces/claude-code` |
| Hermes | `8907` | OpenAI-compatible | Direct OpenAI-format routing | `traces/hermes` |

There is intentionally no `client.py` entrypoint in this package. The split
scripts are the supported deployment mode.

### openclaw_proxy.py

[openclaw_proxy.py](openclaw_proxy.py) is the OpenClaw-specific proxy. It reads
the top-level `openclaw` section from [config.yaml](config.yaml), then uses that
configuration for the listener port, upstream backend, and trajectory directory.
It does not use `agent_proxy_core.py` because OpenClaw has its own gateway and
instance model.

OpenClaw-specific handling includes:

- `X-Instance-Id`
- gateway URL/token registration
- `gateway_instances.json`
- `gateway_tokens.json`
- OpenClaw internal-message filtering
- OpenClaw session/task trajectory cleanup

Start it through:

```bash
python openclaw_proxy.py
```

## Exposed Routes

Independent entrypoints expose only the routes that their agent actually needs.

OpenCode and Hermes:

- `GET /`
- `HEAD /`
- `GET /health`
- `GET /v1/models`
- `/v1/{path:path}`

Claude Code:

- `GET /`
- `HEAD /`
- `GET /health`
- `GET /v1/models`
- `/v1/{path:path}`
- `POST /_agent/session-event`

The independent profile entrypoints intentionally do not expose broad debug or
management routes such as:

- `GET /backends`
- `GET /usage`
- `GET /metrics`

## Configuration Model

`config.yaml` is organized around:

- `backends`
- `profiles`
- `openclaw`
- `auth` / `metrics` / `proxy`

### backends

`backends` define upstream model providers. A backend can contain one or more
endpoints, optional model mapping, endpoint-specific API keys, OpenAI-format
URLs, and extra request headers.

Example:

```yaml
backends:
  my-backend:
    base_url: "https://provider.example.com"
    api_key: "${MY_BACKEND_API_KEY}"
    timeout_s: 600
    max_retries: 1
    retry_delay_s: 0.5
    endpoints:
      - url: "https://provider.example.com"
        model: "provider-model-name"
        openai_url: "https://provider.example.com"
        extra_headers:
          User-Agent: "claude-code/2.1.888"
    load_balance: "least_connections"
```

Do not commit real upstream API keys. Use placeholders, environment expansion,
or a private deployment copy of `config.yaml`.

### profiles

`profiles` bind agent names to listener ports, protocols, backends, and trace
paths.

```yaml
profiles:
  opencode:
    port: 8905
    protocol: "openai"
    backend: "minimax2.5"
    session_dir: "traces/opencode"
    usage_json: "usage/opencode/usage.json"

  claude-code:
    port: 8906
    protocol: "anthropic"
    backend: "glm-5-fp8"
    session_dir: "traces/claude-code"
    usage_json: "usage/claude-code/usage.json"

  hermes:
    port: 8907
    protocol: "openai"
    backend: "GLM-5-FP8"
    session_dir: "traces/hermes"
    usage_json: "usage/hermes/usage.json"
```

Startup validates the required coding-agent profiles. Invalid profiles are
disabled with clear warnings. If all of `opencode`, `claude-code`, and `hermes`
are unusable, the process exits.

### openclaw

OpenClaw is not in `profiles` because it is handled directly by
`openclaw_proxy.py`, not by the shared profile core.

```yaml
openclaw:
  port: 8908
  backend: "GLM-5-FP8"
  session_dir: "traces/openclaw"
```

Fields:

- `port`: listener port for `openclaw_proxy.py`
- `backend`: upstream backend name; must exist in `backends`
- `session_dir`: OpenClaw trajectory directory

### proxy

```yaml
proxy:
  connect_timeout_s: 10
  stream_chunk_size: 8192
  debug: false
  trace: false
  usage_json: "usage.json"
```

- `debug`: prints routing, upstream errors, and retry diagnostics.
- `trace`: prints request/response summaries to stderr.
- `session_json`: legacy trace storage path; profile `session_dir` is preferred.
- `usage_json`: legacy usage storage path; profile `usage_json` is preferred.

## Starting the Proxies

Install Python dependencies:

```bash
pip install fastapi uvicorn aiohttp pyyaml prometheus-client
```

Recommended: start the four proxies as separate processes. Each script owns one
agent and one configured port.

```bash
cd proxy
python opencode_proxy.py
python claude_code_proxy.py
python hermes_proxy.py
python openclaw_proxy.py
```

There is no combined `client.py` startup path. OpenClaw is always started
through `openclaw_proxy.py`; it is not part of the shared profile router.

Quick checks:

```bash
curl http://127.0.0.1:8905/health
curl http://127.0.0.1:8906/health
curl http://127.0.0.1:8907/health
curl http://127.0.0.1:8908/health
```

If the proxy runs on another machine, replace `127.0.0.1` with that host or
tailnet IP.

## Agent Integrations

### OpenCode

OpenCode uses the plugin in
[config/opencode/rl-training-headers](config/opencode/rl-training-headers).

The plugin uses OpenCode's native `chat.headers` hook. Before each LLM request,
it injects:

- `X-Session-Id: <userName>_<sessionID>`
- `X-Turn-Type: main|side`

Point OpenCode's OpenAI-compatible provider at:

```text
http://<proxy-host>:8905/v1
```

If proxy authentication is disabled, the API key can be any non-empty value. If
authentication is enabled, it must match `auth.keys`.

See [config/opencode/README.md](config/opencode/README.md) for installation and
verification.

### Claude Code

Claude Code uses two mechanisms:

1. Environment variables set the model base URL and custom headers.
2. A Claude Code hook reports session start/resume events to the proxy.

Claude Code model requests should go to:

```text
http://<proxy-host>:8906/v1/messages
```

Required model request metadata:

- `X-Agent-Name: claude-code`
- `X-Agent-Run-Id: <stable-run-id>`
- `X-Agent-Workspace-Id: <workspace-id>`
- `X-Agent-Workspace: <workspace-path>`
- `X-Instance-Id: <machine-or-instance-id>`

The hook posts session events to:

```text
http://<proxy-host>:8906/_agent/session-event
```

The proxy uses `X-Agent-Run-Id` to look up the latest session ID reported by the
hook. This lets `/resume`, `/new`, `/clear`, and startup with an existing session
continue writing the correct session trajectory.

Claude Code trajectory paths:

```text
traces/claude-code/<workspace_id>/<session_id>/trajectory.json
traces/claude-code/<workspace_id>/<session_id>/metadata.json
traces/claude-code/<workspace_id>/runs/<run_id>.json
```

See [config/claude-code/README.md](config/claude-code/README.md) for full hook
and settings instructions.

### Hermes

Hermes should use the OpenAI-compatible profile:

```text
http://<proxy-host>:8907/v1
```

Hermes itself must inject:

- `X-Session-Id: <user_name>_<session_id>`
- `X-Turn-Type: main|side`

The recommended integration injects these headers through `extra_headers` in
Hermes' main LLM request path. Background memory flushes and cron jobs should be
marked `side`; user-facing turns should remain `main`.

See [config/hermes/README.md](config/hermes/README.md) for the Hermes patch and
configuration guide.

### OpenClaw

OpenClaw uses the dedicated proxy:

```bash
python openclaw_proxy.py
```

OpenClaw is different because it has its own gateway and instance model. The
plugin in
[config/openclaw/extensions/rl-training-headers](config/openclaw/extensions/rl-training-headers)
does two things:

- injects `X-Session-Id`, `X-Turn-Type`, and `X-Instance-Id` into LLM requests
- registers the OpenClaw gateway URL/token with `openclaw_proxy.py`

OpenClaw runtime settings live in the top-level `openclaw` section of
`config.yaml`:

```yaml
openclaw:
  port: 8908
  backend: "GLM-5-FP8"
  session_dir: "traces/openclaw"
```

Make sure the OpenClaw extension's `proxyRegisterUrl` points to the same port.

See [config/openclaw/README.md](config/openclaw/README.md) for the full OpenClaw
setup.

## Trajectory Format

The main proxy stores one normalized trajectory snapshot per session. A typical
file looks like:

```json
{
  "profile": "claude-code",
  "session_id": "session-id",
  "run_id": "ccrun_workspace_machine_timestamp",
  "workspace_id": "ws_abc123",
  "workspace": "D:\\project",
  "session_source": "registry",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "hello"},
    {"role": "assistant", "content": "<think>...</think>\n\nHi!"}
  ],
  "tools": []
}
```

Important normalization rules:

- Claude Code title-generation requests are skipped so they do not overwrite the
  real conversation trajectory.
- Assistant `<think>...</think>` content is preserved.
- Claude Code `<system-reminder>...</system-reminder>` blocks are split into
  chronological `system` messages instead of being stored as user text.
- Random tool call IDs are removed to reduce non-deterministic noise.

## Usage Accounting

Each profile can write token usage to its own JSON file:

```text
usage/opencode/usage.json
usage/claude-code/usage.json
usage/hermes/usage.json
```

The `/usage` endpoint returns usage by client IP and model:

```bash
curl http://127.0.0.1:8905/usage
curl "http://127.0.0.1:8905/usage?ip=127.0.0.1"
```

## Debugging

Enable request/response tracing:

```yaml
proxy:
  debug: true
  trace: true
```

Common checks:

```bash
curl http://127.0.0.1:8905/backends
curl http://127.0.0.1:8906/backends
curl http://127.0.0.1:8907/backends
```

Claude Code session-event check:

```bash
curl -X POST http://127.0.0.1:8906/_agent/session-event \
  -H "Content-Type: application/json" \
  -d '{"agent_name":"claude-code","run_id":"test-run","session_id":"test-session","workspace_id":"test-workspace"}'
```

Expected response:

```json
{"ok": true, "run_id": "test-run", "active_session_id": "test-session", "workspace_id": "test-workspace"}
```

## Testing

From the repository root:

```bash
python -B -m py_compile proxy/agent_proxy_core.py proxy/opencode_proxy.py proxy/claude_code_proxy.py proxy/hermes_proxy.py proxy/openclaw_proxy.py
python -m unittest discover -s tests -v
```

Some tests cover historical scripts and fixtures outside `proxy/`; that is part
of the current repository structure.

## Security Notes

- Do not commit real upstream API keys.
- Treat trajectory files as sensitive. They may contain prompts, source code,
  tool outputs, local paths, and system reminders.
- If `auth.enabled` is `false`, any client that can reach the proxy port can
  call the proxy. Bind to a trusted network or enable authentication before
  exposing it beyond a private machine or tailnet.
- Claude Code hooks should be best-effort: if the proxy is temporarily
  unavailable, the hook should log the failure but must not block Claude Code.
