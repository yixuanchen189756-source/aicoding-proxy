# Hermes 浠ｇ悊閰嶇疆

璇█锛?[English](README.md) | 绠€浣撲腑鏂?
Hermes 搴旇閫氳繃 Hermes model-provider plugin 鎺ュ叆 AI Coding Proxy锛屼笉闇€瑕佷慨鏀?Hermes 婧愮爜銆?
浠ｇ悊鍚姩鍏ュ彛锛?
```bash
python hermes_proxy.py
```

Hermes 浠ｇ悊鍦板潃锛?
```text
http://<proxy-host>:8907/v1
```

[../../config.yaml](../../config.yaml) 涓搴旂殑浠ｇ悊 profile 鏄細

```yaml
profiles:
  hermes:
    port: 8907
    protocol: "openai"
    backend: "GLM-5-FP8"
    session_dir: "traces/hermes"
    usage_json: "usage/hermes/usage.json"
```

Hermes 杞ㄨ抗浼氬啓鍒帮細

```text
traces/hermes/<session_id>.json
```

## 瀹夎浣嶇疆

鏈」鐩彁渚涚殑 provider plugin 鍦細

```text
config/hermes/model-providers/aicoding-proxy-hermes/
```

鎶婃暣涓洰褰曞鍒跺埌 Hermes 鐨?model-provider plugin 鐩綍锛?
```text
$HERMES_HOME/plugins/model-providers/aicoding-proxy-hermes/
```

濡傛灉娌℃湁璁剧疆 `HERMES_HOME`锛孒ermes 閫氬父浣跨敤锛?
```text
~/.hermes/plugins/model-providers/aicoding-proxy-hermes/
```

## Hermes 閰嶇疆

缂栬緫 Hermes 鐨勯厤缃枃浠讹紝閫氬父鏄?`~/.hermes/config.yaml`锛岄€夋嫨杩欎釜 provider锛?
```yaml
model:
  default: glm-5-fp8
  provider: aicoding-proxy-hermes
  base_url: http://<proxy-host>:8907/v1
  api_key: sk-proxy
  api_mode: chat_completions

auxiliary:
  title_generation:
    provider: custom
    model: glm-5-fp8
    base_url: http://<proxy-host>:8907/v1
    api_key: sk-proxy
    api_mode: chat_completions
```

`<proxy-host>` 瑕佹崲鎴?Hermes 鎵€鍦ㄦ満鍣ㄥ彲浠ヨ闂埌鐨勪唬鐞嗕富鏈哄湴鍧€銆?
濡傛灉 `proxy/config.yaml` 閲?`auth.enabled: false`锛宍api_key` 鍙渶瑕佹槸闈炵┖鍊笺€傚鏋滀唬鐞嗗紑鍚簡璁よ瘉锛宍api_key` 蹇呴』鍖归厤 `auth.keys` 涓殑鍊笺€?
`auxiliary.title_generation` 浼氭妸 Hermes 鐨勫悗鍙版爣棰樼敓鎴愯姹傚浐瀹氬埌鍚屼竴涓唬鐞嗗湴鍧€銆傚畠涓嶆槸杞ㄨ抗 header 鐨勫繀瑕佹潯浠讹紝浣嗗彲浠ラ伩鍏?Hermes 鐢熸垚鏍囬鏃跺洖閫€鍒板叾浠?provider銆?
## Tailnet 鍜屼唬鐞嗙粫杩?
濡傛灉 proxy host 鏄?tailnet 鎴栧眬鍩熺綉鍦板潃锛屽惎鍔?Hermes 鍓嶈缃?`NO_PROXY`锛岄伩鍏?Python/httpx 鎶婅姹傚彂鍒扮郴缁?HTTP 浠ｇ悊锛?
```bash
export NO_PROXY="<proxy-host>"
```

PowerShell锛?
```powershell
$env:NO_PROXY = "<proxy-host>"
```

渚嬪锛?
```powershell
$env:NO_PROXY = "100.64.0.132"
```

Windows 鎸佷箙鍖栬缃細

```powershell
[Environment]::SetEnvironmentVariable("NO_PROXY", "100.64.0.132", "User")
```

濡傛灉涓嶈缃繖涓€硷紝鍙兘鍑虹幇 `curl` 鑳借繛閫氾紝浣?Hermes 鎴?OpenAI Python SDK 鎶?`Connection error` 鐨勬儏鍐点€傝繖閫氬父鏄洜涓?httpx 璇诲彇浜嗙郴缁熶唬鐞嗚缃紝鑰岃浠ｇ悊涓嶈兘澶勭悊 tailnet 娴侀噺銆?
## Workspace Header

浠?workspace 鐩綍鍚姩 Hermes锛?
```bash
cd /path/to/workspace
hermes
```

PowerShell锛?
```powershell
Set-Location C:\path\to\workspace
hermes
```

