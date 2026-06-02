# OpenClaw Proxy Configuration

语言 / Language: [English](README.md) | 简体中文

本目录包含用于采集 RL trace 的 OpenClaw 专用集成资源。

OpenClaw 独立于共享 profile core 处理。OpenClaw 请使用 `proxy/openclaw_proxy.py`，因为 OpenClaw 有自己的 gateway、instance registration 和内部消息模式。

## 目录结构

```text
config/openclaw/
  extensions/
    rl-training-headers/
      注入 RL headers，并向代理注册 OpenClaw gateway。

    task-commands/
      提供 /clear-memory skill 使用的 clear_memory tool。

  skills/
    clear-memory/
      用户可调用的 skill，会调用 clear_memory。

  workspace/
    markdown_templates/
      用于重置 OpenClaw workspace memory 的模板 markdown 文件。
```

## Runtime Components

### OpenClaw Proxy

从 `proxy/` 启动 OpenClaw 专用代理：

```bash
python openclaw_proxy.py
```

`openclaw_proxy.py` 是实际的 OpenClaw 代理服务。它会读取 `proxy/config.yaml` 顶层的 `openclaw` block，用于设置监听端口、上游 backend 和 trace 目录。

默认情况下，当前 OpenClaw 代理监听：

```text
http://0.0.0.0:8908
```

如果想使用不同端口，可以设置 `OPENAI_PROXY_PORT`：

```bash
OPENAI_PROXY_PORT=8908 python openclaw_proxy.py
```

推荐的持久化配置是 `proxy/config.yaml` 顶层的 `openclaw` block：

```yaml
openclaw:
  port: 8908
  backend: "GLM-5-FP8"
  session_dir: "traces/openclaw"
```

重要环境变量：

```text
VLLM_BASE_URL
  上游 backend base URL 的可选覆盖。优先在 proxy/config.yaml 中配置 backend。

VLLM_MODEL_NAME
  发送给上游 backend 的模型名可选覆盖。

VLLM_API_KEY
  上游 API key 的可选覆盖。

OPENAI_PROXY_PORT
  openclaw_proxy.py 的可选端口覆盖。优先配置 proxy/config.yaml 里的 openclaw.port。

OPENAI_PROXY_TRACE=1
  将请求/响应 trace 摘要打印到 stderr。

OPENAI_PROXY_SESSION_FOLDER
  per-session trace 文件夹的根目录。每个 session 会写成
  <session_id>/task_<i>.json。如果没有设置这个环境变量，代理会使用
  proxy/config.yaml 里的 openclaw.session_dir；如果 config.yaml 也没有配置，
  就使用当前工作目录。
```

OpenClaw 代理还会在脚本附近持久化 gateway instance metadata：

```text
gateway_instances.json
```

这些文件包含运行时注册信息，不应视为可移植源文件。

### OpenClaw Client Gateway 要求

OpenClaw client 必须暴露本地 gateway 的 chat-completions endpoint。否则
`openclaw_proxy.py` 可以收到普通模型请求，但无法在 task 完成后把
`/clear-memory` 请求发回 OpenClaw。

在 OpenClaw state/config 文件中，通常是 `openclaw.json`，需要开启本地
LAN gateway、token auth，以及 HTTP OpenAI chat-completions endpoint：

```json
{
  "gateway": {
    "mode": "local",
    "bind": "lan",
    "auth": {
      "mode": "token",
      "token": "<token>"
    },
    "http": {
      "endpoints": {
        "chatCompletions": {
          "enabled": true
        }
      }
    },
    "dangerouslyAllowHostHeaderOriginFallback": true,
    "dangerouslyDisableDeviceAuth": true
  }
}
```

这里的 token 应该和 `rl-training-headers` extension 能从 OpenClaw state
或 `OPENCLAW_GATEWAY_TOKEN` 读取到的 gateway token 一致。当代理通过主机
LAN 或 tailnet 地址访问 OpenClaw，而不是通过 loopback 访问时，需要
`bind: "lan"`。

### rl-training-headers Extension

路径：

```text
config/openclaw/extensions/rl-training-headers/
```

用途：

- 注入 `X-Session-Id`
- 注入 `X-Turn-Type`
- 注入 `X-Instance-Id`
- 向 `openclaw_proxy.py` 注册 OpenClaw gateway URL/token

