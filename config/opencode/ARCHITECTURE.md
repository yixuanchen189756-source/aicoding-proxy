# OpenCode Header Plugin Architecture

This file is kept as a short historical note. The active setup guide is
`README.md`; keep day-to-day configuration there.

## Current Design

OpenCode exposes a native `chat.headers` plugin hook. The
`rl-training-headers` plugin uses that hook to add request metadata directly
before each model call:

```text
X-Session-Id: <sessionID>
X-Agent-Session-Id: <sessionID>
X-Turn-Type: main|side
X-Agent-Workspace: <workspace-path>
```

The plugin does not prefix the session ID with a user ID. The proxy stores the
trajectory as:

```text
traces/opencode/<session_id>.json
```

## Why `chat.headers`

OpenCode can inject headers without monkey-patching `fetch`, which keeps the
integration scoped to the individual request. That is simpler than the older
OpenClaw lifecycle approach, where headers had to be staged before prompt
building and then attached later during the outbound HTTP request.

## Runtime Flow

```text
OpenCode session
  -> chat.headers hook
  -> X-Session-Id / X-Turn-Type / X-Agent-Workspace
  -> opencode_proxy.py on port 8905
  -> configured upstream backend
  -> traces/opencode/<session_id>.json
```

For installation details, provider configuration, and troubleshooting, use
`README.md` in this same folder.
