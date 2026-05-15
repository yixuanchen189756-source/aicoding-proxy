@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "CLAUDE_BIN=%CLAUDE_CODE_BIN%"
if not defined CLAUDE_BIN set "CLAUDE_BIN=claude-js"
set "CLAUDE_ARGS="

:parse_args
if "%~1"=="" goto args_done
if /I "%~1"=="--claude-bin" (
    if "%~2"=="" (
        echo Missing value for --claude-bin 1>&2
        exit /b 2
    )
    set "CLAUDE_BIN=%~2"
    shift
    shift
    goto parse_args
)
if "%~1"=="--" (
    shift
    goto collect_args
)
goto collect_args

:collect_args
if "%~1"=="" goto args_done
set "CLAUDE_ARGS=!CLAUDE_ARGS! %1"
shift
goto collect_args

:args_done
set "CLAUDE_CODE_WORKSPACE=%CD%"

if defined CLAUDE_CODE_WORKSPACE_ID goto workspace_id_done
set "CLAUDE_CODE_HASH_FILE=%TEMP%\claude_code_ws_%RANDOM%%RANDOM%.txt"
<nul set /p "=!CLAUDE_CODE_WORKSPACE!" > "!CLAUDE_CODE_HASH_FILE!"
set "CLAUDE_CODE_WORKSPACE_HASH="
for /f "skip=1 delims=" %%I in ('certutil -hashfile "!CLAUDE_CODE_HASH_FILE!" SHA256 2^>nul') do if not defined CLAUDE_CODE_WORKSPACE_HASH set "CLAUDE_CODE_WORKSPACE_HASH=%%I"
del /q "!CLAUDE_CODE_HASH_FILE!" >nul 2>nul
set "CLAUDE_CODE_WORKSPACE_HASH=!CLAUDE_CODE_WORKSPACE_HASH: =!"
set "CLAUDE_CODE_WORKSPACE_ID=ws_!CLAUDE_CODE_WORKSPACE_HASH:~0,12!"
:workspace_id_done

if defined CLAUDE_CODE_RUN_ID goto run_id_done
set "CLAUDE_CODE_TIMESTAMP=%TIME%"
set "CLAUDE_CODE_TIMESTAMP=!CLAUDE_CODE_TIMESTAMP::=!"
set "CLAUDE_CODE_TIMESTAMP=!CLAUDE_CODE_TIMESTAMP:.=!"
set "CLAUDE_CODE_TIMESTAMP=!CLAUDE_CODE_TIMESTAMP: =0!"
set "CLAUDE_CODE_GUID=%RANDOM%%RANDOM%%RANDOM%"
set "CLAUDE_CODE_RUN_ID=ccrun_!CLAUDE_CODE_WORKSPACE_ID!_!CLAUDE_CODE_TIMESTAMP!_!CLAUDE_CODE_GUID!"
:run_id_done

if not defined CLAUDE_CODE_INSTANCE_ID (
    if defined COMPUTERNAME (
        set "CLAUDE_CODE_INSTANCE_ID=%COMPUTERNAME%"
    ) else (
        for /f "usebackq delims=" %%I in (`hostname`) do set "CLAUDE_CODE_INSTANCE_ID=%%I"
    )
)
if not defined CLAUDE_CODE_INSTANCE_ID set "CLAUDE_CODE_INSTANCE_ID=claude-code-default"

if not defined ANTHROPIC_BASE_URL set "ANTHROPIC_BASE_URL=http://100.64.0.132:8906/v1"
if not defined CLAUDE_CODE_SESSION_EVENT_URL set "CLAUDE_CODE_SESSION_EVENT_URL=http://100.64.0.132:8906/_agent/session-event"

set LF=^


set "ANTHROPIC_CUSTOM_HEADERS=X-Agent-Name: claude-code!LF!X-Agent-Run-Id: !CLAUDE_CODE_RUN_ID!!LF!X-Agent-Workspace-Id: !CLAUDE_CODE_WORKSPACE_ID!!LF!X-Agent-Workspace: !CLAUDE_CODE_WORKSPACE!!LF!X-Instance-Id: !CLAUDE_CODE_INSTANCE_ID!"

echo Claude Code RL wrapper
echo   run_id:       !CLAUDE_CODE_RUN_ID!
echo   workspace_id: !CLAUDE_CODE_WORKSPACE_ID!
echo   workspace:    !CLAUDE_CODE_WORKSPACE!
echo   base_url:     !ANTHROPIC_BASE_URL!

call "%CLAUDE_BIN%" !CLAUDE_ARGS!
exit /b !ERRORLEVEL!
