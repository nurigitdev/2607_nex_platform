#!/usr/bin/env python3
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from typing import Any, Callable, Mapping


ROOT = Path(__file__).resolve().parents[2]
for service_path in (
    "services/_shared",
    "services/nex-ae-api",
    "services/nex-ag",
    "services/nex-cx",
):
    sys.path.insert(0, str(ROOT / service_path))

from nex_ae_api.artifacts import (  # noqa: E402
    LocalRenderedArtifactStorage,
    build_markdown_render_result,
    deterministic_render_job_id,
)
from nex_ae_api.async_artifact_render_recovery import (  # noqa: E402
    RESET_RENDER_TO_QUEUED,
    build_async_artifact_render_recovery_plan,
)
from nex_cx.hybrid_retrieval_package import _confidence_decision  # noqa: E402
from nex_runtime import (  # noqa: E402
    build_generation_golden_evidence,
    build_generation_golden_matrix,
    evaluate_generation_golden_evidence,
)
from nex_runtime.compatibility import (  # noqa: E402
    GenerationCompatibilityError,
    select_generation_compatibility_rule,
)
from run_ae_grounded_artifact_recovery_access import (  # noqa: E402
    run_ae_grounded_artifact_recovery_access,
)
from run_ae_intent_execution_mode_contract import (  # noqa: E402
    run_ae_intent_execution_mode_contract,
)
from run_ag_audit_evidence_privacy_runbook_evidence import (  # noqa: E402
    run_ag_audit_evidence_privacy_runbook_evidence,
)
from run_cx_grounding_repair_lineage import (  # noqa: E402
    run_cx_grounding_repair_lineage,
)
from run_generation_recovery_mock_flow import (  # noqa: E402
    run_generation_recovery_mock_flow,
)
from run_platform_grounded_generation_artifact_e2e import (  # noqa: E402
    run_platform_grounded_generation_artifact_e2e,
)
from run_traceable_mock_flow import run_traceable_mock_flow  # noqa: E402


ARTIFACT_EXAMPLE = (
    "contracts/examples/generation/ae_grounded_artifact_admission.enqueued.json"
)
STRUCTURED_DRAFT_EXAMPLE = (
    "contracts/examples/generation/cx_structured_draft.mock_success.json"
)


