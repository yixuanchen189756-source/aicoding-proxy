#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
OpenAI 兼容代理服务
================================================================================

【设计目的】
本模块是一个代理服务，提供OpenAI兼容的API接口，将请求转发到vLLM后端。

【功能】
1. 兼容OpenAI API格式
2. 支持流式输出（Server-Sent Events）
3. 请求过滤和header处理
4. 健康检查

【使用场景】
在分布式LLM推理架构中作为API网关使用。
客户端可以通过OpenAI SDK直接连接到本服务，
无需关心后端vLLM的具体地址。

【示例】
```python
# 使用OpenAI SDK
from openai import OpenAI

client = OpenAI(
    base_url="http://<proxy-host>:8908/v1",
    api_key="dummy"  # 本服务不需要认证
)

response = client.chat.completions.create(
    model="qwen",
    messages=[{"role": "user", "content": "Hello"}]
)
print(response.choices[0].message.content)
```

【配置】
- VLLM_BASE_URL: vLLM后端地址（必须显式配置，或由 config.yaml 的 openclaw.backend 指定）
- OPENAI_PROXY_PORT: 本服务端口（默认 8081）
- OPENAI_PROXY_TRACE=1: 将 /v1/chat/completions 的用户输入与上游响应摘要打印到 stderr
- OPENAI_PROXY_SESSION_FOLDER: trajectory root; files are saved as {session_id}/task_{i}.json
================================================================================
"""

# 导入标准库
import asyncio  # 异步IO
import copy  # 深拷贝 messages
import json  # JSON解析
import os  # 环境变量
import re  # 正则表达式
import sys  # 标准错误输出
import time  # 时间戳
from pathlib import Path  # 路径
from typing import Any, Optional  # 类型注解
from urllib.parse import urljoin  # URL拼接

# 导入第三方库
import aiohttp  # 异步HTTP客户端

# 导入FastAPI
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse
import uvicorn

# [DISABLED] 实例注册表模块（暂时禁用，从未在通知流程中使用）
# from instance_registry import get_registry, InstanceConfig


# ================================================================================
# 配置常量
# ================================================================================

# vLLM后端地址
# 从环境变量读取，默认本地8078端口
# rstrip("/") 去除末尾斜杠，urljoin会自动处理
def _load_dotenv_file(path: Path) -> None:
    """Load KEY=VALUE pairs from a local .env file without overriding env vars."""
    if not path.exists():
        return
    loaded = 0
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
                loaded += 1
    except Exception as exc:
        print(f"[config-warning] could not read dotenv file {path}: {exc}", file=sys.stderr, flush=True)
        return
    if loaded:
        print(f"[config] loaded {loaded} value(s) from {path}", file=sys.stderr, flush=True)


def _load_dotenv_for_config(config_path: Path) -> None:
    """Load dotenv values before expanding config.yaml placeholders."""
    seen: set[Path] = set()
    for candidate in [config_path.with_name(".env"), Path(__file__).with_name(".env")]:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        _load_dotenv_file(resolved)


def _expand_env_value(value: Any) -> Any:
    """Expand ${ENV_NAME} placeholders recursively in config values."""
    if isinstance(value, str):
        def repl(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in os.environ:
                print(
                    f"[config-warning] config placeholder ${{{name}}} expanded to an empty string",
                    file=sys.stderr,
                    flush=True,
                )
            return os.getenv(name, "")

        return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", repl, value)
    if isinstance(value, list):
        return [_expand_env_value(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand_env_value(v) for k, v in value.items()}
    return value


def _read_config_file(path: Path) -> dict[str, Any]:
    """Read JSON/YAML config data from disk."""
    if not path.exists():
        return {}
    _load_dotenv_for_config(path)
    text = path.read_text(encoding="utf-8")
    try:
        import yaml

        data = yaml.safe_load(text) or {}
    except Exception:
        try:
            data = json.loads(text)
        except Exception:
            data = {}
    data = data if isinstance(data, dict) else {}
    return _expand_env_value(data)


def _parse_simple_backend_settings(text: str, backend_name: str) -> dict[str, Optional[str]]:
    """Parse the small backend subset we need when PyYAML is unavailable."""
    in_backends = False
    current_backend: Optional[str] = None
    backend: dict[str, Any] = {}
    endpoint: dict[str, Any] = {}
    in_endpoints = False

    def scalar(value: str) -> Optional[str]:
        value = value.split(" #", 1)[0].strip()
        if value in {"", "null", "None", "~"}:
            return None
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            return value[1:-1]
        return value

    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        stripped = raw.strip()

        if indent == 0:
            if stripped == "backends:":
                in_backends = True
                continue
            if in_backends:
                break
            continue

        if not in_backends:
            continue

        if indent == 2 and stripped.endswith(":"):
            if current_backend == backend_name:
                break
            current_backend = stripped[:-1]
            backend = {}
            endpoint = {}
            in_endpoints = False
            continue

        if current_backend != backend_name:
            continue

        if indent == 4 and stripped == "endpoints:":
            in_endpoints = True
            continue

        if indent == 4 and ":" in stripped and not in_endpoints:
            key, value = stripped.split(":", 1)
            backend[key.strip()] = scalar(value)
            continue

        if indent == 6 and stripped.startswith("- "):
            in_endpoints = True
            item = stripped[2:].strip()
            if ":" in item:
                key, value = item.split(":", 1)
                endpoint[key.strip()] = scalar(value)
            continue

        if indent == 8 and in_endpoints and ":" in stripped:
            key, value = stripped.split(":", 1)
            endpoint[key.strip()] = scalar(value)

    if current_backend != backend_name and not backend:
        return {"base_url": None, "api_key": None, "model": None}

    base_url = (
        endpoint.get("openai_url")
        or endpoint.get("url")
        or backend.get("openai_url")
        or backend.get("base_url")
    )
    api_key = endpoint.get("api_key") or backend.get("api_key")
    model = endpoint.get("model")
    return _expand_env_value({
        "base_url": (str(base_url).rstrip("/") + "/") if base_url else None,
        "api_key": str(api_key).strip() if api_key else None,
        "model": str(model).strip() if model else None,
    })


def _profile_backend_name(data: dict[str, Any], profile_name: str) -> Optional[str]:
    profiles = data.get("profiles")
    profile = profiles.get(profile_name) if isinstance(profiles, dict) else None
    if not isinstance(profile, dict):
        return None
    backend = profile.get("backend")
    return str(backend).strip() if backend else None


def _openclaw_config_value(data: dict[str, Any], key: str) -> Any:
    section = data.get("openclaw")
    if not isinstance(section, dict):
        return None
    return section.get(key)


def _load_openclaw_proxy_settings(config_path: Optional[Path | str] = None) -> dict[str, Any]:
    default_config_path = Path(__file__).with_name("config.yaml")
    path = Path(config_path or os.getenv("OPENAI_PROXY_CONFIG", str(default_config_path)))
    data = _read_config_file(path)
    section = data.get("openclaw") if isinstance(data, dict) else None
    return dict(section) if isinstance(section, dict) else {}


def _parse_simple_profile_backend(text: str, profile_name: str) -> Optional[str]:
    in_profiles = False
    current_profile: Optional[str] = None

    def scalar(value: str) -> Optional[str]:
        value = value.split(" #", 1)[0].strip()
        if value in {"", "null", "None", "~"}:
            return None
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            return value[1:-1]
        return value

    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        stripped = raw.strip()

        if indent == 0:
            if stripped == "profiles:":
                in_profiles = True
                continue
            if in_profiles:
                break
            continue

        if not in_profiles:
            continue

        if indent == 2 and stripped.endswith(":"):
            current_profile = stripped[:-1]
            continue

        if current_profile == profile_name and indent == 4 and ":" in stripped:
            key, value = stripped.split(":", 1)
            if key.strip() == "backend":
                return scalar(value)

    return None


def _load_upstream_backend_settings(
    config_path: Optional[Path | str] = None,
    backend_name: Optional[str] = None,
) -> dict[str, Optional[str]]:
    """Load OpenAI-compatible upstream settings from shared config.yaml."""
    default_config_path = Path(__file__).with_name("config.yaml")
    path = Path(config_path or os.getenv("OPENAI_PROXY_CONFIG", str(default_config_path)))
    data = _read_config_file(path)
    name = (
        backend_name
        or os.getenv("OPENCLAW_UPSTREAM_BACKEND")
        or _openclaw_config_value(data, "backend")
        or _profile_backend_name(data, "openclaw")
    )
    if not data and path.exists():
        text = path.read_text(encoding="utf-8")
        name = name or _parse_simple_profile_backend(text, "openclaw")
        name = name or "glm-5-fp8"
        return _parse_simple_backend_settings(text, name)
    name = name or "glm-5-fp8"
    backends = data.get("backends")
    backend = backends.get(name) if isinstance(backends, dict) else None
    if not isinstance(backend, dict):
        return {"base_url": None, "api_key": None, "model": None}

    endpoints = backend.get("endpoints")
    endpoint = endpoints[0] if isinstance(endpoints, list) and endpoints and isinstance(endpoints[0], dict) else {}
    base_url = (
        endpoint.get("openai_url")
        or endpoint.get("url")
        or backend.get("openai_url")
        or backend.get("base_url")
    )
    api_key = endpoint.get("api_key") or backend.get("api_key")
    model = endpoint.get("model")
    return {
        "base_url": (str(base_url).rstrip("/") + "/") if base_url else None,
        "api_key": str(api_key).strip() if api_key else None,
        "model": str(model).strip() if model else None,
    }


def _apply_upstream_request_config(
    body_obj: Any,
    headers: dict[str, str],
    *,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
) -> tuple[Any, dict[str, str]]:
    """Apply configured model and bearer token to an outbound upstream request."""
    out_body = copy.deepcopy(body_obj)
    out_headers = {str(k): str(v) for k, v in headers.items()}
    if model and isinstance(out_body, dict):
        out_body["model"] = model
    if api_key:
        for key in list(out_headers.keys()):
            if key.lower() == "authorization":
                del out_headers[key]
        out_headers["authorization"] = f"Bearer {api_key}"
    if not any(key.lower() == "accept-encoding" for key in out_headers):
        out_headers["accept-encoding"] = "identity"
    return out_body, out_headers


_UPSTREAM_BACKEND_SETTINGS = _load_upstream_backend_settings()
_OPENCLAW_PROXY_SETTINGS = _load_openclaw_proxy_settings()

_configured_vllm_base_url = (os.getenv("VLLM_BASE_URL") or _UPSTREAM_BACKEND_SETTINGS.get("base_url") or "").strip()
if not _configured_vllm_base_url:
    raise RuntimeError("OpenClaw upstream base URL is required; set VLLM_BASE_URL or configure openclaw.backend in config.yaml")
VLLM_BASE_URL = _configured_vllm_base_url.rstrip("/") + "/"

VLLM_MODEL_NAME = (
    os.getenv("VLLM_MODEL_NAME", _UPSTREAM_BACKEND_SETTINGS.get("model") or "glm-5-fp8").strip()
)

VLLM_API_KEY = (
    os.getenv("VLLM_API_KEY", _UPSTREAM_BACKEND_SETTINGS.get("api_key") or "").strip()
)

# 本服务监听端口
# 默认8081，避免与vLLM的8078冲突
PROXY_PORT = int(os.getenv("OPENAI_PROXY_PORT", str(_OPENCLAW_PROXY_SETTINGS.get("port") or "8908")))

# 连接超时（秒）
# 建立连接的超时时间
CONNECT_TIMEOUT_S = float(os.getenv("OPENAI_PROXY_CONNECT_TIMEOUT_S", "36000"))

# 流式输出块大小（字节）
# 每次发送给客户端的数据块大小
STREAM_CHUNK_SIZE = int(os.getenv("OPENAI_PROXY_STREAM_CHUNK_SIZE", "8192"))

# 调试开关：设置 OPENAI_PROXY_DEBUG=1 打印关键诊断信息（默认关闭）
DEBUG_PROXY = os.getenv("OPENAI_PROXY_DEBUG", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "y",
    "on",
}

# 轨迹：打印请求/响应格式 + 按 x-session-id 写 JSON（仅 session_id、messages、tools）
TRACE_CONTENT = os.getenv("OPENAI_PROXY_TRACE", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "y",
    "on",
}
SESSION_FOLDER = (
    os.getenv(
        "OPENAI_PROXY_SESSION_FOLDER",
        str(_OPENCLAW_PROXY_SETTINGS.get("session_dir") or os.getcwd()),
    ).strip()
    or os.getcwd()
)

# 轨迹文件计数器（在启动时初始化为现有 json 文件数量）
_trajectory_counter: int = 0

def _redact_secret(value: str, *, keep_start: int = 6, keep_end: int = 4) -> str:
    """
    对可能的密钥做脱敏显示，避免直接打印明文。
    """
    v = (value or "").strip()
    if not v:
        return ""
    if len(v) <= keep_start + keep_end + 3:
        return f"{v[:2]}…{v[-2:]}"
    return f"{v[:keep_start]}…{v[-keep_end:]}"


def _debug_print(msg: str) -> None:
    if DEBUG_PROXY:
        print(f"[proxy-debug] {msg}", file=sys.stderr, flush=True)


def _summarize_headers(headers: dict[str, str]) -> dict[str, str]:
    """
    仅用于调试输出的 header 摘要（会脱敏 Authorization 等字段）。
    """
    out: dict[str, str] = {}
    for k, v in headers.items():
        lk = k.lower()
        if lk in {"authorization", "proxy-authorization", "x-api-key"}:
            out[k] = _redact_secret(str(v))
        else:
            # 避免超长 header 把日志刷屏
            sv = str(v)
            out[k] = sv if len(sv) <= 200 else (sv[:200] + "…")
    return out


def _try_parse_json(body: bytes) -> Optional[dict]:
    if not body:
        return None
    try:
        return json.loads(body.decode("utf-8"))
    except Exception:
        return None


def _truncate(s: str, max_len: int = 4000) -> str:
    if len(s) <= max_len:
        return s
    return s[:max_len] + f"…(truncated, len={len(s)})"


def _safe_filename(value: str) -> str:
    """Make an id safe for use as a single filename segment."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value).strip())
    cleaned = cleaned.strip("._")
    return cleaned or "__empty__"


