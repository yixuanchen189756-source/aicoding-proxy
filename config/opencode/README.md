# OpenCode Proxy Configuration

Language / 语言: English | [简体中文](README.zh-CN.md)

This folder contains the OpenCode integration for RL trace collection.

OpenCode is the simplest supported client because its plugin API exposes a
native `chat.headers` hook. The plugin can inject request headers directly
before every LLM call without monkey-patching `fetch`.

## Files

```text
config/opencode/
  README.md
    This setup and architecture guide.

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
traces/opencode/<session_id>.json
```

## Plugin Purpose

`rl-training-headers` injects:

```text
X-Session-Id: <sessionID>
X-Turn-Type: main|side
X-Agent-Workspace: <workspace-path>
```

These headers let the proxy associate each request with a session and classify
background turns separately from user-facing turns.

## Runtime Hook

The OpenCode plugin uses:

```js
"chat.headers": async (input, output) => {
  const sessionId = input.sessionID ?? "";
  const turnType = SIDE_TRIGGERS.has(input.agent ?? "") ? "side" : "main";

  output.headers = {
    [sessionIdHeader]: sessionId,
    "X-Agent-Session-Id": sessionId,
    [turnTypeHeader]: turnType,
    [workspaceHeader]: workspace,
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

Recommended local OpenCode configuration:

```json
{
  "plugin": ["./plugins/index.js"]
}
```

Parameterized configuration:

```json
{
  "plugin": [
    ["./plugins/index.js", {
      "sessionIdHeader": "X-Session-Id",
      "turnTypeHeader": "X-Turn-Type",
      "workspace": "<workspace-path>"
    }]
  ]
}
```

Options:

| Option | Default | Description |
| --- | --- | --- |
| `sessionIdHeader` | `X-Session-Id` | Header name for the OpenCode session ID. |
| `turnTypeHeader` | `X-Turn-Type` | Header name for main/side classification. |
| `workspace` | `process.cwd()` | Workspace path sent with each request. |
| `workspaceHeader` | `X-Agent-Workspace` | Header name for the workspace path. |
| `debug` | `false` | When `true`, writes plugin lifecycle and hook diagnostics. |
| `debugFile` | unset | File path for debug logs, for example `~/.config/opencode/rl-training-headers-debug.log`. |

`workspace` defaults to the OpenCode plugin process working directory. If you
run OpenCode with a separate project flag such as `opencode run --dir ...`, do
not assume that flag changes the plugin's `process.cwd()`; set the plugin
`workspace` option explicitly when the trace must carry a specific workspace
path.

## Installing the Plugin

OpenCode reliably loads local plugins from its config `plugins/` directory.
Copy the runtime entrypoint into that directory:

```bash
mkdir -p ~/.config/opencode/plugins
cp config/opencode/rl-training-headers/index.js ~/.config/opencode/plugins/index.js
```

On Windows, the equivalent location is:

```text
C:\Users\<you>\.config\opencode\plugins\index.js
```

Then reference the file from `opencode.json`:

```json
{
  "plugin": [
    "./plugins/index.js"
  ]
}
```

The package also has a `package.json` and can be imported as
`rl-training-headers` when it is installed into a Node resolution path, but the
local `plugins/` file is the recommended setup for this repo. It avoids relying
on OpenCode's package cache layout, which can vary by installation.

If you edit `config/opencode/rl-training-headers/index.js`, copy it into
`~/.config/opencode/plugins/index.js` again before retesting.

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
    "./plugins/index.js"
  ]
}
```

The exact OpenCode config shape can vary by version. The invariant is:

- base URL points to `http://<proxy-host>:8905/v1`
- `./plugins/index.js` is loaded
- OpenCode requests carry `X-Session-Id` or `X-Agent-Session-Id`
- OpenCode requests carry `X-Agent-Workspace` when workspace metadata is needed

If proxy authentication is disabled, the API key can be any non-empty value. If
proxy authentication is enabled, it must match `auth.keys` in `config.yaml`.

Only Claude Code uses `run_id` and `workspace_id`. OpenCode does not need either
one; it can send the plain workspace path as `X-Agent-Workspace`.

## Verification

Check that OpenCode loads the plugin:

```bash
opencode debug config --print-logs --log-level DEBUG
```

Expected log fragments:

```text
service=plugin path=./plugins/index.js loading plugin
[rl-training-headers] activated (chat.headers hook)
```

Check the plugin file directly:

```bash
node -e "import('./plugins/index.js').then(m => console.log(m.default.id))"
```

Expected output:

```text
rl-training-headers
```

Check hook behavior manually:

```js
import pluginModule from "./plugins/index.js";

const hooks = await pluginModule.server({}, { workspace: "/path/to/workspace" });
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
  "X-Session-Id": "s1",
  "X-Agent-Session-Id": "s1",
  "X-Turn-Type": "main",
  "X-Agent-Workspace": "/path/to/workspace"
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

If traces are written under `__no_session_id__`:

- confirm the plugin is loaded
- confirm `X-Session-Id` or `X-Agent-Session-Id` is present on the request
- confirm OpenCode is using the proxy base URL
- confirm the request hits port `8905`, not another profile port

If all requests are marked `main`:

- check which `input.agent` value OpenCode sends for background tasks
- add that value to `SIDE_TRIGGERS` if it should be filtered as side traffic
