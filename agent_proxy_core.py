#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
OpenAI 兼容代理服务 - 多后端版本
================================================================================

【设计目的】
本模块是一个代理服务，提供OpenAI兼容的API接口，支持多后端路由。
通过 model name 自动路由到对应的 LLM 后端。

【功能】
1. 兼容OpenAI API格式
2. 多后端路由（精确匹配 + 前缀回退）
3. 支持流式输出（Server-Sent Events）
4. 请求重试（指数退避）
5. 负载均衡（round_robin/random/least_connections）
6. 速率限制（并发数 + RPM）
7. 认证层（Bearer Token）
8. Prometheus 监控指标
9. 健康检查

【配置】
通过 config.yaml 配置多后端、认证、限流等参数。
环境变量 OPENAI_PROXY_CONFIG 可指定配置文件路径。

【示例】
```python
# 使用OpenAI SDK
from openai import OpenAI

client = OpenAI(
    base_url="<configured-profile-base-url>/v1",
    api_key="sk-admin-xxx"  # 认证启用时需要
)

# 路由到 qwen 后端
response = client.chat.completions.create(
    model="qwen",
    messages=[{"role": "user", "content": "Hello"}]
)

# 路由到 deepseek 后端
response = client.chat.completions.create(
    model="deepseek-chat",
    messages=[{"role": "user", "content": "Hello"}]
)
```
================================================================================
"""

# 导入标准库
import asyncio
import copy
import json
import os
import random
import re
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin

# 导入第三方库
import aiohttp
import yaml

# 导入FastAPI
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse
import uvicorn

# 尝试导入 prometheus_client
try:
    from prometheus_client import Counter, Gauge, Histogram, generate_latest
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False


# ================================================================================
# 数据类定义
# ================================================================================

class ConfigError(Exception):
    """Raised when proxy configuration is missing or unusable."""
    pass

@dataclass
class EndpointConfig:
    """端点配置"""
    url: str
    model: Optional[str] = None  # 该端点使用的模型名，None 表示使用请求中的原始模型名
    api_key: Optional[str] = None  # 该端点独立的 API Key，None 表示使用后端的 api_key
    openai_url: Optional[str] = None  # OpenAI 格式请求时使用的 URL，None 表示使用 url
    extra_headers: Optional[dict[str, str]] = None  # 额外请求头


@dataclass
class BackendConfig:
    """后端配置"""
    base_url: str
    api_key: Optional[str] = None
    timeout_s: float = 30.0
    max_retries: int = 3
    retry_delay_s: float = 1.0
    endpoints: list[Any] = field(default_factory=list)  # 支持字符串或 EndpointConfig
    load_balance: str = "round_robin"
    max_concurrent: int = 0
    requests_per_minute: int = 0
    extra_headers: Optional[dict[str, str]] = None  # 额外请求头（适用于该后端所有端点）

    def __post_init__(self):
        # If endpoints are omitted, use explicitly configured base_url as the only endpoint.
        if not self.endpoints and self.base_url:
            self.endpoints = [{"url": self.base_url.rstrip("/")}]


@dataclass
class AuthConfig:
    """认证配置"""
    enabled: bool = False
    keys: list[str] = field(default_factory=list)
    keys_file: Optional[str] = None


@dataclass
class MetricsConfig:
    """监控配置"""
    enabled: bool = True
    path: str = "/metrics"


@dataclass
class ProxyConfig:
    """代理配置"""
    port: int = 8188
    connect_timeout_s: float = 10.0
    stream_chunk_size: int = 8192
    debug: bool = False
    trace: bool = False
    session_json: Optional[str] = None
    usage_json: Optional[str] = None  # 用量统计持久化文件路径


@dataclass
class ProfileConfig:
    """Agent/profile listener configuration."""
    port: int
    protocol: str = "openai"
    backend: Optional[str] = None
    session_dir: Optional[str] = None
    usage_json: Optional[str] = None
    require_agent_header: bool = False
    route_by_model: bool = False


@dataclass
class Config:
    """完整配置"""
    backends: dict[str, BackendConfig]
    default_backend: str
    auth: AuthConfig
    metrics: MetricsConfig
    proxy: ProxyConfig
    profiles: dict[str, "ProfileConfig"] = field(default_factory=dict)


# ================================================================================
# 配置加载
# ================================================================================

_ENV_REF_RE = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")


def _load_dotenv_file(path: Path) -> None:
    """Load simple KEY=VALUE entries without overriding the process environment."""
    if not path.exists() or not path.is_file():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        print(f"[config-warning] could not read dotenv file {path}: {exc}", file=sys.stderr, flush=True)
        return

    loaded = 0
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            continue
        if key in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value
        loaded += 1
    if loaded:
        print(f"[config] loaded {loaded} value(s) from {path}", file=sys.stderr, flush=True)


def _load_dotenv_for_config(config_path: Path) -> None:
    """Load local dotenv values before expanding config placeholders."""
    candidates = [config_path.with_name(".env"), Path(__file__).with_name(".env")]
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        _load_dotenv_file(candidate)


def _expand_env_value(value: Any) -> Any:
    """Expand ${ENV_NAME} strings recursively in config values."""
    if isinstance(value, str):
        m = _ENV_REF_RE.match(value.strip())
        if m:
            name = m.group(1)
            if name not in os.environ:
                print(
                    f"[config-warning] environment variable {name} is not set; "
                    f"config placeholder ${{{name}}} expanded to an empty string",
                    file=sys.stderr,
                    flush=True,
                )
            return os.getenv(name, "")
        return value
    if isinstance(value, list):
        return [_expand_env_value(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand_env_value(v) for k, v in value.items()}
    return value


def _parse_endpoint(ep: Any) -> dict:
    ep = _expand_env_value(ep)
    """解析单个端点配置"""
    if isinstance(ep, str):
        return {"url": ep.rstrip("/"), "model": None, "api_key": None, "openai_url": None, "extra_headers": None}
    elif isinstance(ep, dict):
        return {
            "url": ep.get("url", "").rstrip("/"),
            "model": ep.get("model"),  # 可为 None
            "api_key": ep.get("api_key"),  # 端点独立的 API Key
            "openai_url": (ep.get("openai_url") or "").rstrip("/") or None,
            "extra_headers": ep.get("extra_headers"),  # 端点独立的额外请求头
        }
    else:
        return {"url": str(ep).rstrip("/"), "model": None, "api_key": None, "openai_url": None, "extra_headers": None}


def _parse_backend(name: str, data: dict) -> BackendConfig:
    data = _expand_env_value(data or {})
    """解析单个后端配置"""
    raw_endpoints = data.get("endpoints", [])
    parsed_endpoints = [_parse_endpoint(ep) for ep in raw_endpoints]

    return BackendConfig(
        base_url=str(data.get("base_url") or "").rstrip("/"),
        api_key=data.get("api_key"),
        timeout_s=float(data.get("timeout_s", 30)),
        max_retries=int(data.get("max_retries", 3)),
        retry_delay_s=float(data.get("retry_delay_s", 1.0)),
        endpoints=parsed_endpoints,
        load_balance=data.get("load_balance", "round_robin"),
        max_concurrent=int(data.get("max_concurrent", 0)),
        requests_per_minute=int(data.get("requests_per_minute", 0)),
        extra_headers=data.get("extra_headers"),
    )


def _parse_profile(name: str, data: dict, default_port: int, default_backend: str) -> ProfileConfig:
    """Parse one listener/profile configuration."""
    data = _expand_env_value(data or {})
    protocol = str(data.get("protocol", "openai")).lower().strip()
    if protocol not in {"openai", "anthropic"}:
        protocol = "openai"
    backend = data.get("backend", default_backend)
    if backend == "":
        backend = None
    return ProfileConfig(
        port=int(data.get("port", default_port)),
        protocol=protocol,
        backend=backend,
        session_dir=data.get("session_dir"),
        usage_json=data.get("usage_json"),
        require_agent_header=bool(data.get("require_agent_header", False)),
        route_by_model=bool(data.get("route_by_model", False)),
    )


REQUIRED_PROFILE_NAMES = ("opencode", "claude-code", "hermes")


def _warn_config(message: str) -> None:
    print(f"[config-warning] {message}", file=sys.stderr, flush=True)


def _redact_header_for_log(name: str, value: str) -> str:
    lowered = name.lower()
    if lowered in {"authorization", "x-api-key", "api-key"}:
        return _redact_secret(value)
    if "token" in lowered or "secret" in lowered or "key" in lowered:
        return _redact_secret(value)
    return value


def _validate_backend(name: str, backend: BackendConfig) -> list[str]:
    errors: list[str] = []
    if not backend.base_url and not backend.endpoints:
        errors.append("missing base_url/endpoints")
    if not backend.endpoints:
        errors.append("missing endpoints")
    for i, ep in enumerate(backend.endpoints):
        url = str(ep.get("url") or "").strip()
        if not url:
            errors.append(f"endpoint[{i}] missing url")
        elif not (url.startswith("http://") or url.startswith("https://")):
            errors.append(f"endpoint[{i}] has invalid url: {url}")
        openai_url = ep.get("openai_url")
        if openai_url and not (str(openai_url).startswith("http://") or str(openai_url).startswith("https://")):
            errors.append(f"endpoint[{i}] has invalid openai_url: {openai_url}")
    return errors


def _validate_and_filter_profiles(
    backends: dict[str, BackendConfig],
    profiles: dict[str, ProfileConfig],
) -> dict[str, ProfileConfig]:
    valid_profiles: dict[str, ProfileConfig] = {}

    if not profiles:
        raise ConfigError("config.yaml must define profiles for opencode, claude-code, and hermes")

    for required in REQUIRED_PROFILE_NAMES:
        if required not in profiles:
            _warn_config(f"profile '{required}' is missing and will not be served")

    for profile_name, profile in profiles.items():
        if profile.port <= 0 or profile.port > 65535:
            _warn_config(f"profile '{profile_name}' has invalid port {profile.port}; disabled")
            continue
        if profile.protocol not in {"openai", "anthropic"}:
            _warn_config(f"profile '{profile_name}' has invalid protocol {profile.protocol!r}; disabled")
            continue
        if profile.route_by_model:
            _warn_config(f"profile '{profile_name}' uses route_by_model and cannot be statically validated")
            valid_profiles[profile_name] = profile
            continue
        if not profile.backend:
            _warn_config(f"profile '{profile_name}' does not specify backend; disabled")
            continue
        backend = backends.get(profile.backend)
        if backend is None:
            _warn_config(f"profile '{profile_name}' references missing backend '{profile.backend}'; disabled")
            continue
        backend_errors = _validate_backend(profile.backend, backend)
        if backend_errors:
            _warn_config(
                f"profile '{profile_name}' backend '{profile.backend}' invalid: "
                + "; ".join(backend_errors)
                + "; disabled"
            )
            continue
        valid_profiles[profile_name] = profile

    valid_required = [name for name in REQUIRED_PROFILE_NAMES if name in valid_profiles]
    if not valid_required:
        raise ConfigError(
            "no valid coding-agent profiles available; expected at least one valid "
            "opencode, claude-code, or hermes profile"
        )

    return valid_profiles


def load_config() -> Config:
    """加载配置文件"""
    config_path = os.getenv("OPENAI_PROXY_CONFIG", "config.yaml")
    path = Path(config_path)

    if not path.exists():
        raise ConfigError(f"configuration file not found: {path}")
    _load_dotenv_for_config(path)

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    # 解析后端配置
    backends_data = data.get("backends", {})
    backends = {}
    for name, cfg in backends_data.items():
        backends[name] = _parse_backend(name, cfg or {})

    if not backends:
        raise ConfigError("config.yaml must define at least one backend")

    # 解析认证配置
    auth_data = data.get("auth", {})
    auth = AuthConfig(
        enabled=bool(auth_data.get("enabled", False)),
        keys=auth_data.get("keys", []),
        keys_file=auth_data.get("keys_file"),
    )

    # 从文件加载 API Keys
    if auth.keys_file and Path(auth.keys_file).exists():
        with open(auth.keys_file, "r", encoding="utf-8") as f:
            for line in f:
                key = line.strip()
                if key and key not in auth.keys:
                    auth.keys.append(key)

    # 解析监控配置
    metrics_data = data.get("metrics", {})
    metrics = MetricsConfig(
        enabled=bool(metrics_data.get("enabled", True)),
        path=metrics_data.get("path", "/metrics"),
    )

    # 解析代理配置
    proxy_data = data.get("proxy", {})
    proxy = ProxyConfig(
        port=int(proxy_data.get("port", 8188)),
        connect_timeout_s=float(proxy_data.get("connect_timeout_s", 10)),
        stream_chunk_size=int(proxy_data.get("stream_chunk_size", 8192)),
        debug=bool(proxy_data.get("debug", False)),
        trace=bool(proxy_data.get("trace", False)),
        session_json=proxy_data.get("session_json"),
        usage_json=proxy_data.get("usage_json"),
    )
    default_backend = data.get("default_backend")
    if not default_backend:
        raise ConfigError("config.yaml must define default_backend")
    if default_backend not in backends:
        raise ConfigError(f"default_backend '{default_backend}' is not defined in backends")

    profiles_data = data.get("profiles", {})
    profiles: dict[str, ProfileConfig] = {}
    for name, cfg in profiles_data.items():
        profiles[name] = _parse_profile(name, cfg or {}, proxy.port, default_backend)
    profiles = _validate_and_filter_profiles(backends, profiles)

    return Config(
        backends=backends,
        default_backend=default_backend,
        auth=auth,
        metrics=metrics,
        proxy=proxy,
        profiles=profiles,
    )


# 加载全局配置
_config: Optional[Config] = None


def get_config() -> Config:
    """获取全局配置"""
    global _config
    if _config is None:
        _config = load_config()
    return _config


# ================================================================================
# 负载均衡器
# ================================================================================

class LoadBalancer:
    """负载均衡器"""

    def __init__(self, endpoints: list[dict], strategy: str = "round_robin"):
        self.endpoints = endpoints  # 每个元素是 {"url": str, "model": str|None, "api_key": str|None}
        self.strategy = strategy
        self._index = 0
        self._connections: dict[str, int] = {ep["url"]: 0 for ep in endpoints}
        self._lock = asyncio.Lock()

    async def acquire(self) -> tuple[str, Optional[str], Optional[str]]:
        """获取一个端点，返回 (url, model, api_key)"""
        if self.strategy == "round_robin":
            async with self._lock:
                ep = self.endpoints[self._index % len(self.endpoints)]
                self._index += 1
                self._connections[ep["url"]] += 1
                return ep["url"], ep.get("model"), ep.get("api_key")
        elif self.strategy == "random":
            ep = random.choice(self.endpoints)
            self._connections[ep["url"]] += 1
            return ep["url"], ep.get("model"), ep.get("api_key")
        elif self.strategy == "least_connections":
            async with self._lock:
                ep = min(self.endpoints, key=lambda e: self._connections[e["url"]])
                self._connections[ep["url"]] += 1
                return ep["url"], ep.get("model"), ep.get("api_key")
        else:
            ep = self.endpoints[0]
            self._connections[ep["url"]] += 1
            return ep["url"], ep.get("model"), ep.get("api_key")

    def release(self, endpoint_url: str):
        """释放端点"""
        if endpoint_url in self._connections and self._connections[endpoint_url] > 0:
            self._connections[endpoint_url] -= 1


# ================================================================================
# 速率限制器
# ================================================================================

class RateLimiter:
    """速率限制器"""

    def __init__(self, max_concurrent: int = 0, rpm: int = 0):
        self.semaphore = asyncio.Semaphore(max_concurrent) if max_concurrent > 0 else None
        self.rpm = rpm
        self._requests: deque = deque()
        self._lock = asyncio.Lock()

    async def acquire(self):
        """获取许可"""
        if self.semaphore:
            await self.semaphore.acquire()

        if self.rpm > 0:
            async with self._lock:
                now = time.time()
                # 清理 60 秒前的请求
                while self._requests and now - self._requests[0] > 60:
                    self._requests.popleft()

                if len(self._requests) >= self.rpm:
                    wait = 60 - (now - self._requests[0]) + 0.1
                    await asyncio.sleep(wait)
                    self._requests.popleft()

                self._requests.append(now)

    def release(self):
        """释放许可"""
        if self.semaphore:
            try:
                self.semaphore.release()
            except ValueError:
                pass  # semaphore 已释放


# ================================================================================
# 异常类
# ================================================================================

class RetryExhaustedError(Exception):
    """重试耗尽异常"""
    pass


# ================================================================================
# 工具函数
# ================================================================================

def _redact_secret(value: str, *, keep_start: int = 6, keep_end: int = 4) -> str:
    """对可能的密钥做脱敏显示"""
    v = (value or "").strip()
    if not v:
        return ""
    if len(v) <= keep_start + keep_end + 3:
        return f"{v[:2]}…{v[-2:]}"
    return f"{v[:keep_start]}…{v[-keep_end:]}"


def _debug_print(msg: str) -> None:
    """调试打印"""
    config = get_config()
    if config.proxy.debug:
        print(f"[proxy-debug] {msg}", file=sys.stderr, flush=True)


def _trace_log(label: str, payload: Any) -> None:
    """轨迹日志"""
    config = get_config()
    if not config.proxy.trace:
        return
    try:
        text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    except Exception:
        text = str(payload)
    print(f"[trace:{label}]\n{_truncate(text, 12000)}", file=sys.stderr, flush=True)


def _try_parse_json(body: bytes) -> Optional[dict]:
    """尝试解析 JSON"""
    if not body:
        return None
    try:
        return json.loads(body.decode("utf-8"))
    except Exception:
        return None


def _truncate(s: str, max_len: int = 4000) -> str:
    """截断字符串"""
    if len(s) <= max_len:
        return s
    return s[:max_len] + f"…(truncated, len={len(s)})"


def _get_x_session_id(request: Request) -> str:
    """获取 session ID"""
    for k, v in request.headers.items():
        if k.lower() == "x-session-id":
            s = (v or "").strip()
            return s if s else "__empty_x_session_id__"
    return "__no_x_session_id__"


def _get_session_id(request: Request) -> str:
    """Return the stable session id sent by agent plugins or legacy clients."""
    headers = getattr(request, "headers", {}) or {}
    for key in ("x-agent-session-id", "x-session-id"):
        value = headers.get(key, "")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "__no_session_id__"


def _safe_filename(value: str) -> str:
    """Make an id safe for use as a single filename segment."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    cleaned = cleaned.strip("._")
    return cleaned or "__empty__"


