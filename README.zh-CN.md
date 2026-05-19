# AI Coding Proxy

璇█ / Language: [English](README.md) | 绠€浣撲腑鏂?
AI Coding Proxy 鏄竴涓皬鑰岀洿鎺ャ€佷互鏂囦欢涓轰腑蹇冪殑浠ｇ悊鍖咃紝鐢ㄤ簬閲囬泦 coding agent 杞ㄨ抗锛屽悓鏃舵妸妯″瀷璇锋眰璺敱鍒?`config.yaml` 涓厤缃殑涓婃父 LLM 鏈嶅姟銆?
瀹冮潰鍚戝洓绫?agent锛?
| Agent | 鍚姩鍏ュ彛 | 绔彛 | 瀹㈡埛绔崗璁?| 杞ㄨ抗鏍圭洰褰?|
| --- | --- | ---: | --- | --- |
| OpenCode | `opencode_proxy.py` | `8905` | OpenAI-compatible | `traces/opencode/<session_id>.json` |
| Claude Code | `claude_code_proxy.py` | `8906` | Anthropic Messages | `traces/claude-code/<session_id>.json` |
| Hermes | `hermes_proxy.py` | `8907` | OpenAI-compatible | `traces/hermes/<session_id>.json` |
| OpenClaw | `openclaw_proxy.py` | `8908` | OpenAI-compatible gateway | `traces/openclaw/<session_id>/task_<task_id>.json` |

杩欎釜浠ｇ悊涓嶆浛浠ｈ繖浜?agent銆傚畠浣嶄簬 agent 鍜屼笂娓告ā鍨嬫湇鍔′箣闂达紝璁╂瘡涓姹傞兘鑳藉綊灞炲埌姝ｇ‘鐨?session銆亀orkspace銆乺un 鍜?agent銆?
## 蹇冩櫤妯″瀷

闂锛?  涓轰粈涔堣繖涓寘瀛樺湪锛?
妯″瀷锛?  agent 璇锋眰 + 绋冲畾 headers + proxy profile = 鍙洖鏀剧殑杞ㄨ抗

娴佺▼锛?
```text
Coding agent
  -> agent-specific headers/hooks/plugins
  -> dedicated proxy port
  -> configured upstream backend
  -> per-agent trace files
```

瑙勫垯锛?  姣忎釜 agent 閮芥嫢鏈夎嚜宸辩殑杩涚▼銆佺鍙ｃ€佽姹傚舰鎬佸拰杞ㄨ抗鐩綍銆?
杩欑闅旂鏄湁鎰忚璁＄殑銆侽penCode銆丆laude Code銆丠ermes 鍜?OpenClaw 鏆撮湶鐨勬墿灞曠偣涓嶅悓锛屾墍浠ヤ唬鐞嗘妸瀹冧滑鐨勬帴鍏ラ€昏緫鍒嗗紑锛屽悓鏃跺叡浜?backend 閰嶇疆鍜岃建杩圭害瀹氥€?
## 浠撳簱缁撴瀯

```text
proxy/
  agent_proxy_core.py
    OpenCode銆丆laude Code銆丠ermes 鍏辩敤鐨?FastAPI 鏍稿績銆?    杩欎笉鏄惎鍔ㄨ剼鏈€?
  opencode_proxy.py
  claude_code_proxy.py
  hermes_proxy.py
    寰堣杽鐨勫惎鍔ㄥ叆鍙ｏ紝姣忎釜鑴氭湰鍙粠 config.yaml 閫夋嫨涓€涓?profile銆?
  openclaw_proxy.py
    OpenClaw 涓撶敤浠ｇ悊锛岃礋璐?gateway 娉ㄥ唽鍜?instance 璺敱銆?
  config.yaml
    涓婃父 backend銆乤gent profile銆乤uth銆乼race銆乽sage 鏂囦欢鍜?OpenClaw 璁剧疆銆?
  config/
    opencode/
    claude-code/
    hermes/
    openclaw/
      鍚?agent 涓撶敤鎻掍欢銆乭ook銆佽剼鏈拰閰嶇疆鎸囧崡銆?```

杩欎釜鍖呴噷鏈夋剰涓嶆彁渚?`client.py` 鍏ュ彛銆傝浣跨敤涓婇潰鐨勭嫭绔嬪惎鍔ㄨ剼鏈€?
## 鍓嶇疆鏉′欢

- Python 3.10+
- 浠ｇ悊涓绘満鑳藉璁块棶 `config.yaml` 涓厤缃殑涓婃父妯″瀷鏈嶅姟
- 鑷冲皯涓€涓彲鐢ㄧ殑涓婃父 backend
- 鍚?agent 鐨?header 娉ㄥ叆鏈哄埗锛?  - OpenCode锛歱lugin hook
  - Claude Code锛歸rapper 鐜鍙橀噺 + session hook
  - Hermes锛歮odel-provider plugin
  - OpenClaw锛歟xtension + gateway registration

