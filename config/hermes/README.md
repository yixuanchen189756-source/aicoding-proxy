# Hermes Proxy Configuration

This document describes how Hermes should be configured to use the AI Coding
Proxy and how to inject RL trajectory headers into Hermes LLM requests.

Hermes uses the OpenAI-compatible profile served by `proxy/hermes_proxy.py`.

## Proxy Endpoint

Configure Hermes to send its main LLM requests to:

```text
http://<proxy-host>:8907/v1
```

The matching profile in `proxy/config.yaml` is:

```yaml
profiles:
  hermes:
    port: 8907
    protocol: "openai"
    backend: "GLM-5-FP8"
    session_dir: "traces/hermes"
    usage_json: "usage/hermes/usage.json"
```

Hermes trajectories are written under:

```text
traces/hermes/
```

## Goal

Every Hermes main LLM request should include:

```text
X-Session-Id: <user_name>_<session_id>
X-Turn-Type: main|side
```

These headers let the proxy:

- store requests under stable session IDs
- separate user-facing turns from background maintenance turns
- keep Hermes trajectories independent from OpenCode and Claude Code

## Recommended Hermes Configuration

Add a configuration block to Hermes' config file, for example
`~/.hermes/config.yaml`:

```yaml
rl_training_headers:
  enabled: true
  user_name: "default-user"
  session_id_header: "X-Session-Id"
  turn_type_header: "X-Turn-Type"
```

Fields:

| Field | Default | Description |
| --- | --- | --- |
| `enabled` | `false` | Enables RL header injection. |
| `user_name` | `default-user` | Prefix added to Hermes' session ID. |
| `session_id_header` | `X-Session-Id` | Header name for session identity. |
| `turn_type_header` | `X-Turn-Type` | Header name for main/side classification. |

Hermes' model/provider config should point at the proxy:

```yaml
base_url: "http://<proxy-host>:8907/v1"
api_key: "sk-proxy"
model: "glm-5-fp8"
```

If proxy authentication is disabled, the API key can be any non-empty value. If
proxy authentication is enabled, it must match `auth.keys` in `proxy/config.yaml`.

## Implementation Style

Hermes does not have an OpenCode-style `chat.headers` hook. The cleanest
integration is to add headers where Hermes already builds per-request API
arguments.

The recommended patch points are:

- `AIAgent.__init__`
- `AIAgent._build_api_kwargs`
- `AIAgent.flush_memories`
- cron scheduler agent creation

The patch should only affect Hermes' main client path. Auxiliary clients used
for vision, summaries, or internal helper calls do not need to be included in
the RL training trajectory stream.

## Patch 1: Initialize RL Header State

In `AIAgent.__init__`, initialize defaults:

```python
self._rl_headers_enabled = False
self._rl_user_name = "default-user"
self._rl_session_id_header = "X-Session-Id"
self._rl_turn_type_header = "X-Turn-Type"
self._rl_turn_type = "main"
```

Then read config:

```python
if hasattr(_agent_cfg, "get"):
    _rl_cfg = _agent_cfg.get("rl_training_headers", {})
    if _rl_cfg.get("enabled", False):
        self._rl_headers_enabled = True
        self._rl_user_name = _rl_cfg.get("user_name", "default-user")
        self._rl_session_id_header = _rl_cfg.get("session_id_header", "X-Session-Id")
        self._rl_turn_type_header = _rl_cfg.get("turn_type_header", "X-Turn-Type")
```

Use the same config object Hermes already uses for agent settings.

## Patch 2: Inject Headers in `_build_api_kwargs`

In `_build_api_kwargs`, after Hermes has built `api_kwargs` and after any
existing `extra_headers` logic, merge the RL headers:

```python
if getattr(self, "_rl_headers_enabled", False):
    _rl_sid = f"{getattr(self, '_rl_user_name', 'default-user')}_{getattr(self, 'session_id', '')}"
    _rl_headers = {
        getattr(self, "_rl_session_id_header", "X-Session-Id"): _rl_sid,
        getattr(self, "_rl_turn_type_header", "X-Turn-Type"): getattr(self, "_rl_turn_type", "main"),
    }

    _existing = api_kwargs.get("extra_headers", {})
    if not isinstance(_existing, dict):
        _existing = {}
    _existing.update(_rl_headers)
    api_kwargs["extra_headers"] = _existing
```

Important details:

- use `extra_headers`, not static/default client headers
- merge with existing headers rather than replacing them
- preserve existing Hermes headers such as xAI prompt-cache headers
- run this immediately before returning `api_kwargs`

