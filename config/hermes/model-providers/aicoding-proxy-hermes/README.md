# AI Coding Proxy Hermes Provider

This Hermes model-provider plugin routes Hermes through `hermes_proxy.py` and adds request-scoped trace headers without editing Hermes source code.

Install it by copying this directory to:

```text
$HERMES_HOME/plugins/model-providers/aicoding-proxy-hermes/
```

If `HERMES_HOME` is not set, Hermes normally uses `~/.hermes`, so the target is:

```text
~/.hermes/plugins/model-providers/aicoding-proxy-hermes/
```

Configure Hermes to use the provider:

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

If the proxy host is a tailnet or local-network address, bypass system HTTP proxies for it before starting Hermes:

```bash
export NO_PROXY="<proxy-host>"
```

PowerShell:

```powershell
$env:NO_PROXY = "<proxy-host>"
```

Start Hermes from the workspace directory:

```bash
cd /path/to/workspace
hermes
```

Optional debug log:

```bash
export HERMES_RL_HEADERS_LOG="$HOME/.hermes/aicoding-proxy-headers.jsonl"
```

Each main LLM request receives:

```text
X-Session-Id: <Hermes session_id>
X-Agent-Session-Id: <Hermes session_id>
X-Turn-Type: main
X-Agent-Workspace: <Hermes process cwd>
```

The plugin relies on Hermes' documented `ProviderProfile.build_api_kwargs_extras()` hook, which returns top-level OpenAI client kwargs such as `extra_headers`.
