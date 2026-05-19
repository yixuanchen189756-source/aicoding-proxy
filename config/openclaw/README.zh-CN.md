# OpenClaw 浠ｇ悊閰嶇疆

璇█ / Language: [English](README.md) | 绠€浣撲腑鏂?
鏈洰褰曞寘鍚敤浜庨噰闆?RL 杞ㄨ抗鐨?OpenClaw 涓撶敤闆嗘垚璧勬簮銆?
OpenClaw 鐙珛浜庡叡浜?profile core 澶勭悊銆侽penClaw 璇蜂娇鐢?`proxy/openclaw_proxy.py`锛屽洜涓?OpenClaw 鏈夎嚜宸辩殑 gateway銆乮nstance registration 鍜屽唴閮ㄦ秷鎭ā寮忋€?
## 鐩綍缁撴瀯

```text
config/openclaw/
  extensions/
    rl-training-headers/
      娉ㄥ叆 RL headers锛屽苟鍚戜唬鐞嗘敞鍐?OpenClaw gateway銆?
    task-commands/
      鎻愪緵 /clear-memory skill 浣跨敤鐨?clear_memory tool銆?
  skills/
    clear-memory/
      鐢ㄦ埛鍙皟鐢ㄧ殑 skill锛屼細璋冪敤 clear_memory銆?
  workspace/
    markdown_templates/
      鐢ㄤ簬閲嶇疆 OpenClaw workspace memory 鐨勬ā鏉?markdown 鏂囦欢銆?```

## 杩愯缁勪欢

### OpenClaw Proxy

浠?`proxy/` 鍚姩 OpenClaw 涓撶敤浠ｇ悊锛?
```bash
python openclaw_proxy.py
```

`openclaw_proxy.py` 鏄疄闄呯殑 OpenClaw 浠ｇ悊鏈嶅姟銆傚畠浼氳鍙?`proxy/config.yaml` 椤跺眰鐨?`openclaw` block锛岀敤浜庤缃洃鍚鍙ｃ€佷笂娓?backend 鍜岃建杩圭洰褰曘€?
榛樿鎯呭喌涓嬶紝褰撳墠 OpenClaw 浠ｇ悊鐩戝惉锛?
```text
http://0.0.0.0:8908
```

濡傛灉闇€瑕佷笉鍚岀鍙ｏ紝鍙互璁剧疆 `OPENAI_PROXY_PORT`锛?
```bash
OPENAI_PROXY_PORT=8908 python openclaw_proxy.py
```

鎺ㄨ崘鐨勬寔涔呭寲閰嶇疆鏄?`proxy/config.yaml` 椤跺眰鐨?`openclaw` block锛?
```yaml
openclaw:
  port: 8908
  backend: "GLM-5-FP8"
  session_dir: "traces/openclaw"
```

閲嶈鐜鍙橀噺锛?
```text
VLLM_BASE_URL
  涓婃父 backend base URL 鐨勫彲閫夎鐩栥€備紭鍏堝湪 proxy/config.yaml 涓厤缃?backend銆?
VLLM_MODEL_NAME
  鍙戦€佺粰涓婃父 backend 鐨勬ā鍨嬪悕鐨勫彲閫夎鐩栥€?
VLLM_API_KEY
  涓婃父 API key 鐨勫彲閫夎鐩栥€?
OPENAI_PROXY_PORT
  openclaw_proxy.py 鐨勫彲閫夌鍙ｈ鐩栥€備紭鍏堥厤缃?proxy/config.yaml 閲岀殑
  openclaw.port銆?
OPENAI_PROXY_TRACE=1
  灏嗚姹?鍝嶅簲 trace 鎽樿鎵撳嵃鍒?stderr銆?
OPENAI_PROXY_SESSION_FOLDER
  per-session 杞ㄨ抗鏂囦欢澶圭殑鏍圭洰褰曘€傛瘡涓?session 浼氬啓鎴?  <session_id>/task_<i>.json銆傚鏋滄病鏈夎缃繖涓幆澧冨彉閲忥紝浠ｇ悊浼氫娇鐢?  proxy/config.yaml 閲岀殑 openclaw.session_dir锛涘鏋?config.yaml 涔熸病鏈夐厤缃紝
  灏变娇鐢ㄥ綋鍓嶅伐浣滅洰褰曘€?```

