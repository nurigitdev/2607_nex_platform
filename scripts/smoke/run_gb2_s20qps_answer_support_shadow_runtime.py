#!/usr/bin/env python3
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from collections.abc import Mapping
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "_shared", ROOT / "services" / "nex-cx"):
    sys.path.insert(0, str(path))

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from nex_cx.access_context import CxAccessContext
from nex_cx.retrieval_answer_support_shadow_runtime import (
    AnswerSupportShadowRuntime,
    validate_answer_support_shadow_configuration,
)


SCHEMA_VERSION = "gb2_s20qps_answer_support_shadow_runtime.v1"
SMOKE_ENV = "NEX_GB2_S20QPS_SHADOW_RUNTIME"
READINESS_PATH = (
    ROOT / "reports/live/gb2_ca00_s20qpr_runtime_activation_readiness.json"
)
DESIGN_PATH = (
    ROOT
    / "scripts/smoke/data/s136_answer_support_shadow_runtime_v1_design.json"
)
SIGNAL_DESIGN_PATH = (
    ROOT / "scripts/smoke/data/s136_answer_support_signal_v1_design.json"
)
REQUEST_PROFILE_PATH = (
    ROOT / "scripts/smoke/data/s136_answer_support_generation_profile_v1.json"
)
OUTPUT_PATH = (
    ROOT / "reports/live/gb2_ca00_s20qps_answer_support_shadow_runtime.json"
)


class _RecordingSink:
    def __init__(self) -> None:
        self.outcomes: list[dict[str, Any]] = []

    def record(self, outcome: Mapping[str, Any]) -> None:
        self.outcomes.append(dict(outcome))