## Patch 3: Mark `flush_memories` as Side Traffic

Memory flushes are internal maintenance work, not direct user interaction.

Wrap the body of `flush_memories`:

```python
def flush_memories(self, messages: list = None, min_turns: int = None):
    _prev_rl_turn_type = getattr(self, "_rl_turn_type", "main")
    self._rl_turn_type = "side"

    try:
        # existing flush_memories logic
        ...
    finally:
        self._rl_turn_type = _prev_rl_turn_type
```

The `finally` block matters. Without it, later user-facing turns could be
incorrectly marked as `side`.

## Patch 4: Mark Cron Agents as Side Traffic

When Hermes' cron scheduler creates an `AIAgent`, set:

```python
agent._rl_turn_type = "side"
```

Cron jobs are background tasks and should not be mixed with direct user
interaction data.

## Data Flow

Normal user turn:

```text
User message
  -> Hermes builds AIAgent request
  -> _build_api_kwargs()
  -> extra_headers["X-Session-Id"] = "<user_name>_<session_id>"
  -> extra_headers["X-Turn-Type"] = "main"
  -> POST http://<proxy-host>:8907/v1/chat/completions
  -> proxy writes traces/hermes/<date>/<session>.json
```

Memory flush:

```text
flush_memories()
  -> _rl_turn_type = "side"
  -> _build_api_kwargs()
  -> X-Turn-Type: side
  -> request finishes
  -> _rl_turn_type restored
```

Cron job:

```text
cron scheduler creates AIAgent
  -> agent._rl_turn_type = "side"
  -> all LLM calls from that cron agent are side traffic
```

## Header Semantics

### X-Session-Id

Format:

```text
<user_name>_<session_id>
```

Example:

```text
default-user_abc123def
```

The prefix prevents collisions when multiple Hermes users or machines send data
to the same proxy.

### X-Turn-Type

| Value | Meaning | Typical source |
| --- | --- | --- |
| `main` | User-facing conversation turn | normal chat loop |
| `side` | Background maintenance turn | memory flush, cron |

Training pipelines can filter out `side` traffic if only user-facing behavior
should be trained.

## Verification

### 1. Syntax Check

From the Hermes repository:

```bash
python -m py_compile run_agent.py
python -m py_compile cron/scheduler.py
```

### 2. Config Check

```python
import yaml

with open("/root/.hermes/config.yaml", "r", encoding="utf-8") as f:
    cfg = yaml.safe_load(f)

print(cfg.get("rl_training_headers", {}))
```

Expected:

```python
{
  "enabled": True,
  "user_name": "default-user",
  "session_id_header": "X-Session-Id",
  "turn_type_header": "X-Turn-Type",
}
```

### 3. Proxy Health

```bash
curl http://<proxy-host>:8907/health
curl http://<proxy-host>:8907/v1/models
```

### 4. End-to-End Header Check

Start Hermes, send one message, and inspect proxy logs or captured request
headers. The request should include:

```text
X-Session-Id: default-user_<actual-session-id>
X-Turn-Type: main
```

Trigger a memory flush or cron run and confirm:

```text
X-Turn-Type: side
```

### 5. Trajectory Check

After a successful request, check:

```text
traces/hermes/
```

The stored trajectory should be separate from:

```text
traces/opencode/
traces/claude-code/
```

## Design Decisions

### Use `extra_headers`

`session_id` changes per session, so static client headers are the wrong layer.
`extra_headers` is request-scoped and already matches the way Hermes handles
other dynamic headers.

### Patch the Main Client Path Only

Auxiliary clients are usually internal helper calls. Keeping them out of the
main RL trajectory stream reduces noise.

### Use an Instance Variable for Turn Type

Hermes does not provide a lifecycle hook that carries request state into header
injection. An instance variable is simple and fits the existing `AIAgent` design.

### Restore State with `finally`

Side-turn state must not leak into later user turns. Always restore
`_rl_turn_type` after temporary side operations.

## Troubleshooting

If Hermes requests reach the proxy but trajectories have no useful session ID:

- confirm Hermes sends `X-Session-Id`
- confirm `rl_training_headers.enabled` is true
- confirm the request path goes through `_build_api_kwargs`

If everything is marked `main`:

- confirm `flush_memories` wraps its logic with `_rl_turn_type = "side"`
- confirm cron-created agents set `_rl_turn_type = "side"`

If requests fail before reaching the model:

- confirm Hermes base URL is `http://<proxy-host>:8907/v1`
- confirm proxy `hermes` profile is valid at startup
- confirm upstream backend credentials in `proxy/config.yaml`
