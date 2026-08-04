from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR / "services" / "_shared"))
sys.path.insert(0, str(ROOT_DIR / "services" / "nex-mo"))
sys.path.insert(0, str(ROOT_DIR / "scripts" / "smoke"))

import check_local_live_provider_config as local_config
import run_dgx_live_provider_preflight as dgx_preflight

PROFILE_ENV = "NEX_MO_PROTECTED_LIVE_PROFILE"
DGX_PROFILE_NAME = "dgx_vllm"
DGX_PROFILE_ALIAS = "dgx"
DGX_PCX_LEGACY_PROFILE_NAME = "dgx_pcx_legacy"
SUPPORTED_PROFILE_NAMES = (
    DGX_PROFILE_NAME,
    DGX_PCX_LEGACY_PROFILE_NAME,
    DGX_PROFILE_ALIAS,
)
PROTECTED_PROFILE_ENV_KEYS = tuple(
    dict.fromkeys(
        (
            *local_config.PROTECTED_CONFIG_ENV_KEYS,
            *dgx_preflight.PROTECTED_EVIDENCE_ENV_KEYS,
        )
    )
)


def run_protected_dgx_live_profile(
    environ: dict[str, str] | None = None,
    *,
    requester=None,
    profile_name: str | None = None,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    requested_profile = profile_name if profile_name is not None else env.get(PROFILE_ENV, "")
    resolved_profile = resolve_profile_name(requested_profile)
    if not requested_profile:
        return _profile_evidence(
            status="SKIPPED",
            requested_profile=requested_profile,
            resolved_profile=resolved_profile,
            effective_env=env,
            config_snapshot=None,
            preflight_evidence=None,
            issues=[
                {
                    "stage": "profile_activation",
                    "error_code": "protected_profile_not_enabled",
                    "detail": f"{PROFILE_ENV} is not set.",
                }
            ],
        )
    if resolved_profile is None:
        return _profile_evidence(
            status="FAIL",
            requested_profile=requested_profile,
            resolved_profile=resolved_profile,
            effective_env=env,
            config_snapshot=None,
            preflight_evidence=None,
            issues=[
                {
                    "stage": "profile_activation",
                    "error_code": "protected_profile_unsupported",
                    "detail": f"Unsupported protected live profile: {requested_profile}",
                }
            ],
        )

    effective_env = {
        **protected_profile_defaults(resolved_profile),
        **env,
        "NEX_MO_PROVIDER_MODE": "live",
        "NEX_MO_LIVE_PREFLIGHT": "1",
    }
    config_snapshot = local_config.build_local_live_provider_config_snapshot(
        effective_env,
    )
    if config_snapshot["status"] != "PASS":
        return _profile_evidence(
            status="FAIL",
            requested_profile=requested_profile,
            resolved_profile=resolved_profile,
            effective_env=effective_env,
            config_snapshot=config_snapshot,
            preflight_evidence=None,
            issues=_stage_issues("local_live_config", config_snapshot),
        )

    preflight = dgx_preflight.run_dgx_live_provider_preflight(
        effective_env,
        requester=requester,
    )
    protected_preflight = dgx_preflight.build_protected_preflight_evidence(
        preflight,
        effective_env,
    )
    return _profile_evidence(
        status="PASS" if preflight["status"] == "PASS" else "FAIL",
        requested_profile=requested_profile,
        resolved_profile=resolved_profile,
        effective_env=effective_env,
        config_snapshot=config_snapshot,
        preflight_evidence=protected_preflight,
        issues=_stage_issues("dgx_live_preflight", protected_preflight),
    )


def _profile_evidence(
    *,
    status: str,
    requested_profile: str,
    resolved_profile: str | None,
    effective_env: dict[str, str],
    config_snapshot: dict[str, Any] | None,
    preflight_evidence: dict[str, Any] | None,
    issues: list[dict[str, Any]],
) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "profile_schema_version": "protected_dgx_live_profile.v1",
        "evidence_generated_at": _utc_now(),
        "status": status,
        "profile": {
            "activation_env": PROFILE_ENV,
            "activation_value": DGX_PROFILE_NAME,
            "legacy_activation_value": DGX_PCX_LEGACY_PROFILE_NAME,
            "accepted_values": list(SUPPORTED_PROFILE_NAMES),
            "requested_profile": requested_profile,
            "resolved_profile": resolved_profile,
            "enabled": resolved_profile is not None,
        },
        "effective_flags": {
            "NEX_MO_PROVIDER_MODE": effective_env.get("NEX_MO_PROVIDER_MODE"),
            "NEX_MO_LIVE_PREFLIGHT": effective_env.get("NEX_MO_LIVE_PREFLIGHT"),
        },
        "stage_status": {
            "local_live_config": _optional_status(config_snapshot),
            "dgx_live_preflight": _optional_status(preflight_evidence),
        },
        "config_snapshot": config_snapshot,
        "preflight_evidence": preflight_evidence,
        "issues": issues,
        "redaction": {
            "status": "PASS",
            "policy": "provider endpoints and credentials are excluded",
            "checked_env_keys": [
                key for key in PROTECTED_PROFILE_ENV_KEYS if effective_env.get(key)
            ],
        },
    }
    assert_profile_evidence_redacted(
        json.dumps(evidence, ensure_ascii=False, sort_keys=True),
        effective_env,
    )
    return evidence


