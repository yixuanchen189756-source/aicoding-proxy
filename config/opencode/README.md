# OpenCode Proxy Configuration

Language / 语言: English | [简体中文](README.zh-CN.md)

This folder contains the OpenCode integration for RL trajectory collection.

OpenCode is the simplest supported client because its plugin API exposes a
native `chat.headers` hook. The plugin can inject request headers directly
before every LLM call without monkey-patching `fetch`.

## Files

```text
config/opencode/
  README.md
    This setup and architecture guide.

  ARCHITECTURE.md
    Earlier migration notes. Kept as historical detail.

  rl-training-headers/
    index.js
      Runtime OpenCode plugin entrypoint.

    index.ts
      TypeScript source/reference version.

    package.json
      Package metadata and @opencode-ai/plugin dependency.
```

## Proxy Endpoint

Configure OpenCode's OpenAI-compatible provider to use:

```text
http://<proxy-host>:8905/v1
```

The OpenCode profile in `proxy/config.yaml` is:

```yaml
profiles:
  opencode:
    port: 8905
    protocol: "openai"
    backend: "minimax2.5"
    session_dir: "traces/opencode"
    usage_json: "usage/opencode/usage.json"
```

Requests are stored under:

```text
traces/opencode/
```

## Plugin Purpose

`rl-training-headers` injects:

```text
X-Session-Id: <userName>_<sessionID>
X-Turn-Type: main|side
```

These headers let the proxy associate each request with a session and classify
background turns separately from user-facing turns.

## Runtime Hook

The OpenCode plugin uses:

```js
"chat.headers": async (input, output) => {
  const sessionId = input.sessionID ?? "";
  const combinedSessionId = `${userName}_${sessionId}`;
  const turnType = SIDE_TRIGGERS.has(input.agent ?? "") ? "side" : "main";

  output.headers = {
    [sessionIdHeader]: combinedSessionId,
    [turnTypeHeader]: turnType,
  };
}
```

OpenCode calls this hook before each model request and merges `output.headers`
into the outgoing HTTP request.

## Turn Type Classification

The plugin treats these agents/triggers as `side`:

```text
heartbeat
memory
cron
```

Everything else is `main`.

## Plugin Configuration

Minimum OpenCode configuration:

```json
{
  "plugin": ["rl-training-headers"]
}
```

Parameterized configuration:

```json
{
  "plugin": [
    ["rl-training-headers", {
      "userName": "my-team",
      "sessionIdHeader": "X-Session-Id",
      "turnTypeHeader": "X-Turn-Type"
    }]
  ]
}
```

Options:

| Option | Default | Description |
| --- | --- | --- |
| `userName` | `default-user` | Prefix added to OpenCode's session ID. |
| `sessionIdHeader` | `X-Session-Id` | Header name for the combined session ID. |
| `turnTypeHeader` | `X-Turn-Type` | Header name for main/side classification. |

## Installing the Plugin

For local development, install or link the plugin directory in the way your
OpenCode installation expects. The package name is:

```text
rl-training-headers
```

The package entrypoint is `index.js`, and `package.json` declares:

```json
{
  "type": "module",
  "main": "index.js",
  "exports": {
    ".": "./index.js"
  }
}
```

OpenCode typically caches plugins under:

```text
~/.cache/opencode/packages/
```

If using a local package, make sure the cached package or symlink points to this
`rl-training-headers` directory.

## OpenCode Provider Configuration

Configure OpenCode's provider/model settings so requests go to the proxy.

Conceptual shape:

```json
{
  "provider": {
    "proxy": {
      "npm": "@ai-sdk/openai-compatible",
      "options": {
        "baseURL": "http://<proxy-host>:8905/v1",
        "apiKey": "sk-proxy"
      }
    }
  },
  "plugin": [
    ["rl-training-headers", {
      "userName": "default-user"
    }]
  ]
}
```

The exact OpenCode config shape can vary by version. The invariant is:

- base URL points to `http://<proxy-host>:8905/v1`
- plugin `rl-training-headers` is loaded
- OpenCode requests carry `X-Session-Id`

If proxy authentication is disabled, the API key can be any non-empty value. If
proxy authentication is enabled, it must match `auth.keys` in `config.yaml`.

## Verification

Check that OpenCode loads the plugin:

```bash
opencode debug config --print-logs --log-level DEBUG
```

Expected log fragments:

```text
service=plugin path=rl-training-headers loading plugin
[rl-training-headers] activated (chat.headers hook, user: default-user)
```

Check the module directly:

```bash
node -e "import('rl-training-headers').then(m => console.log(m.default.id))"
```

Expected output:

```text
rl-training-headers
```

Check hook behavior manually:

```js
import pluginModule from "rl-training-headers";

const hooks = await pluginModule.server({}, { userName: "test" });
const output = { headers: {} };

await hooks["chat.headers"](
  {
    sessionID: "s1",
    agent: "default",
    model: {},
    provider: {},
    message: {},
  },
  output,
);

console.log(output.headers);
```

Expected result:

```json
{
  "X-Session-Id": "test_s1",
  "X-Turn-Type": "main"
}
```

## Why This Is Different From OpenClaw

OpenClaw required lifecycle hooks plus a `fetch` patch because it did not expose
the same direct request-header hook.

OpenCode's native `chat.headers` hook is better for this use case:

- no global `fetch` patch
- no pending-header state
- no cleanup race between prompt build and request send
- header injection is scoped to one request

## Troubleshooting

If trajectories are written under `__no_session_id__`:

- confirm the plugin is loaded
- confirm `X-Session-Id` is present on the request
- confirm OpenCode is using the proxy base URL
- confirm the request hits port `8905`, not another profile port

If all requests are marked `main`:

- check which `input.agent` value OpenCode sends for background tasks
- add that value to `SIDE_TRIGGERS` if it should be filtered as side traffic
