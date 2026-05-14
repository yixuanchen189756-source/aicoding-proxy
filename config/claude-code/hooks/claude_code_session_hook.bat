@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "HOOK_LOG=%CLAUDE_CODE_HOOK_LOG%"
if not defined HOOK_LOG set "HOOK_LOG=D:\aicoding_proxy\logs\claude.txt"

for %%I in ("%HOOK_LOG%") do if not exist "%%~dpI" mkdir "%%~dpI" >nul 2>nul

echo [%DATE% %TIME%] [hook.bat] invoked>> "%HOOK_LOG%"
echo   argv: %*>> "%HOOK_LOG%"
echo   cwd: %CD%>> "%HOOK_LOG%"
echo   script: %~dp0claude_code_session_hook.py>> "%HOOK_LOG%"
echo   run_id: %CLAUDE_CODE_RUN_ID%>> "%HOOK_LOG%"
echo   workspace_id: %CLAUDE_CODE_WORKSPACE_ID%>> "%HOOK_LOG%"
echo   session_event_url: %CLAUDE_CODE_SESSION_EVENT_URL%>> "%HOOK_LOG%"

set "HOOK_PYTHON=%CLAUDE_CODE_HOOK_PYTHON%"
if not defined HOOK_PYTHON set "HOOK_PYTHON=python"

echo [%DATE% %TIME%] [hook.bat] launching python: %HOOK_PYTHON%>> "%HOOK_LOG%"
"%HOOK_PYTHON%" "%~dp0claude_code_session_hook.py"
set "HOOK_EXIT=!ERRORLEVEL!"
echo [%DATE% %TIME%] [hook.bat] python exit code: !HOOK_EXIT!>> "%HOOK_LOG%"

exit /b 0