瀹夎 Python 渚濊禆锛?
```bash
pip install -r requirements.txt
```

## 閰嶇疆

杩愯閰嶇疆鍦?[config.yaml](config.yaml) 涓€?
### Backends

`backends` 鎻忚堪涓婃父妯″瀷鏈嶅姟銆傜湡瀹炲嚟璇佽浣跨敤鐜鍙橀噺鍗犱綅绗︼細

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

涓嶈鎻愪氦鐪熷疄浠樿垂 API key銆傛湰鍦?secret 搴旀斁鍦?`.env` 鎴栭儴缃茬幆澧冮噷銆?
### Profiles

`profiles` 鎶婁笁涓叡浜牳蹇?agent 缁戝畾鍒扮鍙ｃ€佸崗璁€乥ackend 鍜岃緭鍑鸿矾寰勶細

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

鏃犳晥 profile 浼氬湪鍚姩鏃惰绂佺敤锛屽苟鎵撳嵃娓呮櫚 warning銆傚鏋滆姹傚惎鍔ㄧ殑 profile 娌℃湁浠讳綍涓€涓彲鐢?backend锛岃繘绋嬩細閫€鍑恒€?
### OpenClaw

OpenClaw 浣跨敤鑷繁鐨勯《灞傞厤缃紝鍥犱负瀹冧笉璧?`agent_proxy_core.py`锛?
```yaml
openclaw:
  port: 8908
  backend: "GLM-5-FP8"
  session_dir: "traces/openclaw"
```

## 鏈湴杩愯

寤鸿姣忎釜浠ｇ悊鍗曠嫭涓€涓粓绔垨杩涚▼绠＄悊鍣細

```bash
cd proxy
python opencode_proxy.py
python claude_code_proxy.py
python hermes_proxy.py
python openclaw_proxy.py
```

鍋ュ悍妫€鏌ワ細

```bash
curl http://<proxy-host>:8905/health
curl http://<proxy-host>:8906/health
curl http://<proxy-host>:8907/health
curl http://<proxy-host>:8908/health
```

杩欓噷浣跨敤 coding agent 鎵€鍦ㄦ満鍣ㄨ兘璁块棶鍒扮殑浠ｇ悊涓绘満鎴?tailnet IP銆?
## Agent 鎺ュ叆

### OpenCode

OpenCode 浣跨敤 `config/opencode/rl-training-headers`锛屽畠浼氭敞鍏ワ細

```text
X-Session-Id: <sessionID>
X-Turn-Type: main|side
```

OpenCode 鐨?OpenAI-compatible provider 搴旀寚鍚戯細

```text
http://<proxy-host>:8905/v1
```

鎸囧崡锛歔config/opencode/README.md](config/opencode/README.md) | [涓枃](config/opencode/README.zh-CN.md)

### Claude Code

Claude Code 闇€瑕佷袱閮ㄥ垎锛?
1. wrapper 鑴氭湰璁剧疆 `ANTHROPIC_BASE_URL`銆乣ANTHROPIC_CUSTOM_HEADERS`銆乣CLAUDE_CODE_RUN_ID` 鍜?workspace metadata
2. session hook 鎶?Claude Code 鐨?`session_id` 浜嬩欢涓婃姤缁欎唬鐞?
閫氳繃 wrapper 鍚姩 Claude Code锛?
```bash
# Windows
config\claude-code\scripts\claude_code_rl.bat

# Linux/macOS
sh config/claude-code/scripts/claude_code_rl.sh
```

妯″瀷绔偣锛?
```text
http://<proxy-host>:8906/v1/messages
```

hook 绔偣锛?
```text
http://<proxy-host>:8906/_agent/session-event
```

鎸囧崡锛歔config/claude-code/README.md](config/claude-code/README.md) | [涓枃](config/claude-code/README.zh-CN.md)

### Hermes

Hermes 搴斾娇鐢?`config/hermes/model-providers/aicoding-proxy-hermes` 閲岀殑 model-provider plugin銆?
杩欎釜 provider 浼氭妸 OpenAI-compatible 璇锋眰鍙戦€佸埌锛?
```text
http://<proxy-host>:8907/v1
```

瀹冧細娣诲姞璇锋眰绾?`extra_headers`锛?
```text
X-Session-Id: <session_id>
X-Turn-Type: main
X-Agent-Workspace: <workspace-path>
```

鎸囧崡锛歔config/hermes/README.md](config/hermes/README.md) | [涓枃](config/hermes/README.zh-CN.md)

### OpenClaw

