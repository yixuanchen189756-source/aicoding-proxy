# AI Coding Proxy

Language / 语言: English | [简体中文](README.zh-CN.md)

AI Coding Proxy is a small, file-oriented proxy package for collecting coding-agent trajectories while routing model requests to configured upstream LLM providers.

It is designed for four agent families:

| Agent | Entrypoint | Port | Client protocol | Trajectory root |
| --- | --- | ---: | --- | --- |
| OpenCode | `opencode_proxy.py` | `8905` | OpenAI-compatible | `traces/opencode` |
| Claude Code | `claude_code_proxy.py` | `8906` | Anthropic Messages | `traces/claude-code` |
| Hermes | `hermes_proxy.py` | `8907` | OpenAI-compatible | `traces/hermes` |
| OpenClaw | `openclaw_proxy.py` | `8908` | OpenAI-compatible gateway | `traces/openclaw` |

The proxy does not replace those agents. It sits between each agent and the upstream model provider so requests can be attributed to the right session, workspace, run, and agent.

## Mental Model

Question:
  Why does this package exist?

Model:
  agent request + stable headers + proxy profile = replayable trajectory

Flow:

```text
Coding agent
  -> agent-specific headers/hooks/plugins
  -> dedicated proxy port
  -> configured upstream backend
  -> per-agent trajectory files
```

Rule:
  each agent owns its own process, port, request shape, and trajectory folder.

This separation is intentional. OpenCode, Claude Code, Hermes, and OpenClaw expose different extension points, so the proxy keeps their integration logic separate while sharing backend configuration and trajectory conventions.

## Repository Layout

```text
proxy/
  agent_proxy_core.py
    Shared FastAPI core for OpenCode, Claude Code, and Hermes.
    This is not a startup script.

  opencode_proxy.py
  claude_code_proxy.py
  hermes_proxy.py
    Thin entrypoints that select exactly one profile from config.yaml.

  openclaw_proxy.py
    OpenClaw-specific proxy with gateway registration and instance routing.

  config.yaml
    Runtime configuration for upstream backends, agent profiles, auth, tracing,
    usage files, and OpenClaw settings.

  config/
    opencode/
    claude-code/
    hermes/
    openclaw/
      Agent-specific plugins, hooks, scripts, and setup guides.
```

There is intentionally no `client.py` entrypoint. Use the dedicated scripts above.

## Requirements

- Python 3.10+
- Network access from the proxy host to your configured upstream model providers
- One configured upstream backend in `config.yaml`
- Agent-specific header injection:
  - OpenCode: plugin hook
  - Claude Code: wrapper environment + session hook
  - Hermes: request `extra_headers` patch
  - OpenClaw: extension + gateway registration

Install Python dependencies:

```bash
pip install -r requirements.txt
```

## Configuration

Runtime configuration lives in [config.yaml](config.yaml).

### Backends

`backends` describe upstream model providers. Use environment-variable placeholders for real credentials:

```yaml
backends:
  my-backend:
    base_url: "https://provider.example.com"
    api_key: "${MY_BACKEND_API_KEY}"
    timeout_s: 600
    endpoints:
      - url: "https://provider.example.com"
        model: "provider-model-name"
        openai_url: "https://provider.example.com"
```

Do not commit real paid-provider API keys. Local secrets belong in `.env` or your deployment environment.

### Profiles

`profiles` bind the three shared-core agents to ports, protocols, backends, and output paths:

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

Invalid profiles are disabled with clear startup warnings. If no requested profile has a valid backend, the process exits.

### OpenClaw

OpenClaw uses its own top-level block because it does not use `agent_proxy_core.py`:

```yaml
openclaw:
  port: 8908
  backend: "GLM-5-FP8"
  session_dir: "traces/openclaw"
```

## Run Locally

Start each proxy in its own terminal or process manager:

```bash
cd proxy
python opencode_proxy.py
python claude_code_proxy.py
python hermes_proxy.py
python openclaw_proxy.py
```

Health checks:

```bash
curl http://<proxy-host>:8905/health
curl http://<proxy-host>:8906/health
curl http://<proxy-host>:8907/health
curl http://<proxy-host>:8908/health
```

Use the proxy host or tailnet IP that your coding-agent machine can reach.

## Agent Setup

### OpenCode

OpenCode uses `config/opencode/rl-training-headers`, which injects:

