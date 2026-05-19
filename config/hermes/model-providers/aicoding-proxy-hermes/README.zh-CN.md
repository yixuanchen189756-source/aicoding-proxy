# AI Coding Proxy Hermes Provider

璇█锛?[English](README.md) | 绠€浣撲腑鏂?
杩欎釜 Hermes model-provider plugin 浼氭妸 Hermes 璇锋眰璺敱鍒?`hermes_proxy.py`锛屽苟鍦ㄤ笉淇敼 Hermes 婧愮爜鐨勬儏鍐典笅娣诲姞杞ㄨ抗 headers銆?
瀹夎鏂瑰紡锛氭妸鏁翠釜鐩綍澶嶅埗鍒帮細

```text
$HERMES_HOME/plugins/model-providers/aicoding-proxy-hermes/
```

濡傛灉娌℃湁璁剧疆 `HERMES_HOME`锛孒ermes 閫氬父浣跨敤锛?
```text
~/.hermes/plugins/model-providers/aicoding-proxy-hermes/
```

鍦?Hermes 閰嶇疆涓€夋嫨杩欎釜 provider锛?
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

濡傛灉 proxy host 鏄?tailnet 鎴栧眬鍩熺綉鍦板潃锛屽惎鍔?Hermes 鍓嶅厛缁曡繃绯荤粺 HTTP 浠ｇ悊锛?
```bash
export NO_PROXY="<proxy-host>"
```

PowerShell锛?
```powershell
$env:NO_PROXY = "<proxy-host>"
```

浠?workspace 鐩綍鍚姩 Hermes锛?
```bash
cd /path/to/workspace
hermes
```

鍙€夎皟璇曟棩蹇楋細

```bash
export HERMES_RL_HEADERS_LOG="$HOME/.hermes/aicoding-proxy-headers.jsonl"
```

鎻掍欢浼氫负姣忎釜涓?LLM 璇锋眰娣诲姞锛?
```text
X-Session-Id: <Hermes session_id>
X-Agent-Session-Id: <Hermes session_id>
X-Turn-Type: main
X-Agent-Workspace: <Hermes process cwd>
```

鎻掍欢渚濊禆 Hermes 瀹樻柟鐨?`ProviderProfile.build_api_kwargs_extras()` 鎵╁睍鐐广€傝繖涓墿灞曠偣鍙互杩斿洖 OpenAI client kwargs锛屼緥濡?`extra_headers`銆?