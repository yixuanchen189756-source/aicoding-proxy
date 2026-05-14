# AI Coding Proxy

语言 / Language: [English](README.md) | 简体中文

本目录是项目最终交付用的代理包，用于接入多个 coding agent，转发它们的 LLM 请求，并按 agent/session/workspace 存储训练轨迹。

这个项目的实现风格是“小而直接”：运行配置放在 `config.yaml`，各个 agent 的插件、hook 和说明放在 `config/` 子目录，代理把轨迹写成 JSON 文件。每个 agent 优先使用它自身最轻量、最稳定的 hook 或插件机制，尽量不侵入 agent 的主流程。

## 项目目标

这个代理主要解决四件事：

- 用同一套代码服务多个 coding agent。
- 把不同 agent 的请求路由到不同的上游模型后端。
- 给每条轨迹绑定稳定的 session/workspace/run metadata。
- 按 agent 分开存储轨迹，方便后续筛选、检查、训练和回放。

这个项目不是为了替代 OpenCode、Claude Code、Hermes 或 OpenClaw。它位于 agent 和上游模型服务之间，在尽量保持 agent 原始行为的同时，增加请求路由、轨迹采集和会话归档能力。

## 目录结构

```text
proxy/
  agent_proxy_core.py
    OpenCode、Claude Code、Hermes 共享的代理核心。下面三个独立入口脚本
    会导入这个文件，并且每次只选择一个 profile。

  opencode_proxy.py
  claude_code_proxy.py
  hermes_proxy.py
    OpenCode、Claude Code、Hermes 的独立 agent 入口。每个脚本只启动对应
    agent 真正需要的接口。

  openclaw_proxy.py
    OpenClaw 专用代理逻辑。负责 OpenClaw gateway 注册、instance 路由、
    token registry、OpenClaw 内部消息处理和轨迹整理，并从 config.yaml
    读取 OpenClaw 运行配置。

  config.yaml
    主运行配置。包含模型后端、agent profile、OpenClaw 运行配置、
    认证、metrics、trace、usage 等配置。

  config/
    opencode/
      OpenCode 插件和说明文档。

    claude-code/
      Claude Code hook 脚本和说明文档。

    hermes/
      Hermes 接入说明。

    openclaw/
      OpenClaw extensions、skills、workspace templates 和说明文档。
```

如果 `config.yaml` 中使用相对路径，运行输出会相对于当前进程工作目录写入：

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

## 代理组成

### 共享核心和独立入口

[agent_proxy_core.py](agent_proxy_core.py) 是 OpenCode、Claude Code、Hermes 的共享代理核心。它不是启动入口；正常使用时请启动对应的独立入口脚本：

```bash
python opencode_proxy.py
python claude_code_proxy.py
python hermes_proxy.py
```

每个入口脚本都会导入 `agent_proxy_core.py`，从 [config.yaml](config.yaml) 中只选择自己的 profile，并创建一个只包含该 coding agent 所需接口的 app。这样每个进程负责一个 agent，部署和排查问题都更清楚。

当前三个主 profile：

| Agent | 端口 | 客户端协议 | 上游处理方式 | 轨迹目录 |
| --- | ---: | --- | --- | --- |
| OpenCode | `8905` | OpenAI-compatible | 直接转发 OpenAI 格式请求 | `traces/opencode` |
| Claude Code | `8906` | Anthropic Messages | 必要时转换为 OpenAI chat/completions | `traces/claude-code` |
| Hermes | `8907` | OpenAI-compatible | 直接转发 OpenAI 格式请求 | `traces/hermes` |

这个包里有意不再提供 `client.py` 入口。拆分后的独立脚本就是支持的部署方式。

### openclaw_proxy.py

[openclaw_proxy.py](openclaw_proxy.py) 是 OpenClaw 专用代理。它会读取 [config.yaml](config.yaml) 顶层的 `openclaw` 配置，并据此设置监听端口、上游 backend 和轨迹目录。它不和前三个 agent 共用 `agent_proxy_core.py`，因为 OpenClaw 有自己的 gateway 和 instance 模型。

OpenClaw 比其他 agent 多了 gateway 和 instance 概念，所以它需要额外处理：

- `X-Instance-Id`
- gateway URL/token 注册
- `gateway_instances.json`
- `gateway_tokens.json`
- OpenClaw 内部消息过滤
- OpenClaw session/task 轨迹整理

启动入口是：

```bash
python openclaw_proxy.py
```

## 接口暴露范围

独立 agent 入口只暴露对应 agent 真正会用到的接口。

