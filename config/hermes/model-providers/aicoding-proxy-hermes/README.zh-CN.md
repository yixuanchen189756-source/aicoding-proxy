# AI Coding Proxy Hermes Provider

语言 / Language: [English](README.md) | 简体中文

这个 Hermes model-provider plugin 会把 Hermes 请求路由到 `hermes_proxy.py`，并在不修改 Hermes 源码的情况下添加 trace headers。

安装方式：把整个目录复制到：

```text
$HERMES_HOME/plugins/model-providers/aicoding-proxy-hermes/
```

如果没有设置 `HERMES_HOME`，Hermes 通常使用 `~/.hermes`，所以目标路径是：

```text
~/.hermes/plugins/model-providers/aicoding-proxy-hermes/
```

在 Hermes 配置中选择这个 provider：

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

如果 proxy host 是 tailnet 或局域网地址，启动 Hermes 前先绕过系统 HTTP 代理：

```bash
export NO_PROXY="<proxy-host>"
```

PowerShell：

```powershell
$env:NO_PROXY = "<proxy-host>"
```

从 workspace 目录启动 Hermes：

```bash
cd /path/to/workspace
hermes
```

可选调试日志：

```bash
export HERMES_RL_HEADERS_LOG="$HOME/.hermes/aicoding-proxy-headers.jsonl"
```

每个 main LLM 请求都会收到：

```text
X-Session-Id: <Hermes session_id>
X-Agent-Session-Id: <Hermes session_id>
X-Turn-Type: main
X-Agent-Workspace: <Hermes process cwd>
```

插件依赖 Hermes 官方的 `ProviderProfile.build_api_kwargs_extras()` hook。这个 hook 可以返回顶层 OpenAI client kwargs，例如 `extra_headers`。
