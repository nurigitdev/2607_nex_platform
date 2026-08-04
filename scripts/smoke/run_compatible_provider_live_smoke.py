#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

import httpx
from jsonschema import Draft202012Validator, ValidationError


ROOT_DIR = Path(__file__).resolve().parents[2]
CONTRACT_ROOT = ROOT_DIR / "contracts"
LIVE_SMOKE_ENV = "NEX_COMPAT_LIVE_SMOKE"
DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_EMBEDDING_MODEL = "Qwen3-Embedding-4B"
DEFAULT_RERANKER_MODEL = "Qwen3-Reranker-0.6B"
DEFAULT_EMBEDDING_DIMENSIONS = 2560
PROTECTED_EVIDENCE_ENV_KEYS = (
    "NEX_COMPAT_EMBEDDING_URL",
    "NEX_COMPAT_EMBEDDING_MODELS_URL",
    "NEX_COMPAT_EMBEDDING_API_KEY",
    "NEX_COMPAT_RERANKER_URL",
    "NEX_COMPAT_RERANKER_MODELS_URL",
    "NEX_COMPAT_RERANKER_API_KEY",
)


HttpRequester = Callable[..., httpx.Response]


@dataclass(frozen=True)
class CompatibleLiveSmokeConfig:
    capability: str
    endpoint_env: str
    url: str
    models_env: str
    models_url: str
    api_key_env: str
    api_key: str | None
    expected_model: str
    expected_dimensions: int | None = None
    request_dimensions: int | None = None
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    @property
    def configured(self) -> bool:
        return bool(self.url and self.models_url)

    @property
    def authorization_configured(self) -> bool:
        return bool(self.api_key)

    def headers(self, *, json_request: bool = False) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if json_request:
            headers["Content-Type"] = "application/json"
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def to_safe_summary(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "capability": self.capability,
            "endpoint_env": self.endpoint_env,
            "models_env": self.models_env,
            "configured": self.configured,
            "runtime_engine": "vllm",
            "request_shape": _request_shape(self.capability),
            "expected_model": self.expected_model,
            "authorization_env": self.api_key_env,
            "authorization_configured": self.authorization_configured,
        }
        if self.expected_dimensions is not None:
            payload["expected_dimensions"] = self.expected_dimensions
        return payload


