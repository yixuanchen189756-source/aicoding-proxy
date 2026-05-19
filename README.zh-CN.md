# AI Coding Proxy

语言 / Language: [English](README.md) | 简体中文

AI Coding Proxy 是一个小而直接、以文件为中心的代理包，用于采集 coding agent 轨迹，同时把模型请求路由到 `config.yaml` 中配置的上游 LLM 服务。

它面向四类 agent：

| Agent | 启动入口 | 端口 | 客户端协议 | 轨迹根目录 |
| --- | --- | ---: | --- | --- |
| OpenCode | `opencode_proxy.py` | `8905` | OpenAI-compatible | `traces/opencode/<session_id>.json` |
| Claude Code | `claude_code_proxy.py` | `8906` | Anthropic Messages | `traces/claude-code/<session_id>.json` |
| Hermes | `hermes_proxy.py` | `8907` | OpenAI-compatible | `traces/hermes/<session_id>.json` |
| OpenClaw | `openclaw_proxy.py` | `8908` | OpenAI-compatible gateway | `traces/openclaw/<session_id>.json` |

这个代理不替代这些 agent。它位于 agent 和上游模型服务之间，让每个请求都能归属到正确的 session、workspace、run 和 agent。

## 心智模型

问题：
  为什么这个包存在？

模型：
  agent 请求 + 稳定 headers + proxy profile = 可回放的轨迹

流程：

```text
Coding agent
  -> agent-specific headers/hooks/plugins
  -> dedicated proxy port
  -> configured upstream backend
  -> per-agent trajectory files
```

规则：
  每个 agent 都拥有自己的进程、端口、请求形态和轨迹目录。

这种隔离是有意设计的。OpenCode、Claude Code、Hermes 和 OpenClaw 暴露的扩展点不同，所以代理把它们的接入逻辑分开，同时共享 backend 配置和轨迹约定。

## 仓库结构

```text
proxy/
  agent_proxy_core.py
    OpenCode、Claude Code、Hermes 共用的 FastAPI 核心。
    这不是启动脚本。

  opencode_proxy.py
  claude_code_proxy.py
  hermes_proxy.py
    很薄的启动入口，每个脚本只从 config.yaml 选择一个 profile。

  openclaw_proxy.py
    OpenClaw 专用代理，负责 gateway 注册和 instance 路由。

  config.yaml
    上游 backend、agent profile、auth、trace、usage 文件和 OpenClaw 设置。

  config/
    opencode/
    claude-code/
    hermes/
    openclaw/
      各 agent 专用插件、hook、脚本和配置指南。
```

这个包里有意不提供 `client.py` 入口。请使用上面的独立启动脚本。

## 前置条件

- Python 3.10+
- 代理主机能够访问 `config.yaml` 中配置的上游模型服务
- 至少一个可用的上游 backend
- 各 agent 的 header 注入机制：
  - OpenCode：plugin hook
  - Claude Code：wrapper 环境变量 + session hook
  - Hermes：model-provider plugin
  - OpenClaw：extension + gateway registration

安装 Python 依赖：

```bash
pip install -r requirements.txt
```

## 配置

运行配置在 [config.yaml](config.yaml) 中。

### Backends

`backends` 描述上游模型服务。真实凭证请使用环境变量占位符：

```yaml
backends:
  my-backend:
    base_url: "https://provider.example.com"
    api_key: "${MY_BACKEND_API_KEY}"
    timeout_s: 600
    endpoints:
      - url: "https://provider.example.com"
        model: "provider-model-name"
        openai_url: "https://provider.example.com"
```

不要提交真实付费 API key。本地 secret 应放在 `.env` 或部署环境里。

### Profiles

`profiles` 把三个共享核心 agent 绑定到端口、协议、backend 和输出路径：

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

无效 profile 会在启动时被禁用，并打印清晰 warning。如果请求启动的 profile 没有任何一个可用 backend，进程会退出。

### OpenClaw

OpenClaw 使用自己的顶层配置，因为它不走 `agent_proxy_core.py`：

```yaml
openclaw:
  port: 8908
  backend: "GLM-5-FP8"
  session_dir: "traces/openclaw"
```

## 本地运行

建议每个代理单独一个终端或进程管理器：

```bash
cd proxy
python opencode_proxy.py
python claude_code_proxy.py
python hermes_proxy.py
python openclaw_proxy.py
```

健康检查：

```bash
curl http://<proxy-host>:8905/health
curl http://<proxy-host>:8906/health
curl http://<proxy-host>:8907/health
curl http://<proxy-host>:8908/health
```