OpenClaw 浠ｇ悊杩樹細鍦ㄨ剼鏈檮杩戜繚瀛?gateway metadata锛?
```text
gateway_tokens.json
gateway_instances.json
```

杩欎簺鏂囦欢鍖呭惈杩愯鏃舵敞鍐屼俊鎭紝涓嶅簲琚涓哄彲绉绘婧愭枃浠躲€?
### rl-training-headers Extension

璺緞锛?
```text
config/openclaw/extensions/rl-training-headers/
```

鐩殑锛?
- 娉ㄥ叆 `X-Session-Id`
- 娉ㄥ叆 `X-Turn-Type`
- 娉ㄥ叆 `X-Instance-Id`
- 鍚?`openclaw_proxy.py` 娉ㄥ唽 OpenClaw gateway URL/token

涓嶅悓浜?OpenCode锛孫penClaw 娌℃湁鍚屾牱鐨勫師鐢?`chat.headers` hook銆傝繖涓?extension 浣跨敤 OpenClaw 鐢熷懡鍛ㄦ湡浜嬩欢鍜屼竴涓緢绐勭殑 `globalThis.fetch` patch锛?
```text
before_prompt_build
  -> compute pending headers from session/trigger
  -> patched fetch injects headers into the next POST
agent_end
  -> clear pending headers
```

extension 杩樹細娉ㄥ唽 service startup hook锛涘鏋滃惎鍔ㄦ敞鍐屾病鏈夊畬鎴愶紝浼氬湪 `before_prompt_build` 鏃堕噸璇曟敞鍐屻€?
### task-commands Extension

璺緞锛?
```text
config/openclaw/extensions/task-commands/
```

鐩殑锛?
- 娉ㄥ唽 `clear_memory` tool
- 浠?`workspace/markdown_templates` 閲嶇疆 workspace markdown 鏂囦欢
- 娓呯悊娌℃湁瀵瑰簲妯℃澘鐨勭幇鏈?`.md` workspace 鏂囦欢

### clear-memory Skill

璺緞锛?
```text
config/openclaw/skills/clear-memory/SKILL.md
```

鐢ㄦ埛鍛戒护锛?
```text
/clear-memory
```

杩欎釜鍛戒护浼氱洿鎺ヨ皟鐢?`clear_memory`銆傚畠浼氬 OpenClaw workspace markdown 鏂囦欢鎵ц鐮村潖鎬ч噸缃紝鎵€浠ュ彧搴斿湪褰撳墠 workspace memory 闇€瑕佷粠妯℃澘閲嶇疆鏃朵娇鐢ㄣ€?
## Header 璇箟

### X-Session-Id

格式：
```text
<openclaw-session-id>
```

插件使用 OpenClaw 的 `ctx.sessionId` 作为 trace session ID。不要用
`ctx.sessionKey` 来做 trace 分组：同一个可见对话、或者 `/clear-memory`
这类内部请求，OpenClaw 都可能产生不同的 `dashboard` / `openai` session key。

这样，同一个 OpenClaw 对话里的用户任务会保留在同一个 session 文件夹下，同时
proxy 仍然会按 task 拆成 `task_<i>.json` 文件。
### X-Turn-Type

| 鍊?| 鍚箟 |
| --- | --- |
| `main` | 闈㈠悜鐢ㄦ埛鐨勪氦浜掋€?|
| `side` | 鍚庡彴鎴栫淮鎶ゆ椿鍔ㄣ€?|

extension 浼氭妸杩欎簺 trigger 瑙嗕负 `side`锛?
```text
heartbeat
memory
cron
```

鍏朵粬璇锋眰閮借涓?`main`銆?
### X-Instance-Id

鏍囪瘑 OpenClaw instance銆傚綋澶氫釜 OpenClaw instances 璋冪敤鍚屼竴涓唬鐞嗘椂锛岃繖鍙互璁╀唬鐞嗗尯鍒?gateway registrations 鍜?traces銆?
鎻掍欢浼氫粠 OpenClaw gateway URL 鐨?origin 娲剧敓杩欎釜鍊硷細

```text
http://100.64.0.70:18789/v1/chat/completions -> 100.64.0.70_18789
```