def _get_profile_trace_path(
    profile_name: str,
    profile: ProfileConfig,
    session_context: dict[str, Any],
    now_ts: Optional[float] = None,
) -> Path:
    """Return the trace path under the profile's configured session_dir."""
    session_id = str(session_context.get("session_id") or "__no_session_id__")
    base = Path(profile.session_dir or "traces")
    return base / f"{_safe_filename(session_id)}.json"


def _profile_trace_enabled(profile: ProfileConfig, config: Config) -> bool:
    return bool(profile.session_dir or config.proxy.session_json)


def _profile_usage_json(profile_name: str, config: Config) -> Optional[str]:
    profile = config.profiles.get(profile_name)
    if profile and profile.usage_json:
        return profile.usage_json
    if profile_name == "default":
        return config.proxy.usage_json
    return None


def _profile_name_for_request(request: Request, config: Config) -> str:
    """Resolve profile from the local listener port, falling back to legacy default."""
    server = getattr(request, "scope", {}).get("server") if hasattr(request, "scope") else None
    port = None
    if isinstance(server, (tuple, list)) and len(server) >= 2:
        port = server[1]
    if port is None:
        port = getattr(getattr(request, "url", None), "port", None)
    for name, profile in config.profiles.items():
        if profile.port == port:
            return name
    if "default" in config.profiles:
        return "default"
    return next(iter(config.profiles.keys()), config.default_backend)


def _extract_model(body: bytes) -> str:
    """从请求体提取 model"""
    obj = _try_parse_json(body)
    if isinstance(obj, dict):
        return str(obj.get("model", ""))
    return ""


def get_backend_name(model: str, config: Config) -> str:
    """
    根据 model name 获取后端名称
    规则：
    1. 精确匹配
    2. 前缀匹配（最长匹配优先）
    3. 返回默认后端
    """
    backends = config.backends

    # 1. 精确匹配
    if model in backends:
        return model

    # 2. 前缀匹配（按长度降序）
    for prefix in sorted(backends.keys(), key=len, reverse=True):
        if model.startswith(prefix):
            return prefix

    # 3. 默认后端
    return config.default_backend


def _backend_name_for_profile(profile_name: str, model: str, config: Config) -> str:
    """Select backend for a profile, optionally falling back to model routing."""
    profile = config.profiles.get(profile_name)
    if profile and profile.backend and not profile.route_by_model:
        return profile.backend
    return get_backend_name(model, config)


def _filtered_upstream_headers(headers: aiohttp.typedefs.LooseHeaders) -> dict[str, str]:
    """过滤上游响应头"""
    out: dict[str, str] = {}
    for k, v in dict(headers).items():
        lk = k.lower()
        if lk in {"content-length", "transfer-encoding", "connection", "keep-alive"}:
            continue
        out[k] = str(v)
    return out


def _filtered_downstream_headers(headers: dict[str, str]) -> dict[str, str]:
    """过滤下游请求头"""
    out: dict[str, str] = {}
    for k, v in headers.items():
        lk = k.lower()
        if lk in {"host", "content-length", "transfer-encoding", "connection", "x-api-key"}:
            continue
        out[k] = str(v)
    return out


def _is_stream_request(request: Request, body: bytes) -> bool:
    """判断是否为流式请求"""
    if request.headers.get("accept", "").lower().startswith("text/event-stream"):
        return True
    ctype = request.headers.get("content-type", "")
    if "application/json" not in ctype.lower():
        return False
    try:
        obj = json.loads(body.decode("utf-8"))
    except Exception:
        return False
    return bool(obj.get("stream", False))


# ================================================================================
# SSE 解析工具
# ================================================================================

def _split_glm_think_markers(content_full: str) -> tuple[Optional[str], Optional[str]]:
    """分割 GLM 思考标记"""
    marker = "</think>"
    if marker not in content_full:
        return None, None
    before, _, after = content_full.partition(marker)
    return before.strip() or None, after


def _parse_sse_events(buffer: bytes) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """解析 SSE 事件"""
    events: list[dict[str, Any]] = []
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
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
        except Exception:
            pass

    content_full = "".join(content_parts)
    reasoning_full = "".join(reasoning_parts)
    think_prefix, visible_after = _split_glm_think_markers(content_full)

    if visible_after is not None:
        vis = _truncate(visible_after.strip(), 12000)
        tp = _truncate(think_prefix, 12000) if think_prefix else None
    else:
        vis = _truncate(content_full, 12000)
        tp = None

    summary: dict[str, Any] = {
        "assistant_content_full": _truncate(content_full, 12000),
        "assistant_reasoning_field": _truncate(reasoning_full, 12000) if reasoning_full else None,
        "assistant_think_prefix": tp,
        "assistant_visible_reply": vis,
    }
    return events, summary


def _summarize_upstream_json_response(data: bytes) -> dict[str, Any]:
    """摘要 JSON 响应"""
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
                        out["assistant_think_prefix"] = _truncate(tp, 8000) if tp else None
                        out["assistant_visible_reply"] = _truncate(vis.strip(), 8000)
                    else:
                        out["assistant_visible_reply"] = _truncate(full, 8000)
            if "text" in c0 and not out.get("assistant_visible_reply"):
                out["text"] = _truncate(str(c0.get("text", "")), 8000)
            finish = c0.get("finish_reason")
            if finish is not None:
                out["finish_reason"] = finish
    return out


def _summarize_messages_for_trace(obj: dict[str, Any]) -> Any:
    """摘要消息"""
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
            content = copy.deepcopy(content)
        entry: dict[str, Any] = {"role": role, "content": content}
        if "name" in m:
            entry["name"] = m.get("name")
        if "tool_calls" in m:
            entry["tool_calls"] = m.get("tool_calls")
        out.append(entry)
    return out


def _extract_last_user_turn(obj: dict[str, Any]) -> Optional[str]:
    """提取最后一条用户消息"""
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