OpenClaw 浣跨敤涓撶敤浠ｇ悊锛?
```bash
python openclaw_proxy.py
```

OpenClaw extension 浼氭敞鍏ワ細

```text
X-Session-Id
X-Turn-Type
X-Instance-Id
```

瀹冭繕浼氬悜 `openclaw_proxy.py` 娉ㄥ唽 OpenClaw gateway URL/token锛岃繖鏍蜂唬鐞嗗氨鑳芥寜 instance 璺敱璇锋眰銆?
鎸囧崡锛歔config/openclaw/README.md](config/openclaw/README.md) | [涓枃](config/openclaw/README.zh-CN.md)

## 杞ㄨ抗

浠ｇ悊浼氭妸 JSON 杞ㄨ抗鍐欏埌姣忎釜 agent 閰嶇疆鐨?`session_dir`銆?
Claude Code 浣跨敤 workspace/session 鐩綍缁撴瀯锛?
```text
traces/opencode/<session_id>.json
traces/claude-code/<session_id>.json
traces/hermes/<session_id>.json
traces/openclaw/<session_id>/task_<task_id>.json
```

OpenClaw proxy 按 task 拆分 trace：每个 session 使用一个文件夹，每个检测到的
task 写入一个 `task_<task_id>.json`。当 task 完成后，proxy 会通知 OpenClaw
gateway 执行 `/clear-memory`，重置 workspace memory files，确保下一个 task
从 clean slate 开始。

鍏稿瀷鐨勫綊涓€鍖栬建杩圭粨鏋勶細

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

褰掍竴鍖栬鍒欙細

- 璺宠繃 Claude Code 鐨?title-generation 璇锋眰銆?- 淇濈暀 assistant 鐨?`<think>...</think>` 鍐呭銆?- Claude Code 鐨?`<system-reminder>...</system-reminder>` 鍧椾細鍙樻垚鎸夋椂闂撮『搴忔帓鍒楃殑 `system` messages銆?- 绉婚櫎闅忔満 tool call ID锛屽噺灏戦潪纭畾鎬у櫔澹般€?
杞ㄨ抗鏂囦欢搴旇涓烘晱鎰熸暟鎹€傚畠浠彲鑳藉寘鍚?prompts銆佷唬鐮併€佸伐鍏疯緭鍑恒€佽矾寰勫拰 system reminders銆?
## 鐢ㄩ噺缁熻

姣忎釜 profile 鍙互鎶?token usage 鍐欏叆閰嶇疆鐨?`usage_json` 璺緞锛?
```text
usage/opencode/usage.json
usage/claude-code/usage.json
usage/hermes/usage.json
```

## 寮€鍙戝懡浠?
缂栬瘧妫€鏌ヤ唬鐞嗚剼鏈細

```bash
python -B -m py_compile proxy/agent_proxy_core.py proxy/opencode_proxy.py proxy/claude_code_proxy.py proxy/hermes_proxy.py proxy/openclaw_proxy.py
```

鍦ㄤ粨搴撴牴鐩綍杩愯娴嬭瘯锛?
```bash
python -m unittest discover -s tests -v
```

## 璐＄尞璇存槑

- 姣忎釜 agent 鐨勯泦鎴愰兘搴斾繚鐣欏湪鑷繁鐨勭洰褰曟垨鍏ュ彛鑴氭湰涓€?- 涓嶈閲嶆柊寮曞叆 `client.py` 鎴?`openclaw_client.py`锛涜繖浜涘悕瀛楀凡缁忔湁鎰忓簾寮冦€?- 鏂囨。瑕佷繚鎸佸彲绉绘銆備娇鐢?`<proxy-host>`銆乣<user-home>`銆乣<workspace-path>` 杩欑被鍗犱綅绗︼紝涓嶈鍐欐満鍣ㄤ笓鐢ㄨ矾寰勩€?- 鏂扮殑 agent 缁嗚妭搴斿啓鍏ュ搴旂殑 `config/<agent>/README.md`锛屽啀浠庢牴 README 閾炬帴杩囧幓銆?- 涓嶈鎻愪氦 `.env`銆佽繍琛屾椂杞ㄨ抗銆乽sage 鏂囦欢銆乬ateway registry 鎴栫湡瀹?API key銆?
## License

褰撳墠浠撳簱杩樻病鏈?license 鏂囦欢銆傚湪鍏紑鍙戝竷鎴栫敤浜庢洿骞挎硾鍒嗗彂鍓嶏紝璇峰厛琛ュ厖 license銆?
## Contact

褰撳墠杩樻病鏈夊叕寮€ maintainer contact銆傚唴閮ㄩ儴缃叉椂锛屽缓璁湪骞挎硾鍏变韩浠撳簱鍓嶈ˉ鍏?owner 鎴?on-call channel銆?