不同于 OpenCode，OpenClaw 没有同样的原生 `chat.headers` hook。这个 extension 使用 OpenClaw 生命周期事件和一个很窄的 `globalThis.fetch` patch：

```text
before_prompt_build
  -> compute pending headers from session/trigger
  -> patched fetch injects headers into the next POST
agent_end
  -> clear pending headers
```

extension 还会注册 service startup hook；如果启动注册没有完成，会在 `before_prompt_build` 时重试注册。

### task-commands Extension

路径：

```text
config/openclaw/extensions/task-commands/
```

用途：

- 注册 `clear_memory` tool
- 从 `workspace/markdown_templates` 重置 workspace markdown 文件
- 清理没有对应模板的现有 `.md` workspace 文件

### clear-memory Skill

路径：

```text
config/openclaw/skills/clear-memory/SKILL.md
```

用户命令：

```text
/clear-memory
```

这个命令会直接调用 `clear_memory`。它会对 OpenClaw workspace markdown 文件执行破坏性重置，所以只应在当前 workspace memory 需要从模板重置时使用。

## Header 语义

### X-Session-Id

格式：

```text
<openclaw-session-id>
```

extension 使用 OpenClaw 的 `ctx.sessionId` 作为 trace session ID。不要使用 `ctx.sessionKey` 做 trace 分组：OpenClaw 可能为同一个可见对话或 `/clear-memory` 这类内部请求创建不同的 `dashboard` 和 `openai` session key。

这样，同一个 OpenClaw 对话里的用户任务会留在同一个 trace 文件夹下，同时代理仍然能把该文件夹拆成多个 `task_<i>.json` 文件。

### X-Turn-Type

| 值 | 含义 |
| --- | --- |
| `main` | 面向用户的交互。 |
| `side` | 后台或维护活动。 |

extension 会把这些 trigger 标记为 `side`：

```text
heartbeat
memory
cron
```

其他请求都视为 `main`。

### X-Instance-Id

标识 OpenClaw instance。当多个 OpenClaw instances 调用同一个代理时，这可以让代理区分 gateway registrations 和 traces。

插件会从 OpenClaw gateway URL 的 origin 派生这个值：

```text
http://100.64.0.70:18789/v1/chat/completions -> 100.64.0.70_18789
```

手动配置的 `instanceId` 会被忽略，避免 `pc-m-main` 这类旧名字继续成为 registry key。

### X-Agent-Workspace

如果插件能解析 workspace 路径，就会把它放到这个 header 中。插件会优先使用 OpenClaw prompt context 里的 workspace 信息；如果没有，就使用当前进程工作目录。

## Extension 配置

`rl-training-headers/openclaw.plugin.json` 定义这些选项：

| Option | Default | Description |
| --- | --- | --- |
| `sessionIdHeader` | `X-Session-Id` | session ID header 名称。 |
| `turnTypeHeader` | `X-Turn-Type` | turn type header 名称。 |
| `instanceIdHeader` | `X-Instance-Id` | instance ID header 名称。 |
| `workspaceHeader` | `X-Agent-Workspace` | workspace 路径 header 名称。 |
| `instanceId` | ignored | 兼容旧配置，但插件会忽略这个值。 |
| `proxyRegisterUrl` | ignored | 兼容旧配置，但插件会忽略这个值。 |
| `gatewayUrl` | Required | OpenClaw gateway URL。 |
| `gatewayToken` | read from OpenClaw state when possible | Gateway auth token。 |
| `gatewayPort` | `18789` | 本地 OpenClaw gateway 端口。 |
| `registerOnStart` | `true` | 是否在 service start 时注册。 |

环境变量 fallback：

```text
OPENCLAW_STATE_DIR
OPENCLAW_GATEWAY_PORT
OPENCLAW_GATEWAY_URL
OPENCLAW_GATEWAY_TOKEN
OPENCLAW_WORKSPACE_DIR
```

OpenClaw 客户端侧只有一个代理地址来源：OpenClaw 自己配置里的当前默认 model provider `baseUrl`，例如：

```text
models.providers.vllm.baseUrl = http://<proxy-host>:8908/v1
```

插件会从 OpenClaw state 读取默认 model provider，去掉末尾的 `/v1`，自动派生：

```text
http://<proxy-host>:8908/register-instance
```

