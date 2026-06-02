# Hermes Proxy Configuration

Language / 语言: English | [简体中文](README.zh-CN.md)

Hermes should use the AI Coding Proxy through a Hermes model-provider plugin, not by editing Hermes source code.

The proxy entrypoint is:

```bash
python hermes_proxy.py
```

The Hermes proxy endpoint is:

```text
http://<proxy-host>:8907/v1
```

The matching proxy profile in [../../config.yaml](../../config.yaml) is:

```yaml
profiles:
  hermes:
    port: 8907
    protocol: "openai"
    backend: "GLM-5-FP8"
    session_dir: "traces/hermes"
    usage_json: "usage/hermes/usage.json"
```

Hermes traces are written as:

```text
traces/hermes/<session_id>.json
```

## What To Install

Install the provider plugin in this folder:

```text
config/hermes/model-providers/aicoding-proxy-hermes/
```

Copy the whole directory to Hermes' model-provider plugin directory:

```text
$HERMES_HOME/plugins/model-providers/aicoding-proxy-hermes/
```

If `HERMES_HOME` is not set, Hermes normally uses:

```text
~/.hermes/plugins/model-providers/aicoding-proxy-hermes/
```

## Hermes Config

Edit Hermes' config file, normally `~/.hermes/config.yaml`, and select the provider:

```yaml
model:
  default: glm-5-fp8
  provider: aicoding-proxy-hermes
  base_url: http://<proxy-host>:8907/v1
  api_key: sk-proxy
  api_mode: chat_completions

auxiliary:
  title_generation:
    provider: custom
    model: glm-5-fp8
    base_url: http://<proxy-host>:8907/v1
    api_key: sk-proxy
    api_mode: chat_completions
```

Use the actual proxy host that the Hermes machine can reach.

If `proxy/config.yaml` has `auth.enabled: false`, `api_key` only needs to be non-empty. If proxy auth is enabled, `api_key` must match one of `auth.keys`.

The explicit `auxiliary.title_generation` block keeps Hermes' background session-title request on the same proxy endpoint. It is optional for trace headers, but it avoids Hermes falling back to another provider when generating titles.

## Tailnet And Proxy Bypass

If the proxy host is a tailnet or local-network address, set `NO_PROXY` before starting Hermes so Python/httpx does not route the request through a system HTTP proxy:

```bash
export NO_PROXY="<proxy-host>"
```

PowerShell:

```powershell
$env:NO_PROXY = "<proxy-host>"
```

For example, replace `<proxy-host>` with the proxy host or tailnet address:

```powershell
$env:NO_PROXY = "<proxy-host>"
```

To persist it on Windows:

```powershell
[Environment]::SetEnvironmentVariable("NO_PROXY", "<proxy-host>", "User")
```

Without this, `curl` may work while Hermes or the OpenAI Python SDK fails with `Connection error`, because httpx can pick up system proxy settings that do not handle tailnet traffic.

## Workspace Header

Start Hermes from the workspace directory:

```bash
cd /path/to/workspace
hermes
```

PowerShell:

```powershell
Set-Location C:\path\to\workspace
hermes
```

The plugin reads the Hermes process cwd and sends it as:

```text
X-Agent-Workspace: <Hermes process cwd>
```

## Headers Sent By The Plugin

For each Hermes LLM request, the provider plugin adds:

```text
X-Session-Id: <Hermes session_id>
X-Agent-Session-Id: <Hermes session_id>
X-Turn-Type: main
X-Agent-Workspace: <Hermes process cwd>
```

Notes:

- `session_id` comes from Hermes' provider runtime context.
- `workspace` comes from the Hermes process cwd.
- Hermes does not need `run_id` or `workspace_id`.
- The plugin uses request-scoped `extra_headers`; it does not patch global HTTP clients.

## Optional Debug Log

To confirm the provider is running and receiving a session ID:

```bash
export HERMES_RL_HEADERS_LOG="$HOME/.hermes/aicoding-proxy-headers.jsonl"
```

PowerShell:

```powershell
$env:HERMES_RL_HEADERS_LOG = "$HOME\.hermes\aicoding-proxy-headers.jsonl"
```

Each request appends one JSON line showing whether a `session_id` and workspace were available. The log intentionally does not include prompts or responses.

## Do I Need To Edit `proxy/config.yaml`?

Usually no.

Only edit `proxy/config.yaml` if you want to change the proxy listener port, upstream backend, usage file, auth keys, or trace folder:

```yaml
profiles:
  hermes:
    port: 8907
    backend: "GLM-5-FP8"
    session_dir: "traces/hermes"
```

The Hermes plugin is installed into Hermes' own plugin directory and selected from Hermes' config. It is not loaded by `proxy/config.yaml`.

## Why A Model-Provider Plugin?

Hermes hooks can observe lifecycle events and add prompt context, but they are not the right layer for mutating HTTP request headers.

The model-provider plugin is the right layer because Hermes calls `ProviderProfile.build_api_kwargs_extras()` while building the model request. That method can return OpenAI client kwargs, including `extra_headers`, for the current request.

## Verification

Start the proxy:

```bash
cd proxy
python hermes_proxy.py
```

Start Hermes with the provider selected, then send a message. The proxy trace should be written to:

```text
traces/hermes/<session_id>.json
```

If the file lands under `__no_session_id__`, enable `HERMES_RL_HEADERS_LOG` and check whether the plugin saw `has_session_id: true`.

To verify Python/OpenAI SDK connectivity from the Hermes machine:

```bash
python -c "from openai import OpenAI; c=OpenAI(api_key='sk-proxy', base_url='http://<proxy-host>:8907/v1'); r=c.chat.completions.create(model='glm-5-fp8', messages=[{'role':'user','content':'hello'}], max_tokens=20); print(repr(r.choices[0].message.content))"
```

If this fails but `curl http://<proxy-host>:8907/health` works, set `NO_PROXY` for the proxy host and retry.