def run_compatible_provider_live_smoke(
    environ: dict[str, str] | None = None,
    *,
    requester: HttpRequester = httpx.request,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    if env.get(LIVE_SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": "compatible_provider_live_smoke.v1",
            "status": "SKIPPED",
            "skip_reason": f"{LIVE_SMOKE_ENV} is not enabled.",
            "runtime_engine": "vllm",
            "checks": [],
        }

    try:
        configs = build_live_smoke_configs(env)
    except ValueError as exc:
        return {
            "smoke_schema_version": "compatible_provider_live_smoke.v1",
            "status": "FAIL",
            "runtime_engine": "vllm",
            "checks": [
                {
                    "check": "configuration",
                    "status": "FAIL",
                    "failure_code": "configuration_invalid",
                    "detail": str(exc),
                }
            ],
        }

    checks: list[dict[str, Any]] = []
    for config in configs:
        checks.append(run_model_list_check(config, requester=requester))
        checks.append(run_request_check(config, requester=requester))
    return {
        "smoke_schema_version": "compatible_provider_live_smoke.v1",
        "status": "PASS" if all(check["status"] == "PASS" for check in checks) else "FAIL",
        "runtime_engine": "vllm",
        "bf16_evidence_policy": {
            "status": "OUT_OF_BAND",
            "reason": "vLLM OpenAI-compatible HTTP APIs do not expose loaded parameter dtype.",
            "required_operator_check": "confirm vLLM launch args/logs include bfloat16 for embedding and reranker providers",
        },
        "checks": checks,
    }


def build_live_smoke_configs(env: dict[str, str]) -> tuple[CompatibleLiveSmokeConfig, ...]:
    timeout_seconds = float(env.get("NEX_COMPAT_LIVE_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS))
    embedding_url = env.get("NEX_COMPAT_EMBEDDING_URL", "")
    reranker_url = env.get("NEX_COMPAT_RERANKER_URL", "")
    return (
        CompatibleLiveSmokeConfig(
            capability="embedding",
            endpoint_env="NEX_COMPAT_EMBEDDING_URL",
            url=embedding_url,
            models_env="NEX_COMPAT_EMBEDDING_MODELS_URL",
            models_url=env.get(
                "NEX_COMPAT_EMBEDDING_MODELS_URL",
                derive_models_url(embedding_url),
            ),
            api_key_env="NEX_COMPAT_EMBEDDING_API_KEY",
            api_key=_empty_to_none(env.get("NEX_COMPAT_EMBEDDING_API_KEY")),
            expected_model=env.get(
                "NEX_COMPAT_LIVE_EXPECTED_EMBEDDING_MODEL",
                DEFAULT_EMBEDDING_MODEL,
            ),
            expected_dimensions=_positive_int(
                env.get("NEX_COMPAT_LIVE_EXPECTED_EMBEDDING_DIMENSIONS"),
                DEFAULT_EMBEDDING_DIMENSIONS,
            ),
            request_dimensions=_optional_positive_int(
                env.get("NEX_COMPAT_EMBEDDING_REQUEST_DIMENSIONS"),
            ),
            timeout_seconds=timeout_seconds,
        ),
        CompatibleLiveSmokeConfig(
            capability="reranking",
            endpoint_env="NEX_COMPAT_RERANKER_URL",
            url=reranker_url,
            models_env="NEX_COMPAT_RERANKER_MODELS_URL",
            models_url=env.get(
                "NEX_COMPAT_RERANKER_MODELS_URL",
                derive_models_url(reranker_url),
            ),
            api_key_env="NEX_COMPAT_RERANKER_API_KEY",
            api_key=_empty_to_none(env.get("NEX_COMPAT_RERANKER_API_KEY")),
            expected_model=env.get(
                "NEX_COMPAT_LIVE_EXPECTED_RERANKER_MODEL",
                DEFAULT_RERANKER_MODEL,
            ),
            timeout_seconds=timeout_seconds,
        ),
    )


def run_model_list_check(
    config: CompatibleLiveSmokeConfig,
    *,
    requester: HttpRequester,
) -> dict[str, Any]:
    base = {
        **config.to_safe_summary(),
        "check": "model_list",
    }
    if not config.models_url:
        return {**base, "status": "FAIL", "failure_code": "models_url_not_configured"}

    try:
        response = requester(
            "GET",
            config.models_url,
            headers=config.headers(),
            timeout=config.timeout_seconds,
        )
        if response.is_error:
            return {
                **base,
                "status": "FAIL",
                "failure_code": f"http_status_{response.status_code}",
            }
        observed_models = _extract_model_ids(response.json())
    except (httpx.HTTPError, ValueError) as exc:
        return {
            **base,
            "status": "FAIL",
            "failure_code": exc.__class__.__name__,
        }

    missing = config.expected_model not in observed_models
    return {
        **base,
        "status": "FAIL" if missing else "PASS",
        "failure_code": "expected_model_missing" if missing else None,
        "observed": {
            "observed_model_count": len(observed_models),
            "expected_model_present": not missing,
        },
    }


def run_request_check(
    config: CompatibleLiveSmokeConfig,
    *,
    requester: HttpRequester,
) -> dict[str, Any]:
    base = {
        **config.to_safe_summary(),
        "check": "request",
    }
    if not config.url:
        return {**base, "status": "FAIL", "failure_code": "endpoint_not_configured"}

    try:
        response = requester(
            "POST",
            config.url,
            headers=config.headers(json_request=True),
            json=_request_payload(config),
            timeout=config.timeout_seconds,
        )
        if response.is_error:
            return {
                **base,
                "status": "FAIL",
                "failure_code": f"http_status_{response.status_code}",
            }
        payload = _normalize_response(config, response.json())
        _validate_contract(_response_schema_key(config.capability), payload)
    except (httpx.HTTPError, ValueError, ValidationError) as exc:
        return {
            **base,
            "status": "FAIL",
            "failure_code": _failure_code(exc, "response_contract_invalid"),
        }

    issues = _response_semantic_issues(config, payload)
    return {
        **base,
        "status": "PASS" if not issues else "FAIL",
        "failure_code": issues[0] if issues else None,
        "observed": _response_observation(config, payload),
    }


def build_protected_smoke_evidence(
    evidence: dict[str, Any],
    environ: dict[str, str] | None = None,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    protected_evidence = {
        **evidence,
        "evidence_schema_version": "compatible_provider_live_smoke_evidence.v1",
        "evidence_generated_at": _utc_now(),
        "redaction": {
            "status": "PASS",
            "policy": "compatible provider endpoints and credentials are excluded",
            "checked_env_keys": [
                key for key in PROTECTED_EVIDENCE_ENV_KEYS if env.get(key)
            ],
        },
    }
    serialized = json.dumps(protected_evidence, ensure_ascii=False, sort_keys=True)
    assert_smoke_evidence_redacted(serialized, env)
    return protected_evidence


def write_protected_smoke_evidence(
    output_path: Path,
    evidence: dict[str, Any],
    environ: dict[str, str] | None = None,
) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, indent=2)
    assert_smoke_evidence_redacted(
        serialized,
        environ if environ is not None else os.environ,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(f"{serialized}\n", encoding="utf-8")


def assert_smoke_evidence_redacted(
    serialized_evidence: str,
    environ: dict[str, str],
) -> None:
    leaked_keys = [
        key
        for key in PROTECTED_EVIDENCE_ENV_KEYS
        if _protected_env_value_leaked(serialized_evidence, environ.get(key))
    ]
    if leaked_keys:
        raise ValueError(
            "compatible provider live smoke evidence contains unredacted "
            f"environment value: {leaked_keys[0]}"
        )


def derive_models_url(provider_url: str) -> str:
    if not provider_url:
        return ""
    parts = urlsplit(provider_url)
    if not parts.scheme or not parts.netloc:
        return ""
    return urlunsplit((parts.scheme, parts.netloc, "/v1/models", "", ""))


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return f"compatible_provider_live_smoke=skipped reason={LIVE_SMOKE_ENV}"
    passed = sum(1 for check in evidence["checks"] if check["status"] == "PASS")
    total = len(evidence["checks"])
    return f"compatible_provider_live_smoke={evidence['status'].lower()} checks={passed}/{total}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run protected live smoke checks for direct vLLM compatible providers."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    parser.add_argument(
        "--output",
        "--evidence-output",
        dest="output",
        type=Path,
        help="Optional protected JSON evidence output path.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_compatible_provider_live_smoke()
    protected_evidence = build_protected_smoke_evidence(evidence)
    if args.output:
        write_protected_smoke_evidence(args.output, protected_evidence)
    if args.summary:
        print(summary_line(evidence))
    else:
        print(json.dumps(protected_evidence, ensure_ascii=False, indent=2))
    return 0 if evidence["status"] in {"PASS", "SKIPPED"} else 1


def _normalize_response(
    config: CompatibleLiveSmokeConfig,
    payload: Any,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("provider response must be a JSON object")
    if config.capability == "embedding":
        return _normalize_vllm_embedding_response(config, payload)
    return _normalize_vllm_rerank_response(config, payload)


def _normalize_vllm_embedding_response(
    config: CompatibleLiveSmokeConfig,
    payload: dict[str, Any],
) -> dict[str, Any]:
    response_items = payload.get("data")
    if not isinstance(response_items, list) or not response_items:
        raise ValueError("embedding response must include non-empty data")
    return {
        "object": payload.get("object", "list"),
        "model": payload.get("model", config.expected_model),
        "data": response_items,
        "usage": _normalize_usage(payload.get("usage")),
    }


def _normalize_vllm_rerank_response(
    config: CompatibleLiveSmokeConfig,
    payload: dict[str, Any],
) -> dict[str, Any]:
    response_items = payload.get("results", payload.get("data"))
    if not isinstance(response_items, list) or not response_items:
        raise ValueError("rerank response must include non-empty results")
    return {
        "model": payload.get("model", config.expected_model),
        "results": [_normalize_vllm_rerank_item(item) for item in response_items],
        "usage": _normalize_usage(payload.get("usage")),
    }


def _normalize_vllm_rerank_item(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError("rerank result item must be an object")
    index = item.get("index")
    if not isinstance(index, int) or index < 0:
        raise ValueError("rerank result index must be a non-negative integer")
    score = item.get("score", item.get("relevance_score"))
    if not isinstance(score, (int, float)) or isinstance(score, bool):
        raise ValueError("rerank result score must be numeric")
    result = {"index": index, "score": float(score)}
    document = item.get("document")
    if isinstance(document, str):
        result["document"] = document
    elif isinstance(document, dict) and isinstance(document.get("text"), str):
        result["document"] = document["text"]
    return result


def _normalize_usage(usage: Any) -> dict[str, int]:
    if not isinstance(usage, dict):
        return {"prompt_tokens": 0, "total_tokens": 0}
    prompt_tokens = _int_or_zero(usage.get("prompt_tokens"))
    total_tokens = _int_or_zero(usage.get("total_tokens"))
    return {"prompt_tokens": prompt_tokens, "total_tokens": total_tokens}


def _response_semantic_issues(
    config: CompatibleLiveSmokeConfig,
    payload: dict[str, Any],
) -> list[str]:
    issues = []
    if payload.get("model") != config.expected_model:
        issues.append("expected_model_missing")
    if config.capability == "embedding" and config.expected_dimensions is not None:
        dimensions = [
            len(item.get("embedding", []))
            for item in payload.get("data", [])
            if isinstance(item, dict)
        ]
        if dimensions != [config.expected_dimensions]:
            issues.append("embedding_dimension_mismatch")
    return issues


def _response_observation(
    config: CompatibleLiveSmokeConfig,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if config.capability == "embedding":
        data = payload.get("data", [])
        first = data[0] if data else {}
        return {
            "model": payload.get("model"),
            "embedding_count": len(data),
            "embedding_dimensions": len(first.get("embedding", []))
            if isinstance(first, dict)
            else 0,
        }
    return {
        "model": payload.get("model"),
        "result_count": len(payload.get("results", [])),
        "top_index": payload.get("results", [{}])[0].get("index")
        if payload.get("results")
        else None,
    }


def _request_payload(config: CompatibleLiveSmokeConfig) -> dict[str, Any]:
    if config.capability == "embedding":
        payload: dict[str, Any] = {
            "model": config.expected_model,
            "input": ["nex compatible provider live smoke"],
            "encoding_format": "float",
        }
        if config.request_dimensions is not None:
            payload["dimensions"] = config.request_dimensions
        return payload
    return {
        "model": config.expected_model,
        "query": "nex compatible provider live smoke",
        "documents": [
            "NeX compatible provider live smoke document.",
            "Unrelated control document.",
        ],
        "top_n": 1,
    }


def _validate_contract(schema_key: str, payload: dict[str, Any]) -> None:
    schema_paths = {
        "compatible_embedding_response": (
            "schemas/service/nex_mo/compatible_embedding_response.v1.schema.json"
        ),
        "compatible_rerank_response": (
            "schemas/service/nex_mo/compatible_rerank_response.v1.schema.json"
        ),
    }
    schema = json.loads((CONTRACT_ROOT / schema_paths[schema_key]).read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(payload)


def _response_schema_key(capability: str) -> str:
    if capability == "embedding":
        return "compatible_embedding_response"
    return "compatible_rerank_response"


def _request_shape(capability: str) -> str:
    if capability == "embedding":
        return "openai_embeddings"
    return "vllm_rerank"


def _extract_model_ids(payload: Any) -> tuple[str, ...]:
    if not isinstance(payload, dict):
        return ()
    raw_models = payload.get("data", payload.get("models"))
    if not isinstance(raw_models, list):
        return ()
    model_ids: list[str] = []
    for item in raw_models:
        if isinstance(item, str):
            model_ids.append(item)
        elif isinstance(item, dict) and isinstance(item.get("id"), str):
            model_ids.append(item["id"])
    return tuple(model_ids)


def _failure_code(exc: Exception, validation_default: str) -> str:
    if isinstance(exc, ValidationError):
        return validation_default
    return exc.__class__.__name__


def _empty_to_none(value: str | None) -> str | None:
    if value:
        return value
    return None


def _positive_int(raw_value: str | None, default: int) -> int:
    if raw_value is None:
        return default
    value = int(raw_value)
    if value < 1:
        raise ValueError("integer value must be positive")
    return value


def _optional_positive_int(raw_value: str | None) -> int | None:
    if raw_value is None or raw_value == "":
        return None
    return _positive_int(raw_value, 1)


def _int_or_zero(value: Any) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return 0


def _protected_env_value_leaked(
    serialized_evidence: str,
    value: str | None,
) -> bool:
    return bool(value) and len(value) >= 8 and value in serialized_evidence


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
