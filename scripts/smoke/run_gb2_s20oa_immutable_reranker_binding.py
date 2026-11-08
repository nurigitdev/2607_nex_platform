#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "_shared",
    ROOT / "services" / "nex-mo",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

from nex_mo.provider_registry import ProviderRouteError  # noqa: E402
from nex_mo.remote_provider import (  # noqa: E402
    build_remote_reranker_execution_config,
    execute_remote_rerank_request,
)
from nex_runtime import (  # noqa: E402
    ModelArtifactRevisionError,
    admit_model_artifact_revision_evidence,
    model_artifact_revision_evidence_digest,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref  # noqa: E402
from run_protected_dgx_live_profile import (  # noqa: E402
    protected_dgx_vllm_profile_defaults,
)

SCHEMA_VERSION = "gb2_s20oa_immutable_reranker_binding.v1"
SMOKE_ENV = "NEX_GB2_S20OA_RERANKER_LIVE"
ARTIFACT_EVIDENCE_ENV = "NEX_GB2_S20OA_ARTIFACT_EVIDENCE_PATH"
S20O_EVIDENCE_ENV = "NEX_GB2_S20OA_S20O_EVIDENCE_PATH"
DEFAULT_S20O_EVIDENCE = (
    ROOT / "reports" / "live" / "gb2_ca00_s20o_provider_profile_audit.json"
)
HttpRequester = Callable[..., Any]


def run_gb2_s20oa_immutable_reranker_binding(
    environ: Mapping[str, str] | None = None,
    *,
    requester: HttpRequester | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }
    effective_env = {**protected_dgx_vllm_profile_defaults(), **env}
    try:
        artifact_path = _required_path(effective_env.get(ARTIFACT_EVIDENCE_ENV))
        s20o_path = Path(
            effective_env.get(S20O_EVIDENCE_ENV, str(DEFAULT_S20O_EVIDENCE))
        )
        artifact_evidence = _load_json_object(artifact_path)
        artifact_revision = admit_model_artifact_revision_evidence(
            artifact_evidence
        )
        prior_evidence = _load_json_object(s20o_path)
        prior_checks = _admit_prior_s20o_evidence(prior_evidence)
        config = build_remote_reranker_execution_config(effective_env)
        if not config.configured:
            raise ValueError("Remote reranker provider endpoint is not configured.")

        response = execute_remote_rerank_request(
            {
                "query": "회사의 프로젝트 비용 전표를 조회한다.",
                "documents": [
                    "프로젝트 비용 전표의 계정과목과 금액을 조회한다.",
                    "사내 식당의 오늘 메뉴를 조회한다.",
                ],
                "top_n": 2,
            },
            environ=effective_env,
            requester=requester,
        )
        results = response.get("results")
        checks = {
            "artifact_evidence_admitted": True,
            "prior_s20o_runtime_gap_was_revision_only": all(
                prior_checks.values()
            ),
            "configured_revision_matches_artifact": (
                config.model_revision == artifact_revision
            ),
            "served_name_is_separate_from_revision": (
                config.model_name != artifact_revision
            ),
            "response_revision_matches_artifact": (
                response.get("model_revision") == artifact_revision
            ),
            "deployment_identity_matches": (
                response.get("deployment_id") == config.deployment_id
            ),
            "live_response_is_ranked": _ranked_response(results),
        }
        result = {
            "evidence_schema_version": SCHEMA_VERSION,
            "evidence_generated_at": _utc_now(),
            "status": "PASS" if all(checks.values()) else "FAIL",
            "checks": checks,
            "failed_checks": [name for name, passed in checks.items() if not passed],
            "binding": {
                "served_model_name": config.model_name,
                "artifact_revision": artifact_revision,
                "deployment_id": config.deployment_id,
                "artifact_evidence_digest": (
                    model_artifact_revision_evidence_digest(artifact_evidence)
                ),
                "prior_s20o_evidence_digest": semantic_sha256_hash_ref(
                    prior_evidence
                ),
            },
            "prior_s20o_checks": prior_checks,
            "live_observation": {
                "result_count": len(results) if isinstance(results, list) else 0,
                "ranked_document_indices": (
                    [item.get("index") for item in results]
                    if isinstance(results, list)
                    else []
                ),
                "scores": (
                    [item.get("score") for item in results]
                    if isinstance(results, list)
                    else []
                ),
            },
            "model_path_persisted": False,
            "provider_endpoint_persisted": False,
            "provider_credential_persisted": False,
            "request_text_persisted": False,
        }
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        json.JSONDecodeError,
        httpx.HTTPError,
        ModelArtifactRevisionError,
        ProviderRouteError,
    ) as exc:
        result = {
            "evidence_schema_version": SCHEMA_VERSION,
            "status": "FAIL",
            "failure_code": "immutable_reranker_binding_failed",
            "detail": exc.__class__.__name__,
        }
    _assert_redacted(result, effective_env)
    return result