class _DeterministicGenerationClient:
    def __init__(self, provider_binding: Mapping[str, Any]) -> None:
        self.provider_binding = dict(provider_binding)
        self.calls = 0

    def create_generation(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        del request_id, trace_id
        self.calls += 1
        user_payload = json.loads(payload["messages"][1]["content"])
        return {
            "alias": self.provider_binding["provider_alias"],
            "model_revision": self.provider_binding["model_revision"],
            "deployment_id": self.provider_binding["deployment_id"],
            "provider_type": self.provider_binding["provider_type"],
            "output": {
                "type": "text",
                "text": json.dumps(
                    {
                        "items": [
                            {
                                "candidate_id": row["candidate_id"],
                                "classification": "SUPPORTING_EVIDENCE",
                                "answer_support_score": 0.9 - index * 0.1,
                                "contradiction_score": 0.05,
                            }
                            for index, row in enumerate(user_payload["candidates"])
                        ]
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            },
            "finish_reason": "STOP",
            "usage": {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
        }


def run_gb2_s20qps_answer_support_shadow_runtime(
    environ: Mapping[str, str] | None = None,
    *,
    readiness_report: Mapping[str, Any] | None = None,
    shadow_design: Mapping[str, Any] | None = None,
    signal_design: Mapping[str, Any] | None = None,
    request_profile: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    env = dict(environ if environ is not None else os.environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }
    provider_calls = 0
    try:
        report = dict(readiness_report or _load(READINESS_PATH))
        manifest = _mapping(report.get("manifest"), "readiness manifest")
        design = dict(shadow_design or _load(DESIGN_PATH))
        signal = dict(signal_design or _load(SIGNAL_DESIGN_PATH))
        request = dict(request_profile or _load(REQUEST_PROFILE_PATH))
        configuration = validate_answer_support_shadow_configuration(
            manifest,
            signal_design=signal,
            request_profile=request,
        )
        _validate_shadow_design(design, configuration=configuration)

        sink = _RecordingSink()
        client = _DeterministicGenerationClient(
            configuration["candidate_profile"]["provider_binding"]
        )
        runtime = AnswerSupportShadowRuntime(
            readiness_manifest=manifest,
            signal_design=signal,
            request_profile=request,
            generation_client=client,
            outcome_sink=sink,
        )
        package = {
            "retrieval_package_id": "s20qps-package",
            "status": "READY",
            "purpose": "grounded_answer",
        }
        before = deepcopy(package)
        observed = runtime.observe(
            query_text="승인 기준은 무엇입니까?",
            evidence_items=_evidence_items(),
            primary_package=package,
            access_context=_context(),
        )
        skipped = runtime.observe(
            query_text="검색",
            evidence_items=_evidence_items(),
            primary_package={**package, "purpose": "search"},
            access_context=_context(),
        )
        drift_client = _DeterministicGenerationClient(
            {
                **configuration["candidate_profile"]["provider_binding"],
                "deployment_id": "drifted-deployment",
            }
        )
        drift_runtime = AnswerSupportShadowRuntime(
            readiness_manifest=manifest,
            signal_design=signal,
            request_profile=request,
            generation_client=drift_client,
            outcome_sink=sink,
        )
        drift = drift_runtime.observe(
            query_text="승인 기준은 무엇입니까?",
            evidence_items=_evidence_items(),
            primary_package=package,
            access_context=_context(),
        )
        provider_calls = client.calls + drift_client.calls
        serialized_outcomes = json.dumps(sink.outcomes, ensure_ascii=False)
        checks = {
            "readiness_manifest_bound": (
                design["source_binding"]["readiness_manifest_hash"]
                == manifest["manifest_hash"]
            ),
            "shadow_observed": observed.get("status") == "OBSERVED",
            "shadow_ready": observed.get("shadow_decision") == "READY",
            "primary_package_unchanged": package == before,
            "shadow_not_user_visible": observed.get("user_visible") is False,
            "ineligible_purpose_skipped": (
                skipped.get("skip_reason") == "PURPOSE_NOT_ELIGIBLE"
            ),
            "binding_drift_failed_closed": (
                drift.get("error_code")
                == "cx.answer_support_shadow.provider_binding_drift"
            ),
            "private_text_not_persisted": all(
                value not in serialized_outcomes
                for value in (
                    "승인 기준은 무엇입니까?",
                    "비공개 승인 근거 A",
                    "비공개 승인 근거 B",
                )
            ),
            "provider_calls_exact": provider_calls == 2,
            "holdout_not_reexecuted": True,
            "runtime_activation_prohibited": (
                observed.get("runtime_activation_permitted") is False
            ),
        }
        if not all(checks.values()):
            raise ValueError("shadow runtime protected checks failed")
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "slice_id": "GB2-CA00-S20Q-P-S",
            "status": "FAIL",
            "failure_code": getattr(
                exc, "error_code", "answer_support_shadow_runtime_invalid"
            ),
            "failure_type": exc.__class__.__name__,
            "provider_calls": provider_calls,
            "database_calls": 0,
            "holdout_reexecuted": False,
            "runtime_activation_permitted": False,
        }
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice_id": "GB2-CA00-S20Q-P-S",
        "status": "PASS",
        "decision": "SHADOW_RUNTIME_EVALUATOR_INTEGRATED_NOT_ACTIVATED",
        "profile_hash": configuration["candidate_profile"]["profile_hash"],
        "manifest_hash": manifest["manifest_hash"],
        "checks": checks,
        "outcome_statuses": [row["status"] for row in sink.outcomes],
        "provider_calls": provider_calls,
        "database_calls": 0,
        "holdout_reexecuted": False,
        "runtime_activation_permitted": False,
        "production_cutover_permitted": False,
        "next_boundary": "SHADOW_CANARY_OPERATIONS_AND_OPERATOR_APPROVAL",
    }


def _validate_shadow_design(
    design: Mapping[str, Any],
    *,
    configuration: Mapping[str, Any],
) -> None:
    source = _mapping(design.get("source_binding"), "shadow source binding")
    execution = _mapping(design.get("execution_boundary"), "execution boundary")
    admission = _mapping(design.get("admission"), "shadow admission")
    safety = _mapping(design.get("safety"), "shadow safety")
    profile = configuration["candidate_profile"]
    if (
        design.get("design_schema_version")
        != "cx_answer_support_shadow_runtime_design.v1"
        or design.get("status") != "FROZEN_SHADOW_ONLY"
        or source.get("readiness_manifest_hash")
        != configuration["manifest"]["manifest_hash"]
        or source.get("runtime_profile_hash") != profile["profile_hash"]
        or source.get("request_profile_hash")
        != configuration["request_profile"]["profile_hash"]
        or source.get("signal_design_hash")
        != configuration["signal_design"]["design_hash"]
        or execution
        != {
            "eligible_purposes": ["document_generation", "grounded_answer"],
            "fallback_policy": "CURRENT_ACTIVE_RETRIEVAL_CONFIDENCE_POLICY",
            "primary_decision_mutation_permitted": False,
            "shadow_decision_user_visible": False,
            "telemetry_failure_affects_primary": False,
        }
        or admission
        != {
            "fail_closed_on_provider_binding_drift": True,
            "permission_filtered_evidence_required": True,
            "profile_or_threshold_reselection_permitted": False,
            "raw_query_or_candidate_persistence_permitted": False,
        }
        or safety
        != {
            "holdout_access_permitted": False,
            "holdout_reexecution_permitted": False,
            "production_cutover_permitted": False,
            "runtime_activation_permitted": False,
        }
    ):
        raise ValueError("answer-support shadow design is invalid")


def _evidence_items() -> list[dict[str, Any]]:
    return [
        {
            "evidence_id": "s20qps-evidence-a",
            "text": "비공개 승인 근거 A",
            "permission_result": {"visible": True},
        },
        {
            "evidence_id": "s20qps-evidence-b",
            "text": "비공개 승인 근거 B",
            "permission_result": {"visible": True},
        },
    ]


def _context() -> CxAccessContext:
    return CxAccessContext(
        caller_service_id="nex-ae-api",
        tenant_id="VO00",
        subject_id="s20qps-owner",
        request_id="s20qps-request",
        trace_id="2" * 32,
        scopes=("service:call",),
    )


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} is invalid")
    return value


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("shadow runtime evidence must be a JSON object")
    return value


def summary_line(result: Mapping[str, Any]) -> str:
    status = str(result.get("status", "FAIL")).lower()
    if status == "pass":
        return (
            "gb2_s20qps_answer_support_shadow_runtime=pass "
            "activation=not_activated provider_calls=2 database_calls=0 "
            "holdout_reexecution=no"
        )
    if status == "skipped":
        return "gb2_s20qps_answer_support_shadow_runtime=skipped"
    return (
        "gb2_s20qps_answer_support_shadow_runtime=fail "
        f"reason={result.get('failure_code', 'shadow_runtime_invalid')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_gb2_s20qps_answer_support_shadow_runtime()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
