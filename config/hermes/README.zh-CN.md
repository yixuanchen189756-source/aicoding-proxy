# Hermes 代理配置

语言 / Language: [English](README.md) | 简体中文

本文档说明如何配置 Hermes 使用 AI Coding Proxy，以及如何把 RL 轨迹 header 注入 Hermes 的 LLM 请求。

Hermes 使用由 `proxy/hermes_proxy.py` 提供的 OpenAI-compatible profile。

## 代理端点

将 Hermes 的主 LLM 请求发送到：

```text
http://<proxy-host>:8907/v1
```

`proxy/config.yaml` 中对应的 profile 是：

```yaml
profiles:
  hermes:
    port: 8907
    protocol: "openai"
    backend: "GLM-5-FP8"
    session_dir: "traces/hermes"
    usage_json: "usage/hermes/usage.json"
```

Hermes 轨迹写入：

```text
traces/hermes/
```

## 目标

每个 Hermes 主 LLM 请求都应该包含：

```text
X-Session-Id: <user_name>_<session_id>
X-Turn-Type: main|side
```

这些 header 让代理能够：

- 按稳定 session ID 保存请求
- 把面向用户的 turn 和后台维护 turn 分开
- 让 Hermes 轨迹独立于 OpenCode 和 Claude Code

## 推荐 Hermes 配置

在 Hermes 配置文件中加入配置块，例如 `~/.hermes/config.yaml`：

```yaml
rl_training_headers:
  enabled: true
  user_name: "default-user"
  session_id_header: "X-Session-Id"
  turn_type_header: "X-Turn-Type"
```

字段：

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `enabled` | `false` | 启用 RL header 注入。 |
| `user_name` | `default-user` | 加在 Hermes session ID 前面的前缀。 |
| `session_id_header` | `X-Session-Id` | session identity 的 header 名称。 |
| `turn_type_header` | `X-Turn-Type` | main/side 分类的 header 名称。 |

Hermes 的 model/provider 配置应指向代理：

```yaml
base_url: "http://<proxy-host>:8907/v1"
api_key: "sk-proxy"
model: "glm-5-fp8"
```

如果代理关闭认证，API key 可以是任意非空值。如果代理开启认证，它必须匹配 `proxy/config.yaml` 中的 `auth.keys`。

## 实现方式

Hermes 没有 OpenCode 那种 `chat.headers` hook。最干净的集成方式是在 Hermes 已经构建 per-request API 参数的位置添加 headers。

推荐 patch 点：

- `AIAgent.__init__`
- `AIAgent._build_api_kwargs`
- `AIAgent.flush_memories`
- cron scheduler 创建 agent 的位置

patch 只应该影响 Hermes 的主 client 路径。用于 vision、summary 或内部 helper 调用的辅助 client 不需要进入 RL 训练轨迹流。

## Patch 1：初始化 RL Header 状态

在 `AIAgent.__init__` 中初始化默认值：

```python
self._rl_headers_enabled = False
self._rl_user_name = "default-user"
self._rl_session_id_header = "X-Session-Id"
self._rl_turn_type_header = "X-Turn-Type"
self._rl_turn_type = "main"
```

然后读取配置：

```python
if hasattr(_agent_cfg, "get"):
    _rl_cfg = _agent_cfg.get("rl_training_headers", {})
    if _rl_cfg.get("enabled", False):
        self._rl_headers_enabled = True
        self._rl_user_name = _rl_cfg.get("user_name", "default-user")
        self._rl_session_id_header = _rl_cfg.get("session_id_header", "X-Session-Id")
        self._rl_turn_type_header = _rl_cfg.get("turn_type_header", "X-Turn-Type")
```

使用 Hermes 已经用于 agent settings 的同一个 config 对象。

## Patch 2：在 `_build_api_kwargs` 中注入 Headers

在 `_build_api_kwargs` 中，等 Hermes 构建好 `api_kwargs`，并处理完已有 `extra_headers` 逻辑后，合并 RL headers：

```python
if getattr(self, "_rl_headers_enabled", False):
    _rl_sid = f"{getattr(self, '_rl_user_name', 'default-user')}_{getattr(self, 'session_id', '')}"
    _rl_headers = {
        getattr(self, "_rl_session_id_header", "X-Session-Id"): _rl_sid,
        getattr(self, "_rl_turn_type_header", "X-Turn-Type"): getattr(self, "_rl_turn_type", "main"),
    }

    _existing = api_kwargs.get("extra_headers", {})
    if not isinstance(_existing, dict):
        _existing = {}
    _existing.update(_rl_headers)
    api_kwargs["extra_headers"] = _existing
```

重要细节：

- 使用 `extra_headers`，不要用静态/default client headers
- 和已有 headers 合并，不要替换
- 保留 Hermes 现有 headers，例如 xAI prompt-cache headers
- 在返回 `api_kwargs` 前立即执行