def _normalize_openclaw_session_id(session_id: str) -> str:
    value = str(session_id or "").strip()
    prefix = "your-fixed-user-name_"
    if value.startswith(prefix):
        return value[len(prefix):] or value
    return value


def _is_clear_memory_request_body(body: bytes) -> bool:
    obj = _try_parse_json(body)
    if not isinstance(obj, dict):
        return False
    messages = obj.get("messages")
    if not isinstance(messages, list):
        return False
    for message in messages:
        if not isinstance(message, dict):
            continue
        if message.get("role") != "user":
            continue
        content = _extract_text_from_content(message.get("content")).strip()
        if content == "/clear-memory":
            return True
    return False


def _summarize_messages_for_trace(obj: dict[str, Any]) -> Any:
    """提取 messages 供打印/落盘；单条 content 过长则截断。"""
    msgs = obj.get("messages")
    if not isinstance(msgs, list):
        return msgs
    out: list[dict[str, Any]] = []
    for i, m in enumerate(msgs):
        if not isinstance(m, dict):
            out.append({"_raw": str(m)[:500]})
            continue
        role = m.get("role", "")
        content = m.get("content")
        if isinstance(content, str):
            content = _truncate(content, 2000)
        elif isinstance(content, list):
            content = _truncate(json.dumps(content, ensure_ascii=False), 2000)
        entry: dict[str, Any] = {"role": role, "content": content}
        if "name" in m:
            entry["name"] = m.get("name")
        if "tool_calls" in m:
            entry["tool_calls"] = m.get("tool_calls")
        out.append(entry)
    return out


def _trace_log(label: str, payload: Any) -> None:
    if not TRACE_CONTENT:
        return
    try:
        text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    except Exception:
        text = str(payload)
    print(f"[trace:{label}]\n{_truncate(text, 12000)}", file=sys.stderr, flush=True)


def _split_glm_think_markers(content_full: str) -> tuple[Optional[str], Optional[str]]:
    """
    GLM / 部分推理模型把「草稿推理」与「对用户回复」放在同一 delta.content 里，
    常见以 `</think>` 为界（前面多为英文思考，后面为面向用户的正文）。
    无标记时返回 (None, None)；有标记时第二个值为标记后的字符串（可为空串）。
    """
    marker = "</think>"
    if marker not in content_full:
        return None, None
    before, _, after = content_full.partition(marker)
    return before.strip() or None, after


def _parse_sse_events(buffer: bytes) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    解析 OpenAI 兼容 SSE：按行拆分 data: 行，跳过 [DONE]。

    返回 (events, summary)，其中 summary 含：
    - assistant_content_full: 拼接的 delta.content
    - assistant_reasoning_field: 拼接的 delta.reasoning_content（若模型单独下发）
    - assistant_visible_reply / assistant_think_prefix: 按 `</think>` 从 content_full 拆分
    - finish_reason: 最后一个 chunk 的 finish_reason（"stop"/"tool_calls"/"length"）
    """
    events: list[dict[str, Any]] = []
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    finish_reason: Optional[str] = None
    text = buffer.decode("utf-8", errors="replace")
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            continue
        try:
            obj = json.loads(payload)
        except json.JSONDecodeError:
            continue
        events.append(obj)
        try:
            for ch in obj.get("choices") or []:
                delta = ch.get("delta") or {}
                c = delta.get("content")
                if isinstance(c, str) and c:
                    content_parts.append(c)
                r = delta.get("reasoning_content")
                if isinstance(r, str) and r:
                    reasoning_parts.append(r)
                # 提取 finish_reason（最后一个非 None 值有效）
                fr = ch.get("finish_reason")
                if fr:
                    finish_reason = fr
        except Exception:
            pass
    content_full = "".join(content_parts)
    reasoning_full = "".join(reasoning_parts)

    # 🐛 Fix: glm-5-fp8 把回答放在 reasoning_content 而不是 content
    # 当 content 为空但 reasoning_content 有实质内容时，用它作为 fallback
    if not content_full and reasoning_full:
        content_full = reasoning_full
        reasoning_full = ""

    think_prefix, visible_after = _split_glm_think_markers(content_full)
    if visible_after is not None:
        vis = _truncate(visible_after.strip(), 12000)
        tp = _truncate(think_prefix, 12000) if think_prefix else None
    else:
        vis = _truncate(content_full, 12000)
        tp = None
    summary: dict[str, Any] = {
        "assistant_content_full": _truncate(content_full, 12000),
        "assistant_reasoning_field": _truncate(reasoning_full, 12000)
        if reasoning_full
        else None,
        "assistant_think_prefix": tp,
        "assistant_visible_reply": vis,
        "finish_reason": finish_reason,
    }
    return events, summary


def _summarize_upstream_json_response(data: bytes) -> dict[str, Any]:
    obj = _try_parse_json(data)
    if not isinstance(obj, dict):
        return {"_raw_preview": _truncate(data.decode("utf-8", errors="replace"), 3000)}
    out: dict[str, Any] = {"id": obj.get("id"), "model": obj.get("model")}
    choices = obj.get("choices")
    if isinstance(choices, list) and choices:
        c0 = choices[0]
        if isinstance(c0, dict):
            msg = c0.get("message") or {}
            if isinstance(msg, dict):
                tc = msg.get("tool_calls")
                if isinstance(tc, list) and tc:
                    out["assistant_tool_calls"] = tc
                if "content" in msg:
                    full = str(msg.get("content", "") or "")
                    out["assistant_content_full"] = _truncate(full, 8000)
                    tp, vis = _split_glm_think_markers(full)
                    if vis is not None:
                        out["assistant_think_prefix"] = (
                            _truncate(tp, 8000) if tp else None
                        )
                        out["assistant_visible_reply"] = _truncate(vis.strip(), 8000)
                    else:
                        out["assistant_visible_reply"] = _truncate(full, 8000)
            if "text" in c0 and not out.get("assistant_visible_reply"):
                out["text"] = _truncate(str(c0.get("text", "")), 8000)
            finish = c0.get("finish_reason")
            if finish is not None:
                out["finish_reason"] = finish
    return out


def _get_x_session_id(request: Request) -> str:
    for k, v in request.headers.items():
        if k.lower() == "x-session-id":
            s = (v or "").strip()
            return _normalize_openclaw_session_id(s) if s else "__empty_x_session_id__"
    return "__no_x_session_id__"


def _get_x_instance_id(request: Request) -> Optional[str]:
    """
    从请求头提取 X-Instance-Id。

    用于区分不同的 OpenClaw 实例。
    """
    for k, v in request.headers.items():
        if k.lower() == "x-instance-id":
            s = (v or "").strip()
            return s if s else None
    return None


def _get_x_gateway_url(request: Request) -> Optional[str]:
    """
    从请求头提取 X-Gateway-Url。

    OpenClaw 可以通过此请求头告知代理它的 Gateway 地址。
    """
    for k, v in request.headers.items():
        if k.lower() == "x-gateway-url":
            s = (v or "").strip()
            return s if s else None
    return None


# def _extract_raw_text_from_content(content: Any) -> str:
#     """
#     第一步：从 content 字段提取原始文本。

#     content 可能是:
#     1. 字符串: 直接返回
#     2. 列表: [{"type": "text", "text": "实际文本"}, ...]
#     """
#     if content is None:
#         return ""

#     if isinstance(content, str):
#         return content

#     if isinstance(content, list):
#         texts = []
#         for item in content:
#             if isinstance(item, dict) and item.get("type") == "text":
#                 text = item.get("text", "")
#                 if text:
#                     texts.append(text)
#         return "\n".join(texts)

#     return str(content)


# def _extract_actual_message(text: str) -> str:
#     """
#     第二步：从原始文本中提取实际用户消息。

#     格式示例：
#     - "sender (untrusted metadata):\n```json\n{...}\n```\n\n[fri 2026-04-03 09:30 utc] 谢谢"
#     - 或者直接是 "[fri 2026-04-03 09:30 utc] 好了"
#     - 或者直接是实际消息（无 metadata 和时间戳）

