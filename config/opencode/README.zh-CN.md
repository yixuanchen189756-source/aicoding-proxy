# OpenCode Proxy Configuration

语言 / Language: [English](README.md) | 简体中文

本目录包含用于采集 RL trace 的 OpenCode 集成配置。

OpenCode 是当前支持的客户端里最简单的一类，因为它的插件 API 原生提供 `chat.headers` hook。插件可以在每次 LLM 请求发出前直接注入请求头，不需要 patch 全局 `fetch`。

## 文件

```text
config/opencode/
  README.md
    英文说明。
  README.zh-CN.md
    本中文说明。
  rl-training-headers/
    index.js
      OpenCode 插件运行入口。
    package.json
    package-lock.json
      包元数据和 @opencode-ai/plugin 依赖。
```

## 代理端点

将 OpenCode 的 OpenAI-compatible provider 配置为：

```text
http://<proxy-host>:8905/v1
```

`proxy/config.yaml` 中对应的 OpenCode profile 是：

```yaml
profiles:
  opencode:
    port: 8905
    protocol: "openai"
    backend: "GLM-5-FP8"
    session_dir: "traces/opencode"
    usage_json: "usage/opencode/usage.json"
```

请求 trace 会写入：

```text
traces/opencode/<session_id>.json
```

## 插件用途

插件会为 OpenCode 的模型请求添加：

```text
X-Session-Id: <OpenCode session id>
X-Turn-Type: main | side
X-Agent-Workspace: <workspace path>
```

这些 header 让代理能够把每个请求绑定到稳定 session，并把后台 turn 和面向用户的 turn 分开标记。

## Runtime Hook

OpenCode 插件使用：

```js
export const RlTrainingHeaders = async ({ app, client, $ }) => ({
  event: async ({ event }) => {},
  "chat.headers": async (input, output) => {
    output.headers["X-Session-Id"] = ...
    output.headers["X-Turn-Type"] = ...
    output.headers["X-Agent-Workspace"] = ...
  },
})
```

OpenCode 会在每次模型请求前调用这个 hook，并把 `output.headers` 合并到即将发出的 HTTP 请求中。

## Turn Type 分类

这些 OpenCode trigger 会被标记为 `side`：

```text
heartbeat
memory
cron
```

其他请求都视为 `main`。

## 插件配置

推荐的本地 OpenCode 配置：

```json
{
  "$schema": "https://opencode.ai/config.json",
  "plugin": ["~/.config/opencode/plugins/index.js"],
  "provider": {
    "glm-proxy": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "GLM Proxy",
      "options": {
        "baseURL": "http://<proxy-host>:8905/v1",
        "apiKey": "sk-proxy"
      },
      "models": {
        "glm-5-fp8": {}
      }
    }
  },
  "model": "glm-proxy/glm-5-fp8"
}
```

`rl-training-headers/index.js` 支持这些选项：

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `sessionIdHeader` | `X-Session-Id` | OpenCode session ID 使用的 header 名称。 |
| `turnTypeHeader` | `X-Turn-Type` | main/side 分类使用的 header 名称。 |
| `workspace` | `process.cwd()` | 每次请求携带的 workspace 路径。 |
| `workspaceHeader` | `X-Agent-Workspace` | workspace 路径使用的 header 名称。 |
| `debug` | `false` | 为 `true` 时写入插件生命周期和 hook 诊断日志。 |
| `debugFile` | 未设置 | debug 日志文件路径，例如 `~/.config/opencode/rl-training-headers-debug.log`。 |

`workspace` 默认来自 OpenCode 插件进程的工作目录。如果使用
`opencode run --dir ...` 这类单独的项目目录参数，不要假设它一定会改变
插件的 `process.cwd()`；当 trace 必须携带指定 workspace 路径时，请显式配置
插件的 `workspace` 选项。

## 安装插件

OpenCode 可以稳定加载配置目录 `plugins/` 下的本地插件文件。把运行入口复制到该目录：

```text
~/.config/opencode/plugins/index.js
```

Windows 上对应的位置是：

```text
%USERPROFILE%\.config\opencode\plugins\index.js
```

然后在 `opencode.json` 中引用这个文件：

```json
{
  "plugin": ["~/.config/opencode/plugins/index.js"]
}
```

这个插件仍然保留了 `package.json`，在安装到 Node 可解析路径后也可以作为 `rl-training-headers` 导入。但对本项目而言，推荐使用 `plugins/` 下的本地文件，这样不依赖 OpenCode 的 package cache 目录结构，不同机器上更稳定。

如果修改了 `config/opencode/rl-training-headers/index.js`，重新测试前需要再复制到：

```text
~/.config/opencode/plugins/index.js
```

## OpenCode Provider 配置

配置 OpenCode 的 provider/model，让请求走代理。

最小示例：

```json
{
  "provider": {
    "glm-proxy": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "GLM Proxy",
      "options": {
        "baseURL": "http://<proxy-host>:8905/v1",
        "apiKey": "sk-proxy"
      },
      "models": {
        "glm-5-fp8": {}
      }
    }
  },
  "model": "glm-proxy/glm-5-fp8"
}
```

不同版本的 OpenCode 配置结构可能不同，但不变的是：

- provider base URL 指向 `http://<proxy-host>:8905/v1`
- OpenCode 请求携带 `X-Session-Id` 或 `X-Agent-Session-Id`
- 如果需要 workspace 元数据，OpenCode 请求携带 `X-Agent-Workspace`

如果代理关闭认证，API key 可以是任意非空值。如果开启认证，它必须匹配 `config.yaml` 中的 `auth.keys`。

只有 Claude Code 使用 `run_id` 和 `workspace_id`。OpenCode 不需要这两个字段；它只需要在必要时通过 `X-Agent-Workspace` 发送普通 workspace 路径。

## 验证

启动代理：

```bash
cd proxy
python opencode_proxy.py
```

启动 OpenCode 并发一条消息。代理日志应显示 session id，trace 应写入：

```text
traces/opencode/<session_id>.json
```

如果落到 `__no_session_id__`，检查：

- 插件是否已加载
- 请求里是否有 `X-Session-Id` 或 `X-Agent-Session-Id`
- OpenCode 使用的是否是代理 base URL
- 请求是否打到 `8905`，而不是其他 profile 端口

如需调试插件：

```json
{
  "plugin": [
    ["~/.config/opencode/plugins/index.js", {
      "debug": true,
      "debugFile": "~/.config/opencode/rl-training-headers-debug.log"
    }]
  ]
}
```

也可以用 Node 做基本加载验证：

```bash
node -e "import('./config/opencode/rl-training-headers/index.js').then(m => console.log(m.default.id))"
```

预期输出：

```text
rl-training-headers
```

## 和 OpenClaw 的区别

OpenClaw 需要生命周期 hook 加一个 `fetch` patch，因为它没有暴露同样直接的请求 header hook。OpenCode 不需要这些复杂性：

- 不需要全局 `fetch` patch
- 不需要 pending-header 状态
- 不存在 prompt build 和 request send 之间的清理竞态
- header 注入只作用于单个请求

## Troubleshooting

如果 trace 写到 `__no_session_id__`：

- 确认插件已加载
- 确认请求里有 `X-Session-Id` 或 `X-Agent-Session-Id`
- 确认 OpenCode 使用的是代理 base URL
- 确认请求打到 `8905`，而不是其他 profile 端口

如果后台请求被标成 `main`：

- 检查 OpenCode 对后台任务发送的 `input.agent` 值
- 如果某个值应该被过滤为 side traffic，把它加入 `SIDE_TRIGGERS`
