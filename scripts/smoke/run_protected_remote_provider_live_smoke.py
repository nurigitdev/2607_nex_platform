#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

import httpx

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR / "services" / "_shared"))
sys.path.insert(0, str(ROOT_DIR / "services" / "nex-mo"))
sys.path.insert(0, str(ROOT_DIR / "scripts" / "smoke"))

import nex_mo.remote_provider as remote_provider
from nex_mo.providers import ProviderRouteError
from run_protected_dgx_live_profile import protected_dgx_vllm_profile_defaults

LIVE_SMOKE_ENV = "NEX_PROTECTED_REMOTE_PROVIDER_LIVE_SMOKE"
SMOKE_SCHEMA_VERSION = "protected_remote_provider_live_smoke.v1"
EVIDENCE_SCHEMA_VERSION = "protected_remote_provider_live_smoke_evidence.v1"
TRACE_ID = "6f2dfc8543574b64a228f56b26209168"
REQUEST_ID = "5ed0aa88-03fe-4db2-a18c-9f7b664e0e41"
EMBEDDING_INPUTS = [
    "NeX protected remote provider live smoke embedding input A.",
    "NeX protected remote provider live smoke embedding input B.",
]
RERANK_QUERY = "NeX protected remote provider live smoke rerank query"
RERANK_DOCUMENTS = [
    "Remote provider live smoke document about NeX retrieval.",
    "Control document for a different topic.",
]
GENERATION_PROMPT = (
    "Return the exact phrase 'remote provider live smoke ok' and no extra text."
)
PROTECTED_ENV_KEYS = (
    "NEX_MO_REMOTE_EMBEDDING_URL",
    "NEX_MO_REMOTE_EMBEDDING_API_KEY",
    "NEX_MO_REMOTE_RERANKER_URL",
    "NEX_MO_REMOTE_RERANKER_API_KEY",
    "NEX_MO_VLLM_BASE_URL",
    "NEX_MO_VLLM_MODELS_URL",
    "NEX_MO_VLLM_CHAT_COMPLETIONS_URL",
    "NEX_MO_VLLM_API_KEY",
    "NEX_MO_LIVE_EMBEDDING_HEALTH_URL",
    "NEX_MO_LIVE_RERANKER_HEALTH_URL",
    "NEX_MO_LIVE_VLLM_MODELS_URL",
)

HttpRequester = Callable[..., httpx.Response]


