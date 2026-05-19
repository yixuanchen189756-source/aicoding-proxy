# Claude Code 浠ｇ悊閰嶇疆

璇█ / Language: [English](README.md) | 绠€浣撲腑鏂?
Claude Code 闆嗘垚鍙湁涓や釜閮ㄥ垎锛?
1. wrapper 鍚姩 Claude Code锛屽苟璁剧疆绋冲畾鐨?run/workspace headers銆?2. hook 鎺ユ敹 Claude Code 鐨?`session_id`锛屽苟娉ㄥ唽鍒颁唬鐞嗐€?
`ANTHROPIC_BASE_URL` 鐢?Claude Code 鑷繁鐨?settings 閰嶇疆銆傝繖浜涜剼鏈笉浼氳鍙?`.env`锛屼笉浼氱寽鍏朵粬閰嶇疆 key锛屼篃涓嶄細鏀瑰啓妯″瀷鍦板潃銆?
## 鏂囦欢

```text
config/claude-code/
  scripts/
    claude_code_rl.sh
    claude_code_rl.bat

  hooks/
    claude_code_session_hook.py
```

## Claude Settings

鍦?Claude settings 涓厤缃唬鐞嗗湴鍧€锛?
```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "http://100.64.0.132:8906"
  }
}
```

浣跨敤瑁?base URL锛屼笉瑕佸姞 `/v1`銆?
## 鍚姩 Claude Code

閫氳繃 wrapper 鍚姩 Claude Code锛岃繖鏍锋ā鍨嬭姹備細甯︿笂 run metadata headers銆?
Linux/macOS锛?
```bash
sh config/claude-code/scripts/claude_code_rl.sh
```

Windows锛?
```bat
config\claude-code\scripts\claude_code_rl.bat
```

wrapper 鍙缃細

```text
CLAUDE_CODE_RUN_ID
CLAUDE_CODE_WORKSPACE_ID
CLAUDE_CODE_WORKSPACE
CLAUDE_CODE_INSTANCE_ID
ANTHROPIC_CUSTOM_HEADERS
```

`ANTHROPIC_BASE_URL` 鐢?Claude Code 澶勭悊銆?
## Hook Settings

鎶?`claude_code_session_hook.py` 澶嶅埗鍒扮ǔ瀹氱殑 Claude hook 浣嶇疆锛屼緥濡傦細

```text
~/.claude/hooks/claude_code_session_hook.py
```

Linux/macOS锛?
```json
{
  "command": "python3 ~/.claude/hooks/claude_code_session_hook.py"
}
```

Windows锛?
```json
{
  "command": "python C:\\Users\\PC-M\\.claude\\hooks\\claude_code_session_hook.py",
  "shell": "powershell"
}
```

Linux 涓嶉渶瑕?`shell` 瀛楁銆俉indows 搴旇浣跨敤 `"shell": "powershell"`銆?
hook 鍙娇鐢ㄤ竴涓唬鐞嗘潵婧愶細

```text
ANTHROPIC_BASE_URL
```

瀹冩妸 session event POST 鍒帮細

```text
<ANTHROPIC_BASE_URL>/_agent/session-event
```

## 杞ㄨ抗缁戝畾

wrapper 浼氭妸 `X-Agent-Run-Id` 鏀捐繘姣忎釜妯″瀷璇锋眰銆俬ook 涓婃姤锛?
```text
run_id -> session_id
```

浠ｇ悊闅忓悗鎶?Claude Code 杞ㄨ抗鍐欏叆锛?
```text
traces/claude-code/<session_id>.json
```

濡傛灉杞ㄨ抗钀藉埌 `__no_session_id__`锛屽彧妫€鏌ヨ繖浜涚偣锛?
1. Claude Code 鏄惁閫氳繃 wrapper 鍚姩銆?2. Claude settings 閲岀殑 `ANTHROPIC_BASE_URL` 鏄惁姝ｇ‘銆?3. hook 鏄惁杩愯骞舵敹鍒?`session_id`銆?4. wrapper 鐨?`CLAUDE_CODE_RUN_ID` 鏄惁鍜?hook 鐜涓€鑷淬€?