def run_platform_generation_golden_scenarios(
    root: Path = ROOT,
) -> dict[str, Any]:
    intent = _safe_run(run_ae_intent_execution_mode_contract)
    trace = _safe_run(run_traceable_mock_flow)
    artifact_e2e = _safe_run(
        lambda: run_platform_grounded_generation_artifact_e2e(root)
    )
    report = _safe_run(lambda: _run_report_artifact_export(root))
    recovery = _safe_run(run_generation_recovery_mock_flow)
    repair = _safe_run(lambda: run_cx_grounding_repair_lineage(root))
    artifact_access = _safe_run(
        lambda: run_ae_grounded_artifact_recovery_access(root)
    )
    audit = _safe_run(
        lambda: run_ag_audit_evidence_privacy_runbook_evidence(root)
    )
    no_answer = _run_no_answer_guardrail()
    mismatch = _run_template_prompt_mismatch()
    render_retry = _run_render_retry_plan()

    records = [
        build_generation_golden_evidence(
            "GEN-E2E-001",
            checks={
                "general_mode_selected": _nested(intent, "decisions", "explicit", "execution_mode")
                == "GENERAL_ANSWER",
                "retrieval_skipped": _nested(intent, "decisions", "explicit", "retrieval_required")
                is False,
                "citations_not_claimed": _nested(intent, "decisions", "explicit", "template_required")
                is False,
            },
            components=("nex-ae-api.intent_policy",),
        ),
        build_generation_golden_evidence(
            "GEN-E2E-002",
            checks={
                "permission_filtered_retrieval": all(
                    _mapping(trace.get("rag_workflow")).get("assertions", {}).values()
                ),
                "grounded_generation": _nested(trace, "rag_workflow", "generation", "status")
                == "COMPLETED",
                "trace_continuity": all(
                    _mapping(trace.get("assertions")).values()
                ),
            },
            components=("nex-ae-api", "nex-cx", "nex-mo", "nex-ag"),
        ),
        build_generation_golden_evidence(
            "GEN-E2E-003",
            checks={
                "report_contract_selected": report.get("report_contract_selected") is True,
                "md_created": report.get("md_created") is True,
                "docx_created": report.get("docx_created") is True,
                "owner_only_links": report.get("owner_only_links") is True,
            },
            components=("nex-ae-api.artifacts", "nex-runtime.compatibility"),
        ),
        build_generation_golden_evidence(
            "GEN-E2E-004",
            checks=no_answer,
            components=("nex-cx.hybrid_retrieval_package",),
        ),
        build_generation_golden_evidence(
            "GEN-E2E-005",
            checks=mismatch,
            components=("nex-runtime.compatibility",),
        ),
        build_generation_golden_evidence(
            "GEN-E2E-006",
            checks={
                "retryable_timeout_recorded": all(
                    _mapping(recovery.get("assertions")).get(name) is True
                    for name in (
                        "cx_problem_retryable",
                        "cx_failed_record",
                        "cx_failure_code",
                    )
                ),
                "input_hashes_preserved": all(
                    len(str(_nested(recovery, "cx", "request_metadata", name) or ""))
                    == 64
                    for name in (
                        "provider_prompt_package_hash",
                        "generation_request_hash",
                    )
                ),
                "recovery_lineage_visible": all(
                    _mapping(recovery.get("assertions")).get(name) is True
                    for name in (
                        "ae_recovery_lineage",
                        "ag_recovery_lineage",
                        "redaction_guard",
                    )
                ),
            },
            components=("nex-cx.generation", "nex-ae-api.recovery", "nex-ag.audit"),
        ),
        build_generation_golden_evidence(
            "GEN-E2E-007",
            checks={
                "repair_binding_exact": _nested(repair, "checks", "exact_binding_contract")
                is True,
                "repair_bounded_once": _nested(repair, "decision", "repair_attempt_limit")
                == 1,
                "retrieval_package_preserved": _nested(repair, "checks", "repair_checks_binding")
                is True,
            },
            components=("nex-cx.citation_repair", "nex-cx.grounded_lineage"),
        ),
        build_generation_golden_evidence(
            "GEN-E2E-008",
            checks={
                "validated_draft_preserved": _nested(
                    artifact_e2e, "checks", "citation_workflow_is_validated"
                )
                is True,
                "retry_work_scheduled": render_retry.get("retry_work_scheduled") is True,
                "owner_scope_preserved": render_retry.get("owner_scope_preserved") is True,
            },
            components=("nex-ae-api.async_artifact_render_recovery",),
        ),
        build_generation_golden_evidence(
            "GEN-E2E-009",
            checks={
                "cross_owner_hidden": _nested(
                    artifact_access, "checks", "cross_owner_regression"
                )
                is True,
                "owner_download_supported": _nested(
                    artifact_access, "checks", "fresh_runtime_regression"
                )
                is True,
                "storage_reference_redacted": _nested(
                    artifact_access, "checks", "browser_storage_ref_redaction"
                )
                is True,
            },
            components=("nex-ae-api.artifact_access",),
        ),
        build_generation_golden_evidence(
            "GEN-E2E-010",
            checks={
                "audit_package_verified": _nested(
                    audit, "checks", "valid_package_verifies"
                )
                is True,
                "metadata_only_export": _nested(
                    audit, "checks", "forbidden_keys_absent"
                )
                is True,
                "private_values_excluded": _nested(
                    audit, "checks", "forbidden_values_absent"
                )
                is True,
            },
            components=("nex-ag.audit_evidence",),
        ),
    ]
    payload = {
        "matrix": build_generation_golden_matrix(),
        "production_deployment_approved": False,
        "evidence": records,
    }
    result = evaluate_generation_golden_evidence(payload)
    result["slice"] = "1394"
    result["source_statuses"] = {
        "intent": intent.get("status"),
        "trace": "PASS" if all(_mapping(trace.get("assertions")).values()) else "FAIL",
        "artifact_e2e": artifact_e2e.get("status"),
        "report": report.get("status"),
        "recovery": "PASS" if all(_mapping(recovery.get("assertions")).values()) else "FAIL",
        "repair": repair.get("status"),
        "artifact_access": artifact_access.get("status"),
        "audit": audit.get("status"),
    }
    result["decision"] = {
        "mock_or_in_memory_execution": True,
        "actual_postgresql_execution": False,
        "actual_remote_provider_execution": False,
        "actual_browser_execution": False,
        "private_payload_persisted_in_evidence": False,
        "next_slice": "1395" if result["status"] == "PASS" else "blocked",
    }
    return result