OpenCode 和 Hermes：

- `GET /`
- `HEAD /`
- `GET /health`
- `GET /v1/models`
- `/v1/{path:path}`

Claude Code：

- `GET /`
- `HEAD /`
- `GET /health`
- `GET /v1/models`
- `/v1/{path:path}`
- `POST /_agent/session-event`

独立 profile 入口有意不暴露宽泛的调试/管理接口，例如：

- `GET /backends`
- `GET /usage`
- `GET /metrics`

## 配置模型

`config.yaml` 主要包含四类配置：

- `backends`
- `profiles`
- `openclaw`
- `auth` / `metrics` / `proxy`

### backends

`backends` 定义上游模型服务。每个 backend 可以有一个或多个 endpoint，也可以配置模型名映射、endpoint 级 API key、OpenAI 格式 URL、额外请求头等。

示例：

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

不要把真实上游 API key 提交到仓库。建议使用占位符、环境变量展开，或者维护一份私有部署版 `config.yaml`。

### profiles

`profiles` 绑定 agent 名称、本地监听端口、协议类型、backend 和轨迹路径。

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

代理启动时会验证 `opencode`、`claude-code`、`hermes` 这些 coding-agent profile。无效 profile 会被禁用并输出清晰 warning。如果三者全部不可用，进程会退出。

### openclaw

OpenClaw 不放在 `profiles` 里，因为它由 `openclaw_proxy.py` 直接处理，而不是普通的共享 profile。

```yaml
openclaw:
  port: 8908
  backend: "GLM-5-FP8"
  session_dir: "traces/openclaw"
```

字段含义：

- `port`: `openclaw_proxy.py` 监听端口。
- `backend`: OpenClaw 使用的上游 backend 名称，必须存在于 `backends`。
- `session_dir`: OpenClaw 轨迹目录。

### proxy

```yaml
proxy:
  connect_timeout_s: 10
  stream_chunk_size: 8192
  debug: false
  trace: false
  usage_json: "usage.json"
```

- `debug`: 打印路由、上游错误、重试等诊断信息。
- `trace`: 把请求/响应摘要打印到 stderr。
- `session_json`: 旧版轨迹存储路径；现在优先使用 profile 的 `session_dir`。
- `usage_json`: 旧版 usage 存储路径；现在优先使用 profile 的 `usage_json`。

## 启动方式

安装依赖：

```bash
pip install fastapi uvicorn aiohttp pyyaml prometheus-client
```

推荐分别启动四个独立代理。每个脚本负责一个 agent 和一个配置好的端口：

```bash
cd proxy
python opencode_proxy.py
python claude_code_proxy.py
python hermes_proxy.py
python openclaw_proxy.py
```

这个包里没有合并式 `client.py` 启动路径。OpenClaw 始终通过 `openclaw_proxy.py` 启动；它不属于共享 profile router。

快速检查：

```bash
curl http://127.0.0.1:8905/health
curl http://127.0.0.1:8906/health
curl http://127.0.0.1:8907/health
curl http://127.0.0.1:8908/health
```

如果代理运行在另一台机器上，把 `127.0.0.1` 换成对应主机 IP 或 tailnet IP。

## Agent 接入方式

### OpenCode

OpenCode 使用 [config/opencode/rl-training-headers](config/opencode/rl-training-headers) 插件。

这个插件使用 OpenCode 原生的 `chat.headers` hook。每次 LLM 请求前，它会注入：

- `X-Session-Id: <userName>_<sessionID>`
- `X-Turn-Type: main|side`

OpenCode 的 OpenAI-compatible provider 应指向：

```text
http://<proxy-host>:8905/v1
```

如果代理没有启用认证，API key 可以是任意非空值。如果启用了认证，API key 必须匹配 `auth.keys`。

详细安装和验证方式见 [config/opencode/README.md](config/opencode/README.md)。

### Claude Code

Claude Code 使用两个机制配合：

1. 环境变量设置模型请求的 base URL 和自定义 header。
2. Claude Code hook 把 session start/resume 事件上报给代理。

Claude Code 的模型请求应指向：

```text
http://<proxy-host>:8906/v1/messages
```

模型请求必须带这些 metadata header：

- `X-Agent-Name: claude-code`
- `X-Agent-Run-Id: <stable-run-id>`
- `X-Agent-Workspace-Id: <workspace-id>`
- `X-Agent-Workspace: <workspace-path>`
- `X-Instance-Id: <machine-or-instance-id>`

hook 上报 session event 到：

```text
http://<proxy-host>:8906/_agent/session-event
```