不要再单独配置 `proxyRegisterUrl`；旧值会被忽略，避免 chat completions 和 registration 指向不同地址。

extension 会尝试从这些位置读取 gateway token：

```text
<OPENCLAW_STATE_DIR>/openclaw.json
%USERPROFILE%\.openclaw\openclaw.json
$HOME/.openclaw/openclaw.json
```

## 安装 Extensions

把 extension 文件夹复制到你的 OpenClaw 安装使用的 extension 位置。典型 Windows 布局：

```text
<user-home>/.openclaw/extensions/rl-training-headers
<user-home>/.openclaw/extensions/task-commands
```

复制 skill：

```text
<user-home>/.openclaw/skills/clear-memory
```

复制或合并 workspace templates：

```text
<user-home>/.openclaw/workspace/markdown_templates
```

复制完成后，重启 OpenClaw 或重新加载 extensions。

## Proxy Registration Flow

预期流程：

```text
OpenClaw starts
  -> rl-training-headers extension loads
  -> extension resolves gateway URL/token/instance ID
  -> extension POSTs registration to openclaw_proxy.py
  -> proxy stores gateway_instances.json
  -> later LLM requests carry X-Instance-Id and X-Session-Id
  -> proxy writes traces by session/task and detects task completion
  -> each completed task triggers one /clear-memory request to the gateway
  -> proxy can route/attribute requests for that instance
```

trace 文件会写入：

```text
traces/openclaw/<session_id>/task_1.json
traces/openclaw/<session_id>/task_2.json
```

当前 `task_<i>.json` 会随着对话推进持续更新。当代理检测到一个 task 完成后，下一个面向用户的 task 会切换到下一个 task 文件。

这是有意设计的：OpenClaw trace 按 task 拆分，而不只是按 session 拆分。task 完成后，代理会通知 OpenClaw gateway 运行 `/clear-memory`。这个命令会从模板重置配置的 workspace memory 文件，因此下一个 task 会从干净状态开始；如果用户继续同一个 session，它仍然会留在同一个 session 文件夹下。

OpenClaw 在处理 `/clear-memory` 请求时可能会创建额外的内部 `openai` session contexts。这些请求会被 trace writer 跳过，不应成为用户可见对话的 session 文件夹。

注册 payload 形状：

```json
{
  "instance_id": "100.64.0.70_18789",
  "gateway_url": "http://<openclaw-gateway-host>:18789/v1/chat/completions",
  "gateway_token": "<token>",
  "gateway_port": "18789",
  "source": "rl-training-headers",
  "reason": "service_start",
  "updated_at": "2026-05-14T00:00:00.000Z"
}
```

## 日志

extension 会尽力把日志写到：

```text
<OPENCLAW_STATE_DIR>/logs/rl-training-headers.log
```

如果没有设置 `OPENCLAW_STATE_DIR`，则写入默认 OpenClaw state directory。

有用日志：

- `module loaded`
- `resolved config ...`
- `service start hook fired`
- `registering gateway instance`
- `registered gateway instance`
- `before_prompt_build seq=... sessionId=... sessionKey=...`
- `fetch POST applying headers seq=... target=... xSession=...`
- `agent_end clearing pending headers seq=...`

## 验证

1. 启动 `openclaw_proxy.py`。
2. 启动已安装 extension 的 OpenClaw。
3. 检查 extension logs，确认 gateway registration。
4. 发送一个普通 OpenClaw prompt。
5. 确认模型请求包含：

```text
X-Session-Id
X-Turn-Type
X-Instance-Id
```

6. 确认代理为该 session 写入 trace。

## Troubleshooting

如果 registration 失败：

- 检查当前 OpenClaw model provider 的 `baseUrl`
- 检查 `openclaw_proxy.py` 是否在运行
- 检查 gateway token 是否存在于 OpenClaw state 中，或是否通过 `OPENCLAW_GATEWAY_TOKEN` 设置
- 检查 `rl-training-headers.log`

如果 headers 缺失：

- 确认 extension log 中出现 `before_prompt_build`
- 确认 LLM 请求是 `POST`
- 确认没有其他 extension 在这个 extension 之后替换 request headers

如果 `/clear-memory` 失败：

- 确认 `task-commands` 已安装并加载
- 确认 `workspace/markdown_templates` 存在
- 确认 OpenClaw 可以写入它的 workspace 目录
