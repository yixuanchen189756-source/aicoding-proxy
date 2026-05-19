from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from providers import register_provider
from providers.base import ProviderProfile


PROVIDER_NAME = "aicoding-proxy-hermes"


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _debug(event: str, payload: dict[str, Any]) -> None:
    log_path = _clean(os.environ.get("HERMES_RL_HEADERS_LOG"))
    if not log_path:
        return

    try:
        path = Path(log_path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": event,
            **payload,
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    except Exception:
        pass


class AICodingProxyHermesProfile(ProviderProfile):
    def build_api_kwargs_extras(
        self, *args: Any, session_id: str | None = None, **context: Any
    ):
        session = _clean(session_id)
        workspace = _clean(os.getcwd())

        headers = {
            "X-Turn-Type": "main",
        }
        if session:
            headers["X-Session-Id"] = session
            headers["X-Agent-Session-Id"] = session
        if workspace:
            headers["X-Agent-Workspace"] = workspace

        _debug(
            "headers_built",
            {
                "provider": PROVIDER_NAME,
                "has_session_id": bool(session),
                "has_workspace": bool(workspace),
                "positional_args": len(args),
                "context_keys": sorted(str(key) for key in context.keys()),
                "headers": sorted(headers.keys()),
            },
        )

        return {}, {"extra_headers": headers}


register_provider(
    AICodingProxyHermesProfile(
        name=PROVIDER_NAME,
        aliases=("aicoding-proxy", "rl-proxy-hermes", "hermes-rl-proxy"),
        api_mode="chat_completions",
        display_name="AI Coding Proxy for Hermes",
        description="OpenAI-compatible AI Coding Proxy provider with RL trajectory headers.",
        env_vars=("HERMES_RL_PROXY_API_KEY", "HERMES_RL_PROXY_BASE_URL"),
        base_url=os.environ.get("HERMES_RL_PROXY_BASE_URL", ""),
        auth_type="api_key",
        default_aux_model=os.environ.get("HERMES_RL_PROXY_MODEL", "glm-5-fp8"),
        fallback_models=(),
    )
)
