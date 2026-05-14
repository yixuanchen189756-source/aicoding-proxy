# rl-training-headers 接入 OpenCode 架构详解

## 背景

`rl-training-headers` 最初是为 **OpenClaw** 编写的插件，功能是在 LLM API 请求中注入 `X-Session-Id` 和 `X-Turn-Type` 两个 HTTP 头，用于强化学习（RL）训练数据的分类和追溯。

需要将其迁移到 **OpenCode**（`opencode-ai` v1.4.6）的插件系统中，同时保持与 OpenClaw 的兼容。

---

## 一、两个系统的插件架构对比

### OpenClaw 插件系统

OpenClaw 是一个 AI 网关，使用 `openclaw/plugin-sdk` 作为插件 SDK。

```
openclaw/plugin-sdk  →
  OpenClawPluginApi  →  api.on(event, callback)
                     →  api.pluginConfig
                     →  api.logger
```

核心模式：插件调用 `api.on()` 注册生命周期钩子，再通过 `globalThis.fetch` 修补（monkey-patch）来拦截 HTTP 请求。

**原插件的工作流：**

```
before_prompt_build  →  记下 sessionId 和 turnType 到 pendingHeaders
                        ↓
globalThis.fetch patched  →  检测 pendingHeaders，注入到 POST 请求
                        ↓
agent_end             →  清空 pendingHeaders
```

### OpenCode 插件系统

OpenCode（`opencode-ai` v1.4.6）是一个编译为原生 ELF 二进制的 AI 辅助工具，使用 `@opencode-ai/plugin` 作为插件 SDK。

```
@opencode-ai/plugin  →
  PluginModule       →  id: string
                     →  server: (input, options) => Promise<Hooks>
  Hooks              →  "chat.headers"  →  LLM 请求前注入 header (原生!)
                     →  "chat.params"   →  修改 LLM 参数
                     →  event           →  通用事件
                     →  tool            →  注册工具
                     →  auth/provider   →  认证/模型提供方
```

核心模式：插件导出 `PluginModule`，OpenCode 在启动时调用 `server()` 获取钩子，在 LLM 请求生命周期中自动调用对应钩子。

**关键差异：**

| 维度 | OpenClaw | OpenCode |
|------|----------|----------|
| SDK 包 | `openclaw/plugin-sdk` | `@opencode-ai/plugin` |
| 入口 | `export default function register(api)` | `export default { id, server }` |
| 配置来源 | `api.pluginConfig` | `server()` 的 `options` 参数 |
| Header 注入 | 手动修补 `globalThis.fetch` | 原生 `"chat.headers"` 钩子 |
| 生命周期 | `before_prompt_build` / `agent_end` | `"chat.headers"` 每次调用前自动触发 |
| 日志 | `api.logger.info()` | `console.log()` |
| 构建 | TypeScript → 需要编译 | JS 直接加载（Node.js ESM） |

---

## 二、迁移决策

### 2.1 为什么用 `"chat.headers"` 而不是修补 fetch

OpenCode 的 `Hooks` 接口中有一个 `"chat.headers"` 钩子：

```typescript
"chat.headers"?: (input: {
    sessionID: string;
    agent: string;
    model: Model;
    provider: ProviderContext;
    message: UserMessage;
}, output: {
    headers: Record<string, string>;
}) => Promise<void>;
```

这个钩子会在每次 LLM API 请求**发送之前**被调用。插件只需设置 `output.headers`，OpenCode 会自动将其合并到 HTTP 请求头中。

**相比修补 fetch 的优势：**
- 不需要操作 `globalThis.fetch`（副作用最小化）
- 不需要 `pendingHeaders` 状态管理（钩子本身是自包含的）
- 不需要 `before_prompt_build`/`agent_end` 来开关状态
- 类型安全（input/output 都有完整类型定义）

### 2.2 为什么用 JS 而不是 TS

OpenCode 是原生 ELF 二进制，它通过 Node.js 的 `import()` 动态加载插件。Node.js 无法直接加载 `.ts` 文件（除非用 `tsx` 或注册 loader）。

