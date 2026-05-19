# OpenCode 浠ｇ悊閰嶇疆

璇█ / Language: [English](README.md) | 绠€浣撲腑鏂?
鏈洰褰曞寘鍚敤浜庨噰闆?RL 杞ㄨ抗鐨?OpenCode 闆嗘垚閰嶇疆銆?
OpenCode 鏄綋鍓嶆敮鎸佺殑瀹㈡埛绔噷鏈€绠€鍗曠殑涓€绫伙紝鍥犱负瀹冪殑鎻掍欢 API 鍘熺敓鎻愪緵
`chat.headers` hook銆傛彃浠跺彲浠ュ湪姣忔 LLM 璇锋眰鍙戝嚭鍓嶇洿鎺ユ敞鍏ヨ姹傚ご锛屼笉闇€瑕?patch 鍏ㄥ眬 `fetch`銆?
## 鏂囦欢

```text
config/opencode/
  README.md
    鑻辨枃閰嶇疆鍜屾灦鏋勮鏄庛€?
  README.zh-CN.md
    鏈腑鏂囪鏄庛€?
  ARCHITECTURE.md
    鏃╂湡杩佺Щ璁板綍锛屼繚鐣欎负鍘嗗彶缁嗚妭銆?
  rl-training-headers/
    index.js
      OpenCode 鎻掍欢杩愯鍏ュ彛銆?
    index.ts
      TypeScript 婧愮爜/鍙傝€冪増鏈€?
    package.json
      鍖呭厓鏁版嵁鍜?@opencode-ai/plugin 渚濊禆銆?```

## 浠ｇ悊绔偣

灏?OpenCode 鐨?OpenAI-compatible provider 閰嶇疆涓猴細

```text
http://<proxy-host>:8905/v1
```

`proxy/config.yaml` 涓搴旂殑 OpenCode profile 鏄細

```yaml
profiles:
  opencode:
    port: 8905
    protocol: "openai"
    backend: "minimax2.5"
    session_dir: "traces/opencode"
    usage_json: "usage/opencode/usage.json"
```

璇锋眰杞ㄨ抗浼氬啓鍏ワ細

```text
traces/opencode/<session_id>.json
```

## 鎻掍欢鐩殑

`rl-training-headers` 浼氭敞鍏ワ細

```text
X-Session-Id: <sessionID>
X-Turn-Type: main|side
X-Agent-Workspace: <workspace-path>
```

杩欎簺 header 璁╀唬鐞嗚兘澶熸妸姣忎釜璇锋眰缁戝畾鍒扮ǔ瀹?session锛屽苟鎶婂悗鍙?turn 鍜岄潰鍚戠敤鎴风殑 turn 鍒嗗紑鏍囪銆?
## 杩愯鏃?Hook

OpenCode 鎻掍欢浣跨敤锛?
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

OpenCode 浼氬湪姣忔妯″瀷璇锋眰鍓嶈皟鐢ㄨ繖涓?hook锛屽苟鎶?`output.headers` 鍚堝苟鍒板嵆灏嗗彂鍑虹殑 HTTP 璇锋眰涓€?
## Turn 绫诲瀷鍒嗙被

鎻掍欢浼氭妸杩欎簺 agent/trigger 瑙嗕负 `side`锛?
```text
heartbeat
memory
cron
```

鍏朵粬璇锋眰閮借涓?`main`銆?
## 鎻掍欢閰嶇疆

鎺ㄨ崘鐨勬湰鍦?OpenCode 閰嶇疆锛?
```json
{
  "plugin": ["./plugins/index.js"]
}
```

甯﹀弬鏁扮殑閰嶇疆锛?
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

閰嶇疆椤癸細

| 閰嶇疆椤?| 榛樿鍊?| 璇存槑 |
| --- | --- | --- |
| `sessionIdHeader` | `X-Session-Id` | OpenCode session ID 鐨?header 鍚嶇О銆?|
| `turnTypeHeader` | `X-Turn-Type` | main/side 鍒嗙被鐨?header 鍚嶇О銆?|
| `workspace` | `process.cwd()` | 姣忔璇锋眰鎼哄甫鐨?workspace 璺緞銆?|
| `workspaceHeader` | `X-Agent-Workspace` | workspace 璺緞浣跨敤鐨?header 鍚嶇О銆?|
| `debug` | `false` | 涓?`true` 鏃跺啓鍏ユ彃浠剁敓鍛藉懆鏈熷拰 hook 璇婃柇鏃ュ織銆?|
| `debugFile` | 鏈缃?| debug 鏃ュ織鏂囦欢璺緞锛屼緥濡?`~/.config/opencode/rl-training-headers-debug.log`銆?|

## 瀹夎鎻掍欢

OpenCode 鍙互绋冲畾鍔犺浇閰嶇疆鐩綍 `plugins/` 涓嬬殑鏈湴鎻掍欢鏂囦欢銆傛妸杩愯鍏ュ彛澶嶅埗鍒拌鐩綍锛?
```bash
mkdir -p ~/.config/opencode/plugins
cp config/opencode/rl-training-headers/index.js ~/.config/opencode/plugins/index.js
```

Windows 涓婂搴旂殑浣嶇疆鏄細