def protected_dgx_profile_defaults() -> dict[str, str]:
    return protected_dgx_vllm_profile_defaults()


def protected_profile_defaults(profile_name: str) -> dict[str, str]:
    if profile_name == DGX_PCX_LEGACY_PROFILE_NAME:
        return protected_dgx_pcx_legacy_profile_defaults()
    return protected_dgx_vllm_profile_defaults()


def resolve_profile_name(requested_profile: str) -> str | None:
    if requested_profile == DGX_PROFILE_ALIAS:
        return DGX_PROFILE_NAME
    if requested_profile in {DGX_PROFILE_NAME, DGX_PCX_LEGACY_PROFILE_NAME}:
        return requested_profile
    return None


def protected_dgx_vllm_profile_defaults() -> dict[str, str]:
    return {
        "NEX_MO_REMOTE_EMBEDDING_REQUEST_SHAPE": "openai_embeddings",
        "NEX_MO_REMOTE_EMBEDDING_MODEL": "Qwen3-Embedding-4B",
        "NEX_MO_REMOTE_EMBEDDING_MODEL_REVISION": "Qwen3-Embedding-4B",
        "NEX_MO_REMOTE_EMBEDDING_DEPLOYMENT_ID": "vllm-embedding-http",
        "NEX_MO_LIVE_EXPECTED_EMBEDDING_MODELS": "Qwen3-Embedding-4B",
        "NEX_MO_REMOTE_RERANKER_REQUEST_SHAPE": "rerank",
        "NEX_MO_REMOTE_RERANKER_MODEL": "Qwen3-Reranker-0.6B",
        "NEX_MO_REMOTE_RERANKER_MODEL_REVISION": "Qwen3-Reranker-0.6B",
        "NEX_MO_REMOTE_RERANKER_DEPLOYMENT_ID": "vllm-reranker-http",
        "NEX_MO_LIVE_EXPECTED_RERANKER_MODELS": "Qwen3-Reranker-0.6B",
        "NEX_MO_VLLM_MODEL": "Qwen3.5-122B-A10B-NVFP4",
        "NEX_MO_VLLM_MODEL_REVISION": "Qwen3.5-122B-A10B-NVFP4",
        "NEX_MO_VLLM_DEPLOYMENT_ID": "vllm-generation-http",
        "NEX_MO_LIVE_EXPECTED_GENERATION_MODELS": "Qwen3.5-122B-A10B-NVFP4",
    }


