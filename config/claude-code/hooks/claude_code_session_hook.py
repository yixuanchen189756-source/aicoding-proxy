#!/usr/bin/env python3
"""Register Claude Code session events with the proxy."""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path


def log(message: str, data: object | None = None) -> None:
    log_path = Path(os.environ.get("CLAUDE_CODE_HOOK_LOG", Path(__file__).with_name("claude_code_session_hook.log")))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(f"[{datetime.now(UTC).isoformat()}] {message}\n")
        if data is not None:
            f.write(json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n")


def main() -> int:
    log("hook invoked", {"argv": sys.argv, "cwd": os.getcwd(), "python": sys.executable})
    raw = sys.stdin.read()
    log("stdin read", {"length": len(raw), "raw": raw})
    event = json.loads(raw or "{}")
    run_id = os.environ["CLAUDE_CODE_RUN_ID"]
    target = os.environ["ANTHROPIC_BASE_URL"].rstrip("/") + "/_agent/session-event"
    log(
        "environment",
        {
            "ANTHROPIC_BASE_URL": os.environ.get("ANTHROPIC_BASE_URL"),
            "CLAUDE_CODE_RUN_ID": run_id,
            "CLAUDE_CODE_WORKSPACE_ID": os.environ.get("CLAUDE_CODE_WORKSPACE_ID"),
            "CLAUDE_CODE_WORKSPACE": os.environ.get("CLAUDE_CODE_WORKSPACE"),
            "CLAUDE_CODE_INSTANCE_ID": os.environ.get("CLAUDE_CODE_INSTANCE_ID"),
        },
    )
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
    }
    log("POST prepared", {"target": target, "payload": payload})
    request = urllib.request.Request(
        target,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    response = urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=2)
    body = response.read().decode("utf-8", errors="replace")
    log("POST success", {"status": getattr(response, "status", None), "body": body})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