鎵嬪姩閰嶇疆鐨?`instanceId` 浼氳蹇界暐锛岄伩鍏?`pc-m-main` 杩欑被鏃у悕瀛楃户缁垚涓?registry key銆?
### X-Agent-Workspace

濡傛灉鎻掍欢鑳借В鏋?workspace 璺緞锛屽氨浼氭妸瀹冩斁鍒拌繖涓?header 涓€傛彃浠朵細浼樺厛浣跨敤 OpenClaw prompt context 閲岀殑 workspace 淇℃伅锛涘鏋滄病鏈夛紝灏变娇鐢ㄥ綋鍓嶈繘绋嬪伐浣滅洰褰曘€?
## Extension 閰嶇疆

`rl-training-headers/openclaw.plugin.json` 瀹氫箟杩欎簺閫夐」锛?
| 閫夐」 | 榛樿鍊?| 璇存槑 |
| --- | --- | --- |
| `sessionIdHeader` | `X-Session-Id` | session ID header 鍚嶇О銆?|
| `turnTypeHeader` | `X-Turn-Type` | turn type header 鍚嶇О銆?|
| `instanceIdHeader` | `X-Instance-Id` | instance ID header 鍚嶇О銆?|
| `workspaceHeader` | `X-Agent-Workspace` | workspace 璺緞 header 鍚嶇О銆?|
| `instanceId` | ignored | 鍏煎鏃ч厤缃紝浣嗘彃浠朵細蹇界暐杩欎釜鍊笺€?|
| `proxyRegisterUrl` | ignored | 鍏煎鏃ч厤缃紝浣嗘彃浠朵細蹇界暐杩欎釜鍊笺€?|
| `gatewayUrl` | 蹇呭～ | OpenClaw gateway URL銆?|
| `gatewayToken` | read from OpenClaw state when possible | Gateway auth token銆?|
| `gatewayPort` | `18789` | 鏈湴 OpenClaw gateway 绔彛銆?|
| `registerOnStart` | `true` | 鏄惁鍦?service start 鏃舵敞鍐屻€?|

鐜鍙橀噺 fallback锛?
```text
OPENCLAW_STATE_DIR
OPENCLAW_GATEWAY_PORT
OPENCLAW_GATEWAY_URL
OPENCLAW_GATEWAY_TOKEN
OPENCLAW_INSTANCE_ID
OPENCLAW_WORKSPACE_DIR
```

OpenClaw 瀹㈡埛绔晶鍙湁涓€涓唬鐞嗗湴鍧€鏉ユ簮锛歄penClaw 鑷繁閰嶇疆閲岀殑褰撳墠榛樿 model provider `baseUrl`锛屼緥濡傦細

```text
models.providers.vllm.baseUrl = http://100.64.0.132:8908/v1
```

鎻掍欢浼氫粠 OpenClaw state 璇诲彇榛樿 model provider锛屽幓鎺夋湯灏剧殑 `/v1`锛岃嚜鍔ㄦ淳鐢燂細

```text
http://100.64.0.132:8908/register-instance
```

涓嶈鍐嶅崟鐙厤缃?`proxyRegisterUrl`锛涙棫鍊间細琚拷鐣ワ紝閬垮厤 chat completions 鍜?registration 鎸囧悜涓嶅悓鍦板潃銆?
extension 浼氬皾璇曚粠杩欎簺浣嶇疆璇诲彇 gateway token锛?
```text
<OPENCLAW_STATE_DIR>/openclaw.json
%USERPROFILE%\.openclaw\openclaw.json
$HOME/.openclaw/openclaw.json
```

## 瀹夎 Extensions

鎶?extension 鏂囦欢澶瑰鍒跺埌浣犵殑 OpenClaw 瀹夎浣跨敤鐨?extension 浣嶇疆銆傚吀鍨嬪竷灞€锛?
```text
<user-home>/.openclaw/extensions/rl-training-headers
<user-home>/.openclaw/extensions/task-commands
```

澶嶅埗 skill锛?
```text
<user-home>/.openclaw/skills/clear-memory
```

澶嶅埗鎴栧悎骞?workspace templates锛?
```text
<user-home>/.openclaw/workspace/markdown_templates
```