这里使用 coding agent 所在机器能访问到的代理主机或 tailnet IP。

## Agent 接入

### OpenCode

OpenCode 使用 `config/opencode/rl-training-headers`，它会注入：

```text
X-Session-Id: <sessionID>
X-Turn-Type: main|side
```

OpenCode 的 OpenAI-compatible provider 应指向：

```text
http://<proxy-host>:8905/v1
```

指南：[config/opencode/README.md](config/opencode/README.md) | [中文](config/opencode/README.zh-CN.md)

### Claude Code

Claude Code 需要两部分：

1. wrapper 脚本设置 `ANTHROPIC_BASE_URL`、`ANTHROPIC_CUSTOM_HEADERS`、`CLAUDE_CODE_RUN_ID` 和 workspace metadata
2. session hook 把 Claude Code 的 `session_id` 事件上报给代理

通过 wrapper 启动 Claude Code：

```bash
# Windows
config\claude-code\scripts\claude_code_rl.bat

# Linux/macOS
sh config/claude-code/scripts/claude_code_rl.sh
```

模型端点：

```text
http://<proxy-host>:8906/v1/messages
```

hook 端点：

```text
http://<proxy-host>:8906/_agent/session-event
```

指南：[config/claude-code/README.md](config/claude-code/README.md) | [中文](config/claude-code/README.zh-CN.md)

### Hermes

Hermes 应使用 `config/hermes/model-providers/aicoding-proxy-hermes` 里的 model-provider plugin。

这个 provider 会把 OpenAI-compatible 请求发送到：

```text
http://<proxy-host>:8907/v1
```

它会添加请求级 `extra_headers`：

```text
X-Session-Id: <session_id>
X-Turn-Type: main
X-Agent-Workspace: <workspace-path>
```

指南：[config/hermes/README.md](config/hermes/README.md) | [中文](config/hermes/README.zh-CN.md)

### OpenClaw

OpenClaw 使用专用代理：

```bash
python openclaw_proxy.py
```

OpenClaw extension 会注入：

```text
X-Session-Id
X-Turn-Type
X-Instance-Id
```

它还会向 `openclaw_proxy.py` 注册 OpenClaw gateway URL/token，这样代理就能按 instance 路由请求。

指南：[config/openclaw/README.md](config/openclaw/README.md) | [中文](config/openclaw/README.zh-CN.md)

## 轨迹

代理会把 JSON 轨迹写到每个 agent 配置的 `session_dir`。

Claude Code 使用 workspace/session 目录结构：

```text
traces/opencode/<session_id>.json
traces/claude-code/<session_id>.json
traces/hermes/<session_id>.json
traces/openclaw/<session_id>.json
```

典型的归一化轨迹结构：

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

归一化规则：

- 跳过 Claude Code 的 title-generation 请求。
- 保留 assistant 的 `<think>...</think>` 内容。
- Claude Code 的 `<system-reminder>...</system-reminder>` 块会变成按时间顺序排列的 `system` messages。
- 移除随机 tool call ID，减少非确定性噪声。

轨迹文件应视为敏感数据。它们可能包含 prompts、代码、工具输出、路径和 system reminders。

## 用量统计

每个 profile 可以把 token usage 写入配置的 `usage_json` 路径：

```text
usage/opencode/usage.json
usage/claude-code/usage.json
usage/hermes/usage.json
```

## 开发命令

编译检查代理脚本：

```bash
python -B -m py_compile proxy/agent_proxy_core.py proxy/opencode_proxy.py proxy/claude_code_proxy.py proxy/hermes_proxy.py proxy/openclaw_proxy.py
```

在仓库根目录运行测试：

```bash
python -m unittest discover -s tests -v
```

## 贡献说明

- 每个 agent 的集成都应保留在自己的目录或入口脚本中。
- 不要重新引入 `client.py` 或 `openclaw_client.py`；这些名字已经有意废弃。
- 文档要保持可移植。使用 `<proxy-host>`、`<user-home>`、`<workspace-path>` 这类占位符，不要写机器专用路径。
- 新的 agent 细节应写入对应的 `config/<agent>/README.md`，再从根 README 链接过去。
- 不要提交 `.env`、运行时轨迹、usage 文件、gateway registry 或真实 API key。

## License

当前仓库还没有 license 文件。在公开发布或用于更广泛分发前，请先补充 license。

## Contact

当前还没有公开 maintainer contact。内部部署时，建议在广泛共享仓库前补充 owner 或 on-call channel。