#     策略：
#     1. 如果有 "sender (untrusted metadata):" 开头，跳过它
#     2. 移除 ```json ... ``` 代码块
#     3. 移除时间戳 [fri 2026-04-03 09:30 utc] 格式
#     4. 返回清理后的消息
#     """
#     if not text:
#         return ""

#     # 跳过 "sender (untrusted metadata):" 开头
#     if text.startswith("sender (untrusted metadata):"):
#         text = text[len("sender (untrusted metadata):"):].lstrip()

#     # 移除 ```json ... ``` 代码块
#     text = re.sub(r'```json\s*.*?```\s*', '', text, flags=re.DOTALL)

#     # 移除时间戳 [fri 2026-04-03 09:30 utc] 格式
#     text = re.sub(r'\[[a-z]{3}\s+\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}\s+utc\]\s*', '', text, flags=re.IGNORECASE)

#     # 清理多余的空白
#     text = text.strip()

#     return text


# def _extract_text_from_content(content: Any) -> str:
#     """
#     从 content 字段提取实际用户消息（去除 metadata 和时间戳）。
#     """
#     raw_text = _extract_raw_text_from_content(content)
#     return _extract_actual_message(raw_text)

import re

def _extract_text_from_content(content) -> str:
    """
    从 OpenClaw / Claude 风格 content 中提取实际可读文本。
    """
    if content is None:
        return ""

    # 如果是字符串，尝试解析成 list
    if isinstance(content, str):
        s = content.strip()
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                content = parsed
            else:
                return s
        except Exception:
            return s

    if isinstance(content, list):
        texts = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") != "text":
                continue
            text = item.get("text", "")
            if not text:
                continue

            # 去掉 Sender metadata + ```json``` 整块
            text = re.sub(
                r"Sender\s*\(untrusted metadata\):\s*```json.*?```",
                "",
                text,
                flags=re.DOTALL | re.IGNORECASE
            )

            # 去掉时间戳 [Tue 2026-04-07 09:44 UTC] 或类似格式
            text = re.sub(
                r"\[[A-Za-z]{3}\s+\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}\s+UTC\]",
                "",
                text
            )

            # 清理空白
            text = text.strip()
            if text:
                texts.append(text)

        return "\n".join(texts)

    return str(content)

# 模型完成声明关键词（只看模型消息，不看用户消息）
_MODEL_COMPLETION_KEYWORDS = [
    "完成了", "完了", "已完成", "已成功",
    "全部完成", "已经完成", "已经成功",
]


def _detect_task_completion(
    messages: list[dict[str, Any]],
    response_summary: Optional[dict[str, Any]] = None,
) -> tuple[Optional[bool], str]:
    """
    检测任务是否完成。

    逻辑：
    1. TodoWrite 检查（保留）
    2. 模型最后消息关键词匹配 → 完成
    3. 交给 LLM 判断

    返回 (result, reason):
    - result=True: 任务完成
    - result=False: 任务未完成
    - result=None: 不确定，需要 LLM 兜底
    """
    t0 = time.perf_counter()
    print(f"[detect] 开始检测任务完成, messages 数量: {len(messages) if messages else 0}", file=sys.stderr, flush=True)

    if not messages:
        return False, "no_messages"

    # ── 1. 检查 TodoWrite 状态 ──
    td_start = time.perf_counter()
    todo_result = _check_todos(messages)
    td_elapsed = (time.perf_counter() - td_start) * 1000
    print(f"[detect] TodoWrite 检查结果: {todo_result}, 耗时={td_elapsed:.2f}ms", file=sys.stderr, flush=True)

    if todo_result == "has_incomplete":
        return False, "todos_incomplete"
    if todo_result == "all_completed":
        return True, "todos_all_completed"

    # ── 2. 模型最后消息关键词匹配 ──
    kw_start = time.perf_counter()
    last_assistant_text = _get_last_assistant_text(messages)
    kw_elapsed = (time.perf_counter() - kw_start) * 1000
    if last_assistant_text:
        for keyword in _MODEL_COMPLETION_KEYWORDS:
            if keyword in last_assistant_text:
                print(f"[detect] 关键词匹配: '{keyword}', 耗时={kw_elapsed:.2f}ms", file=sys.stderr, flush=True)
                return True, f"keyword_match: {keyword}"

    print(f"[detect] 无关键词匹配，耗时={kw_elapsed:.2f}ms，交给 LLM", file=sys.stderr, flush=True)

    # ── 3. 交给 LLM ──
    total_elapsed = (time.perf_counter() - t0) * 1000
    print(f"[detect] _detect_task_completion 总耗时={total_elapsed:.2f}ms, 返回 None", file=sys.stderr, flush=True)
    return None, "no_keyword_need_llm"


# ================================================================================
# 任务完成检测 - 辅助函数
# ================================================================================

def _check_todos(messages: list[dict[str, Any]]) -> Optional[str]:
    """
    检查消息中 TodoWrite 的状态。

    返回:
    - "has_incomplete": 有未完成的 todos
    - "all_completed": 所有 todos 都完成
    - None: 没有 TodoWrite
    """
    for msg in reversed(messages[-6:]):
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        tool_calls = msg.get("tool_calls", [])
        if not isinstance(tool_calls, list):
            continue
        for tc in tool_calls:
            if not isinstance(tc, dict):
                continue
            func = tc.get("function", {})
            if not isinstance(func, dict):
                continue
            if func.get("name") == "TodoWrite":
                try:
                    args = json.loads(func.get("arguments", "{}"))
                    todos = args.get("todos", [])
                    if isinstance(todos, list) and len(todos) > 0:
                        all_done = all(
                            t.get("status") == "completed"
                            for t in todos
                            if isinstance(t, dict)
                        )
                        if all_done:
                            return "all_completed"
                        else:
                            return "has_incomplete"
                except json.JSONDecodeError:
                    pass
    return None


def _get_last_assistant_text(messages: list[dict[str, Any]]) -> Optional[str]:
    """获取最后一条 assistant 消息的文本"""
    for msg in reversed(messages):
        if isinstance(msg, dict) and msg.get("role") == "assistant":
            return _extract_text_from_content(msg.get("content"))
    return None


def _get_last_user_text(messages: list[dict[str, Any]]) -> Optional[str]:
    """获取最后一条 user 消息的文本"""
    for msg in reversed(messages):
        if isinstance(msg, dict) and msg.get("role") == "user":
            content = _extract_text_from_content(msg.get("content"))
            if content.strip() == "/clear-memory":
                continue
            return content
    return None


def _is_openclaw_internal_message(text: str) -> bool:
    """检测是否是 OpenClaw 内部的 housekeeping 消息（不是真实用户任务）。"""
    if not text:
        return False
    # OpenClaw 新会话时发送的内部 filename slug 请求
    if "Based on this conversation, generate a short 1-2 word filename slug" in text:
        return True
    return False


def _extract_turn_pairs(
    messages: list[dict[str, Any]],
    req_messages: Optional[list[dict[str, Any]]] = None,
) -> list[tuple[str, str]]:
    """
    从消息列表中提取所有 (user_text, assistant_final_text) 交互对。
    跳过工具调用和工具返回，只取每轮最终的文字回答。
    跳过 OpenClaw 内部的 housekeeping 消息（如新会话时的 filename slug 请求）。
    """
    pairs: list[tuple[str, str]] = []
    current_user: Optional[str] = None

    all_msgs = list(messages) if messages else []

    for msg in all_msgs:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")

        if role == "user":
            content = _extract_text_from_content(msg.get("content"))
            if content and content.strip() != "/clear-memory":
                if _is_openclaw_internal_message(content):
                    current_user = None  # 跳过内部消息，清空当前 user
                    continue
                current_user = content

        elif role == "assistant":
            # 忽略有 tool_calls 的 assistant 消息（还在调用工具中）
            if msg.get("tool_calls"):
                continue
            assistant_text = _extract_text_from_content(msg.get("content"))
            if current_user and assistant_text:
                pairs.append((current_user, assistant_text))
                current_user = None  # 配对后清空，避免重复

    return pairs


def _build_completion_judge_prompt(
    messages: list[dict[str, Any]],
    req_messages: Optional[list[dict[str, Any]]] = None,
) -> str:
    """
    构造 LLM 判定任务完成的 prompt。

    策略：传入所有 (用户任务 → AI最终回答) 交互对，
    而不是只看最后一条消息。工具调用中间过程忽略。
    """
    pairs = _extract_turn_pairs(messages)

    # 截断辅助
    def trunc(s: str, max_len: int) -> str:
        return s if len(s) <= max_len else s[:max_len] + "..."

    turns_text = ""
    for i, (user_text, assistant_text) in enumerate(pairs, 1):
        turns_text += f"\n--- 第 {i} 轮 ---\n用户: {trunc(user_text, 300)}\nAI: {trunc(assistant_text, 500)}\n"

    if not turns_text:
        # 保底：一条交互都没有，才用旧方式
        user_text = _get_last_user_text(messages) or ""
        assistant_text = _get_last_assistant_text(messages) or ""
        turns_text = f"\n用户: {trunc(user_text, 300)}\nAI: {trunc(assistant_text, 500)}\n"

    return (
        "判断以下对话的任务是否已完成。\n"
        "\n"
        "【重要判断标准】\n"
        "- 用户必须明确提出了一个任务（如：帮我写代码、修改文件、执行命令、分析问题等）\n"
        "- 如果用户只是打招呼、问候、说'你好'、'有什么可以帮你'之类的客套话 → NO\n"
        "- 如果用户没有提出具体任务或请求 → NO\n"
        "- AI已完整回答了用户的问题 → YES\n"
        "- AI已完成用户明确要求的工作 → YES\n"
        "- 用户表示满意、感谢、不再需要帮助 → YES\n"
        "- 用户还有后续问题或新的请求 → NO\n"
        "- AI还在执行中或需要继续操作 → NO\n"
        "- 不确定 → NO\n"
        "\n"
        "只回答 YES 或 NO。\n"
        + turns_text
    )


def _extract_yes_no_decision(content: str, reasoning_content: str = "") -> tuple[str, bool]:
    """Return the leading YES/NO judge answer, ignoring leaked thinking text."""

    def clean(text: str) -> str:
        text = re.sub(r"```json.*?```", "", text or "", flags=re.DOTALL).strip()
        return text

    content_clean = clean(content)
    reasoning_clean = clean(reasoning_content)

    candidates: list[str] = []
    if content_clean:
        candidates.append(content_clean)
        if "</think>" in content_clean:
            before, _, after = content_clean.partition("</think>")
            candidates.extend([before.strip(), after.strip()])
    if reasoning_clean:
        candidates.append(reasoning_clean)

    for candidate in candidates:
        match = re.match(r"^\s*(YES|NO)\b", candidate, flags=re.IGNORECASE)
        if match:
            token = match.group(1).upper()
            return token, token == "YES"

    return "", False