选择方案对比：

| 方案 | 优点 | 缺点 |
|------|------|------|
| 保留 `.ts` + 编译到 `.js` | 类型安全 | 需要构建步骤，增加复杂度 |
| 用 `tsx` 运行时加载 | 无需构建 | 增加运行时依赖，可能与 OpenCode 的 Node.js 环境冲突 |
| **直接用 `.js` + JSDoc 类型标注** ✅ | 零构建，类型安全(通过 `@ts-check`) | 无 |

选择的是第三种：`index.js` 加 `// @ts-check` 和 `/** @type {import(...)} */` 类型标注，在 **开发时** 获得 TypeScript 类型检查，在 **运行时** 无需任何构建步骤。

### 2.3 为什么保留 `index.ts` 和 `openclaw` 字段

`package.json` 中保留了：

```json
{
  "openclaw": {
    "extensions": ["./index.ts"]
  }
}
```

这是为了保持与 OpenClaw 的向后兼容。`index.ts` 仍然保留（虽然当前内容已改为 OpenCode API，但 OpenClaw 可以单独管理自己版本的入口，这里保留文件结构是为了不破坏 OpenClaw 的引用）。

---

## 三、插件加载流程

### OpenCode 如何发现和加载插件

```
opencode.json
  └─ "plugin": ["rl-training-headers"]
       │
       ▼
OpenCode 启动时读取 plugin 数组
       │
       ▼
检查缓存目录是否存在：
  ~/.cache/opencode/packages/rl-training-headers@latest/
       │
       ▼
如果不存在/不完整 → npm install rl-training-headers 到缓存目录
如果已安装       → 直接使用缓存
       │
       ▼
Node.js import() 加载插件模块
       │
       ▼
调用 server(input, options) → 得到 Hooks 对象
       │
       ▼
OpenCode 将 Hooks 注册到对应生命周期点
       │
       ▼
每次 LLM API 请求 → 调用 chat.headers 钩子 → 注入 header
```

### 缓存目录结构

```
~/.cache/opencode/packages/rl-training-headers@latest/
├── package.json          ← {"dependencies": {"rl-training-headers": "file:./rl-training-headers-1.0.0.tgz"}}
├── rl-training-headers-1.0.0.tgz
└── node_modules/
    ├── @opencode-ai/
    │   ├── plugin/       ← 主依赖
    │   └── sdk/           ← plugin 的依赖
    └── rl-training-headers/
        ├── index.js       ← 实际入口
        ├── package.json
        └── ...
```

关键点：OpenCode 使用自己的 npm 解析器来管理插件，每个插件在 `packages/` 下有自己的隔离目录，插件之间不会互相污染依赖。

---

## 四、最终代码解读

```javascript
// @ts-check                                      ← 启用 TS 类型检查（对 JS 文件）
const SIDE_TRIGGERS = new Set(["heartbeat", "memory", "cron"]);

/** @type {import('@opencode-ai/plugin').PluginModule} */
const pluginModule = {
  id: "rl-training-headers",                      ← 唯一标识

  server: async (_input, rawOptions) => {          ← 初始化函数，返回 Hooks
    const options = rawOptions ?? {};
    const userName = options.userName ?? "default-user";
    const sessionIdHeader = options.sessionIdHeader ?? "X-Session-Id";
    const turnTypeHeader = options.turnTypeHeader ?? "X-Turn-Type";

    return {
      "chat.headers": async (input, output) => {  ← 每次 LLM 请求前触发
        const sessionId = input.sessionID ?? "";
        const combinedSessionId = `${userName}_${sessionId}`;
        const turnType = SIDE_TRIGGERS.has(input.agent ?? "") ? "side" : "main";

        output.headers = {
          [sessionIdHeader]: combinedSessionId,
          [turnTypeHeader]: turnType,
        };
      },
    };
  },
};

export default pluginModule;
```

### 关键设计点