鎻掍欢璇诲彇 Hermes 杩涚▼鐨?cwd锛屽苟鎶婂畠鍙戦€佷负锛?
```text
X-Agent-Workspace: <Hermes process cwd>
```

## 鎻掍欢鍙戦€佺殑 Headers

姣忎釜 Hermes LLM 璇锋眰閮戒細娣诲姞锛?
```text
X-Session-Id: <Hermes session_id>
X-Agent-Session-Id: <Hermes session_id>
X-Turn-Type: main
X-Agent-Workspace: <Hermes process cwd>
```

璇存槑锛?
- `session_id` 鏉ヨ嚜 Hermes provider runtime context銆?- `workspace` 鏉ヨ嚜 Hermes 杩涚▼ cwd銆?- Hermes 涓嶉渶瑕?`run_id` 鎴?`workspace_id`銆?- 鎻掍欢浣跨敤璇锋眰绾?`extra_headers`锛屼笉 patch 鍏ㄥ眬 HTTP client銆?
## 鍙€夎皟璇曟棩蹇?
濡傛灉瑕佺‘璁?provider 鏄惁鐪熺殑杩愯銆佹槸鍚︽嬁鍒颁簡 session ID锛?
```bash
export HERMES_RL_HEADERS_LOG="$HOME/.hermes/aicoding-proxy-headers.jsonl"
```

PowerShell锛?
```powershell
$env:HERMES_RL_HEADERS_LOG = "$HOME\.hermes\aicoding-proxy-headers.jsonl"
```

姣忎釜璇锋眰浼氳拷鍔犱竴琛?JSON锛屾樉绀烘槸鍚︽嬁鍒颁簡 `session_id` 鍜?workspace銆傛棩蹇椾笉浼氳褰?prompt 鎴栨ā鍨嬪洖绛斻€?
## 闇€瑕佹敼 `proxy/config.yaml` 鍚楋紵

閫氬父涓嶉渶瑕併€?
鍙湁褰撲綘鎯虫敼鍙樹唬鐞嗙洃鍚鍙ｃ€佷笂娓?backend銆乽sage 鏂囦欢銆佽璇?key 鎴栬建杩圭洰褰曟椂锛屾墠闇€瑕佹敼 `proxy/config.yaml`锛?
```yaml
profiles:
  hermes:
    port: 8907
    backend: "GLM-5-FP8"
    session_dir: "traces/hermes"
```

Hermes plugin 瀹夎鍦?Hermes 鑷繁鐨勬彃浠剁洰褰曢噷锛屽苟鐢?Hermes 閰嶇疆鏂囦欢閫夋嫨銆俙proxy/config.yaml` 涓嶈礋璐ｅ姞杞?Hermes plugin銆?
## 涓轰粈涔堢敤 Model-Provider Plugin

Hermes hooks 鍙互瑙傚療鐢熷懡鍛ㄦ湡浜嬩欢锛屼篃鍙互娉ㄥ叆 prompt context锛屼絾瀹冧滑涓嶆槸淇敼 HTTP request headers 鐨勫悎閫傚眰銆?
model-provider plugin 鎵嶆槸鍚堥€傚眰锛屽洜涓?Hermes 鏋勫缓妯″瀷璇锋眰鏃朵細璋冪敤 `ProviderProfile.build_api_kwargs_extras()`銆傝繖涓柟娉曞彲浠ヤ负褰撳墠璇锋眰杩斿洖 OpenAI client kwargs锛屽寘鎷?`extra_headers`銆?
## 楠岃瘉

鍚姩浠ｇ悊锛?
```bash
cd proxy
python hermes_proxy.py
```

鐢ㄨ provider 鍚姩 Hermes 鍚庡彂閫佷竴鏉℃秷鎭€備唬鐞嗗簲璇ュ啓鍑猴細

```text
traces/hermes/<session_id>.json
```

濡傛灉鏂囦欢钀藉埌 `__no_session_id__`锛屾墦寮€ `HERMES_RL_HEADERS_LOG`锛岀‘璁ゆ棩蹇楅噷鏄惁鏈?`has_session_id: true`銆?
楠岃瘉 Hermes 鏈哄櫒涓婄殑 Python/OpenAI SDK 杩為€氭€э細

```bash
python -c "from openai import OpenAI; c=OpenAI(api_key='sk-proxy', base_url='http://<proxy-host>:8907/v1'); r=c.chat.completions.create(model='glm-5-fp8', messages=[{'role':'user','content':'hello'}], max_tokens=20); print(repr(r.choices[0].message.content))"
```

濡傛灉杩欎釜鍛戒护澶辫触锛屼絾 `curl http://<proxy-host>:8907/health` 鍙互鎴愬姛锛岀粰 proxy host 璁剧疆 `NO_PROXY` 鍚庨噸璇曘€?