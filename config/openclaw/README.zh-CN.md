# OpenClaw 代理配置

语言 / Language: [English](README.md) | 简体中文

本目录包含用于采集 RL 轨迹的 OpenClaw 专用集成资源。

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

## 运行组件

### OpenClaw Proxy

从 `proxy/` 启动 OpenClaw 专用代理：

```bash
python openclaw_proxy.py
```

`openclaw_proxy.py` 是实际的 OpenClaw 代理服务。它会读取 `proxy/config.yaml` 顶层的 `openclaw` block，用于设置监听端口、上游 backend 和轨迹目录。

默认情况下，当前 OpenClaw 代理监听：

```text
http://0.0.0.0:8908
```

如果需要不同端口，可以设置 `OPENAI_PROXY_PORT`：

```bash
OPENAI_PROXY_PORT=8288 python openclaw_proxy.py
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
  发送给上游 backend 的模型名的可选覆盖。

VLLM_API_KEY
  上游 API key 的可选覆盖。

OPENAI_PROXY_PORT
  openclaw_proxy.py 的可选端口覆盖。优先配置 proxy/config.yaml 里的
  openclaw.port。

OPENAI_PROXY_TRACE=1
  将请求/响应 trace 摘要打印到 stderr。

OPENAI_PROXY_SESSION_FOLDER
  per-session 轨迹文件目录。
```

OpenClaw 代理还会在脚本附近保存 gateway metadata：

```text
gateway_tokens.json
gateway_instances.json
```

这些文件包含运行时注册信息，不应被视为可移植源文件。

### rl-training-headers Extension

路径：

```text
config/openclaw/extensions/rl-training-headers/
```

目的：

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

目的：

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
<fixed-user-name>_<openclaw-session-id>
```

当前 extension 代码在 `index.ts` 中使用固定用户命名空间：

```ts
const FIXED_USER_NAME = "your-fixed-user-name";
```

生产使用前，如果需要按用户或机器区分，请修改它。

### X-Turn-Type

| 值 | 含义 |
| --- | --- |
| `main` | 面向用户的交互。 |
| `side` | 后台或维护活动。 |

extension 会把这些 trigger 视为 `side`：

```text
heartbeat
memory
cron
```

其他请求都视为 `main`。

### X-Instance-Id

标识 OpenClaw instance。当多个 OpenClaw instances 调用同一个代理时，这可以让代理区分 gateway registrations 和 trajectories。

默认解析顺序：

1. plugin config `instanceId`
2. `OPENCLAW_INSTANCE_ID`
3. `COMPUTERNAME`
4. `openclaw-default`

## Extension 配置

`rl-training-headers/openclaw.plugin.json` 定义这些选项：

| 选项 | 默认值 | 说明 |
| --- | --- | --- |
| `sessionIdHeader` | `X-Session-Id` | session ID header 名称。 |
| `turnTypeHeader` | `X-Turn-Type` | turn type header 名称。 |
| `instanceIdHeader` | `X-Instance-Id` | instance ID header 名称。 |
| `instanceId` | environment or machine name | 稳定的 OpenClaw instance ID。 |
| `proxyRegisterUrl` | `http://127.0.0.1:8288/register-instance` | `openclaw_proxy.py` 上的注册端点。 |
| `gatewayUrl` | `http://127.0.0.1:<gatewayPort>/v1/chat/completions` | OpenClaw gateway URL。 |
| `gatewayToken` | read from OpenClaw state when possible | Gateway auth token。 |
| `gatewayPort` | `18789` | 本地 OpenClaw gateway 端口。 |
| `registerOnStart` | `true` | 是否在 service start 时注册。 |

环境变量 fallback：

```text
OPENCLAW_STATE_DIR
OPENCLAW_GATEWAY_PORT
OPENCLAW_PROXY_REGISTER_URL
OPENCLAW_GATEWAY_URL
OPENCLAW_GATEWAY_TOKEN
OPENCLAW_INSTANCE_ID
OPENCLAW_WORKSPACE_DIR
```

注意：extension 默认 `proxyRegisterUrl` 是 `8288`，而当前 OpenClaw 代理默认端口是 `8908`。可以使用以下任一方式：

```text
Option A: run openclaw_proxy.py on 8288
  OPENAI_PROXY_PORT=8288 python openclaw_proxy.py

Option B: point the extension to 8908
  OPENCLAW_PROXY_REGISTER_URL=http://127.0.0.1:8908/register-instance
```

两个值必须匹配，否则 gateway registration 会失败。

extension 会尝试从这些位置读取 gateway token：

```text
<OPENCLAW_STATE_DIR>/openclaw.json
%USERPROFILE%\.openclaw\openclaw.json
$HOME/.openclaw/openclaw.json
```

## 安装 Extensions

把 extension 文件夹复制到你的 OpenClaw 安装使用的 extension 位置。典型布局：

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
  -> proxy can route/attribute requests for that instance
```

注册 payload 形状：

```json
{
  "instance_id": "DESKTOP-123",
  "gateway_url": "http://127.0.0.1:18789/v1/chat/completions",
  "gateway_token": "<token>",
  "gateway_port": "18789",
  "source": "rl-training-headers",
  "reason": "service_start",
  "updated_at": "2026-05-14T00:00:00.000Z"
}
```

## 日志

extension 会 best-effort 写日志到：

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
- `before_prompt_build sessionId=...`
- `agent_end clearing pending headers`

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

6. 确认代理为该 session 写入轨迹。

## 排查问题

如果 registration 失败：

- 检查 `proxyRegisterUrl`
- 检查 `openclaw_proxy.py` 是否在运行
- 检查 gateway token 是否存在于 OpenClaw state 中，或是否通过 `OPENCLAW_GATEWAY_TOKEN` 设置
- 查看 `rl-training-headers.log`

如果 headers 缺失：

- 确认 extension log 中出现 `before_prompt_build`
- 确认 LLM 请求是 `POST`
- 确认没有其他 extension 在此之后替换 request headers

如果 `/clear-memory` 失败：

- 确认 `task-commands` 已安装并加载
- 确认 `workspace/markdown_templates` 存在
- 确认 OpenClaw 可以写入 workspace directory
