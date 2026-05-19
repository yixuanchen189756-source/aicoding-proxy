# Hermes Proxy Configuration

语言 / Language: [English](README.md) | 简体中文

Hermes 应该通过 Hermes model-provider plugin 接入 AI Coding Proxy，不需要修改 Hermes 源码。

代理入口是：

```bash
python hermes_proxy.py
```

Hermes 代理端点是：

```text
http://<proxy-host>:8907/v1
```

[../../config.yaml](../../config.yaml) 中对应的代理 profile 是：

```yaml
profiles:
  hermes:
    port: 8907
    protocol: "openai"
    backend: "GLM-5-FP8"
    session_dir: "traces/hermes"
    usage_json: "usage/hermes/usage.json"
```

Hermes trace 会写入：

```text
traces/hermes/<session_id>.json
```

## 安装位置

provider plugin 位于：

```text
config/hermes/model-providers/aicoding-proxy-hermes/
```

把整个目录复制到 Hermes 的 model-provider plugin 目录：

```text
$HERMES_HOME/plugins/model-providers/aicoding-proxy-hermes/
```

如果没有设置 `HERMES_HOME`，Hermes 通常使用：

```text
~/.hermes/plugins/model-providers/aicoding-proxy-hermes/
```

## Hermes 配置

编辑 Hermes 的配置文件，通常是 `~/.hermes/config.yaml`，并选择这个 provider：

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

`<proxy-host>` 要换成 Hermes 所在机器可以访问到的代理主机地址。

如果 `proxy/config.yaml` 里 `auth.enabled: false`，`api_key` 只需要是非空值。如果代理开启了认证，`api_key` 必须匹配 `auth.keys` 中的值。

显式的 `auxiliary.title_generation` 会把 Hermes 的后台标题生成请求固定到同一个代理地址。它不是 trace header 的必要条件，但可以避免 Hermes 生成标题时回退到其他 provider。

## Tailnet 和代理绕过

如果 proxy host 是 tailnet 或局域网地址，启动 Hermes 前先设置 `NO_PROXY`，避免 Python/httpx 把请求交给系统 HTTP 代理：

```bash
export NO_PROXY="<proxy-host>"
```

PowerShell：

```powershell
$env:NO_PROXY = "<proxy-host>"
```

例如：

```powershell
$env:NO_PROXY = "100.64.0.132"
```

Windows 持久化：

```powershell
[Environment]::SetEnvironmentVariable("NO_PROXY", "100.64.0.132", "User")
```

如果不设置这个值，可能出现 `curl` 能连通，但 Hermes 或 OpenAI Python SDK 报 `Connection error` 的情况。这通常是因为 httpx 读取了系统代理设置，而该代理不能处理 tailnet 流量。

## Workspace Header

从 workspace 目录启动 Hermes：

```bash
cd /path/to/workspace
hermes
```

PowerShell：

```powershell
Set-Location C:\path\to\workspace
hermes
```

插件读取 Hermes 进程的 cwd，并发送为：

```text
X-Agent-Workspace: <Hermes process cwd>
```

## 插件发送的 Headers

每个 Hermes LLM 请求都会添加：

```text
X-Session-Id: <Hermes session_id>
X-Agent-Session-Id: <Hermes session_id>
X-Turn-Type: main
X-Agent-Workspace: <Hermes process cwd>
```

说明：

- `session_id` 来自 Hermes provider runtime context。
- `workspace` 来自 Hermes 进程 cwd。
- Hermes 不需要 `run_id` 或 `workspace_id`。
- 插件使用请求级 `extra_headers`，不 patch 全局 HTTP client。

## 可选调试日志

如果要确认 provider 是否真的运行、是否拿到了 session ID：

```bash
export HERMES_RL_HEADERS_LOG="$HOME/.hermes/aicoding-proxy-headers.jsonl"
```

PowerShell：

```powershell
$env:HERMES_RL_HEADERS_LOG = "$HOME\.hermes\aicoding-proxy-headers.jsonl"
```

每个请求会追加一行 JSON，显示是否拿到了 `session_id` 和 workspace。日志不会记录 prompt 或模型回答。

## 需要修改 `proxy/config.yaml` 吗？

通常不需要。

只有当你想改变代理监听端口、上游 backend、usage 文件、认证 key 或 trace 目录时，才需要改 `proxy/config.yaml`：

```yaml
profiles:
  hermes:
    port: 8907
    backend: "GLM-5-FP8"
    session_dir: "traces/hermes"
```

Hermes plugin 安装在 Hermes 自己的插件目录里，并由 Hermes 配置文件选择。`proxy/config.yaml` 不负责加载 Hermes plugin。

## 为什么用 Model-Provider Plugin

Hermes hooks 可以观察生命周期事件，也可以注入 prompt context，但它们不是修改 HTTP request headers 的合适层。

model-provider plugin 才是合适层，因为 Hermes 构建模型请求时会调用 `ProviderProfile.build_api_kwargs_extras()`。这个方法可以为当前请求返回 OpenAI client kwargs，包括 `extra_headers`。

## 验证

启动代理：

```bash
cd proxy
python hermes_proxy.py
```

用该 provider 启动 Hermes 后发送一条消息。代理应写出：

```text
traces/hermes/<session_id>.json
```

如果文件落到 `__no_session_id__`，打开 `HERMES_RL_HEADERS_LOG`，确认日志里是否有 `has_session_id: true`。

验证 Hermes 机器上的 Python/OpenAI SDK 连通性：

```bash
python -c "from openai import OpenAI; c=OpenAI(api_key='sk-proxy', base_url='http://<proxy-host>:8907/v1'); r=c.chat.completions.create(model='glm-5-fp8', messages=[{'role':'user','content':'hello'}], max_tokens=20); print(repr(r.choices[0].message.content))"
```

如果这个命令失败，但 `curl http://<proxy-host>:8907/health` 可以成功，给 proxy host 设置 `NO_PROXY` 后重试。