```text
C:\Users\<you>\.config\opencode\plugins\index.js
```

鐒跺悗鍦?`opencode.json` 涓紩鐢ㄨ繖涓枃浠讹細

```json
{
  "plugin": [
    "./plugins/index.js"
  ]
}
```

杩欎釜鎻掍欢浠嶇劧淇濈暀浜?`package.json`锛屽湪瀹夎鍒?Node 鍙В鏋愯矾寰勫悗涔熷彲浠ヤ綔涓?`rl-training-headers` 瀵煎叆銆備絾瀵规湰椤圭洰鑰岃█锛屾帹鑽愪娇鐢?`plugins/` 涓嬬殑鏈湴鏂囦欢锛?杩欐牱涓嶄緷璧?OpenCode 鐨?package cache 鐩綍缁撴瀯锛屼笉鍚屾満鍣ㄤ笂鏇寸ǔ銆?
濡傛灉淇敼浜?`config/opencode/rl-training-headers/index.js`锛岄噸鏂版祴璇曞墠闇€瑕佸啀娆″鍒跺埌
`~/.config/opencode/plugins/index.js`銆?
## OpenCode Provider 閰嶇疆

閰嶇疆 OpenCode 鐨?provider/model锛岃璇锋眰璧颁唬鐞嗐€?
姒傚康缁撴瀯濡備笅锛?
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

涓嶅悓鐗堟湰鐨?OpenCode 閰嶇疆缁撴瀯鍙兘涓嶅悓锛屼絾涓嶅彉鐨勬槸锛?
- base URL 鎸囧悜 `http://<proxy-host>:8905/v1`
- 宸插姞杞?`./plugins/index.js` 鎻掍欢
- OpenCode 璇锋眰鎼哄甫 `X-Session-Id` 鎴?`X-Agent-Session-Id`
- 濡傛灉闇€瑕?workspace 鍏冩暟鎹紝OpenCode 璇锋眰鎼哄甫 `X-Agent-Workspace`

濡傛灉浠ｇ悊鍏抽棴璁よ瘉锛孉PI key 鍙互鏄换鎰忛潪绌哄€笺€傚鏋滃紑鍚璇侊紝瀹冨繀椤诲尮閰?`config.yaml` 涓殑 `auth.keys`銆?
鍙湁 Claude Code 浣跨敤 `run_id` 鍜?`workspace_id`銆侽penCode 涓嶉渶瑕佽繖涓や釜瀛楁锛?瀹冨彧闇€瑕佸湪蹇呰鏃堕€氳繃 `X-Agent-Workspace` 鍙戦€佹櫘閫?workspace 璺緞銆?
## 楠岃瘉

妫€鏌?OpenCode 鏄惁鍔犺浇鎻掍欢锛?
```bash
opencode debug config --print-logs --log-level DEBUG
```

棰勬湡鏃ュ織鐗囨锛?
```text
service=plugin path=./plugins/index.js loading plugin
[rl-training-headers] activated (chat.headers hook)
```

鐩存帴妫€鏌ユ彃浠舵枃浠讹細

```bash
node -e "import('./plugins/index.js').then(m => console.log(m.default.id))"
```

棰勬湡杈撳嚭锛?
```text
rl-training-headers
```

鎵嬪姩妫€鏌?hook 琛屼负锛?
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

棰勬湡缁撴灉锛?
```json
{
  "X-Session-Id": "s1",
  "X-Agent-Session-Id": "s1",
  "X-Turn-Type": "main",
  "X-Agent-Workspace": "/path/to/workspace"
}
```

## 鍜?OpenClaw 鐨勫尯鍒?
OpenClaw 闇€瑕佺敓鍛藉懆鏈?hook 鍔犱竴涓?`fetch` patch锛屽洜涓哄畠娌℃湁鏆撮湶鍚屾牱鐩存帴鐨勮姹?header hook銆?
OpenCode 鍘熺敓 `chat.headers` hook 鏇撮€傚悎杩欎釜鍦烘櫙锛?
- 涓嶉渶瑕佸叏灞€ `fetch` patch
- 涓嶉渶瑕?pending-header 鐘舵€?- 涓嶅瓨鍦?prompt build 鍜?request send 涔嬮棿鐨勬竻鐞嗙珵鎬?- header 娉ㄥ叆鍙綔鐢ㄤ簬鍗曚釜璇锋眰

## 鎺掓煡闂

濡傛灉杞ㄨ抗鍐欏埌浜?`__no_session_id__`锛?
- 纭鎻掍欢宸插姞杞?- 纭璇锋眰閲屾湁 `X-Session-Id` 鎴?`X-Agent-Session-Id`
- 纭 OpenCode 浣跨敤鐨勬槸浠ｇ悊 base URL
- 纭璇锋眰鎵撳埌 `8905`锛岃€屼笉鏄叾浠?profile 绔彛

濡傛灉鎵€鏈夎姹傞兘鏍囨垚 `main`锛?
- 妫€鏌?OpenCode 瀵瑰悗鍙颁换鍔″彂閫佺殑 `input.agent` 鍊?- 濡傛灉鏌愪釜鍊煎簲璇ヨ杩囨护涓?side traffic锛屾妸瀹冨姞鍏?`SIDE_TRIGGERS`