def _build_chat_request_trace(body: bytes) -> dict[str, Any]:
    """构建请求轨迹"""
    obj = _try_parse_json(body)
    if not isinstance(obj, dict):
        return {"_parse_error": True, "raw_preview": _truncate(body.decode("utf-8", errors="replace"), 2000)}
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
# Anthropic ↔ OpenAI 格式转换
# ================================================================================

def _is_anthropic_request_body(obj: dict) -> bool:
    """判断请求体是否为 Anthropic 格式"""
    if "system" in obj:
        return True
    if "messages" in obj and "choices" not in obj and "object" not in obj:
        for msg in obj.get("messages", []):
            c = msg.get("content")
            if isinstance(c, list):
                for block in c:
                    if isinstance(block, dict) and block.get("type") in ("tool_result", "tool_use", "thinking"):
                        return True
            if msg.get("role") in ("tool",):
                return False
    return False


def _anthropic_messages_to_openai(messages: list) -> list:
    """将 Anthropic 格式的 messages 转换为 OpenAI 格式

    OpenAI 格式要求 tool 消息紧跟在 assistant(tool_calls) 之后，
    因此当 user 消息同时包含 text 和 tool_result 时，
    先输出 tool 消息，再输出 user 文本消息。
    """
    result: list[dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content")

        if role == "user":
            if isinstance(content, str):
                result.append({"role": "user", "content": content})
            elif isinstance(content, list):
                text_parts: list[str] = []
                image_parts: list[dict] = []
                tool_results: list[dict] = []
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    btype = block.get("type", "")
                    if btype == "text":
                        text_parts.append(block.get("text", ""))
                    elif btype == "image":
                        src = block.get("source", {})
                        if src.get("type") == "base64":
                            data_uri = f"data:{src.get('media_type', 'image/png')};base64,{src.get('data', '')}"
                            image_parts.append({"type": "image_url", "image_url": {"url": data_uri}})
                    elif btype == "tool_result":
                        tr_content = block.get("content", "")
                        if isinstance(tr_content, list):
                            tr_content = "\n".join(
                                b.get("text", "") for b in tr_content if isinstance(b, dict) and b.get("type") == "text"
                            )
                        tool_results.append({
                            "role": "tool",
                            "tool_call_id": block.get("tool_use_id", ""),
                            "content": str(tr_content),
                        })
                # OpenAI 要求 tool 消息紧跟 assistant(tool_calls)，所以先输出 tool_results
                result.extend(tool_results)
                # 再输出 user 文本/图片
                if text_parts or image_parts:
                    parts: list[dict] = []
                    for t in text_parts:
                        parts.append({"type": "text", "text": t})
                    parts.extend(image_parts)
                    if parts:
                        if len(parts) == 1 and text_parts and not image_parts:
                            result.append({"role": "user", "content": text_parts[0]})
                        else:
                            result.append({"role": "user", "content": parts})
            else:
                result.append({"role": "user", "content": str(content) if content else ""})

        elif role == "assistant":
            if isinstance(content, str):
                result.append({"role": "assistant", "content": content})
            elif isinstance(content, list):
                text_parts_a: list[str] = []
                tool_uses: list[dict] = []
                reasoning_parts: list[str] = []
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    btype = block.get("type", "")
                    if btype == "text":
                        text_parts_a.append(block.get("text", ""))
                    elif btype == "thinking":
                        thinking_text = block.get("thinking", "")
                        if thinking_text:
                            reasoning_parts.append(thinking_text)
                    elif btype == "tool_use":
                        tool_uses.append({
                            "id": block.get("id", ""),
                            "type": "function",
                            "function": {
                                "name": block.get("name", ""),
                                "arguments": json.dumps(block.get("input", {}), ensure_ascii=False),
                            },
                        })
                assistant_msg: dict[str, Any] = {"role": "assistant"}
                if text_parts_a:
                    assistant_msg["content"] = "\n".join(text_parts_a)
                else:
                    assistant_msg["content"] = None
                if tool_uses:
                    assistant_msg["tool_calls"] = tool_uses
                if reasoning_parts:
                    assistant_msg["reasoning_content"] = "\n".join(reasoning_parts)
                result.append(assistant_msg)
            else:
                result.append({"role": "assistant", "content": str(content) if content else ""})
    return result


def _anthropic_tools_to_openai(tools: list) -> list:
    """将 Anthropic 格式的 tools 转换为 OpenAI 格式"""
    result: list[dict] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        func: dict[str, Any] = {
            "name": tool.get("name", ""),
            "parameters": tool.get("input_schema", {}),
        }
        if "description" in tool:
            func["description"] = tool["description"]
        result.append({"type": "function", "function": func})
    return result


def _anthropic_tool_choice_to_openai(tc: Any) -> Any:
    """将 Anthropic 格式的 tool_choice 转换为 OpenAI 格式"""
    if tc is None:
        return None
    if isinstance(tc, str):
        return tc
    if isinstance(tc, dict):
        t = tc.get("type", "")
        if t == "auto":
            return "auto"
        elif t == "any":
            return "required"
        elif t == "none":
            return "none"
        elif t == "tool":
            return {"type": "function", "function": {"name": tc.get("name", "")}}
    return "auto"


def _anthropic_to_openai_request(body: bytes) -> tuple[bytes, bool]:
    """
    将 Anthropic 格式请求体转换为 OpenAI 格式。
    返回 (转换后的 body, 是否发生了转换)。
    如果不是 Anthropic 格式，返回原样。
    """
    try:
        obj = json.loads(body.decode("utf-8"))
    except Exception:
        return body, False

    if not isinstance(obj, dict) or not _is_anthropic_request_body(obj):
        return body, False

    openai_req: dict[str, Any] = {}

    # model
    openai_req["model"] = obj.get("model", "")

    # system -> system message
    messages: list[dict[str, Any]] = []
    system = obj.get("system")
    if system is not None:
        if isinstance(system, str):
            messages.append({"role": "system", "content": system})
        elif isinstance(system, list):
            texts = [b.get("text", "") for b in system if isinstance(b, dict) and b.get("type") == "text"]
            if texts:
                messages.append({"role": "system", "content": "\n".join(texts)})

    # messages
    messages.extend(_anthropic_messages_to_openai(obj.get("messages", [])))
    openai_req["messages"] = messages

    # max_tokens
    if "max_tokens" in obj:
        openai_req["max_tokens"] = obj["max_tokens"]

    # stream
    if "stream" in obj:
        openai_req["stream"] = obj["stream"]

    # temperature
    if "temperature" in obj:
        openai_req["temperature"] = obj["temperature"]

    # top_p
    if "top_p" in obj:
        openai_req["top_p"] = obj["top_p"]

    # stop_sequences -> stop
    if "stop_sequences" in obj:
        openai_req["stop"] = obj["stop_sequences"]

    # thinking -> 启用思考模式
    thinking_cfg = obj.get("thinking")
    thinking_enabled = isinstance(thinking_cfg, dict) and thinking_cfg.get("type") == "enabled"
    if thinking_enabled:
        budget = thinking_cfg.get("budget_tokens")
        if budget:
            openai_req["max_completion_tokens"] = budget

    # tools
    if "tools" in obj:
        openai_req["tools"] = _anthropic_tools_to_openai(obj["tools"])

    # tool_choice
    tc = obj.get("tool_choice")
    if tc is not None:
        openai_tc = _anthropic_tool_choice_to_openai(tc)
        if openai_tc is not None:
            openai_req["tool_choice"] = openai_tc
        if isinstance(tc, dict) and tc.get("disable_parallel_tool_use"):
            openai_req["parallel_tool_calls"] = False

    # metadata.user_id -> user
    metadata = obj.get("metadata")
    if isinstance(metadata, dict) and "user_id" in metadata:
        openai_req["user"] = metadata["user_id"]

    # 确保所有 assistant 消息都有 reasoning_content
    # 部分后端（如 Kimi）在服务端始终启用思考，要求 assistant 消息必须携带
    # reasoning_content，即使客户端未显式请求 thinking 也会校验。
    # 因此无条件填充，缺失或为空时补一个占位值。
    for msg in openai_req.get("messages", []):
        if msg.get("role") == "assistant":
            rc = msg.get("reasoning_content")
            if rc is None or (isinstance(rc, str) and not rc.strip()):
                msg["reasoning_content"] = "ok"

    converted = json.dumps(openai_req, ensure_ascii=False).encode("utf-8")
    return converted, True


# --- 响应转换 ---

_FINISH_REASON_TO_STOP_REASON = {
    "stop": "end_turn",
    "length": "max_tokens",
    "tool_calls": "tool_use",
    "content_filter": "refusal",
}

_STOP_REASON_TO_FINISH_REASON = {v: k for k, v in _FINISH_REASON_TO_STOP_REASON.items()}
_STOP_REASON_TO_FINISH_REASON["stop_sequence"] = "stop"
_STOP_REASON_TO_FINISH_REASON["pause_turn"] = "stop"


def _openai_to_anthropic_response_obj(openai_resp: dict) -> dict:
    """将 OpenAI 格式的非流式响应 dict 转换为 Anthropic 格式 dict"""
    choices = openai_resp.get("choices", [])
    choice = choices[0] if choices else {}
    message = choice.get("message", {})

    content: list[dict[str, Any]] = []
    msg_content = message.get("content")
    if msg_content:
        content.append({"type": "text", "text": msg_content})

    for tc in message.get("tool_calls", []):
        if not isinstance(tc, dict):
            continue
        func = tc.get("function", {})
        try:
            inp = json.loads(func.get("arguments", "{}"))
        except (json.JSONDecodeError, TypeError):
            inp = {}
        content.append({
            "type": "tool_use",
            "id": tc.get("id", ""),
            "name": func.get("name", ""),
            "input": inp,
        })

    if not content:
        content.append({"type": "text", "text": ""})

    finish_reason = choice.get("finish_reason", "stop")
    stop_reason = _FINISH_REASON_TO_STOP_REASON.get(finish_reason, "end_turn")

    usage = openai_resp.get("usage", {})
    anthropic_usage = {
        "input_tokens": usage.get("prompt_tokens", 0),
        "output_tokens": usage.get("completion_tokens", 0),
    }

    return {
        "type": "message",
        "id": openai_resp.get("id", ""),
        "model": openai_resp.get("model", ""),
        "role": "assistant",
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": anthropic_usage,
    }


def _openai_to_anthropic_response(data: bytes) -> bytes:
    """将 OpenAI 格式的非流式响应字节转换为 Anthropic 格式字节"""
    try:
        obj = json.loads(data.decode("utf-8"))
    except Exception:
        return data
    if not isinstance(obj, dict) or "choices" not in obj:
        return data
    result = _openai_to_anthropic_response_obj(obj)
    return json.dumps(result, ensure_ascii=False).encode("utf-8")


# --- 流式响应转换 ---

def _make_anthropic_sse(event_type: str, data: dict) -> bytes:
    """构造 Anthropic SSE 事件"""
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")


def _convert_openai_stream_chunk_to_anthropic(raw_line: str, state: dict) -> list[bytes]:
    """
    将单个 OpenAI SSE chunk 行转换为 Anthropic SSE 事件列表。

    state 维护转换上下文：
      - started: bool
      - msg_id: str
      - model: str
      - block_index: int
      - current_block_type: str | None  ("text" | "tool_use")
      - input_tokens: int
    """
    events: list[bytes] = []

    if raw_line.strip() == "data: [DONE]" or raw_line.strip() == "[DONE]":
        if state.get("current_block_type"):
            events.append(_make_anthropic_sse("content_block_stop", {
                "type": "content_block_stop",
                "index": state["block_index"],
            }))
            state["block_index"] += 1
            state["current_block_type"] = None
        # 只有在还没发过 message_delta 时才发（finish_reason 可能已经触发过）
        if not state.get("delta_sent"):
            events.append(_make_anthropic_sse("message_delta", {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                "usage": {"output_tokens": 0},
            }))
        events.append(_make_anthropic_sse("message_stop", {"type": "message_stop"}))
        return events

    if not raw_line.strip().startswith("data:"):
        return events
    payload = raw_line.strip()[5:].strip()
    try:
        chunk = json.loads(payload)
    except json.JSONDecodeError:
        return events

    if not isinstance(chunk, dict):
        return events

    if chunk.get("id"):
        state["msg_id"] = chunk["id"]
    if chunk.get("model"):
        state["model"] = chunk["model"]
    if chunk.get("usage") and isinstance(chunk["usage"], dict):
        state["input_tokens"] = chunk["usage"].get("prompt_tokens", state.get("input_tokens", 0))

    choices = chunk.get("choices", [])
    if not choices:
        return events

    for choice in choices:
        if not isinstance(choice, dict):
            continue
        delta = choice.get("delta", {})
        if not isinstance(delta, dict):
            delta = {}

        # 第一个 chunk：发送 message_start
        if not state.get("started") and delta.get("role") == "assistant":
            state["started"] = True
            events.append(_make_anthropic_sse("message_start", {
                "type": "message_start",
                "message": {
                    "id": state.get("msg_id", ""),
                    "type": "message",
                    "role": "assistant",
                    "content": [],
                    "model": state.get("model", ""),
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": state.get("input_tokens", 0), "output_tokens": 0},
                },
            }))
            if delta.get("content") is None and not delta.get("tool_calls"):
                continue

        # 文本内容
        content_text = delta.get("content")
        if content_text is not None:
            if not state.get("started"):
                state["started"] = True
                events.append(_make_anthropic_sse("message_start", {
                    "type": "message_start",
                    "message": {
                        "id": state.get("msg_id", ""),
                        "type": "message",
                        "role": "assistant",
                        "content": [],
                        "model": state.get("model", ""),
                        "stop_reason": None,
                        "stop_sequence": None,
                        "usage": {"input_tokens": state.get("input_tokens", 0), "output_tokens": 0},
                    },
                }))

            if state.get("current_block_type") != "text":
                if state.get("current_block_type"):
                    events.append(_make_anthropic_sse("content_block_stop", {
                        "type": "content_block_stop",
                        "index": state["block_index"],
                    }))
                    state["block_index"] += 1
                events.append(_make_anthropic_sse("content_block_start", {
                    "type": "content_block_start",
                    "index": state["block_index"],
                    "content_block": {"type": "text", "text": ""},
                }))
                state["current_block_type"] = "text"
            events.append(_make_anthropic_sse("content_block_delta", {
                "type": "content_block_delta",
                "index": state["block_index"],
                "delta": {"type": "text_delta", "text": content_text},
            }))

        # Tool calls
        tool_calls = delta.get("tool_calls")
        if isinstance(tool_calls, list):
            for tc in tool_calls:
                if not isinstance(tc, dict):
                    continue
                if tc.get("id"):
                    if state.get("current_block_type"):
                        events.append(_make_anthropic_sse("content_block_stop", {
                            "type": "content_block_stop",
                            "index": state["block_index"],
                        }))
                        state["block_index"] += 1
                    func = tc.get("function", {})
                    if not state.get("started"):
                        state["started"] = True
                        events.append(_make_anthropic_sse("message_start", {
                            "type": "message_start",
                            "message": {
                                "id": state.get("msg_id", ""),
                                "type": "message",
                                "role": "assistant",
                                "content": [],
                                "model": state.get("model", ""),
                                "stop_reason": None,
                                "stop_sequence": None,
                                "usage": {"input_tokens": state.get("input_tokens", 0), "output_tokens": 0},
                            },
                        }))
                    events.append(_make_anthropic_sse("content_block_start", {
                        "type": "content_block_start",
                        "index": state["block_index"],
                        "content_block": {
                            "type": "tool_use",
                            "id": tc["id"],
                            "name": func.get("name", ""),
                            "input": {},
                        },
                    }))
                    state["current_block_type"] = "tool_use"

                func = tc.get("function", {})
                if func.get("arguments"):
                    if not state.get("started"):
                        state["started"] = True
                        events.append(_make_anthropic_sse("message_start", {
                            "type": "message_start",
                            "message": {
                                "id": state.get("msg_id", ""),
                                "type": "message",
                                "role": "assistant",
                                "content": [],
                                "model": state.get("model", ""),
                                "stop_reason": None,
                                "stop_sequence": None,
                                "usage": {"input_tokens": state.get("input_tokens", 0), "output_tokens": 0},
                            },
                        }))
                    events.append(_make_anthropic_sse("content_block_delta", {
                        "type": "content_block_delta",
                        "index": state["block_index"],
                        "delta": {"type": "input_json_delta", "partial_json": func["arguments"]},
                    }))

        # finish_reason
        finish_reason = choice.get("finish_reason")
        if finish_reason:
            if state.get("current_block_type"):
                events.append(_make_anthropic_sse("content_block_stop", {
                    "type": "content_block_stop",
                    "index": state["block_index"],
                }))
                state["block_index"] += 1
                state["current_block_type"] = None

            stop_reason = _FINISH_REASON_TO_STOP_REASON.get(finish_reason, "end_turn")
            output_tokens = 0
            if chunk.get("usage") and isinstance(chunk["usage"], dict):
                output_tokens = chunk["usage"].get("completion_tokens", 0)

            events.append(_make_anthropic_sse("message_delta", {
                "type": "message_delta",
                "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                "usage": {"output_tokens": output_tokens},
            }))
            state["delta_sent"] = True

    return events


# ================================================================================
# 用量统计
# ================================================================================

class UsageTracker:
    """按 IP + 模型统计 token 用量"""

    def __init__(self):
        self._lock = asyncio.Lock()
        # {ip: {model: {"input_tokens": int, "output_tokens": int, "requests": int}}}
        self._usage: dict[str, dict[str, dict[str, int]]] = {}

    async def record(self, client_ip: str, model: str, input_tokens: int, output_tokens: int) -> None:
        """记录一次请求的 token 用量"""
        async with self._lock:
            ip_data = self._usage.setdefault(client_ip, {})
            model_data = ip_data.setdefault(model, {"input_tokens": 0, "output_tokens": 0, "requests": 0})
            model_data["input_tokens"] += input_tokens
            model_data["output_tokens"] += output_tokens
            model_data["requests"] += 1

    async def get_all(self) -> dict[str, dict[str, dict[str, int]]]:
        """获取全部用量数据"""
        async with self._lock:
            return copy.deepcopy(self._usage)

    async def get_by_ip(self, client_ip: str) -> dict[str, dict[str, int]]:
        """获取指定 IP 的用量数据"""
        async with self._lock:
            return copy.deepcopy(self._usage.get(client_ip, {}))

    def load(self, data: dict[str, dict[str, dict[str, int]]]) -> None:
        """从持久化数据加载"""
        self._usage = data if isinstance(data, dict) else {}

    def snapshot(self) -> dict[str, dict[str, dict[str, int]]]:
        """获取当前数据快照（同步，调用方需持有锁或在启动时调用）"""
        return copy.deepcopy(self._usage)


def _normalize_usage(usage: dict) -> dict[str, int]:
    """统一 Anthropic 和 OpenAI 两种 usage 格式

    Anthropic: input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens
    OpenAI: prompt_tokens, completion_tokens, reasoning_tokens
    """
    # Anthropic 格式
    if "input_tokens" in usage or "output_tokens" in usage:
        input_total = (
            int(usage.get("input_tokens", 0) or 0)
            + int(usage.get("cache_creation_input_tokens", 0) or 0)
            + int(usage.get("cache_read_input_tokens", 0) or 0)
        )
        return {
            "input_tokens": input_total,
            "output_tokens": int(usage.get("output_tokens", 0) or 0),
        }
    # OpenAI 格式
    if "prompt_tokens" in usage or "completion_tokens" in usage:
        return {
            "input_tokens": int(usage.get("prompt_tokens", 0) or 0),
            "output_tokens": int(usage.get("completion_tokens", 0) or 0),
        }
    return {"input_tokens": 0, "output_tokens": 0}


def _extract_usage_from_json(data: bytes) -> dict[str, Any]:
    """从非流式 JSON 响应中提取 usage 和实际模型名"""
    obj = _try_parse_json(data)
    if not isinstance(obj, dict):
        return {}
    usage = obj.get("usage")
    if not isinstance(usage, dict):
        return {}
    return {
        **_normalize_usage(usage),
        "model": obj.get("model"),
    }


def _extract_usage_from_sse(buffer: bytes) -> dict[str, Any]:
    """从流式 SSE 响应中提取 usage 和实际模型名

    支持 Anthropic 和 OpenAI 两种 SSE 格式：
    - Anthropic: message_start/message_delta 事件，usage 含 input_tokens/output_tokens/cache_*
    - OpenAI: chat.completion.chunk，最终 chunk 含 usage (prompt_tokens/completion_tokens)
    """
    text = buffer.decode("utf-8", errors="replace")
    last_usage_raw: Optional[dict] = None
    actual_model: Optional[str] = None
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
        # Anthropic: 从 message_start 提取实际模型名
        if obj.get("type") == "message_start":
            msg = obj.get("message")
            if isinstance(msg, dict) and msg.get("model"):
                actual_model = msg["model"]
        # OpenAI: 从 chunk 提取模型名
        if obj.get("model"):
            actual_model = obj["model"]
        # Anthropic: message_delta 包含最终的 usage
        if obj.get("type") == "message_delta":
            du = obj.get("usage")
            if isinstance(du, dict):
                last_usage_raw = du
        # OpenAI: 顶层 usage（流式最后一个 chunk）
        if "usage" in obj and isinstance(obj["usage"], dict):
            last_usage_raw = obj["usage"]
    result = _normalize_usage(last_usage_raw) if last_usage_raw else {"input_tokens": 0, "output_tokens": 0}
    if actual_model:
        result["model"] = actual_model
    return result


# ================================================================================
# 全局状态
# ================================================================================

# HTTP 会话池（按后端名称）
_sessions: dict[str, aiohttp.ClientSession] = {}

# 负载均衡器
_load_balancers: dict[str, LoadBalancer] = {}

# 速率限制器
_rate_limiters: dict[str, RateLimiter] = {}

# 轨迹存储
_trajectories_lock: Optional[asyncio.Lock] = None
_trajectories: dict[str, dict[str, Any]] = {}
_trace_queue: Optional[asyncio.Queue] = None
_trace_worker_task: Optional[asyncio.Task] = None
_agent_session_registry_lock: Optional[asyncio.Lock] = None
_agent_session_registry: dict[str, dict[str, Any]] = {}

# 有效的 API Keys
_valid_api_keys: set[str] = set()

# Prometheus 指标
if PROMETHEUS_AVAILABLE:
    REQUESTS_TOTAL = Counter(
        "proxy_requests_total",
        "Total requests",
        ["backend", "model", "status"]
    )
    REQUEST_DURATION = Histogram(
        "proxy_request_duration_seconds",
        "Request duration",
        ["backend", "model"]
    )
    ACTIVE_REQUESTS = Gauge(
        "proxy_active_requests",
        "Active requests",
        ["backend"]
    )
    BACKEND_ERRORS = Counter(
        "proxy_backend_errors_total",
        "Backend errors",
        ["backend", "error_type"]
    )
else:
    # 降级：无 Prometheus 时使用简单计数
    class _SimpleCounter:
        def __init__(self):
            self._counts: dict[str, int] = {}
        def labels(self, **kwargs):
            return self
        def inc(self):
            pass

    class _SimpleGauge:
        def labels(self, **kwargs):
            return self
        def inc(self):
            pass
        def dec(self):
            pass

    class _SimpleHistogram:
        def labels(self, **kwargs):
            return self
        def time(self):
            return self
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    REQUESTS_TOTAL = _SimpleCounter()
    REQUEST_DURATION = _SimpleHistogram()
    ACTIVE_REQUESTS = _SimpleGauge()
    BACKEND_ERRORS = _SimpleCounter()


# 用量统计器
_usage_tracker: UsageTracker = UsageTracker()
_usage_tracker: UsageTracker = UsageTracker()
_usage_trackers: dict[str, UsageTracker] = {}
_usage_persist_queue: Optional[asyncio.Queue] = None
_usage_persist_worker: Optional[asyncio.Task] = None
_startup_lock: Optional[asyncio.Lock] = None
_startup_complete: bool = False
_active_profile_names: Optional[set[str]] = None


def _set_active_profiles(profile_names: Optional[list[str] | tuple[str, ...] | set[str]]) -> None:
    """Restrict process-wide startup/shutdown work to selected profiles."""
    global _active_profile_names
    if profile_names is None:
        _active_profile_names = None
    else:
        _active_profile_names = {str(name) for name in profile_names}


def _selected_profile_names(config: Config) -> list[str]:
    if _active_profile_names is None:
        return list(config.profiles.keys())
    return [name for name in config.profiles.keys() if name in _active_profile_names]


def _selected_backend_names(config: Config, profile_names: list[str]) -> set[str]:
    selected: set[str] = set()
    for profile_name in profile_names:
        profile = config.profiles.get(profile_name)
        if profile is None:
            continue
        if profile.route_by_model or not profile.backend:
            return set(config.backends.keys())
        selected.add(profile.backend)
    return selected


# ================================================================================
# 用量持久化
# ================================================================================

def _usage_tracker_for_profile(profile_name: str) -> UsageTracker:
    if profile_name == "default":
        return _usage_tracker
    return _usage_trackers.setdefault(profile_name, UsageTracker())


async def _persist_usage_json(profile_name: str = "default") -> None:
    """持久化用量统计"""
    config = get_config()
    usage_json = _profile_usage_json(profile_name, config)
    if not usage_json:
        return
    snapshot = await _usage_tracker_for_profile(profile_name).get_all()
    path = Path(usage_json)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")

    def _write() -> None:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)
        tmp.replace(path)

    await asyncio.to_thread(_write)