def _required_path(value: object) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{ARTIFACT_EVIDENCE_ENV} is required.")
    return Path(value.strip())


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("evidence must be a JSON object")
    return payload


def _admit_prior_s20o_evidence(evidence: Mapping[str, Any]) -> dict[str, bool]:
    audit = evidence.get("source_and_runtime_audit")
    findings = audit.get("findings") if isinstance(audit, Mapping) else None
    decision = evidence.get("decision")
    if not isinstance(findings, Mapping) or not isinstance(decision, Mapping):
        raise ValueError("S20O evidence is incomplete")
    return {
        "s20o_passed": evidence.get("status") == "PASS",
        "primary_decision_was_revision_correction": decision.get("code")
        == "PROVIDER_RUNTIME_PROFILE_CORRECTION_REQUIRED",
        "immutable_revision_was_unbound": findings.get(
            "immutable_model_source_revision_bound"
        )
        is False,
        "sequence_classifier_override_was_confirmed": findings.get(
            "sequence_classifier_override_confirmed"
        )
        is True,
        "reranker_template_was_confirmed": findings.get(
            "qwen3_reranker_template_confirmed"
        )
        is True,
    }


def _ranked_response(results: object) -> bool:
    if not isinstance(results, list) or len(results) != 2:
        return False
    if not all(isinstance(item, Mapping) for item in results):
        return False
    return (
        results[0].get("index") == 0
        and results[1].get("index") == 1
        and isinstance(results[0].get("score"), int | float)
        and isinstance(results[1].get("score"), int | float)
        and results[0]["score"] > results[1]["score"]
    )


def _assert_redacted(result: object, environ: Mapping[str, str]) -> None:
    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)
    protected = (
        str(environ.get("NEX_MO_REMOTE_RERANKER_URL", "")),
        str(environ.get("NEX_MO_REMOTE_RERANKER_API_KEY", "")),
        "회사의 프로젝트 비용 전표를 조회한다.",
        "프로젝트 비용 전표의 계정과목과 금액을 조회한다.",
        "사내 식당의 오늘 메뉴를 조회한다.",
    )
    if any(len(value) >= 4 and value in serialized for value in protected):
        raise ValueError("Immutable binding evidence contains protected data.")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def summary_line(result: Mapping[str, Any]) -> str:
    status = str(result.get("status", "FAIL")).lower()
    if status == "skipped":
        return f"gb2_s20oa_reranker_binding=skipped reason={SMOKE_ENV}"
    if status == "pass":
        binding = result.get("binding", {})
        return (
            "gb2_s20oa_reranker_binding=pass "
            f"revision={binding.get('artifact_revision')}"
        )
    return (
        "gb2_s20oa_reranker_binding=fail checks="
        f"{','.join(result.get('failed_checks') or []) or 'execution'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = run_gb2_s20oa_immutable_reranker_binding()
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            f"{json.dumps(result, indent=2, sort_keys=True)}\n",
            encoding="utf-8",
        )
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