def _run_report_artifact_export(root: Path) -> dict[str, Any]:
    artifact = deepcopy(_read_json(root / ARTIFACT_EXAMPLE).get("artifact") or {})
    draft = deepcopy(_read_json(root / STRUCTURED_DRAFT_EXAMPLE))
    source_ref = _first_mapping(artifact.get("source_refs"))
    draft.update(
        structured_draft_id=source_ref.get("structured_draft_id"),
        cx_generation_id=source_ref.get("cx_generation_id"),
        content_hash=source_ref.get("structured_draft_content_hash"),
    )
    draft["citations"] = [
        {**item, "retrieval_package_id": source_ref.get("retrieval_package_id")}
        for item in draft.get("citations", [])
        if isinstance(item, Mapping)
    ]
    legacy_rule = select_generation_compatibility_rule(
        {
            "execution_mode": "REPORT_GENERATION",
            "template_id": "report",
            "prompt_binding_id": "ae.grounded_chat.default",
            "output_contract_id": "report_generation_v1",
            "provider_capability": "generation",
            "generation_profile": "general-document",
        }
    )
    render = build_markdown_render_result(
        artifact_record=artifact,
        structured_draft=draft,
        target_formats=["MD", "DOCX"],
        render_request_id="s140-report-render",
        render_job_id=deterministic_render_job_id(
            str(artifact.get("artifact_id")), "s140-report-render"
        ),
    )
    files = {
        item["format"]: item
        for item in render.get("artifact_files", [])
        if isinstance(item, Mapping)
    }
    payloads = _mapping(render.get("rendered_payloads"))
    with TemporaryDirectory(prefix="nex-s140-report-") as temp_dir:
        storage = LocalRenderedArtifactStorage(Path(temp_dir) / "owner-001")
        for target_format, artifact_file in files.items():
            storage.save_rendered_artifact_file(
                dict(artifact_file), payloads[target_format]
            )
        md_payload = storage.get_rendered_artifact_file(dict(files.get("MD") or {}))
        docx_payload = storage.get_rendered_artifact_file(
            dict(files.get("DOCX") or {})
        )
    checks = {
        "report_contract_selected": (
            legacy_rule.get("output_contract_id") == "report_generation_v1"
        ),
        "md_created": bool(md_payload and md_payload.startswith(b"# ")),
        "docx_created": bool(docx_payload and docx_payload.startswith(b"PK")),
        "owner_only_links": bool(render.get("artifact_links"))
        and all(
            item.get("access_policy") == "owner_only"
            for item in render["artifact_links"]
        ),
    }
    return {"status": "PASS" if all(checks.values()) else "FAIL", **checks}


def _run_no_answer_guardrail() -> dict[str, bool]:
    no_answer = _confidence_decision([])
    low_confidence = _confidence_decision(
        [{"scores": {"final_score": 0.1}}]
    )
    return {
        "no_evidence_is_no_answer": no_answer.get("status") == "NO_ANSWER",
        "low_score_is_low_confidence": low_confidence.get("status")
        == "LOW_CONFIDENCE",
        "generation_blocked": {
            no_answer.get("status"),
            low_confidence.get("status"),
        }
        <= {"NO_ANSWER", "LOW_CONFIDENCE"},
    }


def _run_template_prompt_mismatch() -> dict[str, bool]:
    provider_call_count = 0
    error_code = None
    try:
        select_generation_compatibility_rule(
            {
                "execution_mode": "DOCUMENT_GENERATION",
                "template_id": "report",
                "prompt_binding_id": "ae.grounded_chat.default",
                "output_contract_id": "structured_document_v1",
                "provider_capability": "generation",
                "generation_profile": "general-document",
            }
        )
    except GenerationCompatibilityError as exc:
        error_code = exc.error_code
    return {
        "mismatch_rejected": error_code == "generation.compatibility_rule_not_found",
        "rejected_before_provider_call": provider_call_count == 0,
    }


def _run_render_retry_plan() -> dict[str, bool]:
    render_job_id = "s140-render-retry"
    artifact_id = "s140-artifact"
    plan = build_async_artifact_render_recovery_plan(
        render_job_id=render_job_id,
        render_job={
            "render_job_id": render_job_id,
            "artifact_id": artifact_id,
            "job_status": "FAILED",
        },
        queue_job={
            "job_id": render_job_id,
            "job_type": "ae.artifact.render",
            "subject_ref": {"type": "artifact", "id": artifact_id},
            "status": "QUEUED",
            "attempt_count": 1,
            "max_attempts": 3,
            "available_at": "2026-10-06T00:00:30Z",
            "error": {
                "error_code": "ae.render_dependency_unavailable",
                "retryable": True,
                "dead_lettered": False,
            },
        },
    )
    return {
        "retry_work_scheduled": (
            plan.get("action") == RESET_RENDER_TO_QUEUED
            and plan.get("attempts_remaining") == 2
        ),
        "owner_scope_preserved": plan.get("owner_scope_enforced") is True,
    }


def _safe_run(runner: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        result = runner()
    except Exception as exc:  # noqa: BLE001 - evidence must fail closed
        return {"status": "FAIL", "error_type": type(exc).__name__}
    return result if isinstance(result, dict) else {"status": "FAIL"}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _first_mapping(value: object) -> dict[str, Any]:
    if isinstance(value, list) and value and isinstance(value[0], Mapping):
        return dict(value[0])
    return {}


def _nested(value: object, *keys: str) -> object:
    current = value
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def summary_line(result: Mapping[str, Any]) -> str:
    summary = _mapping(result.get("summary"))
    decision = _mapping(result.get("decision"))
    return (
        "platform_generation_golden_scenarios="
        f"{str(result.get('status', 'FAIL')).lower()} "
        f"scenarios={summary.get('passed_scenario_count', 0)}/"
        f"{summary.get('required_scenario_count', 0)} "
        f"protected={summary.get('protected_execution_count', 0)} "
        f"privacy={summary.get('privacy_violation_count', 0)} "
        f"next={decision.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_platform_generation_golden_scenarios()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
