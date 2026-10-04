from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os
from urllib.parse import urlsplit


SERVICE_ENDPOINTS = {
    "nex-oa": ("NEX_OA_BASE_URL", "http://127.0.0.1:8101"),
    "nex-ag": ("NEX_AG_BASE_URL", "http://127.0.0.1:8102"),
    "nex-ae-api": ("NEX_AE_API_BASE_URL", "http://127.0.0.1:8103"),
    "nex-cx": ("NEX_CX_BASE_URL", "http://127.0.0.1:8104"),
    "nex-mo": ("NEX_MO_BASE_URL", "http://127.0.0.1:8105"),
}

PROVIDER_TIMEOUT_SETTINGS = {
    "embedding": (
        "NEX_MO_REMOTE_EMBEDDING_TIMEOUT_SECONDS",
        "NEX_MO_EMBEDDING_MAX_ATTEMPTS",
        "NEX_CX_MO_EMBEDDING_TIMEOUT_SECONDS",
        15.0,
        3,
    ),
    "reranking": (
        "NEX_MO_REMOTE_RERANKER_TIMEOUT_SECONDS",
        "NEX_MO_RERANKER_MAX_ATTEMPTS",
        "NEX_CX_MO_RERANKER_TIMEOUT_SECONDS",
        15.0,
        3,
    ),
    "generation": (
        "NEX_MO_VLLM_TIMEOUT_SECONDS",
        "NEX_MO_GENERATION_MAX_ATTEMPTS",
        "NEX_CX_MO_GENERATION_TIMEOUT_SECONDS",
        60.0,
        2,
    ),
}
DEFAULT_RETRY_AFTER_MAX_SECONDS = 5.0
DEFAULT_TIMEOUT_SAFETY_MARGIN_SECONDS = 5.0
DEFAULT_CX_MO_TIMEOUT_SECONDS = {
    "embedding": 60.0,
    "reranking": 60.0,
    "generation": 130.0,
}


class RuntimeEndpointPolicyError(ValueError):
    pass


@dataclass(frozen=True)
class ServiceEndpointResolution:
    service_id: str
    environment_name: str
    base_url: str


@dataclass(frozen=True)
class ProviderTimeoutBudget:
    capability: str
    upstream_timeout_seconds: float
    max_attempts: int
    retry_after_max_seconds: float
    safety_margin_seconds: float
    minimum_client_timeout_seconds: float
    client_timeout_seconds: float


def resolve_service_endpoint(
    service_id: str,
    *,
    environ: Mapping[str, str] | None = None,
) -> ServiceEndpointResolution:
    try:
        environment_name, default_url = SERVICE_ENDPOINTS[service_id]
    except KeyError as exc:
        raise RuntimeEndpointPolicyError(
            f"unsupported service endpoint: {service_id}"
        ) from exc
    env = os.environ if environ is None else environ
    base_url = (env.get(environment_name) or default_url).strip().rstrip("/")
    if not _safe_base_url(base_url):
        raise RuntimeEndpointPolicyError(
            f"invalid service endpoint configuration: {environment_name}"
        )
    return ServiceEndpointResolution(service_id, environment_name, base_url)


def resolve_cx_mo_timeout_budget(
    capability: str,
    *,
    environ: Mapping[str, str] | None = None,
) -> ProviderTimeoutBudget:
    try:
        (
            upstream_env,
            attempts_env,
            client_env,
            default_upstream,
            default_attempts,
        ) = PROVIDER_TIMEOUT_SETTINGS[capability]
    except KeyError as exc:
        raise RuntimeEndpointPolicyError(
            f"unsupported provider capability: {capability}"
        ) from exc
    env = os.environ if environ is None else environ
    upstream = _positive_float(env, upstream_env, default_upstream)
    attempts = _positive_int(env, attempts_env, default_attempts)
    retry_after = _positive_float(
        env,
        "NEX_MO_RETRY_AFTER_MAX_SECONDS",
        DEFAULT_RETRY_AFTER_MAX_SECONDS,
    )
    safety_margin = _positive_float(
        env,
        "NEX_CX_MO_TIMEOUT_SAFETY_MARGIN_SECONDS",
        DEFAULT_TIMEOUT_SAFETY_MARGIN_SECONDS,
    )
    minimum = upstream * attempts + retry_after * max(0, attempts - 1) + safety_margin
    client_timeout = _positive_float(
        env,
        client_env,
        DEFAULT_CX_MO_TIMEOUT_SECONDS[capability],
    )
    if client_timeout < minimum:
        raise RuntimeEndpointPolicyError(
            f"{client_env} must be at least {minimum:g} seconds"
        )
    return ProviderTimeoutBudget(
        capability=capability,
        upstream_timeout_seconds=upstream,
        max_attempts=attempts,
        retry_after_max_seconds=retry_after,
        safety_margin_seconds=safety_margin,
        minimum_client_timeout_seconds=minimum,
        client_timeout_seconds=client_timeout,
    )


def _positive_float(
    env: Mapping[str, str], name: str, default: float
) -> float:
    raw = env.get(name)
    try:
        value = default if raw is None or not raw.strip() else float(raw)
    except (AttributeError, ValueError) as exc:
        raise RuntimeEndpointPolicyError(f"{name} must be numeric") from exc
    if value <= 0:
        raise RuntimeEndpointPolicyError(f"{name} must be positive")
    return value


def _positive_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    try:
        value = default if raw is None or not raw.strip() else int(raw)
    except (AttributeError, ValueError) as exc:
        raise RuntimeEndpointPolicyError(f"{name} must be an integer") from exc
    if value <= 0:
        raise RuntimeEndpointPolicyError(f"{name} must be positive")
    return value


def _safe_base_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme in {"http", "https"}
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
        and parsed.path in {"", "/"}
        and not parsed.query
        and not parsed.fragment
        and (port is None or 1 <= port <= 65535)
    )