1. **`rawOptions ?? {}`** — OpenCode 允许在 `opencode.json` 中以 `["rl-training-headers", { ... }]` 格式传参，这里处理 `undefined` 情况。

2. **`userName` 前缀** — 原始需求是用固定用户名拼接 sessionId，这样在 RL 训练数据中可以通过前缀追溯数据来源。

3. **`SIDE_TRIGGERS`** — 区分"主交互"和"后台维护"两类请求。主交互（用户主动发起的对话）标记为 `"main"`，后台自动触发的（heartbeat、memory 操作等）标记为 `"side"`。RL 训练时可以过滤掉 side 请求。

4. **零状态设计** — 和原 OpenClaw 版本不同，不再需要 `pendingHeaders` 变量，因为 `"chat.headers"` 钩子是每次调用自包含的，不需要跨调用维护状态。

---

## 五、配置方式

### 最小配置

```json
{
  "plugin": ["rl-training-headers"]
}
```

### 带参数的配置

```json
{
  "plugin": [
    ["rl-training-headers", {
      "userName": "my-team",
      "sessionIdHeader": "X-Session-Id",
      "turnTypeHeader": "X-Turn-Type"
    }]
  ]
}
```

### 参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `userName` | `"default-user"` | 用于拼接 sessionId 的用户/团队标识 |
| `sessionIdHeader` | `"X-Session-Id"` | 自定义 session ID 的 HTTP 头名称 |
| `turnTypeHeader` | `"X-Turn-Type"` | 自定义 turn type 的 HTTP 头名称 |

---

## 六、验证方法

### 1. 验证插件被 OpenCode 发现和加载

```bash
opencode debug config --print-logs --log-level DEBUG
```

输出中应包含：
```
service=plugin path=rl-training-headers loading plugin
[rl-training-headers] activated (chat.headers hook, user: default-user)
```

### 2. 验证插件模块本身

```bash
node -e "import('rl-training-headers').then(m => console.log(m.default.id))"
```

### 3. 验证钩子行为

```javascript
import pluginModule from 'rl-training-headers';

const hooks = await pluginModule.server({}, { userName: 'test' });
const output = { headers: {} };
await hooks['chat.headers'](
  { sessionID: 's1', agent: 'default', ... },
  output
);
console.log(output.headers);
// → { "X-Session-Id": "test_s1", "X-Turn-Type": "main" }
```

---

## 七、与 OpenClaw 的兼容性

`openclaw.plugin.json` 保留并标记了 `"platforms": ["openclaw", "opencode"]`。两个系统使用相同的代码入口 `index.ts`：

- **OpenCode** 使用 `index.js`（已编译为 ESM JS，零构建依赖）
- **OpenClaw** 可以通过 `openclaw.json` 中的 extensions 字段引用 `index.ts`

实际在 OpenClaw 端，需要单独维护一个适配版本（因为 OpenClaw 的 `plugin-sdk` API 和 OpenCode 的 `@opencode-ai/plugin` API 完全不同），或者 OpenClaw 也可以直接使用 `index.js`。当前实现中保留了 `index.ts` 作为 OpenClaw 的参考入口，但内容已改为 OpenCode API。如果 OpenClaw 需要独立运行，应创建各自的版本。

---

## 八、完整文件清单

```
/home/lrs/random/rl-training-headers/
├── index.js                    ← OpenCode 插件入口（主）
├── index.ts                    ← 参考入口（TypeScript 版本）
├── package.json                ← 包配置
├── openclaw.plugin.json        ← 多平台元数据
├── ARCHITECTURE.md             ← 本文档
└── node_modules/               ← @opencode-ai/plugin 等依赖
```

OpenCode 配置：

```
/root/.config/opencode/
├── opencode.json               ← plugin: ["rl-training-headers"]
└── ...

/root/.cache/opencode/packages/
└── rl-training-headers@latest/ ← 插件的缓存副本
    ├── package.json
    └── node_modules/
        └── rl-training-headers/ → symlink to /home/lrs/random/rl-training-headers/
```