def _load_usage_json(profile_name: str = "default") -> None:
    """启动时加载用量统计"""
    config = get_config()
    usage_json = _profile_usage_json(profile_name, config)
    if not usage_json:
        return
    path = Path(usage_json)
    if not path.exists():
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            _usage_tracker_for_profile(profile_name).load(data)
    except Exception as e:
        _debug_print(f"加载用量统计失败: {e}")


async def _usage_persist_worker_loop() -> None:
    """用量持久化工作线程（带防抖，合并高频写入）"""
    assert _usage_persist_queue is not None
    debounce_s = 2.0
    while True:
        try:
            profile_name = await _usage_persist_queue.get()
        except asyncio.CancelledError:
            break
        # 防抖：排空队列中积压的信号，只做一次写入
        while not _usage_persist_queue.empty():
            try:
                profile_name = _usage_persist_queue.get_nowait()
                _usage_persist_queue.task_done()
            except asyncio.QueueEmpty:
                break
        await asyncio.sleep(debounce_s)
        try:
            await _persist_usage_json(str(profile_name or "default"))
        finally:
            _usage_persist_queue.task_done()


def _enqueue_usage_persist(profile_name: str = "default") -> None:
    """非阻塞入队用量持久化任务"""
    if _usage_persist_queue is None:
        return
    try:
        _usage_persist_queue.put_nowait(profile_name)
    except asyncio.QueueFull:
        pass