```text
X-Session-Id: <userName>_<sessionID>
X-Turn-Type: main|side
```

Point OpenCode's OpenAI-compatible provider at:

```text
http://<proxy-host>:8905/v1
```

Guide: [config/opencode/README.md](config/opencode/README.md) | [中文](config/opencode/README.zh-CN.md)

### Claude Code

Claude Code needs two pieces:

1. wrapper scripts that set `ANTHROPIC_BASE_URL`, `ANTHROPIC_CUSTOM_HEADERS`, `CLAUDE_CODE_RUN_ID`, and workspace metadata
2. a session hook that reports Claude Code `session_id` events to the proxy

Start Claude Code through:

```bash
# Windows
config\claude-code\scripts\claude_code_rl.bat

# Linux/macOS
sh config/claude-code/scripts/claude_code_rl.sh
```

The model endpoint is:

```text
http://<proxy-host>:8906/v1/messages
```

The hook endpoint is:

```text
http://<proxy-host>:8906/_agent/session-event
```

Guide: [config/claude-code/README.md](config/claude-code/README.md) | [中文](config/claude-code/README.zh-CN.md)

### Hermes

Hermes should send OpenAI-compatible requests to:

```text
http://<proxy-host>:8907/v1
```

Hermes must add request-scoped `extra_headers`:

```text
X-Session-Id: <user_name>_<session_id>
X-Turn-Type: main|side
```

Guide: [config/hermes/README.md](config/hermes/README.md) | [中文](config/hermes/README.zh-CN.md)

### OpenClaw

OpenClaw uses the dedicated proxy:

```bash
python openclaw_proxy.py
```

The OpenClaw extension injects:

```text
X-Session-Id
X-Turn-Type
X-Instance-Id
```

It also registers the OpenClaw gateway URL/token with `openclaw_proxy.py`, which lets the proxy route requests for each instance.

Guide: [config/openclaw/README.md](config/openclaw/README.md) | [中文](config/openclaw/README.zh-CN.md)

## Trajectories

The proxy writes JSON trajectories under each agent's configured `session_dir`.

Claude Code uses a workspace/session layout:

```text
traces/claude-code/<workspace_id>/<session_id>/trajectory.json
traces/claude-code/<workspace_id>/<session_id>/metadata.json
traces/claude-code/<workspace_id>/runs/<run_id>.json
```

Typical normalized trajectory shape:

```json
{
  "profile": "claude-code",
  "session_id": "session-id",
  "run_id": "ccrun_workspace_machine_timestamp",
  "workspace_id": "ws_abc123",
  "workspace": "<workspace-path>",
  "session_source": "registry",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "hello"},
    {"role": "assistant", "content": "<think>...</think>\n\nHi!"}
  ],
  "tools": []
}
```

Normalization rules:

- Claude Code title-generation requests are skipped.
- Assistant `<think>...</think>` content is preserved.
- Claude Code `<system-reminder>...</system-reminder>` blocks become chronological `system` messages.
- Random tool call IDs are removed to reduce non-deterministic noise.

Treat trajectory files as sensitive. They may contain prompts, code, tool output, paths, and system reminders.

## Usage Accounting

Each profile can write token usage to its configured `usage_json` path:

```text
usage/opencode/usage.json
usage/claude-code/usage.json
usage/hermes/usage.json
```

## Development Commands

Compile-check the proxy scripts:

```bash
python -B -m py_compile proxy/agent_proxy_core.py proxy/opencode_proxy.py proxy/claude_code_proxy.py proxy/hermes_proxy.py proxy/openclaw_proxy.py
```

Run the test suite from the repository root:

```bash
python -m unittest discover -s tests -v
```

## Contribution Notes

- Keep each agent integration in its own folder or entrypoint.
- Do not reintroduce `client.py` or `openclaw_client.py`; those names are intentionally retired.
- Keep docs portable. Use placeholders such as `<proxy-host>`, `<user-home>`, and `<workspace-path>` instead of machine-specific paths.
- Add new agent-specific details to that agent's `config/<agent>/README.md`, then link from this root README.
- Do not commit `.env`, runtime traces, usage files, gateway registries, or real API keys.

## License

No license file is currently included. Add one before publishing or distributing this package beyond private/internal use.

## Contact

No public maintainer contact is defined yet. For internal deployments, document the owner or on-call channel here before sharing the repository broadly.
