# OpenCode 代理配置

语言 / Language: [English](README.md) | 简体中文

本目录包含用于采集 RL 轨迹的 OpenCode 集成配置。

OpenCode 是当前支持的客户端里最简单的一类，因为它的插件 API 原生提供
`chat.headers` hook。插件可以在每次 LLM 请求发出前直接注入请求头，不需要
patch 全局 `fetch`。

## 文件

```text
config/opencode/
  README.md
    英文配置和架构说明。

  README.zh-CN.md
    本中文说明。

  ARCHITECTURE.md
    早期迁移记录，保留为历史细节。

  rl-training-headers/
    index.js
      OpenCode 插件运行入口。

    index.ts
      TypeScript 源码/参考版本。

    package.json
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
    backend: "minimax2.5"
    session_dir: "traces/opencode"
    usage_json: "usage/opencode/usage.json"
```

请求轨迹会写入：

```text
traces/opencode/<session_id>.json
```

## 插件目的

`rl-training-headers` 会注入：

```text
X-Session-Id: <sessionID>
X-Turn-Type: main|side
X-Agent-Workspace: <workspace-path>
```

这些 header 让代理能够把每个请求绑定到稳定 session，并把后台 turn 和面向用户的 turn 分开标记。

## 运行时 Hook

OpenCode 插件使用：

```js
"chat.headers": async (input, output) => {
  const sessionId = input.sessionID ?? "";
  const turnType = SIDE_TRIGGERS.has(input.agent ?? "") ? "side" : "main";

  output.headers = {
    [sessionIdHeader]: sessionId,
    "X-Agent-Session-Id": sessionId,
    [turnTypeHeader]: turnType,
    [workspaceHeader]: workspace,
  };
}
```

OpenCode 会在每次模型请求前调用这个 hook，并把 `output.headers` 合并到即将发出的 HTTP 请求中。

## Turn 类型分类

插件会把这些 agent/trigger 视为 `side`：

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
  "plugin": ["./plugins/index.js"]
}
```

带参数的配置：

```json
{
  "plugin": [
    ["./plugins/index.js", {
      "sessionIdHeader": "X-Session-Id",
      "turnTypeHeader": "X-Turn-Type",
      "workspace": "<workspace-path>"
    }]
  ]
}
```

配置项：

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `sessionIdHeader` | `X-Session-Id` | OpenCode session ID 的 header 名称。 |
| `turnTypeHeader` | `X-Turn-Type` | main/side 分类的 header 名称。 |
| `workspace` | `process.cwd()` | 每次请求携带的 workspace 路径。 |
| `workspaceHeader` | `X-Agent-Workspace` | workspace 路径使用的 header 名称。 |
| `debug` | `false` | 为 `true` 时写入插件生命周期和 hook 诊断日志。 |
| `debugFile` | 未设置 | debug 日志文件路径，例如 `~/.config/opencode/rl-training-headers-debug.log`。 |

## 安装插件

OpenCode 可以稳定加载配置目录 `plugins/` 下的本地插件文件。把运行入口复制到该目录：

```bash
mkdir -p ~/.config/opencode/plugins
cp config/opencode/rl-training-headers/index.js ~/.config/opencode/plugins/index.js
```

Windows 上对应的位置是：

```text
C:\Users\<you>\.config\opencode\plugins\index.js
```

然后在 `opencode.json` 中引用这个文件：

```json
{
  "plugin": [
    "./plugins/index.js"
  ]
}
```

这个插件仍然保留了 `package.json`，在安装到 Node 可解析路径后也可以作为
`rl-training-headers` 导入。但对本项目而言，推荐使用 `plugins/` 下的本地文件；
这样不依赖 OpenCode 的 package cache 目录结构，不同机器上更稳。

如果修改了 `config/opencode/rl-training-headers/index.js`，重新测试前需要再次复制到
`~/.config/opencode/plugins/index.js`。

## OpenCode Provider 配置

配置 OpenCode 的 provider/model，让请求走代理。

概念结构如下：

```json
{
  "provider": {
    "proxy": {
      "npm": "@ai-sdk/openai-compatible",
      "options": {
        "baseURL": "http://<proxy-host>:8905/v1",
        "apiKey": "sk-proxy"
      }
    }
  },
  "plugin": [
    "./plugins/index.js"
  ]
}
```

不同版本的 OpenCode 配置结构可能不同，但不变的是：

- base URL 指向 `http://<proxy-host>:8905/v1`
- 已加载 `./plugins/index.js` 插件
- OpenCode 请求携带 `X-Session-Id` 或 `X-Agent-Session-Id`
- 如果需要 workspace 元数据，OpenCode 请求携带 `X-Agent-Workspace`

如果代理关闭认证，API key 可以是任意非空值。如果开启认证，它必须匹配 `config.yaml` 中的 `auth.keys`。

只有 Claude Code 使用 `run_id` 和 `workspace_id`。OpenCode 不需要这两个字段；
它只需要在必要时通过 `X-Agent-Workspace` 发送普通 workspace 路径。

## 验证

检查 OpenCode 是否加载插件：

```bash
opencode debug config --print-logs --log-level DEBUG
```

预期日志片段：

```text
service=plugin path=./plugins/index.js loading plugin
[rl-training-headers] activated (chat.headers hook)
```

直接检查插件文件：

```bash
node -e "import('./plugins/index.js').then(m => console.log(m.default.id))"
```

预期输出：

```text
rl-training-headers
```

手动检查 hook 行为：

```js
import pluginModule from "./plugins/index.js";

const hooks = await pluginModule.server({}, { workspace: "/path/to/workspace" });
const output = { headers: {} };

await hooks["chat.headers"](
  {
    sessionID: "s1",
    agent: "default",
    model: {},
    provider: {},
    message: {},
  },
  output,
);

console.log(output.headers);
```

预期结果：

```json
{
  "X-Session-Id": "s1",
  "X-Agent-Session-Id": "s1",
  "X-Turn-Type": "main",
  "X-Agent-Workspace": "/path/to/workspace"
}
```

## 和 OpenClaw 的区别

OpenClaw 需要生命周期 hook 加一个 `fetch` patch，因为它没有暴露同样直接的请求 header hook。

OpenCode 原生 `chat.headers` hook 更适合这个场景：

- 不需要全局 `fetch` patch
- 不需要 pending-header 状态
- 不存在 prompt build 和 request send 之间的清理竞态
- header 注入只作用于单个请求

## 排查问题

如果轨迹写到了 `__no_session_id__`：

- 确认插件已加载
- 确认请求里有 `X-Session-Id` 或 `X-Agent-Session-Id`
- 确认 OpenCode 使用的是代理 base URL
- 确认请求打到 `8905`，而不是其他 profile 端口

如果所有请求都标成 `main`：

- 检查 OpenCode 对后台任务发送的 `input.agent` 值
- 如果某个值应该被过滤为 side traffic，把它加入 `SIDE_TRIGGERS`