# ================================================================================
# 轨迹持久化
# ================================================================================

async def _persist_session_json() -> None:
    """持久化会话轨迹"""
    config = get_config()
    if not config.proxy.session_json or _trajectories_lock is None:
        return
    async with _trajectories_lock:
        snapshot = {"sessions": dict(_trajectories)}
    path = Path(config.proxy.session_json)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")

    def _write() -> None:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)
        tmp.replace(path)

    await asyncio.to_thread(_write)


async def _trace_worker() -> None:
    """轨迹写入工作线程"""
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
    """入队持久化任务"""
    if _trace_queue is None:
        return
    try:
        _trace_queue.put_nowait(1)
    except asyncio.QueueFull:
        pass


async def _agent_registry_lock() -> asyncio.Lock:
    global _agent_session_registry_lock
    if _agent_session_registry_lock is None:
        _agent_session_registry_lock = asyncio.Lock()
    return _agent_session_registry_lock


async def _persist_agent_session_metadata(entry: dict[str, Any]) -> None:
    """Persist Claude Code run/session metadata best-effort."""
    if entry.get("agent_name") != "claude-code":
        return
    workspace_id = _safe_filename(str(entry.get("workspace_id") or "__unknown_workspace__"))
    run_id = _safe_filename(str(entry.get("run_id") or "__unknown_run__"))
    session_id = str(entry.get("active_session_id") or "")
    config = get_config()
    profile = config.profiles.get("claude-code")
    trace_root = Path(profile.session_dir if profile and profile.session_dir else "traces")
    file_stem = _safe_filename(session_id) if session_id else run_id
    metadata_path = trace_root / "_metadata" / workspace_id / f"{file_stem}.json"

    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        tmp.replace(path)

    await asyncio.to_thread(_write_json, metadata_path, entry)


async def _record_agent_session_event(event: dict[str, Any], persist: bool = True) -> dict[str, Any]:
    """Record a hook-reported agent session event and update the active run mapping."""
    agent_name = str(event.get("agent_name") or event.get("agent") or "").strip() or "claude-code"
    run_id = str(event.get("run_id") or "").strip()
    if agent_name != "claude-code" or not run_id:
        return {"ok": False, "error": "invalid_agent_session_event"}

    session_id = str(event.get("session_id") or "").strip()
    workspace_id = str(event.get("workspace_id") or "").strip() or "__unknown_workspace__"
    lock = await _agent_registry_lock()
    async with lock:
        existing = _agent_session_registry.get(run_id, {})
        active_session_id = session_id or existing.get("active_session_id") or ""
        entry = {
            **existing,
            "agent_name": agent_name,
            "run_id": run_id,
            "active_session_id": active_session_id,
            "workspace_id": workspace_id,
            "workspace": event.get("workspace") or existing.get("workspace"),
            "instance_id": event.get("instance_id") or existing.get("instance_id"),
            "transcript_path": event.get("transcript_path") or existing.get("transcript_path"),
            "cwd": event.get("cwd") or existing.get("cwd"),
            "source": event.get("source") or event.get("hook_event_name") or existing.get("source"),
            "last_hook_event_name": event.get("hook_event_name") or existing.get("last_hook_event_name"),
            "updated_at": event.get("timestamp") or datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
        _agent_session_registry[run_id] = entry

    if persist:
        await _persist_agent_session_metadata(entry)

    return {
        "ok": True,
        "run_id": run_id,
        "active_session_id": active_session_id,
        "workspace_id": workspace_id,
    }


async def _lookup_agent_session(run_id: str) -> Optional[dict[str, Any]]:
    """Look up current active session metadata for a run id."""
    if not run_id:
        return None
    lock = await _agent_registry_lock()
    async with lock:
        entry = _agent_session_registry.get(run_id)
        return copy.deepcopy(entry) if entry else None


async def _resolve_session_context(profile_name: str, request: Request) -> dict[str, Any]:
    """Resolve session/workspace context from headers and the Claude run registry."""
    headers = getattr(request, "headers", {}) or {}
    explicit_session = (
        headers.get("x-agent-session-id")
        or headers.get("x-session-id")
        or ""
    ).strip()
    workspace = (headers.get("x-agent-workspace") or "").strip() or None
    run_id = (headers.get("x-agent-run-id") or "").strip() if profile_name == "claude-code" else ""
    workspace_id = (
        (headers.get("x-agent-workspace-id") or "").strip() or "__unknown_workspace__"
        if profile_name == "claude-code"
        else None
    )

    if explicit_session:
        ctx = {
            "session_id": explicit_session,
            "workspace": workspace,
            "source": "header",
        }
        if profile_name == "claude-code":
            ctx["run_id"] = run_id
            ctx["workspace_id"] = workspace_id
        return ctx

    if profile_name == "claude-code" and run_id:
        registered = await _lookup_agent_session(run_id)
        if registered and registered.get("active_session_id"):
            return {
                "session_id": registered["active_session_id"],
                "run_id": run_id,
                "workspace_id": registered.get("workspace_id") or workspace_id,
                "workspace": registered.get("workspace") or workspace,
                "source": "registry",
            }

    return {
        "session_id": "__no_session_id__",
        "workspace": workspace,
        "source": "fallback",
        **(
            {"run_id": run_id or None, "workspace_id": workspace_id}
            if profile_name == "claude-code"
            else {}
        ),
    }


def _assistant_message_from_response_summary(response_summary: dict[str, Any]) -> dict[str, Any]:
    """从响应摘要构造 assistant 消息"""
    mode = str(response_summary.get("mode", ""))
    status = int(response_summary.get("http_status") or 0)
    if status >= 400 or "error" in mode:
        raw = response_summary.get("raw_body") or ""
        return {
            "role": "assistant",
            "content": _truncate(f"[upstream error {status}] {raw}", 20000),
        }
    text = (response_summary.get("assistant_content_full") or "").strip()
    if not text:
        text = (response_summary.get("assistant_visible_reply") or "").strip()
    if not text:
        text = (response_summary.get("text") or "").strip()
    msg: dict[str, Any] = {"role": "assistant", "content": text}
    tc = response_summary.get("assistant_tool_calls")
    if isinstance(tc, list) and tc:
        msg["tool_calls"] = tc
    return msg


def _strip_markdown_json_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if len(lines) >= 3 and lines[0].strip().lower() in {"```json", "```"} and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return stripped


def _is_system_reminder_text(text: str) -> bool:
    stripped = text.strip()
    return stripped.startswith("<system-reminder>") and "</system-reminder>" in stripped


def _structured_trace_content_blocks(content: Any) -> Optional[list[Any]]:
    if isinstance(content, list):
        return content
    if not isinstance(content, str):
        return None
    stripped = content.strip()
    if not stripped.startswith("["):
        return None
    try:
        parsed = json.loads(stripped)
    except Exception:
        return None
    return parsed if isinstance(parsed, list) else None


def _normalize_trace_messages(messages: list[Any]) -> list[Any]:
    normalized: list[Any] = []
    for message in messages:
        if not isinstance(message, dict):
            normalized.append(message)
            continue
        if message.get("role") != "user":
            normalized.append(copy.deepcopy(message))
            continue

        blocks = _structured_trace_content_blocks(message.get("content"))
        if blocks is None:
            content = message.get("content")
            if isinstance(content, str) and _is_system_reminder_text(content):
                normalized.append({"role": "system", "content": content})
            else:
                normalized.append(copy.deepcopy(message))
            continue

        emitted = False
        for block in blocks:
            if not isinstance(block, dict):
                normalized.append({"role": "user", "content": str(block)})
                emitted = True
                continue
            if block.get("type") == "text":
                text = str(block.get("text") or "")
                role = "system" if _is_system_reminder_text(text) else "user"
                normalized.append({"role": role, "content": text})
                emitted = True
                continue
            normalized.append({"role": "user", "content": json.dumps(block, ensure_ascii=False)})
            emitted = True
        if not emitted:
            normalized.append(copy.deepcopy(message))
    return normalized


def _is_title_generation_response(response_summary: dict[str, Any]) -> bool:
    text = (
        response_summary.get("assistant_visible_reply")
        or response_summary.get("assistant_content_full")
        or response_summary.get("text")
        or ""
    )
    if not isinstance(text, str) or not text.strip():
        return False
    try:
        obj = json.loads(_strip_markdown_json_fence(text))
    except Exception:
        return False
    if not isinstance(obj, dict):
        return False
    keys = set(obj.keys())
    return "title" in keys and keys <= {"title"}


def _is_title_generation_request(request_summary: dict[str, Any]) -> bool:
    messages = request_summary.get("messages")
    if not isinstance(messages, list):
        return False

    has_opencode_title_system = False
    has_opencode_title_user = False
    for message in messages:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, str):
            continue
        normalized = content.lower()
        if message.get("role") == "system" and (
            "generate a concise" in normalized
            and "title" in normalized
            and "return json" in normalized
            and '"title"' in normalized
        ):
            return True
        if message.get("role") == "system" and (
            "you are a title generator" in normalized
            and "generate a brief title" in normalized
            and "never use tools" in normalized
            and "never respond to questions, just generate a title" in normalized
        ):
            has_opencode_title_system = True
        if message.get("role") == "user" and "generate a title for this conversation" in normalized:
            has_opencode_title_user = True
    if has_opencode_title_system and has_opencode_title_user:
        return True
    return False


def _strip_thinking_block(text: str) -> str:
    return re.sub(r"^\s*<think>.*?</think>\s*", "", text, flags=re.DOTALL)


def _is_new_topic_detection_response(response_summary: dict[str, Any]) -> bool:
    text = (
        response_summary.get("assistant_visible_reply")
        or response_summary.get("assistant_content_full")
        or response_summary.get("text")
        or ""
    )
    if not isinstance(text, str) or not text.strip():
        return False
    try:
        obj = json.loads(_strip_markdown_json_fence(_strip_thinking_block(text)))
    except Exception:
        return False
    if not isinstance(obj, dict):
        return False
    keys = set(obj.keys())
    return "isNewTopic" in keys and "title" in keys and keys <= {"isNewTopic", "title"}