def run_protected_remote_provider_live_smoke(
    environ: dict[str, str] | None = None,
    *,
    requester: HttpRequester | None = None,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    if env.get(LIVE_SMOKE_ENV) != "1":
        return build_evidence(
            status="SKIPPED",
            env=env,
            effective_env=env,
            stage_status={"activation": "SKIPPED"},
            provider_evidence=None,
            issues=[
                {
                    "stage": "activation",
                    "error_code": "protected_remote_provider_live_smoke_not_enabled",
                    "detail": f"{LIVE_SMOKE_ENV} is not enabled.",
                }
            ],
        )

    effective_env = {
        **protected_dgx_vllm_profile_defaults(),
        **env,
        "NEX_MO_PROVIDER_MODE": "live",
    }
    issues = configuration_issues(effective_env)
    if issues:
        return build_evidence(
            status="FAIL",
            env=env,
            effective_env=effective_env,
            stage_status={"activation": "PASS", "configuration": "FAIL"},
            provider_evidence=None,
            issues=issues,
        )

    remote_provider.reset_remote_provider_telemetry()
    stage_status = {
        "activation": "PASS",
        "configuration": "PASS",
        "embedding": "NOT_RUN",
        "reranking": "NOT_RUN",
        "generation": "NOT_RUN",
        "assertions": "NOT_RUN",
    }
    provider_evidence: dict[str, Any] = {
        "smoke_schema_version": SMOKE_SCHEMA_VERSION,
        "trace_id": TRACE_ID,
        "request_id": REQUEST_ID,
        "providers": {},
        "telemetry": [],
        "assertions": {},
    }

    try:
        embedding = run_embedding_check(effective_env, requester=requester)
        stage_status["embedding"] = "PASS"
        provider_evidence["providers"]["embedding"] = embedding

        reranking = run_reranker_check(effective_env, requester=requester)
        stage_status["reranking"] = "PASS"
        provider_evidence["providers"]["reranking"] = reranking

        generation = run_generation_check(effective_env, requester=requester)
        stage_status["generation"] = "PASS"
        provider_evidence["providers"]["generation"] = generation

        provider_evidence["telemetry"] = telemetry_summary(effective_env)
        provider_evidence["assertions"] = assert_provider_evidence(provider_evidence)
        stage_status["assertions"] = "PASS"
        return build_evidence(
            status="PASS",
            env=env,
            effective_env=effective_env,
            stage_status=stage_status,
            provider_evidence=provider_evidence,
            issues=[],
        )
    except Exception as exc:
        failed_stage = next(
            (
                stage
                for stage in ("embedding", "reranking", "generation", "assertions")
                if stage_status[stage] == "NOT_RUN"
            ),
            "assertions",
        )
        stage_status[failed_stage] = "FAIL"
        provider_evidence["telemetry"] = telemetry_summary(effective_env)
        return build_evidence(
            status="FAIL",
            env=env,
            effective_env=effective_env,
            stage_status=stage_status,
            provider_evidence=provider_evidence,
            issues=[safe_issue(failed_stage, exc)],
        )


def configuration_issues(env: dict[str, str]) -> list[dict[str, str]]:
    required = {
        "NEX_MO_REMOTE_EMBEDDING_URL": bool(env.get("NEX_MO_REMOTE_EMBEDDING_URL")),
        "NEX_MO_REMOTE_RERANKER_URL": bool(env.get("NEX_MO_REMOTE_RERANKER_URL")),
        "NEX_MO_VLLM_GENERATION_URL": bool(
            env.get("NEX_MO_VLLM_CHAT_COMPLETIONS_URL")
            or env.get("NEX_MO_VLLM_BASE_URL")
        ),
    }
    issues = [
        {
            "stage": "configuration",
            "error_code": "provider_endpoint_missing",
            "detail": f"{key} is required for protected remote provider live smoke.",
        }
        for key, configured in required.items()
        if not configured
    ]
    if env.get("NEX_MO_REMOTE_EMBEDDING_REQUEST_SHAPE") != "openai_embeddings":
        issues.append(
            {
                "stage": "configuration",
                "error_code": "embedding_request_shape_not_compatible",
                "detail": "Embedding request shape must be openai_embeddings.",
            }
        )
    if env.get("NEX_MO_REMOTE_RERANKER_REQUEST_SHAPE") != "rerank":
        issues.append(
            {
                "stage": "configuration",
                "error_code": "reranker_request_shape_not_compatible",
                "detail": "Reranker request shape must be rerank.",
            }
        )
    return issues


def run_embedding_check(
    env: dict[str, str],
    *,
    requester: HttpRequester | None,
) -> dict[str, Any]:
    response = remote_provider.execute_remote_embedding_request(
        {
            "alias": "mock-embedding-default",
            "inputs": EMBEDDING_INPUTS,
        },
        environ=env,
        requester=requester,
    )
    data = response.get("data", [])
    dimensions = [
        len(item.get("embedding", []))
        for item in data
        if isinstance(item, dict)
    ]
    if len(data) != len(EMBEDDING_INPUTS) or not dimensions or min(dimensions) < 1:
        raise AssertionError("embedding response count or dimension mismatch")
    return {
        "capability": "embedding",
        "status": "PASS",
        "request_shape": env["NEX_MO_REMOTE_EMBEDDING_REQUEST_SHAPE"],
        "model_revision": response["model_revision"],
        "deployment_id": response["deployment_id"],
        "observed": {
            "embedding_count": len(data),
            "embedding_dimensions": dimensions[0],
            "usage": response.get("usage", {}),
        },
    }


def run_reranker_check(
    env: dict[str, str],
    *,
    requester: HttpRequester | None,
) -> dict[str, Any]:
    response = remote_provider.execute_remote_rerank_request(
        {
            "alias": "mock-reranker-default",
            "query": RERANK_QUERY,
            "documents": RERANK_DOCUMENTS,
            "top_n": 2,
        },
        environ=env,
        requester=requester,
    )
    results = response.get("results", [])
    if not results:
        raise AssertionError("reranker response had no results")
    first = results[0]
    if not isinstance(first.get("index"), int):
        raise AssertionError("reranker top result index missing")
    return {
        "capability": "reranking",
        "status": "PASS",
        "request_shape": env["NEX_MO_REMOTE_RERANKER_REQUEST_SHAPE"],
        "model_revision": response["model_revision"],
        "deployment_id": response["deployment_id"],
        "observed": {
            "result_count": len(results),
            "top_index": first["index"],
            "top_score": first["score"],
            "usage": response.get("usage", {}),
        },
    }


def run_generation_check(
    env: dict[str, str],
    *,
    requester: HttpRequester | None,
) -> dict[str, Any]:
    response = remote_provider.execute_remote_generation_request(
        {
            "alias": "general-llm-default",
            "provider_capability": "generation",
            "prompt": GENERATION_PROMPT,
            "temperature": 0.0,
            "max_output_tokens": 32,
        },
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        environ=env,
        requester=requester,
    )
    output = response.get("output", {})
    output_text = output.get("text") if isinstance(output, dict) else None
    if not isinstance(output_text, str) or not output_text.strip():
        raise AssertionError("generation response output text missing")
    return {
        "capability": "generation",
        "status": "PASS",
        "request_shape": "openai_chat_completions",
        "model_revision": response["model_revision"],
        "deployment_id": response["deployment_id"],
        "observed": {
            "mo_generation_id": response["mo_generation_id"],
            "finish_reason": response["finish_reason"],
            "output_length": len(output_text),
            "usage": response.get("usage", {}),
        },
    }


def telemetry_summary(env: dict[str, str]) -> list[dict[str, Any]]:
    return [
        {
            "capability": item["capability"],
            "configured": item["configured"],
            "request_shape": item["request_shape"],
            "model_name": item["model_name"],
            "model_revision": item["model_revision"],
            "deployment_id": item["deployment_id"],
            "authorization_env": item["authorization_env"],
            "authorization_configured": item["authorization_configured"],
            "request_count": item["request_count"],
            "success_count": item["success_count"],
            "failure_count": item["failure_count"],
            "retryable_failure_count": item["retryable_failure_count"],
            "degraded_count": item["degraded_count"],
            "last_outcome": item["last_outcome"],
            "last_latency_ms": item["last_latency_ms"],
            "last_error_code": item["last_error_code"],
            "last_failure_kind": item["last_failure_kind"],
        }
        for item in remote_provider.list_remote_provider_telemetry(environ=env)
    ]


def assert_provider_evidence(provider_evidence: dict[str, Any]) -> dict[str, bool]:
    providers = provider_evidence["providers"]
    telemetry = {
        item["capability"]: item for item in provider_evidence.get("telemetry", [])
    }
    assertions = {
        "embedding_observed": providers["embedding"]["observed"]["embedding_count"]
        == len(EMBEDDING_INPUTS),
        "embedding_dimension_observed": providers["embedding"]["observed"][
            "embedding_dimensions"
        ]
        > 0,
        "reranking_observed": providers["reranking"]["observed"]["result_count"] >= 1,
        "generation_observed": providers["generation"]["observed"]["output_length"] > 0,
        "embedding_telemetry_success": telemetry["embedding"]["success_count"] == 1,
        "reranking_telemetry_success": telemetry["reranking"]["success_count"] == 1,
        "generation_telemetry_success": telemetry["generation"]["success_count"] == 1,
    }
    if not all(assertions.values()):
        raise AssertionError(f"protected remote provider evidence mismatch: {assertions}")
    return assertions


def build_evidence(
    *,
    status: str,
    env: dict[str, str],
    effective_env: dict[str, str],
    stage_status: dict[str, str],
    provider_evidence: dict[str, Any] | None,
    issues: list[dict[str, Any]],
) -> dict[str, Any]:
    evidence = {
        "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
        "evidence_generated_at": _utc_now(),
        "status": status,
        "activation": {
            "env": LIVE_SMOKE_ENV,
            "enabled": env.get(LIVE_SMOKE_ENV) == "1",
            "required_profile": "dgx_vllm",
        },
        "provider_config": {
            "embedding": provider_config_summary(
                effective_env,
                endpoint_env="NEX_MO_REMOTE_EMBEDDING_URL",
                model_env="NEX_MO_REMOTE_EMBEDDING_MODEL",
                request_shape_env="NEX_MO_REMOTE_EMBEDDING_REQUEST_SHAPE",
                api_key_env="NEX_MO_REMOTE_EMBEDDING_API_KEY",
            ),
            "reranking": provider_config_summary(
                effective_env,
                endpoint_env="NEX_MO_REMOTE_RERANKER_URL",
                model_env="NEX_MO_REMOTE_RERANKER_MODEL",
                request_shape_env="NEX_MO_REMOTE_RERANKER_REQUEST_SHAPE",
                api_key_env="NEX_MO_REMOTE_RERANKER_API_KEY",
            ),
            "generation": {
                "configured": bool(
                    effective_env.get("NEX_MO_VLLM_CHAT_COMPLETIONS_URL")
                    or effective_env.get("NEX_MO_VLLM_BASE_URL")
                ),
                "endpoint_env": "NEX_MO_VLLM_CHAT_COMPLETIONS_URL",
                "base_url_env": "NEX_MO_VLLM_BASE_URL",
                "model": effective_env.get("NEX_MO_VLLM_MODEL"),
                "request_shape": "openai_chat_completions",
                "authorization_env": "NEX_MO_VLLM_API_KEY",
                "authorization_configured": bool(effective_env.get("NEX_MO_VLLM_API_KEY")),
            },
        },
        "stage_status": stage_status,
        "provider_evidence": provider_evidence,
        "issues": issues,
        "redaction": {
            "status": "PASS",
            "policy": (
                "provider endpoints, credentials, raw smoke prompts, generation output, "
                "rerank documents, and embedding vectors are excluded"
            ),
            "checked_env_keys": [
                key for key in PROTECTED_ENV_KEYS if effective_env.get(key)
            ],
        },
    }
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
    assert_evidence_redacted(serialized, effective_env)
    return evidence


def provider_config_summary(
    env: dict[str, str],
    *,
    endpoint_env: str,
    model_env: str,
    request_shape_env: str,
    api_key_env: str,
) -> dict[str, Any]:
    return {
        "configured": bool(env.get(endpoint_env)),
        "endpoint_env": endpoint_env,
        "model": env.get(model_env),
        "request_shape": env.get(request_shape_env),
        "authorization_env": api_key_env,
        "authorization_configured": bool(env.get(api_key_env)),
    }


def safe_issue(stage: str, exc: Exception) -> dict[str, Any]:
    if isinstance(exc, ProviderRouteError):
        issue = {
            "stage": stage,
            "error_code": exc.error_code,
            "status_code": exc.status_code,
            "retryable": exc.retryable,
            "degraded": exc.degraded,
        }
        if exc.failure_kind:
            issue["failure_kind"] = exc.failure_kind
        if exc.upstream_status_code is not None:
            issue["upstream_status_code"] = exc.upstream_status_code
        return issue
    return {
        "stage": stage,
        "error_code": exc.__class__.__name__,
    }


def assert_evidence_redacted(serialized_evidence: str, env: dict[str, str]) -> None:
    leaked_values = [
        key
        for key in PROTECTED_ENV_KEYS
        if _protected_value_leaked(serialized_evidence, env.get(key))
    ]
    if leaked_values:
        raise ValueError(
            "protected remote provider live smoke evidence contains unredacted "
            f"environment value: {leaked_values[0]}"
        )
    leaked_smoke_inputs = [
        label
        for label, value in {
            "embedding_input": EMBEDDING_INPUTS[0],
            "rerank_query": RERANK_QUERY,
            "rerank_document": RERANK_DOCUMENTS[0],
            "generation_prompt": GENERATION_PROMPT,
        }.items()
        if value in serialized_evidence
    ]
    if leaked_smoke_inputs:
        raise ValueError(
            "protected remote provider live smoke evidence contains raw smoke input: "
            f"{leaked_smoke_inputs[0]}"
        )


def write_evidence(output_path: Path, evidence: dict[str, Any], env: dict[str, str] | None = None) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, indent=2)
    assert_evidence_redacted(serialized, env if env is not None else os.environ)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(f"{serialized}\n", encoding="utf-8")


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return f"protected_remote_provider_live_smoke=skipped reason={LIVE_SMOKE_ENV}"
    if evidence["status"] == "FAIL":
        failed = [
            stage
            for stage, status in evidence.get("stage_status", {}).items()
            if status == "FAIL"
        ]
        failed_stages = ",".join(failed) if failed else "unknown"
        return f"protected_remote_provider_live_smoke=fail failed_stages={failed_stages}"
    providers = evidence["provider_evidence"]["providers"]
    return (
        "protected_remote_provider_live_smoke=pass "
        f"embedding_dim={providers['embedding']['observed']['embedding_dimensions']} "
        f"rerank_top={providers['reranking']['observed']['top_index']} "
        f"generation_finish={providers['generation']['observed']['finish_reason']}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run protected live smoke checks against remote MO providers."
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
    evidence = run_protected_remote_provider_live_smoke()
    if args.output:
        write_evidence(args.output, evidence)
    if args.summary:
        print(summary_line(evidence))
    else:
        print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0 if evidence["status"] in {"PASS", "SKIPPED"} else 1


def _protected_value_leaked(serialized_evidence: str, value: str | None) -> bool:
    return bool(value) and len(value) >= 8 and value in serialized_evidence


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