async def _llm_judge_completion(
    messages: list[dict[str, Any]],
    response_summary: Optional[dict[str, Any]] = None,
    req_messages: Optional[list[dict[str, Any]]] = None,
) -> bool:
    """
    用 LLM 判断任务是否完成。

    调用同一个 vLLM 后端，发送极简 prompt。
    超时或异常时返回 False（宁可漏触发也不误触发）。
    """
    t0 = time.perf_counter()
    # 诊断：打印入参完整内容
    user_from_msg = _get_last_user_text(messages) if messages else None
    user_from_req = _get_last_user_text(req_messages) if req_messages else None
    last_asst = _get_last_assistant_text(messages) if messages else None
    print(f"[detect-llm] 入参: messages={len(messages) if messages else 0}条, req_messages={len(req_messages) if req_messages else 0}条", file=sys.stderr, flush=True)
    print(f"[detect-llm] user_from_msg={user_from_msg!r}, user_from_req={user_from_req!r}, last_asst={last_asst!r}", file=sys.stderr, flush=True)
    print(f"[detect-llm] messages 完整内容: {json.dumps(messages, ensure_ascii=False)[:1000]}", file=sys.stderr, flush=True)
    print(f"[detect-llm] req_messages 完整内容: {json.dumps(req_messages, ensure_ascii=False)[:1000]}", file=sys.stderr, flush=True)
    prompt = _build_completion_judge_prompt(messages, req_messages)
    print(f"[detect-llm] 调用 LLM 判定任务完成", file=sys.stderr, flush=True)
    print(f"[detect-llm] prompt:\n{prompt}", file=sys.stderr, flush=True)

    try:
        session = await _ensure_session()
        payload = {
            "model": VLLM_MODEL_NAME,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 1024,
            "temperature": 0,
        }
        headers = {
            "Content-Type": "application/json",
        }
        payload, headers = _apply_upstream_request_config(
            payload,
            headers,
            model=VLLM_MODEL_NAME,
            api_key=VLLM_API_KEY,
        )

        # 使用 vLLM 后端
        judge_url = urljoin(VLLM_BASE_URL, "v1/chat/completions")
        req_start = time.perf_counter()
        async with session.post(
            judge_url,
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=36000.0),
        ) as resp:
            req_elapsed = (time.perf_counter() - req_start) * 1000
            print(f"[detect-llm] vLLM HTTP 响应耗时={req_elapsed:.2f}ms, status={resp.status}", file=sys.stderr, flush=True)
            if resp.status != 200:
                resp_text = await resp.text()
                print(f"[detect-llm] LLM 返回状态码: {resp.status}, 响应: {resp_text[:200]}", file=sys.stderr, flush=True)
                return False
            data = await resp.json()
            print(f"[detect-llm] vLLM 响应: status={resp.status}, data前200={json.dumps(data, ensure_ascii=False)[:200]}", file=sys.stderr, flush=True)
            choices = data.get("choices", [])
            if not choices:
                print(f"[detect-llm] LLM 无响应 choices=[]", file=sys.stderr, flush=True)
                return False
            msg = choices[0].get("message", {})
            # Some OpenAI-compatible GLM endpoints leak hidden thinking across
            # content/reasoning_content, e.g. "NO</think>..." in content. The
            # judge contract is only the leading YES/NO token.
            raw_content = str(msg.get("content") or "")
            raw_reasoning = str(msg.get("reasoning_content") or "")
            decision_token, decision = _extract_yes_no_decision(raw_content, raw_reasoning)
            print(
                f"[detect-llm] LLM 原始 content: {raw_content!r}, reasoning长度={len(raw_reasoning)}",
                file=sys.stderr,
                flush=True,
            )
            if raw_reasoning:
                print(
                    f"[detect-llm] LLM reasoning 预览: {raw_reasoning[:300]!r}",
                    file=sys.stderr,
                    flush=True,
                )
            total_elapsed = (time.perf_counter() - t0) * 1000
            print(f"[detect-llm] YES/NO decision token: '{decision_token or '<none>'}'", file=sys.stderr, flush=True)
            if decision:
                print(f"[detect-llm] 判定: 任务完成, 总耗时={total_elapsed:.2f}ms", file=sys.stderr, flush=True)
                return True
            print(f"[detect-llm] 判定: 任务未完成, 总耗时={total_elapsed:.2f}ms", file=sys.stderr, flush=True)
            return False

    except asyncio.TimeoutError:
        elapsed = (time.perf_counter() - t0) * 1000
        print(f"[detect-llm] LLM 超时，耗时={elapsed:.2f}ms，默认未完成", file=sys.stderr, flush=True)
        return False
    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        print(f"[detect-llm] LLM 异常: {type(e).__name__}: {e}, 耗时={elapsed:.2f}ms", file=sys.stderr, flush=True)
        return False


def _extract_last_user_turn(obj: dict[str, Any]) -> Optional[str]:
    """OpenClaw 等多把 user content 存成 JSON 字符串数组，取最后一条 user 的可见文本。"""
    msgs = obj.get("messages")
    if not isinstance(msgs, list):
        return None
    for m in reversed(msgs):
        if not isinstance(m, dict) or m.get("role") != "user":
            continue
        c = m.get("content")
        if isinstance(c, str):
            s = c.strip()
            if s.startswith("["):
                try:
                    arr = json.loads(s)
                    if isinstance(arr, list) and arr and isinstance(arr[0], dict):
                        t = arr[0].get("text")
                        if isinstance(t, str):
                            return _truncate(t, 4000)
                except Exception:
                    pass
            return _truncate(c, 4000)
        if isinstance(c, list):
            return _truncate(json.dumps(c, ensure_ascii=False), 2000)
    return None

def _extract_last_turn(messages: list[dict]) -> list[dict]:
    """
    提取最后一轮对话：

    定义：
    - 从最后一个 user 消息开始
    - 到 messages 结尾（包含 assistant / tool / system 等）

    返回：
    - list[dict]
    """
    if not isinstance(messages, list) or not messages:
        return []

    # 从后往前找最后一个 user
    last_user_idx = None
    for i in range(len(messages) - 1, -1, -1):
        m = messages[i]
        if isinstance(m, dict) and m.get("role") == "user":
            last_user_idx = i
            break

    # 没找到 user（极少见，防御性处理）
    if last_user_idx is None:
        return []

    # 从该 user 到结尾
    return messages[last_user_idx:]

def _build_chat_request_trace(body: bytes) -> dict[str, Any]:
    obj = _try_parse_json(body)
    if not isinstance(obj, dict):
        return {
            "_parse_error": True,
            "raw_preview": _truncate(body.decode("utf-8", errors="replace"), 2000),
        }
    tools = obj.get("tools")
    tools_n = len(tools) if isinstance(tools, list) else None
    tools_payload: Any = None
    if isinstance(tools, list):
        tools_payload = tools
    return {
        "model": obj.get("model"),
        "stream": obj.get("stream"),
        "store": obj.get("store"),
        "max_tokens": obj.get("max_tokens"),
        "max_completion_tokens": obj.get("max_completion_tokens"),
        "last_user_turn": _extract_last_user_turn(obj),
        "messages": _summarize_messages_for_trace(obj),
        "tools": tools_payload,
        "tools_count": tools_n,
    }


# ================================================================================
# 全局状态
# ================================================================================

# HTTP会话
# 使用全局变量保存aiohttp.ClientSession
# 避免每次请求都创建新会话
_session: Optional[aiohttp.ClientSession] = None

# 按 session 保存 {session_id, messages, tools}（同 id 覆盖）+ 异步队列持久化
_trajectories_lock: Optional[asyncio.Lock] = None
_trajectories: dict[str, dict[str, Any]] = {}
_trace_queue: Optional[asyncio.Queue] = None
_trace_worker_task: Optional[asyncio.Task] = None

def _make_state_key(instance_id: Optional[str], session_id: str) -> str:
    """
    生成状态存储的组合键。

    格式: "{instance_id}:{session_id}"
    如果 instance_id 为空，使用 "default" 作为前缀。
    """
    iid = (instance_id or "default").strip()
    if not iid:
        iid = "default"
    return f"{iid}:{session_id}"


# Task tracking: session_id -> message count when task started
# OpenClaw sends full session history each time, so we just need to know where current task started
_task_start_index: dict[str, int] = {}
_task_file_index: dict[str, int] = {}
_new_session_clear_memory_sent: set[str] = set()


# ================================================================================
# Gateway instance registry
# ================================================================================

GATEWAY_INSTANCES_FILE = Path(__file__).parent / "gateway_instances.json"
_gateway_instances: dict[str, dict[str, str]] = {}