def protected_dgx_pcx_legacy_profile_defaults() -> dict[str, str]:
    return {
        "NEX_MO_REMOTE_EMBEDDING_REQUEST_SHAPE": "nex_pcx_embeddings_v1",
        "NEX_MO_REMOTE_EMBEDDING_MODEL": "Qwen3-embedding-4B",
        "NEX_MO_REMOTE_EMBEDDING_MODEL_REVISION": "Qwen3-embedding-4B",
        "NEX_MO_REMOTE_EMBEDDING_DEPLOYMENT_ID": "remote-embedding-http",
        "NEX_MO_LIVE_EXPECTED_EMBEDDING_MODELS": "Qwen3-embedding-4B",
        "NEX_MO_REMOTE_EMBEDDING_PROFILE_NAME": "qwen3_4b_2560",
        "NEX_MO_REMOTE_EMBEDDING_MODEL_KEY": "qwen3_embedding_4b",
        "NEX_MO_REMOTE_EMBEDDING_INPUT_TYPE": "document",
        "NEX_MO_REMOTE_EMBEDDING_OUTPUT_DIMENSION": "2560",
        "NEX_MO_REMOTE_EMBEDDING_NORMALIZE": "true",
        "NEX_MO_REMOTE_RERANKER_REQUEST_SHAPE": "nex_pcx_rerank_v1",
        "NEX_MO_REMOTE_RERANKER_MODEL": "Qwen3-Reranker-0.6B",
        "NEX_MO_REMOTE_RERANKER_MODEL_REVISION": "Qwen3-Reranker-0.6B",
        "NEX_MO_REMOTE_RERANKER_DEPLOYMENT_ID": "remote-reranker-http",
        "NEX_MO_LIVE_EXPECTED_RERANKER_MODELS": "Qwen3-Reranker-0.6B",
        "NEX_MO_REMOTE_RERANKER_PROFILE_NAME": "qwen3_reranker_0_6b",
        "NEX_MO_REMOTE_RERANKER_MODEL_ID": "Qwen/Qwen3-Reranker-0.6B",
        "NEX_MO_REMOTE_RERANKER_SOURCE_PROFILE_NAME": "qwen3_4b_2560",
        "NEX_MO_REMOTE_RERANKER_SOURCE_RETRIEVAL_STRATEGY": "preflight",
        "NEX_MO_REMOTE_RERANKER_SOURCE_SCORE": "0.5",
        "NEX_MO_VLLM_MODEL": "Qwen3.5-122B-A10B-NVFP4",
        "NEX_MO_VLLM_MODEL_REVISION": "Qwen3.5-122B-A10B-NVFP4",
        "NEX_MO_VLLM_DEPLOYMENT_ID": "vllm-generation-http",
        "NEX_MO_LIVE_EXPECTED_GENERATION_MODELS": "Qwen3.5-122B-A10B-NVFP4",
    }


def _optional_status(payload: dict[str, Any] | None) -> str:
    if payload is None:
        return "NOT_RUN"
    return str(payload.get("status", "UNKNOWN"))


def _stage_issues(stage: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    if payload["status"] == "PASS":
        return []
    if stage == "local_live_config":
        return [
            {
                "stage": stage,
                "error_code": issue.get("error_code", "local_live_config_failed"),
                "capability": issue.get("capability"),
            }
            for issue in payload.get("issues", [])
        ]
    return [
        {
            "stage": stage,
            "error_code": check.get("failure_code", "dgx_live_preflight_failed"),
            "capability": check.get("capability"),
        }
        for check in payload.get("checks", [])
        if check.get("status") != "PASS"
    ]


def write_profile_evidence(
    output_path: Path,
    evidence: dict[str, Any],
    environ: dict[str, str] | None = None,
) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, indent=2)
    assert_profile_evidence_redacted(
        serialized,
        environ if environ is not None else os.environ,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(f"{serialized}\n", encoding="utf-8")


def assert_profile_evidence_redacted(
    serialized_evidence: str,
    environ: dict[str, str],
) -> None:
    leaked_keys = [
        key
        for key in PROTECTED_PROFILE_ENV_KEYS
        if _protected_env_value_leaked(serialized_evidence, environ.get(key))
    ]
    if leaked_keys:
        raise ValueError(
            f"protected live profile evidence contains unredacted environment value: {leaked_keys[0]}"
        )


def _protected_env_value_leaked(
    serialized_evidence: str,
    value: str | None,
) -> bool:
    return bool(value) and len(value) >= 8 and value in serialized_evidence


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return f"protected_dgx_live_profile=skipped reason={PROFILE_ENV}"
    return (
        f"protected_dgx_live_profile={evidence['status'].lower()} "
        f"config={evidence['stage_status']['local_live_config']} "
        f"preflight={evidence['stage_status']['dgx_live_preflight']}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the protected DGX live provider profile."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    parser.add_argument("--output", type=Path, help="Optional protected JSON output path.")
    parser.add_argument(
        "--profile",
        help=f"Protected live profile name. Defaults to {PROFILE_ENV}.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_protected_dgx_live_profile(profile_name=args.profile)
    if args.output:
        write_profile_evidence(args.output, evidence)
    if args.summary:
        print(summary_line(evidence))
    else:
        print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0 if evidence["status"] in {"PASS", "SKIPPED"} else 1


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