def _is_new_topic_detection_request(request_summary: dict[str, Any]) -> bool:
    messages = request_summary.get("messages")
    if not isinstance(messages, list):
        return False

    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "system":
            continue
        content = message.get("content")
        if not isinstance(content, str):
            continue
        normalized = content.lower()
        if (
            "analyze if this message indicates a new conversation topic" in normalized
            and "isnewtopic" in normalized
            and "title" in normalized
            and "json object" in normalized
        ):
            return True
    return False


def _is_conversation_summary_request(request_summary: dict[str, Any]) -> bool:
    messages = request_summary.get("messages")
    if not isinstance(messages, list):
        return False

    has_summary_system = False
    has_title_user = False
    for message in messages:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, str):
            continue
        normalized = content.lower()
        if message.get("role") == "system" and (
            "summarize this coding conversation in under 50 characters" in normalized
        ):
            has_summary_system = True
        if message.get("role") == "user" and (
            "please write a 5-10 word title for the following conversation" in normalized
        ):
            has_title_user = True
    return has_summary_system and has_title_user


def _is_claude_internal_policy_request(request_summary: dict[str, Any]) -> bool:
    messages = request_summary.get("messages")
    if not isinstance(messages, list):
        return False

    has_internal_task_system = False
    has_policy_spec = False
    for message in messages:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, str):
            continue
        normalized = content.lower()
        if message.get("role") == "system" and (
            "your task is to" in normalized
            and "policy spec" in normalized
        ):
            has_internal_task_system = True
        if message.get("role") == "user" and "<policy_spec>" in normalized:
            has_policy_spec = True
    return has_internal_task_system and has_policy_spec


def _trace_message_roles(messages: Any) -> list[str]:
    if not isinstance(messages, list):
        return []
    roles: list[str] = []
    for message in messages:
        if isinstance(message, dict):
            roles.append(str(message.get("role") or ""))
        else:
            roles.append(type(message).__name__)
    return roles


def _first_system_excerpt(messages: Any) -> str | None:
    if not isinstance(messages, list):
        return None
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "system":
            continue
        content = message.get("content")
        if isinstance(content, str):
            return _truncate(content.replace("\n", "\\n"), 500)
    return None


def _assistant_response_excerpt(response_summary: dict[str, Any]) -> str:
    text = (
        response_summary.get("assistant_visible_reply")
        or response_summary.get("assistant_content_full")
        or response_summary.get("text")
        or response_summary.get("raw_body")
        or ""
    )
    return _truncate(str(text).replace("\n", "\\n"), 500)


def _agent_header_snapshot(headers: Any) -> dict[str, str]:
    wanted = {
        "x-agent-session-id",
        "x-session-id",
        "x-turn-type",
        "x-agent-name",
        "x-agent-workspace",
        "user-agent",
    }
    out: dict[str, str] = {}
    try:
        items = headers.items()
    except Exception:
        return out
    for key, value in items:
        lowered = str(key).lower()
        if lowered in wanted:
            out[lowered] = _truncate(str(value), 500)
    return out


def _request_trace_with_merged_assistant(
    request_summary: dict[str, Any],
    response_summary: dict[str, Any],
) -> dict[str, Any]:
    """合并请求和响应轨迹"""
    out = copy.deepcopy(request_summary)
    msgs = out.get("messages")
    if not isinstance(msgs, list):
        msgs = []
        out["messages"] = msgs
    msgs.append(_assistant_message_from_response_summary(response_summary))
    return out


def _strip_ids_from_tool_calls(messages: list[Any]) -> list[Any]:
    """移除 tool_calls 中的 id"""
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
    profile_name: str,
    session_context: dict[str, Any] | str,
    request_summary: dict[str, Any],
    response_summary: dict[str, Any],
) -> None:
    """覆盖会话轨迹"""
    config = get_config()
    profile = config.profiles.get(profile_name)
    if profile is None or not _profile_trace_enabled(profile, config):
        return
    if isinstance(session_context, str):
        session_context = {"session_id": session_context}
    session_id = str(session_context.get("session_id") or "__no_session_id__")
    title_request = _is_title_generation_request(request_summary)
    title_response = _is_title_generation_response(response_summary)
    topic_request = _is_new_topic_detection_request(request_summary)
    topic_response = _is_new_topic_detection_response(response_summary)
    summary_request = _is_conversation_summary_request(request_summary)
    internal_policy_request = (
        profile_name == "claude-code"
        and _is_claude_internal_policy_request(request_summary)
    )
    if title_request or title_response or topic_request or topic_response or summary_request or internal_policy_request:
        skip_log = {
            "profile": profile_name,
            "session_id": session_id,
            "workspace": session_context.get("workspace"),
            "reason": {
                "title_request": title_request,
                "title_response": title_response,
                "new_topic_request": topic_request,
                "new_topic_response": topic_response,
                "conversation_summary_request": summary_request,
                "internal_policy_request": internal_policy_request,
            },
            "request_message_roles": _trace_message_roles(request_summary.get("messages")),
            "first_system_excerpt": _first_system_excerpt(request_summary.get("messages")),
            "assistant_response_excerpt": _assistant_response_excerpt(response_summary),
        }
        if profile_name == "claude-code":
            skip_log["run_id"] = session_context.get("run_id")
            skip_log["workspace_id"] = session_context.get("workspace_id")
        _trace_log("trace_skip_internal_request", skip_log)
        return
    merged = _request_trace_with_merged_assistant(request_summary, response_summary)
    raw_msgs = merged.get("messages")
    if not isinstance(raw_msgs, list):
        raw_msgs = []
    msgs = _strip_ids_from_tool_calls(_normalize_trace_messages(raw_msgs))
    write_log = {
        "profile": profile_name,
        "session_id": session_id,
        "workspace": session_context.get("workspace"),
        "request_message_roles": _trace_message_roles(request_summary.get("messages")),
        "final_message_roles": _trace_message_roles(msgs),
        "first_system_excerpt": _first_system_excerpt(request_summary.get("messages")),
        "assistant_response_excerpt": _assistant_response_excerpt(response_summary),
    }
    if profile_name == "claude-code":
        write_log["run_id"] = session_context.get("run_id")
        write_log["workspace_id"] = session_context.get("workspace_id")
    _trace_log("trace_write_snapshot", write_log)
    tools = merged.get("tools")
    if tools is not None and not isinstance(tools, list):
        tools = None
    snapshot = {
        "profile": profile_name,
        "session_id": session_id,
        "workspace": session_context.get("workspace"),
        "session_source": session_context.get("source"),
        "messages": msgs,
        "tools": tools,
    }
    if profile_name == "claude-code":
        snapshot["run_id"] = session_context.get("run_id")
        snapshot["workspace_id"] = session_context.get("workspace_id")
    else:
        snapshot.pop("run_id", None)
        snapshot.pop("workspace_id", None)
    path = _get_profile_trace_path(profile_name, profile, session_context)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")

    def _write() -> None:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)
        tmp.replace(path)

    await asyncio.to_thread(_write)


# ================================================================================
# 请求重试
# ================================================================================

async def request_with_retry(
    session: aiohttp.ClientSession,
    method: str,
    url: str,
    max_retries: int = 3,
    retry_delay: float = 1.0,
    **kwargs,
) -> aiohttp.ClientResponse:
    """
    带重试的请求

    仅对 5xx 错误和网络错误重试，4xx 错误直接返回。
    使用指数退避策略。
    """
    last_error: Optional[str] = None

    for attempt in range(max_retries):
        try:
            resp = await session.request(method, url, **kwargs)
            # 4xx 不重试
            if resp.status < 500:
                return resp
            last_error = f"HTTP {resp.status}"
            # 读取错误响应体以便关闭连接
            await resp.read()
            resp.release()
        except asyncio.TimeoutError:
            last_error = "timeout"
        except aiohttp.ClientError as e:
            last_error = str(e)

        # 最后一次尝试不再等待
        if attempt < max_retries - 1:
            delay = retry_delay * (2 ** attempt)  # 指数退避
            _debug_print(f"请求失败 {last_error}，{delay:.1f}s 后重试 (attempt {attempt + 1}/{max_retries})")
            await asyncio.sleep(delay)

    raise RetryExhaustedError(f"重试耗尽: {last_error}")


# ================================================================================
# FastAPI 应用
# ================================================================================

app = FastAPI(title="OpenAI-Compatible Proxy (Multi-Backend)")


# ================================================================================
# 应用生命周期
# ================================================================================

@app.on_event("startup")
async def _startup() -> None:
    """应用启动"""
    global _sessions, _load_balancers, _rate_limiters, _valid_api_keys
    global _trajectories_lock, _trace_queue, _trace_worker_task, _agent_session_registry_lock
    global _startup_lock, _startup_complete

    config = get_config()
    if _startup_lock is None:
        _startup_lock = asyncio.Lock()
    async with _startup_lock:
        if _startup_complete:
            return

        await _startup_once(config)
        _startup_complete = True


async def _startup_once(config: Config) -> None:
    """Initialize shared process-wide resources once."""
    global _sessions, _load_balancers, _rate_limiters, _valid_api_keys
    global _trajectories_lock, _trace_queue, _trace_worker_task
    global _usage_persist_queue, _usage_persist_worker

    profile_names = _selected_profile_names(config)
    backend_names = _selected_backend_names(config, profile_names)

    for name, backend in config.backends.items():
        if backend_names and name not in backend_names:
            continue
        timeout = aiohttp.ClientTimeout(
            total=None,
            connect=config.proxy.connect_timeout_s,
            sock_connect=config.proxy.connect_timeout_s,
            sock_read=None,
        )

        # 构造请求头
        headers = {}
        if backend.api_key:
            headers["Authorization"] = f"Bearer {backend.api_key}"

        _sessions[name] = aiohttp.ClientSession(timeout=timeout, headers=headers)

        # 初始化负载均衡器
        _load_balancers[name] = LoadBalancer(
            endpoints=backend.endpoints,
            strategy=backend.load_balance,
        )

        # 初始化速率限制器
        if backend.max_concurrent > 0 or backend.requests_per_minute > 0:
            _rate_limiters[name] = RateLimiter(
                max_concurrent=backend.max_concurrent,
                rpm=backend.requests_per_minute,
            )

    # 初始化认证
    if config.auth.enabled:
        _valid_api_keys = set(config.auth.keys)

    # 初始化轨迹
    _trajectories_lock = asyncio.Lock()
    _agent_session_registry_lock = asyncio.Lock()
    if config.proxy.session_json:
        _trace_queue = asyncio.Queue(maxsize=512)
        _trace_worker_task = asyncio.create_task(_trace_worker())

    # 初始化用量统计
    global _usage_persist_queue, _usage_persist_worker
    for profile_name in profile_names:
        _load_usage_json(profile_name)
    if any(_profile_usage_json(profile_name, config) for profile_name in profile_names):
        _usage_persist_queue = asyncio.Queue(maxsize=512)
        _usage_persist_worker = asyncio.create_task(_usage_persist_worker_loop())


@app.on_event("shutdown")
async def _shutdown() -> None:
    """应用关闭"""
    global _sessions, _trace_worker_task, _usage_persist_worker, _startup_complete
    if not _startup_complete:
        return
    _startup_complete = False

    # 停止轨迹工作线程
    if _trace_worker_task is not None:
        _trace_worker_task.cancel()
        try:
            await _trace_worker_task
        except asyncio.CancelledError:
            pass
        _trace_worker_task = None
        await _persist_session_json()

    # 停止用量持久化工作线程
    if _usage_persist_worker is not None:
        _usage_persist_worker.cancel()
        try:
            await _usage_persist_worker
        except asyncio.CancelledError:
            pass
        _usage_persist_worker = None
        for profile_name in _selected_profile_names(get_config()):
            await _persist_usage_json(profile_name)

    # 关闭所有会话
    for name, session in _sessions.items():
        await session.close()
        _debug_print(f"关闭会话: {name}")

    _sessions.clear()