## Patch 3：把 `flush_memories` 标记为 Side Traffic

Memory flush 是内部维护工作，不是直接用户交互。

包住 `flush_memories` 的主体：

```python
def flush_memories(self, messages: list = None, min_turns: int = None):
    _prev_rl_turn_type = getattr(self, "_rl_turn_type", "main")
    self._rl_turn_type = "side"

    try:
        # existing flush_memories logic
        ...
    finally:
        self._rl_turn_type = _prev_rl_turn_type
```

`finally` 很重要。没有它，后续面向用户的 turn 可能会错误地继续标成 `side`。

## Patch 4：把 Cron Agents 标记为 Side Traffic

当 Hermes 的 cron scheduler 创建 `AIAgent` 时，设置：

```python
agent._rl_turn_type = "side"
```

Cron jobs 是后台任务，不应和直接用户交互数据混在一起。

## 数据流

普通用户 turn：

```text
User message
  -> Hermes builds AIAgent request
  -> _build_api_kwargs()
  -> extra_headers["X-Session-Id"] = "<user_name>_<session_id>"
  -> extra_headers["X-Turn-Type"] = "main"
  -> POST http://<proxy-host>:8907/v1/chat/completions
  -> proxy writes traces/hermes/<date>/<session>.json
```

Memory flush：

```text
flush_memories()
  -> _rl_turn_type = "side"
  -> _build_api_kwargs()
  -> X-Turn-Type: side
  -> request finishes
  -> _rl_turn_type restored
```

Cron job：

```text
cron scheduler creates AIAgent
  -> agent._rl_turn_type = "side"
  -> all LLM calls from that cron agent are side traffic
```

## Header 语义

### X-Session-Id

格式：

```text
<user_name>_<session_id>
```

示例：

```text
default-user_abc123def
```

前缀可以避免多个 Hermes 用户或机器向同一个代理发送数据时发生冲突。

### X-Turn-Type

| 值 | 含义 | 常见来源 |
| --- | --- | --- |
| `main` | 面向用户的对话 turn | 普通 chat loop |
| `side` | 后台维护 turn | memory flush、cron |

如果训练只需要用户可见行为，训练 pipeline 可以过滤掉 `side` traffic。

## 验证

### 1. 语法检查

在 Hermes 仓库中：

```bash
python -m py_compile run_agent.py
python -m py_compile cron/scheduler.py
```

### 2. 配置检查

```python
import yaml

with open("~/.hermes/config.yaml", "r", encoding="utf-8") as f:
    cfg = yaml.safe_load(f)

print(cfg.get("rl_training_headers", {}))
```

预期：

```python
{
  "enabled": True,
  "user_name": "default-user",
  "session_id_header": "X-Session-Id",
  "turn_type_header": "X-Turn-Type",
}
```

### 3. 代理健康检查

```bash
curl http://<proxy-host>:8907/health
curl http://<proxy-host>:8907/v1/models
```

### 4. 端到端 Header 检查

启动 Hermes，发送一条消息，然后查看代理日志或捕获的请求 headers。请求应该包含：

```text
X-Session-Id: default-user_<actual-session-id>
X-Turn-Type: main
```

触发 memory flush 或 cron run，并确认：

```text
X-Turn-Type: side
```

### 5. 轨迹检查

请求成功后，检查：

```text
traces/hermes/
```

存储的轨迹应独立于：

```text
traces/opencode/
traces/claude-code/
```

## 设计决策

### 使用 `extra_headers`

`session_id` 会随 session 改变，所以静态 client headers 是错误层级。`extra_headers` 是 request-scoped，也符合 Hermes 处理其他动态 header 的方式。

### 只 Patch 主 Client 路径

辅助 clients 通常是内部 helper 调用。把它们排除在主 RL 轨迹流外可以减少噪声。

### 用实例变量保存 Turn Type

Hermes 没有一个能把 request state 传入 header injection 的生命周期 hook。实例变量简单，并且符合现有 `AIAgent` 设计。

### 用 `finally` 恢复状态

side-turn 状态不能泄漏到后续用户 turn。临时 side 操作结束后必须恢复 `_rl_turn_type`。

## 排查问题

如果 Hermes 请求到达代理，但轨迹没有有效 session ID：

- 确认 Hermes 发送了 `X-Session-Id`
- 确认 `rl_training_headers.enabled` 为 true
- 确认请求路径经过 `_build_api_kwargs`

如果所有内容都被标记为 `main`：

- 确认 `flush_memories` 用 `_rl_turn_type = "side"` 包住逻辑
- 确认 cron 创建的 agents 设置了 `_rl_turn_type = "side"`

如果请求在到达模型前失败：

- 确认 Hermes base URL 是 `http://<proxy-host>:8907/v1`
- 确认代理的 `hermes` profile 启动时有效
- 确认 `proxy/config.yaml` 中的上游 backend 凭证正确