def _load_gateway_instances() -> None:
    """Load gateway instance registry from disk."""
    global _gateway_instances
    if not GATEWAY_INSTANCES_FILE.exists():
        print("[gateway] Instance registry file does not exist yet", file=sys.stderr, flush=True)
        _gateway_instances = {}
        return
    try:
        with open(GATEWAY_INSTANCES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("registry root must be an object")
        clean: dict[str, dict[str, str]] = {}
        for instance_id, value in data.items():
            if not isinstance(value, dict):
                continue
            iid = str(instance_id).strip()
            gateway_url = str(value.get("gateway_url") or "").strip()
            gateway_token = str(value.get("gateway_token") or "").strip()
            gateway_port = str(value.get("gateway_port") or "").strip()
            if not iid or not gateway_url or not gateway_token:
                continue
            clean[iid] = {
                "instance_id": iid,
                "gateway_url": gateway_url,
                "gateway_token": gateway_token,
                "gateway_port": gateway_port,
            }
        _gateway_instances = clean
        print(f"[gateway] Loaded {len(_gateway_instances)} gateway instances", file=sys.stderr, flush=True)
    except Exception as e:
        print(f"[gateway] Failed to load gateway instances: {e}", file=sys.stderr, flush=True)
        _gateway_instances = {}


def _save_gateway_instances() -> None:
    """Persist gateway instance registry to disk."""
    try:
        tmp_path = GATEWAY_INSTANCES_FILE.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(_gateway_instances, f, ensure_ascii=False, indent=2)
        tmp_path.replace(GATEWAY_INSTANCES_FILE)
        print(f"[gateway] Saved {len(_gateway_instances)} gateway instances", file=sys.stderr, flush=True)
    except Exception as e:
        print(f"[gateway] Failed to save gateway instances: {e}", file=sys.stderr, flush=True)


def _register_gateway_instance(
    instance_id: Any,
    gateway_url: Any,
    gateway_token: Any,
    gateway_port: Any = None,
) -> bool:
    """Register one OpenClaw instance's gateway URL and token."""
    iid = str(instance_id).strip() if instance_id else ""
    url = str(gateway_url).strip() if gateway_url else ""
    token = str(gateway_token).strip() if gateway_token else ""
    port = str(gateway_port).strip() if gateway_port else ""
    if not iid or not url or not token:
        return False
    _gateway_instances[iid] = {
        "instance_id": iid,
        "gateway_url": url,
        "gateway_token": token,
        "gateway_port": port,
    }
    _save_gateway_instances()
    print(
        f"[gateway] Registered instance {iid}: url={url}, port={port or 'none'}, token={token[:10]}...",
        file=sys.stderr,
        flush=True,
    )
    return True


def _get_gateway_instance(instance_id: Optional[str]) -> Optional[dict[str, str]]:
    """Return registry entry for an OpenClaw instance id."""
    iid = str(instance_id).strip() if instance_id else ""
    if not iid:
        return None
    entry = _gateway_instances.get(iid)
    return dict(entry) if isinstance(entry, dict) else None


def _resolve_gateway_for_request(
    instance_id: Optional[str],
    gateway_url: Optional[str],
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Resolve gateway URL/token for a proxied request."""
    iid = str(instance_id).strip() if instance_id else None
    url = str(gateway_url).strip() if gateway_url else None

    entry = _get_gateway_instance(iid)
    if entry:
        resolved_url = url or entry.get("gateway_url")
        token = entry.get("gateway_token")
        return resolved_url, token, iid

    return url, None, iid


async def _persist_session_json() -> None:
    """
    将轨迹保存到 SESSION_FOLDER/{session_id}/task_{i}.json
    同时清理已保存实例的 _task_start_index 条目，避免内存泄漏。
    """
    global _trajectory_counter

    if not SESSION_FOLDER or _trajectories_lock is None:
        return

    async with _trajectories_lock:
        # 获取当前所有轨迹
        trajectories = dict(_trajectories)

    if not trajectories:
        return

    # 记录已保存的 state_key，用于后续清理
    saved_keys: list[str] = []

    # 为每个 session 生成一个独立的轨迹文件
    for state_key, trajectory in trajectories.items():
        session_id = str(trajectory.get("session_id") or state_key or "__no_session_id__")
        task_index = int(trajectory.get("task_index") or 1)

        # 从轨迹中获取 session_id / task_index
        session_dir = Path(SESSION_FOLDER) / _safe_filename(session_id)
        filepath = session_dir / f"task_{task_index}.json"
        filename = str(filepath)
        tmp = filepath.with_suffix(filepath.suffix + ".tmp")

        def _write() -> None:
            filepath.parent.mkdir(parents=True, exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(trajectory, f, ensure_ascii=False, indent=2)
            tmp.replace(filepath)

        await asyncio.to_thread(_write)
        print(f"[trace] 已保存轨迹到 {filename}, state_key={state_key}", file=sys.stderr, flush=True)
        saved_keys.append(state_key)

    # 清空轨迹（因为已经保存到文件）
    async with _trajectories_lock:
        _trajectories.clear()

    # ✅ 保留 _task_start_index 条目
    # 任务完成时已更新 start_index 为下一任务的起点，
    # 不能删除，否则下次会重新初始化并跳过用户消息


async def _trace_worker() -> None:
    assert _trace_queue is not None
    while True:
        try:
            await _trace_queue.get()
        except asyncio.CancelledError:
            break
        try:
            await _persist_session_json()
        finally:
            _trace_queue.task_done()


def _enqueue_persist() -> None:
    if _trace_queue is None:
        return
    try:
        _trace_queue.put_nowait(1)
    except asyncio.QueueFull:
        pass


def _assistant_message_from_response_summary(
    response_summary: dict[str, Any],
) -> dict[str, Any]:
    """从轨迹用的 response 摘要构造一条 assistant 消息（仅 content，与 OpenAI 兼容）。"""
    mode = str(response_summary.get("mode", ""))
    status = int(response_summary.get("http_status") or 0)
    if status >= 400 or "error" in mode:
        raw = response_summary.get("raw_body") or ""
        return {
            "role": "assistant",
            "content": _truncate(f"[upstream error {status}] {raw}", 20000),
        }
    text = (response_summary.get("assistant_visible_reply") or "").strip()
    if not text:
        text = (response_summary.get("assistant_content_full") or "").strip()
    if not text:
        text = (response_summary.get("text") or "").strip()
    msg: dict[str, Any] = {"role": "assistant", "content": text if text else None}
    tc = response_summary.get("assistant_tool_calls")
    if isinstance(tc, list) and tc:
        msg["tool_calls"] = tc
    return msg


def _extract_messages_for_task(
    all_messages: list[dict[str, Any]],
    start_index: int,
    response_summary: dict[str, Any]
) -> list[dict[str, Any]]:
    """
    从所有消息中提取当前任务的消息。

    策略：
    1. 如果 start_index > 0，先加上系统提示词（索引0）
    2. 从 start_index 开始提取消息
    3. 清理每条消息的 content（解析 OpenClaw 格式）
    4. 追加本轮 assistant 响应
    """
    messages = []

    # start_index > 0 时，补充系统提示词（索引0）
    if start_index > 0 and len(all_messages) > 0:
        first_msg = all_messages[0]
        if isinstance(first_msg, dict) and first_msg.get("role") == "system":
            messages.append(_clean_message_content(first_msg))

    # 提取 start_index 之后的消息
    task_messages = all_messages[start_index:]
    if start_index > 0:
        first_user_offset = next(
            (
                idx
                for idx, msg in enumerate(task_messages)
                if isinstance(msg, dict) and msg.get("role") == "user"
            ),
            None,
        )
        if first_user_offset is not None:
            task_messages = task_messages[first_user_offset:]

    for msg in task_messages:
        if isinstance(msg, dict):
            cleaned = _clean_message_content(msg)
            if cleaned.get("role") == "user" and not str(cleaned.get("content") or "").strip():
                continue
            messages.append(cleaned)

    # 追加本轮 assistant 响应
    assistant_msg = _assistant_message_from_response_summary(response_summary)
    messages.append(assistant_msg)

    return messages


def _request_trace_with_merged_assistant(
    request_summary: dict[str, Any],
    response_summary: dict[str, Any],
) -> dict[str, Any]:
    """在 request 轨迹副本的 messages 末尾追加本轮 assistant 回复，不再单独存 response。"""
    out = copy.deepcopy(request_summary)
    msgs = out.get("messages")
    if not isinstance(msgs, list):
        msgs = []
        out["messages"] = msgs
    msgs.append(_assistant_message_from_response_summary(response_summary))
    return out


def _strip_ids_from_tool_calls(messages: list[Any]) -> list[Any]:
    """轨迹落盘前移除每条 message.tool_calls[*].id。"""
    out: list[Any] = []
    for m in messages:
        if not isinstance(m, dict):
            out.append(m)
            continue
        md = copy.deepcopy(m)
        tc = md.get("tool_calls")
        if isinstance(tc, list):
            for call in tc:
                if isinstance(call, dict) and "id" in call:
                    del call["id"]
        out.append(md)
    return out


async def _overwrite_session_trace(
    session_id: str,
    request_summary: dict[str, Any],
    response_summary: dict[str, Any],
) -> None:
    """同一 x-session-id 只保留最新一轮；落盘仅含 session_id、messages、tools。"""
    if not SESSION_FOLDER or _trajectories_lock is None:
        return
    merged = _request_trace_with_merged_assistant(request_summary, response_summary)
    raw_msgs = merged.get("messages")
    if not isinstance(raw_msgs, list):
        raw_msgs = []
    msgs = _strip_ids_from_tool_calls(raw_msgs)
    tools = merged.get("tools")
    if tools is not None and not isinstance(tools, list):
        tools = None
    async with _trajectories_lock:
        _trajectories[session_id] = {
            "session_id": session_id,
            "messages": msgs,
            "tools": tools,
        }
    _enqueue_persist()


async def _notify_gateway_task_done(
    session_id: str,
    gateway_url: Optional[str] = None,
    gateway_token: Optional[str] = None,
    instance_id: Optional[str] = None,
    max_retries: int = 3,
    base_delay: float = 1.0,
) -> None:
    """
    任务完成时，发送 /clear-memory 请求到对应实例的 Gateway。

    Args:
        session_id: 会话 ID
        gateway_url: Gateway URL resolved from the instance registry or request headers
        gateway_token: Gateway token resolved from the instance registry
        instance_id: OpenClaw instance ID
        max_retries: 最大重试次数
        base_delay: 基础延迟（秒），用于指数退避
    """
    t0 = time.perf_counter()
    print(f"[clear-memory][{session_id}] 检测到任务完成，instance_id={instance_id}", file=sys.stderr, flush=True)

    # 如果没有 URL，无法发送通知
    if not gateway_url:
        elapsed = (time.perf_counter() - t0) * 1000
        print(f"[clear-memory][{session_id}] 无 Gateway URL，跳过通知, elapsed={elapsed:.2f}ms", file=sys.stderr, flush=True)
        return

    token = str(gateway_token).strip() if gateway_token else ""
    t1 = time.perf_counter()
    print(f"[clear-memory][{session_id}] resolved instance={instance_id}, token={token[:10] + '...' if token else 'None'}, 耗时={(t1-t0)*1000:.2f}ms", file=sys.stderr, flush=True)

    if not token:
        elapsed = (time.perf_counter() - t0) * 1000
        print(f"[clear-memory][{session_id}] ❌ instance {instance_id} 未注册 Token，跳过通知, elapsed={elapsed:.2f}ms", file=sys.stderr, flush=True)
        print(f"[clear-memory][{session_id}] 已注册实例列表: {list(_gateway_instances.keys())}", file=sys.stderr, flush=True)
        return

    url = gateway_url
    print(f"[clear-memory][{session_id}] 使用 URL: {url}, instance_id: {instance_id}", file=sys.stderr, flush=True)

    payload = {
        "model": "openclaw/default",
        "messages": [
            {"role": "user", "content": "/clear-memory"}
        ]
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }

    # 带指数退避的重试
    for attempt in range(max_retries + 1):
        try:
            session = await _ensure_session()
            # 计算延迟：指数退避 base_delay * (2 ** attempt)
            if attempt > 0:
                delay = base_delay * (2 ** (attempt - 1))
                print(f"[clear-memory][{session_id}] 等待 {delay:.1f}s 后重试...", file=sys.stderr, flush=True)
                await asyncio.sleep(delay)

            req_start = time.perf_counter()
            print(f"[clear-memory][{session_id}] 发送请求到 {url} (尝试 {attempt + 1}/{max_retries + 1})", file=sys.stderr, flush=True)

            async with session.post(
                url,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=36000.0),
            ) as resp:
                req_elapsed = (time.perf_counter() - req_start) * 1000
                response_text = await resp.text()
                print(f"[clear-memory][{session_id}] 响应状态: {resp.status}, 请求耗时={req_elapsed:.2f}ms", file=sys.stderr, flush=True)
                if resp.status >= 400:
                    print(f"[clear-memory][{session_id}] 请求失败: {response_text[:500]}", file=sys.stderr, flush=True)
                    if attempt < max_retries:
                        continue  # 继续重试
                    print(f"[clear-memory][{session_id}] 所有重试失败", file=sys.stderr, flush=True)
                else:
                    print(f"[clear-memory][{session_id}] 请求成功", file=sys.stderr, flush=True)
                total_elapsed = (time.perf_counter() - t0) * 1000
                print(f"[clear-memory][{session_id}] 总耗时={total_elapsed:.2f}ms", file=sys.stderr, flush=True)
                return

        except asyncio.TimeoutError:
            elapsed = (time.perf_counter() - t0) * 1000
            print(f"[clear-memory][{session_id}] 请求超时 (尝试 {attempt + 1}), 总耗时={elapsed:.2f}ms", file=sys.stderr, flush=True)
            if attempt >= max_retries:
                print(f"[clear-memory][{session_id}] 所有重试超时，放弃通知", file=sys.stderr, flush=True)
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            print(f"[clear-memory][{session_id}] 请求异常: {type(e).__name__}: {e} (尝试 {attempt + 1}), 总耗时={elapsed:.2f}ms", file=sys.stderr, flush=True)
            if attempt >= max_retries:
                print(f"[clear-memory][{session_id}] 所有重试失败，放弃通知", file=sys.stderr, flush=True)


async def _accumulate_session_trace(
    session_id: str,
    request_summary: dict[str, Any],
    response_summary: dict[str, Any],
    instance_id: Optional[str] = None,
    gateway_url: Optional[str] = None,
    gateway_token: Optional[str] = None,
) -> None:
    """
    Track task lifecycle using message index instead of accumulating turns.

    OpenClaw sends full session history with each request, so we:
    1. Track which message index the current task started at
    2. Extract only new messages since task start when task completes
    3. Update the start index after saving
    """
    t0 = time.perf_counter()
    print(f"[accumulate][{session_id}] === 开始处理, elapsed=0.000ms", file=sys.stderr, flush=True)

    # 使用组合键区分不同实例
    if not SESSION_FOLDER or _trajectories_lock is None:
        elapsed = (time.perf_counter() - t0) * 1000
        print(f"[accumulate][{session_id}] ❌ 提前返回！SESSION_FOLDER 或 _trajectories_lock 为空, elapsed={elapsed:.2f}ms", file=sys.stderr, flush=True)
        return

    # ✅ 检测是否是 /clear-memory 内部轮次（整轮跳过）
    req_messages = request_summary.get("messages", [])
    state_key = _make_state_key(instance_id, session_id)
    print(f"[accumulate][{session_id}] state_key={state_key}, elapsed={(time.perf_counter()-t0)*1000:.2f}ms", file=sys.stderr, flush=True)
    t2 = time.perf_counter()
    if isinstance(req_messages, list):
        for msg in reversed(req_messages):
            if isinstance(msg, dict) and msg.get("role") == "user":
                content = _extract_text_from_content(msg.get("content"))
                if content.strip() == "/clear-memory":
                    elapsed = (time.perf_counter() - t0) * 1000
                    print(f"[accumulate][{session_id}] 检测到 /clear-memory 轮次，整轮跳过, elapsed={elapsed:.2f}ms", file=sys.stderr, flush=True)
                    return
                break
    print(f"[accumulate][{session_id}] /clear-memory 检查完成, elapsed={(time.perf_counter()-t2)*1000:.2f}ms", file=sys.stderr, flush=True)

    tools = request_summary.get("tools")
    if tools is not None and not isinstance(tools, list):
        tools = None

    # ✅ 初始化或获取任务起始索引
    if state_key not in _task_start_index:
        # 新会话：没有旧消息需要跳过，从 0 开始
        # （同会话的后续任务：key 已存在，使用任务完成时更新的值）
        _task_start_index[state_key] = 0
        _task_file_index[state_key] = 1
        print(f"[accumulate][{session_id}] 新会话，起始索引: 0", file=sys.stderr, flush=True)

    start_index = _task_start_index[state_key]
    task_index = _task_file_index.get(state_key, 1)
    print(f"[accumulate][{session_id}] 当前任务起始索引: {start_index}, 请求消息总数: {len(req_messages) if isinstance(req_messages, list) else 0}", file=sys.stderr, flush=True)

    # ✅ 提取当前任务的消息（从 start_index 开始）+ 本轮 assistant 响应
    t3 = time.perf_counter()
    messages = _extract_messages_for_task(req_messages, start_index, response_summary)
    print(f"[accumulate][{session_id}] 提取的消息数量: {len(messages)}, 耗时={(time.perf_counter()-t3)*1000:.2f}ms", file=sys.stderr, flush=True)

    # ✅ finish_reason=tool_calls 表示模型还在调用工具，跳过
    # finish_reason=None 表示未获取到，也跳过（可能流未正常结束）
    # finish_reason=stop 或 length 继续检测
    finish_reason = (response_summary or {}).get("finish_reason")
    print(f"[accumulate][{session_id}] finish_reason={finish_reason}", file=sys.stderr, flush=True)

    if finish_reason == "tool_calls":
        elapsed = (time.perf_counter() - t0) * 1000
        print(f"[accumulate][{session_id}] 模型还在调用工具，跳过任务完成检测, elapsed={elapsed:.2f}ms", file=sys.stderr, flush=True)
        return

    if finish_reason is None:
        print(f"[accumulate][{session_id}] ⚠️ finish_reason=None（可能是提取失败），继续检测", file=sys.stderr, flush=True)

    # Always persist the latest user-visible turn snapshot. Task completion only
    # controls task-boundary advancement and OpenClaw cleanup notification.
    t_snapshot = time.perf_counter()
    async with _trajectories_lock:
        _trajectories[state_key] = {
            "session_id": session_id,
            "instance_id": instance_id,
            "task_index": task_index,
            "messages": messages,
            "tools": tools,
        }
        _enqueue_persist()
    snapshot_elapsed = (time.perf_counter() - t_snapshot) * 1000
    print(f"[accumulate][{session_id}] 已保存当前轨迹快照 task_{task_index}.json，保存耗时={snapshot_elapsed:.2f}ms", file=sys.stderr, flush=True)

    # ✅ 检测任务完成（TodoWrite 检查 + LLM 判断）
    t4 = time.perf_counter()
    task_completed, reason = _detect_task_completion(messages, response_summary)
    detect_elapsed = (time.perf_counter() - t4) * 1000
    print(f"[accumulate][{session_id}] 任务完成检测结果: {task_completed}, 原因: {reason}, 检测耗时={detect_elapsed:.2f}ms", file=sys.stderr, flush=True)

    if task_completed is None:
        # 不确定，调用 LLM 兜底（glm 模型只取 content，不看 reasoning_content）
        print(f"[accumulate][{session_id}] 无关键词匹配，调用 LLM 判断", file=sys.stderr, flush=True)
        t5 = time.perf_counter()
        task_completed = await _llm_judge_completion(messages, response_summary)
        llm_elapsed = (time.perf_counter() - t5) * 1000
        print(f"[accumulate][{session_id}] LLM 判定结果: {task_completed}, LLM 耗时={llm_elapsed:.2f}ms", file=sys.stderr, flush=True)

    if task_completed:
        # ✅ 任务完成，更新任务边界
        t6 = time.perf_counter()
        async with _trajectories_lock:
            # ✅ 更新任务起始索引
            # req_messages 是请求带来的消息，本轮还追加了1条 assistant 响应
            # 下一个任务应从 assistant 响应之后开始，所以 +1
            # The next OpenClaw request history starts the next task at the
            # current request length. Adding one skips that first new user turn.
            new_start = len(req_messages) if isinstance(req_messages, list) else 1
            _task_start_index[state_key] = new_start
            _task_file_index[state_key] = task_index + 1
        save_elapsed = (time.perf_counter() - t6) * 1000
        print(f"[accumulate][{session_id}] 任务完成，更新起始索引到: {new_start}, 下一轨迹=task_{task_index + 1}.json, 耗时={save_elapsed:.2f}ms", file=sys.stderr, flush=True)

        # 发送通知
        print(f"[accumulate][{session_id}] 准备调用 _notify_gateway_task_done, gateway_url={gateway_url}, instance_id={instance_id}", file=sys.stderr, flush=True)
        t7 = time.perf_counter()
        await _notify_gateway_task_done(session_id, gateway_url, gateway_token, instance_id)
        notify_elapsed = (time.perf_counter() - t7) * 1000
        total_elapsed = (time.perf_counter() - t0) * 1000
        print(f"[accumulate][{session_id}] _notify_gateway_task_done 完成, 通知耗时={notify_elapsed:.2f}ms, 总耗时={total_elapsed:.2f}ms", file=sys.stderr, flush=True)
    else:
        elapsed = (time.perf_counter() - t0) * 1000
        print(f"[accumulate][{session_id}] 任务未完成，整轮结束, 总耗时={elapsed:.2f}ms", file=sys.stderr, flush=True)


# ================================================================================
# FastAPI应用
# =============================================================================

app = FastAPI(title="OpenAI-Compatible Proxy")


# ================================================================================
# 应用生命周期管理
# =============================================================================


@app.on_event("startup")
async def _startup() -> None:
    """
    应用启动时执行

    【功能】
    创建全局HTTP会话

    【会话配置】
    - total: 无超时限制（用于流式响应）
    - connect: 连接建立超时
    - sock_connect: socket连接超时
    - sock_read: socket读取超时（无限制）
    """
    global _session, _trajectories_lock, _trace_queue, _trace_worker_task

    _load_gateway_instances()

    # 创建超时配置
    timeout = aiohttp.ClientTimeout(
        total=None,  # 总体超时无限制
        connect=CONNECT_TIMEOUT_S,  # 连接超时
        sock_connect=CONNECT_TIMEOUT_S,  # socket连接超时
        sock_read=36000,  # socket 读取超时 36000 秒（防无限等待）
    )

    # 创建会话
    _session = aiohttp.ClientSession(timeout=timeout)
    _trajectories_lock = asyncio.Lock()
    if SESSION_FOLDER:
        # 初始化轨迹计数器：统计现有 json 文件数量
        global _trajectory_counter
        session_path = Path(SESSION_FOLDER)
        if session_path.exists():
            existing_files = list(session_path.glob("*.json"))
            _trajectory_counter = len(existing_files)
            print(f"[trace] 发现现有轨迹文件 {_trajectory_counter} 个", file=sys.stderr, flush=True)
        else:
            session_path.mkdir(parents=True, exist_ok=True)
            _trajectory_counter = 0

        _trace_queue = asyncio.Queue(maxsize=512)
        _trace_worker_task = asyncio.create_task(_trace_worker())

    _debug_print(
        f"startup: VLLM_BASE_URL={VLLM_BASE_URL.rstrip('/')} PROXY_PORT={PROXY_PORT} "
        f"CONNECT_TIMEOUT_S={CONNECT_TIMEOUT_S} STREAM_CHUNK_SIZE={STREAM_CHUNK_SIZE}"
    )
    print(
        f"[startup] openclaw proxy is listening on http://0.0.0.0:{PROXY_PORT} "
        f"(health: http://<proxy-host>:{PROXY_PORT}/health, upstream: {VLLM_BASE_URL.rstrip('/')})",
        file=sys.stderr,
        flush=True,
    )
    if TRACE_CONTENT:
        print(
            f"[trace] OPENAI_PROXY_TRACE=1 将打印 chat/completions 的请求/响应摘要到 stderr",
            file=sys.stderr,
            flush=True,
        )
    if SESSION_FOLDER:
        print(
            f"[trace] OPENAI_PROXY_SESSION_FOLDER={SESSION_FOLDER} 轨迹存储到独立文件",
            file=sys.stderr,
            flush=True,
        )

    # [DISABLED] 实例注册表后台 Worker（暂时禁用，从未在通知流程中使用）
    # TODO: 如果后续需要按 instance_id 配对 Token，重新启用
    # registry = get_registry()
    # await registry.start()


@app.on_event("shutdown")
async def _shutdown() -> None:
    """
    应用关闭时执行

    【功能】
    关闭全局HTTP会话，释放资源
    """
    global _session, _trace_worker_task

    if _trace_worker_task is not None:
        _trace_worker_task.cancel()
        try:
            await _trace_worker_task
        except asyncio.CancelledError:
            pass
        _trace_worker_task = None
        await _persist_session_json()

    # [DISABLED] 实例注册表后台 Worker（暂时禁用）
    # registry = get_registry()
    # await registry.stop()

    if _session is not None:
        await _session.close()
        _session = None


# ================================================================================
# 工具函数
# ==============================================================================

def _clean_message_content(msg: dict) -> dict:
    if not isinstance(msg, dict):
        return msg

    new_msg = dict(msg)

    if msg.get("role") in {"user", "assistant"}:
        cleaned = _extract_text_from_content(msg.get("content"))
        new_msg["content"] = cleaned

    return new_msg

def _filtered_upstream_headers(
    headers: aiohttp.typedefs.LooseHeaders,
) -> dict[str, str]:
    """
    过滤上游响应头

    【功能】
    移除不应该转发给客户端的响应头

    【需要移除的header】
    - content-length: 内容长度（可能因代理修改而变化）
    - transfer-encoding: 传输编码（如chunked）
    - connection: 连接管理
    - keep-alive: 长连接

    【参数】
    - headers: 原始响应头

    【返回值】
    - dict: 过滤后的响应头
    """
    out: dict[str, str] = {}
    for k, v in dict(headers).items():
        # 转为小写比较
        lk = k.lower()
        if lk in {"content-length", "transfer-encoding", "connection", "keep-alive"}:
            continue
        out[k] = str(v)
    return out


def _filtered_downstream_headers(headers: dict[str, str]) -> dict[str, str]:
    """
    过滤下游请求头

    【功能】
    移除不应该转发给上游的请求头

    【需要移除的header】
    - host: 会替换为上游地址
    - content-length: 可能需要重新计算
    - transfer-encoding: 传输编码
    - connection: 连接管理

    【参数】
    - headers: 原始请求头

    【返回值】
    - dict: 过滤后的请求头
    """
    out: dict[str, str] = {}
    for k, v in headers.items():
        lk = k.lower()
        if lk in {"host", "content-length", "transfer-encoding", "connection"}:
            continue
        out[k] = str(v)
    return out


def _is_stream_request(request: Request, body: bytes) -> bool:
    """
    判断是否为流式请求

    【判断逻辑】
    1. 检查Accept header是否包含text/event-stream
    2. 如果Content-Type是application/json，检查body中stream字段

    【参数】
    - request: FastAPI请求对象
    - body: 请求体字节

    【返回值】
    - bool: 是否为流式请求
    """
    # 方式1: 检查Accept header
    if request.headers.get("accept", "").lower().startswith("text/event-stream"):
        return True

    # 方式2: 检查Content-Type
    ctype = request.headers.get("content-type", "")
    if "application/json" not in ctype.lower():
        return False

    # 解析JSON body
    try:
        obj = json.loads(body.decode("utf-8"))
    except Exception:
        return False

    # 检查stream字段
    return bool(obj.get("stream", False))


async def _ensure_session() -> aiohttp.ClientSession:
    """
    确保会话已创建

    【返回值】
    - aiohttp.ClientSession: HTTP会话

    【异常】
    - RuntimeError: 会话未创建且无法创建
    """
    global _session
    if _session is None:
        # 尝试启动
        await _startup()
        if _session is None:
            raise RuntimeError("aiohttp session not initialized")
    return _session


# ================================================================================
# 代理路由
# =============================================================================


@app.api_route(
    "/v1/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
)
async def proxy_v1(path: str, request: Request) -> Response:
    """
    OpenAI兼容API代理

    【路由】
    /v1/*  -> 转发到 vLLM /v1/*

    【支持的方法】
    GET, POST, PUT, PATCH, DELETE, OPTIONS

    【处理流程】
    1. 获取/创建HTTP会话
    2. 构造上游URL
    3. 过滤请求头
    4. 判断是否流式请求
    5. 转发请求
    6. 处理响应

    【参数】
    - path: URL路径（不含/v1/前缀）
    - request: FastAPI请求对象

    【返回值】
    - Response: 代理响应
    """
    # 确保会话已创建
    session = await _ensure_session()

    # 构造上游URL
    # urljoin自动处理路径拼接
    upstream_url = urljoin(VLLM_BASE_URL, f"v1/{path}")

    # 获取查询参数
    params = list(request.query_params.multi_items())

    # 获取请求体
    body = await request.body()

    # 过滤请求头
    headers = _filtered_downstream_headers(dict(request.headers))
    headers["accept"] = "text/event-stream"

    trace_chat = path.rstrip("/").endswith("chat/completions")
    session_id = _get_x_session_id(request)
    instance_id = _get_x_instance_id(request)
    gateway_url = _get_x_gateway_url(request)
    gateway_url, gateway_token, resolved_instance_id = _resolve_gateway_for_request(
        instance_id,
        gateway_url,
    )

    # 调试：打印提取到的请求头
    print(f"[debug] 提取请求头: session_id={session_id}, instance_id={instance_id}, gateway_url={gateway_url}", file=sys.stderr, flush=True)
    print(f"[debug] resolved gateway: instance_id={resolved_instance_id}, gateway_url={gateway_url}, has_token={bool(gateway_token)}", file=sys.stderr, flush=True)

    state_key = _make_state_key(resolved_instance_id or instance_id, session_id)
    is_clear_memory_request = _is_clear_memory_request_body(body)
    if trace_chat and is_clear_memory_request:
        print(f"[clear-memory][{session_id}] internal /clear-memory request detected; forwarding upstream without session-start trigger", file=sys.stderr, flush=True)

    has_real_session_id = session_id and session_id != "__no_x_session_id__"
    if (
        trace_chat
        and has_real_session_id
        and not is_clear_memory_request
        and state_key not in _new_session_clear_memory_sent
    ):
        _new_session_clear_memory_sent.add(state_key)
        print(f"[session-start][{session_id}] 新 session，触发 /clear-memory, state_key={state_key}", file=sys.stderr, flush=True)
        asyncio.create_task(
            _notify_gateway_task_done(
                session_id,
                gateway_url,
                gateway_token,
                resolved_instance_id or instance_id,
                max_retries=1,
            )
        )
    request_trace: Optional[dict[str, Any]] = None
    if trace_chat and (TRACE_CONTENT or SESSION_FOLDER):
        request_trace = _build_chat_request_trace(body)
        if TRACE_CONTENT:
            _trace_log(
                "downstream_request",
                {"x_session_id": session_id, "path": f"/v1/{path}", **request_trace},
            )

    if DEBUG_PROXY:
        raw_headers = dict(request.headers)
        auth_present = "authorization" in {k.lower() for k in raw_headers.keys()}
        auth_value = ""
        for k, v in raw_headers.items():
            if k.lower() == "authorization":
                auth_value = str(v)
                break
        body_obj = _try_parse_json(body)
        body_keys = (
            sorted(list(body_obj.keys())) if isinstance(body_obj, dict) else None
        )
        model = body_obj.get("model") if isinstance(body_obj, dict) else None
        stream = body_obj.get("stream") if isinstance(body_obj, dict) else None
        _debug_print(
            "downstream request: "
            f"method={request.method} path=/v1/{path} upstream_url={upstream_url} "
            f"query_items={len(params)} content_type={request.headers.get('content-type', '')} "
            f"accept={request.headers.get('accept', '')} "
            f"auth_present={auth_present} auth={_redact_secret(auth_value)} "
            f"body_len={len(body)} json_keys={body_keys} model={model} stream={stream}"
        )
        _debug_print(
            f"downstream headers (filtered->upstream): {json.dumps(_summarize_headers(headers), ensure_ascii=False)}"
        )

    # 判断是否为流式请求
    if _is_stream_request(request, body):
        # -------------------- 流式响应 --------------------

        # ✅ 1. 正确解析 JSON body（关键修复）
        body_obj = None
        try:
            body_obj = json.loads(body.decode("utf-8")) if body else None
        except Exception:
            pass

        # ✅ 2. 强制 streaming 相关 header
        body_obj, headers = _apply_upstream_request_config(
            body_obj,
            headers,
            model=VLLM_MODEL_NAME,
            api_key=VLLM_API_KEY,
        )
        headers["accept"] = "text/event-stream"
        headers["cache-control"] = "no-cache"

        # 捕获 gen() 需要的变量（避免闭包问题）
        _upstream_url = upstream_url
        _params = params
        _body_obj = body_obj
        _headers = headers
        _session_ref = session

        async def gen():
            acc = bytearray()
            first_chunk = True
            t0 = time.perf_counter()
            upstream_resp = None

            try:
                print(f"[gen][{session_id}] 发送上游请求...", file=sys.stderr, flush=True)

                # 在 gen() 内部发送请求，用 async with 正确管理响应生命周期
                async with _session_ref.request(
                    request.method,
                    _upstream_url,
                    params=_params,
                    json=_body_obj,
                    headers=_headers,
                ) as upstream_resp:

                    print(f"[gen][{session_id}] 上游响应: status={upstream_resp.status}, "
                          f"CT={upstream_resp.headers.get('content-type')}, "
                          f"content-length={upstream_resp.headers.get('content-length')}, "
                          f"transfer-encoding={upstream_resp.headers.get('transfer-encoding')}, "
                          f"connection={upstream_resp.headers.get('connection')}", file=sys.stderr, flush=True)

                    if upstream_resp.status >= 400:
                        # 上游返回错误，读取完整响应
                        data = await upstream_resp.read()
                        text = data.decode("utf-8", errors="replace")
                        print(f"[gen][{session_id}] ⚠️ 上游错误: status={upstream_resp.status}, body={text[:500]}", file=sys.stderr, flush=True)
                        yield data
                        return

                    print(f"[gen][{session_id}] 开始读取流", file=sys.stderr, flush=True)

                    async for chunk in upstream_resp.content.iter_any():
                        if chunk:
                            if first_chunk:
                                ttfb = (time.perf_counter() - t0) * 1000
                                print(f"[gen][{session_id}] 收到首个 chunk，长度={len(chunk)}，TTFB={ttfb:.2f}ms", file=sys.stderr, flush=True)
                                first_chunk = False

                            acc.extend(chunk)
                            yield chunk
                        else:
                            # 收到空 chunk，记录但继续
                            wait_elapsed = (time.perf_counter() - t0) * 1000
                            print(f"[gen][{session_id}] ⚠️ 收到空 chunk，已等待={wait_elapsed:.0f}ms, acc长度={len(acc)}", file=sys.stderr, flush=True)

                    stream_done = time.perf_counter()
                    stream_elapsed = (stream_done - t0) * 1000
                    print(f"[gen][{session_id}] 流读取完成，acc 长度: {len(acc)}，流耗时={stream_elapsed:.2f}ms", file=sys.stderr, flush=True)

            except aiohttp.client_exceptions.ClientPayloadError as e:
                total = (time.perf_counter() - t0) * 1000
                # ⚠️ vLLM 发送了不完整的 chunked 响应（如提前关闭连接），
                # aiohttp 无法完成解析。已有数据在 acc 中，视为流正常结束。
                print(f"[gen][{session_id}] ⚠️ vLLM 流异常终止(ClientPayloadError)，"
                      f"已收到 {len(acc)} bytes，total={total:.2f}ms", file=sys.stderr, flush=True)

            except Exception as e:
                total = (time.perf_counter() - t0) * 1000
                print(f"[gen][{session_id}] 流读取异常: {type(e).__name__}: {e}，total={total:.2f}ms", file=sys.stderr, flush=True)
                raise

            finally:
                print(f"[gen][{session_id}] 流结束，进入 finally, acc长度={len(acc)}", file=sys.stderr, flush=True)

                raw = bytes(acc)

                # ✅ 补 DONE（防前端卡）
                if b"[DONE]" not in raw:
                    yield b"data: [DONE]\n\n"

                # ✅ 核心：解析 SSE + 触发轨迹
                if trace_chat and (TRACE_CONTENT or SESSION_FOLDER):
                    # ⚠️ 修复：raw 为空时直接跳过，避免触发"0 个事件"警告
                    # 触发场景：HTTP 错误路径、vLLM 超时/无响应、ClientPayloadError 后 acc 仍为空
                    if len(raw) == 0:
                        print(f"[gen][{session_id}] ⚠️ raw 为空（上游无数据），跳过 SSE 解析", file=sys.stderr, flush=True)
                        # 仍然触发轨迹，但用空摘要
                        _http_status = upstream_resp.status if upstream_resp is not None else 0
                        resp_summary: dict[str, Any] = {
                            "mode": "stream_empty",
                            "http_status": _http_status,
                            "sse_events_count": 0,
                            "assistant_content_full": "",
                            "assistant_reasoning_field": None,
                            "assistant_think_prefix": None,
                            "assistant_visible_reply": "",
                            "finish_reason": None,
                        }
                    else:
                        t_parse = time.perf_counter()
                        events, sse_summary = _parse_sse_events(raw)
                        parse_elapsed = (time.perf_counter() - t_parse) * 1000

                        print(f"[gen][{session_id}] SSE 解析完成，事件数: {len(events)}，解析耗时={parse_elapsed:.2f}ms", file=sys.stderr, flush=True)
                        if len(events) == 0:
                            print(f"[gen][{session_id}] ⚠️ 0 个事件！raw 长度: {len(raw)}, 前500字节: {raw[:500]}", file=sys.stderr, flush=True)
                            print(f"[gen][{session_id}] sse_summary: {sse_summary}", file=sys.stderr, flush=True)

                        _http_status = 200
                        if upstream_resp is not None:
                            try:
                                _http_status = upstream_resp.status
                            except Exception:
                                pass

                        resp_summary = {
                            "mode": "stream",
                            "http_status": _http_status,
                            "sse_events_count": len(events),
                            **sse_summary,
                        }

                    if TRACE_CONTENT:
                        _trace_log(
                            "upstream_response_sse",
                            {"x_session_id": session_id, **resp_summary},
                        )

                    if SESSION_FOLDER and request_trace is not None:
                        t_acc = time.perf_counter()
                        print(f"[gen][{session_id}] 创建 accumulate 任务", file=sys.stderr, flush=True)

                        asyncio.create_task(
                            _accumulate_session_trace(
                                session_id,
                                request_trace,
                                resp_summary,
                                instance_id,
                                gateway_url,
                                gateway_token,
                            )
                        )
                        acc_created = (time.perf_counter() - t_acc) * 1000
                        total = (time.perf_counter() - t0) * 1000
                        print(f"[gen][{session_id}] accumulate 任务已创建，任务耗时={acc_created:.2f}ms，gen 总耗时={total:.2f}ms", file=sys.stderr, flush=True)

                total = (time.perf_counter() - t0) * 1000
                print(f"[gen][{session_id}] gen() 退出，total={total:.2f}ms", file=sys.stderr, flush=True)
        return StreamingResponse(
            gen(),
            status_code=200,
            media_type="text/event-stream",
        )

    else:
        # -------------------- 非流式响应 --------------------
        # 使用async with确保响应被正确关闭
        body_obj = None
        try:
            body_obj = json.loads(body.decode("utf-8")) if body else None
        except Exception:
            pass

        body_obj, headers = _apply_upstream_request_config(
            body_obj,
            headers,
            model=VLLM_MODEL_NAME,
            api_key=VLLM_API_KEY,
        )

        async with session.request(
            request.method,
            upstream_url,
            params=params,
            json=body_obj,   # ✅ 关键修复：用 json= 替代 data=
            headers=headers,
        ) as upstream_resp:

            # 读取响应内容
            data = await upstream_resp.read()

            preview = ""
            try:
                preview = data.decode("utf-8", errors="replace")
            except Exception:
                preview = repr(data[:200])
            preview_dbg = preview[:2000] + "…" if len(preview) > 2000 else preview

            if DEBUG_PROXY and upstream_resp.status >= 400:
                ct = upstream_resp.headers.get("content-type", "")
                _debug_print(
                    f"upstream response: status={upstream_resp.status} content_type={ct} "
                    f"body_preview={preview_dbg}"
                )

            if trace_chat and (TRACE_CONTENT or SESSION_FOLDER):
                if upstream_resp.status >= 400:
                    err_summary = {
                        "mode": "non_stream_error",
                        "http_status": upstream_resp.status,
                        "raw_body": _truncate(preview, 8000),
                    }
                    if TRACE_CONTENT:
                        _trace_log(
                            "upstream_response_error",
                            {"x_session_id": session_id, **err_summary},
                        )
                    if SESSION_FOLDER and request_trace is not None:
                        asyncio.create_task(
                            _accumulate_session_trace(
                                session_id,
                                request_trace,
                                err_summary,
                                instance_id,
                                gateway_url,
                                gateway_token,
                            )
                        )
                else:
                    resp_summary: dict[str, Any] = {
                        "mode": "non_stream",
                        "http_status": upstream_resp.status,
                        **_summarize_upstream_json_response(data),
                    }
                    if TRACE_CONTENT:
                        _trace_log(
                            "upstream_response_json",
                            {"x_session_id": session_id, **resp_summary},
                        )
                    if SESSION_FOLDER and request_trace is not None:
                        asyncio.create_task(
                            _accumulate_session_trace(
                                session_id,
                                request_trace,
                                resp_summary,
                                instance_id,
                                gateway_url,
                                gateway_token,
                            )
                        )

            # 获取响应头
            media_type = upstream_resp.headers.get("content-type", "application/json")
            resp_headers = _filtered_upstream_headers(upstream_resp.headers)

            # 返回响应
            return Response(
                content=data,
                status_code=upstream_resp.status,
                headers=resp_headers,
                media_type=media_type,
            )


# ================================================================================
# 实例注册接口
# ================================================================================


# [DISABLED] 实例注册接口（暂时禁用，从未在通知流程中使用）
# @app.post("/register-instance")
# async def register_instance(request: Request) -> dict[str, Any]:
#     """
#     注册 OpenClaw 实例的 Gateway URL 和 Token。
#
#     OpenClaw 可以通过此接口注册自己的 Gateway URL 和 Token，
#     用于后续的任务完成通知。
#
#     请求体格式：
#     {
#         "instance_id": "alpha",
#         "gateway_url": "http://YOUR_GATEWAY_HOST:PORT/v1/chat/completions",
#         "gateway_token": "your_token_here"
#     }
#
#     返回：
#     {
#         "success": true,
#         "message": "Instance registered successfully"
#     }
#     """
#     try:
#         body = await request.body()
#         data = json.loads(body.decode("utf-8"))
#     except Exception as e:
#         return {"success": False, "message": f"Invalid JSON: {e}"}
#
#     instance_id = data.get("instance_id")
#     gateway_url = data.get("gateway_url")
#     gateway_token = data.get("gateway_token")
#
#     if not instance_id:
#         return {"success": False, "message": "Missing instance_id"}
#
#     if not gateway_url:
#         return {"success": False, "message": "Missing gateway_url"}
#
#     if not gateway_token:
#         return {"success": False, "message": "Missing gateway_token"}
#
#     registry = get_registry()
#     success = await registry.register(instance_id, gateway_url, gateway_token)
#
#     if success:
#         return {"success": True, "message": "Instance registered successfully"}
#     else:
#         return {"success": False, "message": "Registration failed"}
#
#
# @app.get("/instances")
# async def list_instances() -> dict[str, Any]:
#     """
#     列出所有已注册的实例。
#
#     返回：
#     {
#         "instances": ["alpha", "beta"],
#         "count": 2
#     }
#     """
#     registry = get_registry()
#     instances = registry.list_instances()
#     return {"instances": instances, "count": len(instances)}


@app.post("/register-instance")
async def register_instance(request: Request) -> dict[str, Any]:
    """Register one OpenClaw instance gateway URL and token."""
    print("[register-instance] Received registration request", file=sys.stderr, flush=True)
    try:
        body = await request.body()
        data = json.loads(body.decode("utf-8"))
    except Exception as e:
        return {"success": False, "message": f"Invalid JSON: {e}"}

    instance_id = data.get("instance_id")
    gateway_url = data.get("gateway_url")
    gateway_token = data.get("gateway_token") or data.get("token")
    gateway_port = data.get("gateway_port") or data.get("port")

    if not instance_id:
        return {"success": False, "message": "Missing instance_id"}
    if not gateway_url:
        return {"success": False, "message": "Missing gateway_url"}
    if not gateway_token:
        return {"success": False, "message": "Missing gateway_token"}

    success = _register_gateway_instance(instance_id, gateway_url, gateway_token, gateway_port)
    if success:
        return {"success": True, "message": "Instance registered successfully"}
    return {"success": False, "message": "Registration failed"}


@app.get("/instances")
async def list_instances() -> dict[str, Any]:
    """List registered OpenClaw instances with redacted tokens."""
    instances = []
    for instance_id, entry in sorted(_gateway_instances.items()):
        token = entry.get("gateway_token", "")
        instances.append(
            {
                "instance_id": instance_id,
                "gateway_url": entry.get("gateway_url"),
                "gateway_port": entry.get("gateway_port"),
                "gateway_token": _redact_secret(token),
            }
        )
    return {"instances": instances, "count": len(instances)}


# ================================================================================
# 健康检查端点
# =============================================================================


@app.get("/health")
async def health() -> dict[str, str]:
    """
    健康检查

    【返回值】
    - ok: 状态标识
    - vllm_base_url: vLLM后端地址
    """
    return {"ok": "true", "vllm_base_url": VLLM_BASE_URL.rstrip("/")}


# ================================================================================
# 主入口
# =============================================================================


def main() -> None:
    """
    主函数

    【功能】
    启动FastAPI服务器
    """
    uvicorn.run(
        app,
        host="0.0.0.0",  # 监听所有网卡
        port=PROXY_PORT,  # 监听端口
        workers=1,  # 工作进程数
        log_level="info",  # 日志级别
    )


if __name__ == "__main__":
    main()