# ================================================================================
# 认证中间件
# ================================================================================

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """认证中间件"""
    config = get_config()

    if not config.auth.enabled:
        return await call_next(request)

    # 跳过健康检查和指标端点
    if request.url.path in ["/health", config.metrics.path]:
        return await call_next(request)

    # 提取 API Key
    auth_header = request.headers.get("authorization", "")
    api_key = None

    if auth_header.startswith("Bearer "):
        api_key = auth_header[7:]
    elif auth_header.startswith("bearer "):
        api_key = auth_header[7:]

    # 检查 x-api-key header
    if not api_key:
        api_key = request.headers.get("x-api-key", "")

    if api_key not in _valid_api_keys:
        return Response(
            content='{"error": {"message": "Unauthorized", "type": "invalid_api_key"}}',
            status_code=401,
            media_type="application/json",
        )

    return await call_next(request)


# ================================================================================
# 代理路由
# ================================================================================

@app.get("/v1/models")
async def list_models() -> dict[str, Any]:
    """返回支持的模型列表（固定返回 glm-5-fp8）"""
    return {
        "object": "list",
        "data": [
            {
                "id": "glm-5-fp8",
                "object": "model",
                "created": 1677610602,
                "owned_by": "openai",
            }
        ],
    }


@app.api_route(
    "/v1/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
)
async def proxy_v1(path: str, request: Request) -> Response:
    """
    OpenAI 兼容 API 代理

    根据 model name 路由到对应后端，支持多端点故障转移（Failover）
    """
    config = get_config()
    profile_name = _profile_name_for_request(request, config)
    profile = config.profiles.get(profile_name)
    if profile is None:
        return Response(
            content='{"error": {"message": "No profile available", "type": "profile_error"}}',
            status_code=503,
            media_type="application/json",
        )

    # 获取请求体
    body = await request.body()

    # 提取 model 并路由
    model = _extract_model(body)
    backend_name = _backend_name_for_profile(profile_name, model, config)
    backend = config.backends.get(backend_name)

    if not backend:
        return Response(
            content='{"error": {"message": "No backend available", "type": "backend_error"}}',
            status_code=503,
            media_type="application/json",
        )

    # 获取会话
    session = _sessions.get(backend_name)
    if not session:
        return Response(
            content='{"error": {"message": "Backend session not initialized", "type": "backend_error"}}',
            status_code=503,
            media_type="application/json",
        )

    # 获取负载均衡器
    load_balancer = _load_balancers.get(backend_name)

    # 获取速率限制器
    rate_limiter = _rate_limiters.get(backend_name)

    # 客户端 IP（优先从代理头获取真实 IP）
    client_ip = (
        request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or request.headers.get("x-real-ip", "").strip()
        or (request.client.host if request.client else "unknown")
    )

    # 判断是否流式请求
    is_stream = _is_stream_request(request, body)

    # 获取查询参数
    params = list(request.query_params.multi_items())

    # 过滤请求头
    headers = _filtered_downstream_headers(dict(request.headers))
    # 禁用上游压缩，确保 SSE 内容可解析
    headers["Accept-Encoding"] = "identity"

    # 轨迹相关
    trace_chat = path.rstrip("/").endswith("chat/completions") or path.rstrip("/") == "messages"
    trace_enabled = config.proxy.trace or _profile_trace_enabled(profile, config)
    session_context = await _resolve_session_context(profile_name, request)
    session_id = str(session_context.get("session_id") or "__no_session_id__")

    # 遍历所有端点尝试请求（故障转移）
    endpoints = backend.endpoints
    last_error: Optional[str] = None
    pre_acquired_url: Optional[str] = None
    if load_balancer and endpoints:
        acquired_url, _, _ = await load_balancer.acquire()
        pre_acquired_url = acquired_url
        first = [ep for ep in endpoints if ep.get("url") == acquired_url]
        rest = [ep for ep in endpoints if ep.get("url") != acquired_url]
        endpoints = first + rest

    for ep_index, ep in enumerate(endpoints):
        endpoint_url = ep.get("url")
        connection_url = endpoint_url
        endpoint_model = ep.get("model")
        endpoint_api_key = ep.get("api_key")
        endpoint_openai_url = ep.get("openai_url")

        # 判断是否为 OpenAI 格式请求（/v1/chat/completions 等）
        is_openai_request = profile.protocol == "openai" and path.rstrip("/").startswith("chat/")

        # 判断是否为 Anthropic 格式请求且需要格式转换
        is_anthropic_request = profile.protocol == "anthropic" and path.rstrip("/") == "messages"
        needs_anthropic_conversion = is_anthropic_request and endpoint_openai_url is not None

        # OpenAI 格式请求优先使用 openai_url
        if is_openai_request and endpoint_openai_url:
            endpoint_url = endpoint_openai_url

        if config.proxy.debug:
            _debug_print(
                f"request: model={model} -> backend={backend_name} endpoint={endpoint_url} (attempt {ep_index + 1}/{len(endpoints)})"
            )

        # 如果端点指定了模型名，替换请求体中的 model
        request_body = body

        # Anthropic → OpenAI 格式转换
        if needs_anthropic_conversion:
            request_body, _ = _anthropic_to_openai_request(body)
            if config.proxy.debug:
                _debug_print(f"anthropic->openai conversion applied for endpoint {endpoint_openai_url}")

        try:
            body_obj = json.loads(request_body.decode("utf-8"))
            modified = False
            # 模型名映射
            if endpoint_model is not None:
                body_obj["model"] = endpoint_model
                modified = True
                if config.proxy.debug:
                    _debug_print(f"model mapping: {model} -> {endpoint_model}")
            # 流式请求时注入 stream_options 以确保上游返回 usage
            if is_stream and body_obj.get("stream"):
                if "stream_options" not in body_obj:
                    body_obj["stream_options"] = {"include_usage": True}
                    modified = True
            if modified:
                request_body = json.dumps(body_obj, ensure_ascii=False).encode("utf-8")
        except Exception:
            pass  # 解析失败，保持原样

        # 构造上游 URL
        if needs_anthropic_conversion:
            # Anthropic 请求转换后，发送到 openai_url 的 chat/completions 端点
            upstream_url = urljoin(endpoint_openai_url.rstrip("/") + "/", "v1/chat/completions")
        else:
            upstream_url = urljoin(endpoint_url.rstrip("/") + "/", f"v1/{path}")

        # 构造请求头（端点可能有自己的 API Key）
        request_headers = dict(headers)
        # 应用后端级 extra_headers
        if backend.extra_headers and isinstance(backend.extra_headers, dict):
            request_headers.update(backend.extra_headers)
        # 应用端点级 extra_headers（优先级更高）
        endpoint_extra_headers = ep.get("extra_headers")
        if endpoint_extra_headers and isinstance(endpoint_extra_headers, dict):
            request_headers.update(endpoint_extra_headers)
        # 如果端点或后端有自己的 API Key，覆盖下游传来的认证头，避免客户端凭证干扰上游认证
        effective_api_key = endpoint_api_key or backend.api_key
        if effective_api_key is not None:
            request_headers["Authorization"] = f"Bearer {effective_api_key}"
            # 清除下游可能传来的 x-api-key（Anthropic 客户端常用）
            request_headers.pop("x-api-key", None)
            if config.proxy.debug:
                _debug_print(f"using backend/endpoint API key: {_redact_secret(effective_api_key)}")

        # 请求轨迹
        request_trace: Optional[dict[str, Any]] = None
        if trace_chat and trace_enabled:
            request_trace = _build_chat_request_trace(request_body)
            request_trace["backend"] = backend_name
            request_trace["endpoint"] = endpoint_url
            if config.proxy.trace:
                _trace_log(
                    "downstream_request",
                    {
                        "x_session_id": session_id,
                        "agent_headers": _agent_header_snapshot(headers),
                        "path": f"/v1/{path}",
                        **request_trace,
                    },
                )

        cleanup_deferred = False
        try:
            # 速率限制
            if rate_limiter:
                await rate_limiter.acquire()

            # 增加连接计数
            if load_balancer and connection_url != pre_acquired_url:
                load_balancer._connections[connection_url] = load_balancer._connections.get(connection_url, 0) + 1

            # Prometheus 指标
            ACTIVE_REQUESTS.labels(backend=backend_name).inc()

            if PROMETHEUS_AVAILABLE:
                timer = REQUEST_DURATION.labels(backend=backend_name, model=model).time()
                timer.__enter__()

            # -------------------- 流式响应 --------------------
            if is_stream:
                upstream_resp = await request_with_retry(
                    session,
                    request.method,
                    upstream_url,
                    max_retries=backend.max_retries,
                    retry_delay=backend.retry_delay_s,
                    params=params,
                    data=request_body if request_body else None,
                    headers=request_headers,
                )

                # 错误响应
                if upstream_resp.status >= 400:
                    data = await upstream_resp.read()
                    ct = upstream_resp.headers.get("content-type", "application/json")
                    resp_headers = _filtered_upstream_headers(upstream_resp.headers)

                    preview = data.decode("utf-8", errors="replace")
                    preview_dbg = preview[:2000] + "…" if len(preview) > 2000 else preview

                    _debug_print(f"upstream error: status={upstream_resp.status} body={preview_dbg}")

                    if trace_chat and trace_enabled:
                        err_summary = {
                            "mode": "stream_error",
                            "http_status": upstream_resp.status,
                            "raw_body": _truncate(preview, 8000),
                        }
                        if config.proxy.trace:
                            _trace_log("upstream_response_error", {"x_session_id": session_id, **err_summary})
                        if request_trace is not None:
                            await _overwrite_session_trace(profile_name, session_context, request_trace, err_summary)

                    upstream_resp.release()

                    REQUESTS_TOTAL.labels(backend=backend_name, model=model, status=upstream_resp.status).inc()

                    return Response(
                        content=data,
                        status_code=upstream_resp.status,
                        headers=resp_headers,
                        media_type=ct,
                    )

                # 成功响应
                media_type = upstream_resp.headers.get("content-type", "text/event-stream")
                resp_headers = _filtered_upstream_headers(upstream_resp.headers)
                up_stream_status = upstream_resp.status

                # Anthropic 转换时需要调整 Content-Type
                if needs_anthropic_conversion:
                    media_type = "text/event-stream"

                async def gen():
                    acc = bytearray()
                    # 流式转换状态（用于 OpenAI→Anthropic SSE 转换）
                    conv_state: dict[str, Any] = {
                        "started": False,
                        "msg_id": "",
                        "model": "",
                        "block_index": 0,
                        "current_block_type": None,
                        "input_tokens": 0,
                    }
                    try:
                        async for chunk in upstream_resp.content.iter_chunked(config.proxy.stream_chunk_size):
                            if not chunk:
                                continue
                            acc.extend(chunk)
                            if needs_anthropic_conversion:
                                # 逐行解析 OpenAI SSE 并转换为 Anthropic SSE
                                text = chunk.decode("utf-8", errors="replace")
                                for line in text.splitlines():
                                    stripped = line.strip()
                                    if not stripped:
                                        continue
                                    anthro_events = _convert_openai_stream_chunk_to_anthropic(stripped, conv_state)
                                    for ev in anthro_events:
                                        yield ev
                                    # 空行分隔 SSE 事件
                                    if anthro_events:
                                        yield b"\n"
                            else:
                                yield chunk
                    finally:
                        upstream_resp.release()
                        if load_balancer:
                            load_balancer.release(connection_url)
                        if rate_limiter:
                            rate_limiter.release()
                        try:
                            ACTIVE_REQUESTS.labels(backend=backend_name).dec()
                        except Exception:
                            pass
                        if PROMETHEUS_AVAILABLE:
                            try:
                                timer.__exit__(None, None, None)
                            except Exception:
                                pass

                        if trace_chat and trace_enabled:
                            raw = bytes(acc)
                            events, sse_summary = _parse_sse_events(raw)
                            sample_ev = [
                                _truncate(json.dumps(e, ensure_ascii=False), 2500)
                                for e in events[:4]
                            ]
                            resp_summary: dict[str, Any] = {
                                "mode": "stream",
                                "http_status": up_stream_status,
                                "sse_events_count": len(events),
                                "sse_sample_event_strings": sample_ev,
                                **sse_summary,
                            }
                            if config.proxy.trace:
                                _trace_log("upstream_response_sse", {"x_session_id": session_id, **resp_summary})
                            if trace_enabled and request_trace is not None:
                                await _overwrite_session_trace(profile_name, session_context, request_trace, resp_summary)

                        # 记录用量
                        raw = bytes(acc)
                        _debug_print(f"[stream usage] ip={client_ip} model={model} acc_len={len(raw)} last_500={raw[-500:].decode('utf-8', errors='replace')!r}")
                        usage_data = _extract_usage_from_sse(raw)
                        _debug_print(f"[stream usage] ip={client_ip} model={model} usage_data={usage_data}")
                        actual_model = usage_data.get("model") or model
                        await _usage_tracker_for_profile(profile_name).record(
                            client_ip, actual_model,
                            usage_data.get("input_tokens", 0),
                            usage_data.get("output_tokens", 0),
                        )
                        _enqueue_usage_persist(profile_name)

                REQUESTS_TOTAL.labels(backend=backend_name, model=model, status=up_stream_status).inc()

                cleanup_deferred = True
                return StreamingResponse(
                    gen(),
                    status_code=up_stream_status,
                    headers=resp_headers,
                    media_type=media_type,
                )

            # -------------------- 非流式响应 --------------------
            else:
                upstream_resp = await request_with_retry(
                    session,
                    request.method,
                    upstream_url,
                    max_retries=backend.max_retries,
                    retry_delay=backend.retry_delay_s,
                    params=params,
                    data=request_body if request_body else None,
                    headers=request_headers,
                )

                data = await upstream_resp.read()

                preview = data.decode("utf-8", errors="replace")
                preview_dbg = preview[:2000] + "…" if len(preview) > 2000 else preview

                if config.proxy.debug and upstream_resp.status >= 400:
                    _debug_print(f"upstream error: status={upstream_resp.status} body={preview_dbg}")

                if trace_chat and trace_enabled:
                    if upstream_resp.status >= 400:
                        err_summary = {
                            "mode": "non_stream_error",
                            "http_status": upstream_resp.status,
                            "raw_body": _truncate(preview, 8000),
                        }
                        if config.proxy.trace:
                            _trace_log("upstream_response_error", {"x_session_id": session_id, **err_summary})
                        if request_trace is not None:
                            await _overwrite_session_trace(profile_name, session_context, request_trace, err_summary)
                    else:
                        resp_summary: dict[str, Any] = {
                            "mode": "non_stream",
                            "http_status": upstream_resp.status,
                            **_summarize_upstream_json_response(data),
                        }
                        if config.proxy.trace:
                            _trace_log("upstream_response_json", {"x_session_id": session_id, **resp_summary})
                        if trace_enabled and request_trace is not None:
                            await _overwrite_session_trace(profile_name, session_context, request_trace, resp_summary)

                media_type = upstream_resp.headers.get("content-type", "application/json")
                resp_headers = _filtered_upstream_headers(upstream_resp.headers)

                REQUESTS_TOTAL.labels(backend=backend_name, model=model, status=upstream_resp.status).inc()

                # 记录用量（仅成功响应）
                if upstream_resp.status < 400:
                    usage_data = _extract_usage_from_json(data)
                    actual_model = usage_data.get("model") or model
                    await _usage_tracker_for_profile(profile_name).record(
                        client_ip, actual_model,
                        usage_data.get("input_tokens", 0),
                        usage_data.get("output_tokens", 0),
                    )
                    _enqueue_usage_persist(profile_name)

                # Anthropic 格式转换：OpenAI 响应 → Anthropic 响应
                if needs_anthropic_conversion and upstream_resp.status < 400:
                    data = _openai_to_anthropic_response(data)
                    media_type = "application/json"

                return Response(
                    content=data,
                    status_code=upstream_resp.status,
                    headers=resp_headers,
                    media_type=media_type,
                )

        except RetryExhaustedError as e:
            last_error = str(e)
            BACKEND_ERRORS.labels(backend=backend_name, error_type="retry_exhausted").inc()
            _debug_print(f"endpoint {endpoint_url} failed: {last_error}, trying next...")

        except Exception as e:
            last_error = str(e)
            _debug_print(f"endpoint {endpoint_url} error: {last_error}, trying next...")

        finally:
            # 释放资源（即使失败也要释放，以便下一个端点可以继续）
            if not cleanup_deferred:
                try:
                    ACTIVE_REQUESTS.labels(backend=backend_name).dec()
                except Exception:
                    pass
                if rate_limiter:
                    rate_limiter.release()
                if load_balancer:
                    load_balancer.release(connection_url)
                if PROMETHEUS_AVAILABLE:
                    try:
                        timer.__exit__(None, None, None)
                    except Exception:
                        pass

        # 等待短暂时间后尝试下一个端点（避免雪崩）
        await asyncio.sleep(0.5)

    # 所有端点都失败
    _debug_print(f"all endpoints failed for backend {backend_name}, last error: {last_error}")
    return Response(
        content=f'{{"error": {{"message": "All endpoints failed. Last error: {last_error}", "type": "all_endpoints_failed"}}}}',
        status_code=502,
        media_type="application/json",
    )


