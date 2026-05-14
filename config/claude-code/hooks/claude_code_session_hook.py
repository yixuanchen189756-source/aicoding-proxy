#!/usr/bin/env python3
"""Claude Code hook script that reports session events to the local proxy."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path


DEFAULT_LOG_PATH = Path(__file__).resolve().parent / "claude_code_session_hook.log"
DEFAULT_SESSION_EVENT_URL = "http://127.0.0.1:8906/_agent/session-event"


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _log_path() -> Path:
    return Path(os.environ.get("CLAUDE_CODE_HOOK_LOG") or DEFAULT_LOG_PATH)


def _session_event_url() -> str:
    return os.environ.get("CLAUDE_CODE_SESSION_EVENT_URL", DEFAULT_SESSION_EVENT_URL).strip()


def debug_log(message: str, data: object | None = None) -> None:
    """Best-effort file logger for Claude Code hooks.

    Hooks must never fail Claude Code, so every logging error is swallowed.
    """
    try:
        path = _log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(f"[{_now()}] {message}\n")
            if data is not None:
                if isinstance(data, str):
                    rendered = data
                else:
                    rendered = json.dumps(data, ensure_ascii=False, indent=2, default=str)
                if len(rendered) > 20000:
                    rendered = rendered[:20000] + "\n...<truncated>"
                for line in rendered.splitlines() or [""]:
                    f.write(f"  {line}\n")
    except Exception:
        pass


def read_event() -> dict:
    raw = sys.stdin.read()
    debug_log("stdin read", {"length": len(raw), "raw": raw})
    if not raw.strip():
        debug_log("stdin empty; no session event will be posted")
        return {}
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        debug_log("stdin JSON parse failed", {"error": str(exc)})
        return {}
    if not isinstance(obj, dict):
        debug_log("stdin JSON is not an object", {"type": type(obj).__name__, "value": obj})
        return {}
    debug_log(
        "event parsed",
        {
            "hook_event_name": obj.get("hook_event_name"),
            "session_id": obj.get("session_id"),
            "transcript_path": obj.get("transcript_path"),
            "cwd": obj.get("cwd"),
            "source": obj.get("source"),
            "keys": sorted(obj.keys()),
        },
    )
    return obj


def _proxy_env_snapshot() -> dict[str, str | None]:
    names = [
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
    ]
    return {name: os.environ.get(name) for name in names if os.environ.get(name)}


def _post_json_no_proxy(target: str, payload: dict) -> tuple[int | None, str | None, str]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        target,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=2) as response:
        response_body = response.read().decode("utf-8", errors="replace")
        return (
            getattr(response, "status", None),
            getattr(response, "reason", None),
            response_body,
        )


def main() -> int:
    debug_log(
        "hook invoked",
        {
            "argv": sys.argv,
            "python": sys.executable,
            "cwd": os.getcwd(),
            "log_path": str(_log_path()),
        },
    )
    event = read_event()
    run_id = os.environ.get("CLAUDE_CODE_RUN_ID", "").strip()
    env_snapshot = {
        "CLAUDE_CODE_RUN_ID": run_id,
        "CLAUDE_CODE_WORKSPACE_ID": os.environ.get("CLAUDE_CODE_WORKSPACE_ID"),
        "CLAUDE_CODE_WORKSPACE": os.environ.get("CLAUDE_CODE_WORKSPACE"),
        "CLAUDE_CODE_INSTANCE_ID": os.environ.get("CLAUDE_CODE_INSTANCE_ID"),
        "CLAUDE_CODE_SESSION_EVENT_URL": os.environ.get("CLAUDE_CODE_SESSION_EVENT_URL"),
        "ANTHROPIC_BASE_URL": os.environ.get("ANTHROPIC_BASE_URL"),
        "has_ANTHROPIC_CUSTOM_HEADERS": bool(os.environ.get("ANTHROPIC_CUSTOM_HEADERS")),
        "proxy_env": _proxy_env_snapshot(),
    }
    debug_log("environment snapshot", env_snapshot)
    if not event:
        debug_log("skip POST: empty or invalid hook event")
        return 0
    if not run_id:
        debug_log("skip POST: missing CLAUDE_CODE_RUN_ID")
        return 0

    payload = {
        "agent_name": "claude-code",
        "run_id": run_id,
        "workspace_id": os.environ.get("CLAUDE_CODE_WORKSPACE_ID"),
        "workspace": os.environ.get("CLAUDE_CODE_WORKSPACE"),
        "instance_id": os.environ.get("CLAUDE_CODE_INSTANCE_ID"),
        "hook_event_name": event.get("hook_event_name"),
        "session_id": event.get("session_id"),
        "transcript_path": event.get("transcript_path"),
        "cwd": event.get("cwd"),
        "source": event.get("source"),
        "prompt": event.get("prompt"),
        "timestamp": _now(),
    }
    target = _session_event_url()
    debug_log("POST prepared", {"target": target, "payload": payload})
    try:
        status, reason, response_body = _post_json_no_proxy(target, payload)
        debug_log(
            "POST success",
            {
                "status": status,
                "reason": reason,
                "response_body": response_body,
                "proxy_mode": "disabled",
            },
        )
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        # Hooks must never block or fail Claude Code.
        debug_log(
            "POST failed",
            {
                "type": type(exc).__name__,
                "error": str(exc),
                "target": target,
            },
        )
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