代理用 `X-Agent-Run-Id` 查询 hook 最近上报的 session ID。这样 `/resume`、`/new`、`/clear`，以及启动时直接打开已有 session，都能继续写入正确的 session 轨迹。

Claude Code 轨迹路径：

```text
traces/claude-code/<workspace_id>/<session_id>/trajectory.json
traces/claude-code/<workspace_id>/<session_id>/metadata.json
traces/claude-code/<workspace_id>/runs/<run_id>.json
```

完整 hook 和 settings 配置见 [config/claude-code/README.md](config/claude-code/README.md)。

### Hermes

Hermes 应配置为使用 OpenAI-compatible profile：

```text
http://<proxy-host>:8907/v1
```

Hermes 自身需要在主 LLM 请求中注入：

- `X-Session-Id: <user_name>_<session_id>`
- `X-Turn-Type: main|side`

推荐做法是在 Hermes 构造 LLM 请求参数时，通过 `extra_headers` 注入这些 header。后台 memory flush、cron 等任务应标记为 `side`，用户主动交互应标记为 `main`。

Hermes patch 和配置说明见 [config/hermes/README.md](config/hermes/README.md)。

### OpenClaw

OpenClaw 使用独立代理：

```bash
python openclaw_proxy.py
```

OpenClaw 和前三者不同，因为它有自己的 gateway 和 instance 模型。[config/openclaw/extensions/rl-training-headers](config/openclaw/extensions/rl-training-headers) 插件负责：

- 给 LLM 请求注入 `X-Session-Id`、`X-Turn-Type`、`X-Instance-Id`
- 向 `openclaw_proxy.py` 注册 OpenClaw gateway URL/token

OpenClaw 的运行配置在 `config.yaml` 顶层 `openclaw` 段：

```yaml
openclaw:
  port: 8908
  backend: "GLM-5-FP8"
  session_dir: "traces/openclaw"
```

请确保 OpenClaw 插件里的 `proxyRegisterUrl` 指向同一个端口。

完整 OpenClaw 配置说明见 [config/openclaw/README.md](config/openclaw/README.md)。

## 轨迹格式

主代理会为每个 session 存储一个归一化后的轨迹快照。典型结构：

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

重要归一化规则：

- Claude Code 的 title-generation 请求会被跳过，避免覆盖真实对话轨迹。
- assistant 的 `<think>...</think>` 内容会保留。
- Claude Code 的 `<system-reminder>...</system-reminder>` block 会按时间顺序拆成 `system` message，而不是混在 user message 里。
- tool call 里的随机 ID 会被移除，减少非确定性噪声。

## 用量统计

每个 profile 可以写入自己的 token usage JSON：

```text
usage/opencode/usage.json
usage/claude-code/usage.json
usage/hermes/usage.json
```

`/usage` 接口可以按 client IP 和 model 查看用量：

```bash
curl http://127.0.0.1:8905/usage
curl "http://127.0.0.1:8905/usage?ip=127.0.0.1"
```

## 调试

打开请求/响应 trace：

```yaml
proxy:
  debug: true
  trace: true
```

常用检查：

```bash
curl http://127.0.0.1:8905/backends
curl http://127.0.0.1:8906/backends
curl http://127.0.0.1:8907/backends
```

Claude Code session-event 手动测试：

```bash
curl -X POST http://127.0.0.1:8906/_agent/session-event \
  -H "Content-Type: application/json" \
  -d '{"agent_name":"claude-code","run_id":"test-run","session_id":"test-session","workspace_id":"test-workspace"}'
```

期望返回：

```json
{"ok": true, "run_id": "test-run", "active_session_id": "test-session", "workspace_id": "test-workspace"}
```

## 测试

在仓库根目录运行：

```bash
python -B -m py_compile proxy/agent_proxy_core.py proxy/opencode_proxy.py proxy/claude_code_proxy.py proxy/hermes_proxy.py proxy/openclaw_proxy.py
python -m unittest discover -s tests -v
```

部分测试会覆盖 `proxy/` 之外的历史脚本和测试 fixtures，这是当前仓库结构的一部分。

## 安全注意事项

- 不要提交真实上游 API key。
- 轨迹文件是敏感数据，可能包含 prompt、源码、工具输出、本地路径和 system reminder。
- 如果 `auth.enabled` 为 `false`，任何能访问代理端口的客户端都可以调用代理。暴露到非可信网络前，请绑定到可信网络或启用认证。
- Claude Code hook 应该是 best-effort：代理暂时不可用时，hook 应记录失败但不能阻塞 Claude Code。