# ================================================================================
# 健康检查
# ================================================================================

@app.get("/")
async def root() -> dict[str, str]:
    """根路径"""
    return {"status": "ok", "service": "openai-compatible-proxy"}


@app.head("/")
async def root_head() -> Response:
    """根路径 HEAD 请求"""
    return Response(status_code=200)


@app.get("/health")
async def health(request: Request) -> dict[str, Any]:
    """健康检查"""
    config = get_config()
    profile_name = _profile_name_for_request(request, config)
    profile = config.profiles.get(profile_name)

    backends_status = {}
    for name, backend in config.backends.items():
        backends_status[name] = {
            "endpoints": backend.endpoints,
            "load_balance": backend.load_balance,
        }

    return {
        "ok": True,
        "profile": profile_name,
        "protocol": profile.protocol if profile else None,
        "port": profile.port if profile else None,
        "backend": profile.backend if profile else None,
        "default_backend": config.default_backend,
        "backends": backends_status,
        "auth_enabled": config.auth.enabled,
    }


# ================================================================================
# 后端列表
# ================================================================================

@app.get("/backends")
async def list_backends(request: Request) -> dict[str, Any]:
    """列出所有后端"""
    config = get_config()
    profile_name = _profile_name_for_request(request, config)

    backends_info = {}
    for name, backend in config.backends.items():
        backends_info[name] = {
            "endpoints": backend.endpoints,
            "load_balance": backend.load_balance,
            "max_retries": backend.max_retries,
            "max_concurrent": backend.max_concurrent,
            "requests_per_minute": backend.requests_per_minute,
        }

    return {
        "profile": profile_name,
        "default_backend": config.default_backend,
        "backends": backends_info,
    }


# ================================================================================
# 用量统计
# ================================================================================

@app.post("/_agent/session-event")
async def agent_session_event(request: Request) -> dict[str, Any]:
    """Receive Claude Code hook session events."""
    try:
        event = await request.json()
    except Exception:
        return {"ok": False, "error": "invalid_json"}
    if not isinstance(event, dict):
        return {"ok": False, "error": "invalid_json_object"}
    return await _record_agent_session_event(event)


@app.get("/usage")
async def get_usage(request: Request, ip: Optional[str] = None) -> dict[str, Any]:
    """
    查询 token 用量统计

    - 不带参数：返回所有 IP 的用量
    - ?ip=xxx：返回指定 IP 的用量
    """
    profile_name = _profile_name_for_request(request, get_config())
    tracker = _usage_tracker_for_profile(profile_name)
    if ip:
        ip_data = await tracker.get_by_ip(ip)
        # 按 IP 汇总各模型
        ip_input = 0
        ip_output = 0
        ip_requests = 0
        for m in ip_data.values():
            ip_input += m.get("input_tokens", 0)
            ip_output += m.get("output_tokens", 0)
            ip_requests += m.get("requests", 0)
        return {
            "ip": ip,
            "profile": profile_name,
            "usage_by_model": ip_data,
            "summary": {
                "total_requests": ip_requests,
                "total_input_tokens": ip_input,
                "total_output_tokens": ip_output,
            },
        }
    else:
        all_data = await tracker.get_all()
        # 汇总：按模型 + 全局总计
        total_input = 0
        total_output = 0
        total_requests = 0
        by_model: dict[str, dict[str, int]] = {}
        for ip_data in all_data.values():
            for model_name, model_data in ip_data.items():
                mi = model_data.get("input_tokens", 0)
                mo = model_data.get("output_tokens", 0)
                mr = model_data.get("requests", 0)
                total_input += mi
                total_output += mo
                total_requests += mr
                agg = by_model.setdefault(model_name, {"input_tokens": 0, "output_tokens": 0, "requests": 0})
                agg["input_tokens"] += mi
                agg["output_tokens"] += mo
                agg["requests"] += mr
        return {
            "usage_by_ip_model": all_data,
            "profile": profile_name,
            "usage_by_model": by_model,
            "summary": {
                "ips": len(all_data),
                "models": list(by_model.keys()),
                "total_requests": total_requests,
                "total_input_tokens": total_input,
                "total_output_tokens": total_output,
            },
        }


# ================================================================================
# Prometheus 指标
# ================================================================================

@app.get("/metrics")
async def metrics() -> Response:
    """Prometheus 指标"""
    config = get_config()

    if not config.metrics.enabled or not PROMETHEUS_AVAILABLE:
        return Response(
            content="# Prometheus metrics not available (install prometheus-client)",
            media_type="text/plain",
        )

    return Response(
        content=generate_latest(),
        media_type="text/plain",
    )


# ================================================================================
# 主入口
# ================================================================================

def create_profile_app(profile_name: str) -> FastAPI:
    """Create a minimal app for one coding-agent profile."""
    profile_app = FastAPI(title=f"AI Coding Proxy ({profile_name})")
    profile_app.on_event("startup")(_startup)

    async def _profile_startup_message() -> None:
        config = get_config()
        profile = config.profiles.get(profile_name)
        if profile is None:
            return
        print(
            f"[startup] {profile_name} proxy is listening on http://0.0.0.0:{profile.port} "
            f"(health: http://<proxy-host>:{profile.port}/health)",
            file=sys.stderr,
            flush=True,
        )

    profile_app.on_event("startup")(_profile_startup_message)
    profile_app.on_event("shutdown")(_shutdown)
    profile_app.middleware("http")(auth_middleware)

    # Agent-facing routes used by all three profile clients.
    profile_app.get("/")(root)
    profile_app.head("/")(root_head)
    profile_app.get("/health")(health)
    profile_app.get("/v1/models")(list_models)
    profile_app.api_route(
        "/v1/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    )(proxy_v1)

    # Claude Code needs this hook endpoint to bind run_id -> session_id.
    if profile_name == "claude-code":
        profile_app.post("/_agent/session-event")(agent_session_event)

    return profile_app


async def _serve_profile(
    profile_name: str,
    profile: ProfileConfig,
    app_instance: Optional[FastAPI] = None,
) -> None:
    """Serve the shared app on one profile port."""
    server_config = uvicorn.Config(
        app_instance or app,
        host="0.0.0.0",
        port=profile.port,
        workers=1,
        log_level="warning",
        access_log=False,
    )
    await uvicorn.Server(server_config).serve()


async def run_servers() -> None:
    """Run all configured profile listeners in one process."""
    config = get_config()
    _set_active_profiles(None)
    await asyncio.gather(
        *[_serve_profile(name, profile) for name, profile in config.profiles.items()]
    )


async def run_profile_server(profile_name: str) -> None:
    """Run one profile listener as an independent process."""
    config = get_config()
    profile = config.profiles.get(profile_name)
    if profile is None:
        raise ConfigError(f"profile '{profile_name}' is not configured or is invalid")
    _set_active_profiles({profile_name})
    await _serve_profile(profile_name, profile, app_instance=create_profile_app(profile_name))


def main_profile(profile_name: str) -> None:
    """Entry point for independent profile scripts."""
    try:
        asyncio.run(run_profile_server(profile_name))
    except ConfigError as e:
        print(f"[config-error] {e}", file=sys.stderr, flush=True)
        raise SystemExit(1) from e


def main() -> None:
    """主函数"""
    try:
        asyncio.run(run_servers())
    except ConfigError as e:
        print(f"[config-error] {e}", file=sys.stderr, flush=True)
        raise SystemExit(1) from e


if __name__ == "__main__":
    main()