澶嶅埗瀹屾垚鍚庯紝閲嶅惎 OpenClaw 鎴栭噸鏂板姞杞?extensions銆?
## Proxy Registration Flow

棰勬湡娴佺▼锛?
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

杞ㄨ抗鏂囦欢浼氬啓鍏ワ細

```text
traces/openclaw/<session_id>/task_1.json
traces/openclaw/<session_id>/task_2.json
```

褰撳墠 `task_<i>.json` 浼氶殢鐫€瀵硅瘽鎺ㄨ繘鎸佺画鏇存柊銆傚綋浠ｇ悊妫€娴嬪埌涓€涓?task 瀹屾垚鍚庯紝涓嬩竴涓潰鍚戠敤鎴风殑 task 浼氬垏鎹㈠埌涓嬩竴涓?task 鏂囦欢銆?

OpenClaw proxy 按 task 拆分 trace，而不是只按 session 保存一个文件。task
完成后，proxy 会通知 OpenClaw gateway 执行 `/clear-memory`，用模板重置
workspace memory files，确保下一个 task 从 clean slate 开始；如果用户继续同一
session，新的 task 仍然写在同一个 session 文件夹下。

OpenClaw 在处理 `/clear-memory` 时可能会创建额外的内部 `openai` session
context。这些内部请求会被 trace writer 跳过，不应该成为用户可见对话的 session
文件夹。
娉ㄥ唽 payload 褰㈢姸锛?
```json
{
  "instance_id": "DESKTOP-123",
  "gateway_url": "http://<openclaw-gateway-host>:18789/v1/chat/completions",
  "gateway_token": "<token>",
  "gateway_port": "18789",
  "source": "rl-training-headers",
  "reason": "service_start",
  "updated_at": "2026-05-14T00:00:00.000Z"
}
```

## 鏃ュ織

extension 浼?best-effort 鍐欐棩蹇楀埌锛?
```text
<OPENCLAW_STATE_DIR>/logs/rl-training-headers.log
```

濡傛灉娌℃湁璁剧疆 `OPENCLAW_STATE_DIR`锛屽垯鍐欏叆榛樿 OpenClaw state directory銆?
有用日志：

- `module loaded`
- `resolved config ...`
- `service start hook fired`
- `registering gateway instance`
- `registered gateway instance`
- `before_prompt_build seq=... sessionId=... sessionKey=...`
- `fetch POST applying headers seq=... target=... xSession=...`
- `agent_end clearing pending headers seq=...`

## 楠岃瘉

1. 鍚姩 `openclaw_proxy.py`銆?2. 鍚姩宸插畨瑁?extension 鐨?OpenClaw銆?3. 妫€鏌?extension logs锛岀‘璁?gateway registration銆?4. 鍙戦€佷竴涓櫘閫?OpenClaw prompt銆?5. 纭妯″瀷璇锋眰鍖呭惈锛?
```text
X-Session-Id
X-Turn-Type
X-Instance-Id
```

6. 纭浠ｇ悊涓鸿 session 鍐欏叆杞ㄨ抗銆?
## 鎺掓煡闂

濡傛灉 registration 澶辫触锛?
- 妫€鏌ュ綋鍓?OpenClaw model provider 鐨?`baseUrl`
- 妫€鏌?`openclaw_proxy.py` 鏄惁鍦ㄨ繍琛?- 妫€鏌?gateway token 鏄惁瀛樺湪浜?OpenClaw state 涓紝鎴栨槸鍚﹂€氳繃 `OPENCLAW_GATEWAY_TOKEN` 璁剧疆
- 鏌ョ湅 `rl-training-headers.log`

濡傛灉 headers 缂哄け锛?
- 纭 extension log 涓嚭鐜?`before_prompt_build`
- 纭 LLM 璇锋眰鏄?`POST`
- 纭娌℃湁鍏朵粬 extension 鍦ㄦ涔嬪悗鏇挎崲 request headers

濡傛灉 `/clear-memory` 澶辫触锛?
- 纭 `task-commands` 宸插畨瑁呭苟鍔犺浇
- 纭 `workspace/markdown_templates` 瀛樺湪
- 纭 OpenClaw 鍙互鍐欏叆 workspace directory
