@echo off
setlocal EnableExtensions EnableDelayedExpansion

if not defined CLAUDE_CODE_BIN set "CLAUDE_CODE_BIN=claude-js"
if not defined CLAUDE_CODE_WORKSPACE set "CLAUDE_CODE_WORKSPACE=%CD%"
if not defined CLAUDE_CODE_WORKSPACE_ID for /f %%I in ('powershell -NoProfile -Command "$p=$env:CLAUDE_CODE_WORKSPACE; $b=[Text.Encoding]::UTF8.GetBytes($p); $h=[Security.Cryptography.SHA256]::Create().ComputeHash($b); 'ws_' + ([BitConverter]::ToString($h).Replace('-','').Substring(0,12).ToLower())"') do set "CLAUDE_CODE_WORKSPACE_ID=%%I"
if not defined CLAUDE_CODE_INSTANCE_ID set "CLAUDE_CODE_INSTANCE_ID=%COMPUTERNAME%"
if not defined CLAUDE_CODE_RUN_ID set "CLAUDE_CODE_RUN_ID=ccrun_!CLAUDE_CODE_WORKSPACE_ID!_%RANDOM%%RANDOM%"

set LF=^


set "ANTHROPIC_CUSTOM_HEADERS=X-Agent-Name: claude-code!LF!X-Agent-Run-Id: !CLAUDE_CODE_RUN_ID!!LF!X-Agent-Workspace-Id: !CLAUDE_CODE_WORKSPACE_ID!!LF!X-Agent-Workspace: !CLAUDE_CODE_WORKSPACE!!LF!X-Instance-Id: !CLAUDE_CODE_INSTANCE_ID!"

call "%CLAUDE_CODE_BIN%" %*
exit /b !ERRORLEVEL!
