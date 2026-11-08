from __future__ import annotations

import json
from pathlib import Path

import pytest
import run_gb2_s20qpaq_answer_support_policy_steady_state_operations_continuation as smoke
from nex_cx.retrieval_answer_support_policy_steady_state_operations_review import (
    build_policy_steady_state_operations_operator_decision,
    decide_policy_steady_state_operations_review,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from test_nex_cx_retrieval_answer_support_policy_steady_state_operations_review import (
    _design,
    _report,
)

DECIDED_AT = "2026-11-06T10:39:14.455159Z"


def test_continuation_binds_review_and_promotes_base_acceptance() -> None:
    review, receipt = _review_evidence()
    result = smoke.run_gb2_s20qpaq_answer_support_policy_steady_state_operations_continuation(
        _env(),
        review_report=review,
        review_receipt=receipt,
        base_runner=_passing_base,
    )

    assert result["status"] == "PASS"
    assert result["decision"] == smoke.DECISION
    assert result["slice_id"] == "GB2-CA00-S20Q-P-AQ"
    assert result["continuation_receipt_hash"] == receipt["receipt_hash"]
    assert result["checks"]["pap_review_report_bound"] is True
    assert result["checks"]["pap_continuation_receipt_bound"] is True
    assert result["checks"]["continuation_policy_bound"] is True
    assert result["next_boundary"] == smoke.NEXT_BOUNDARY
    assert "samples=12" in smoke.summary_line(result)


def test_continuation_is_protected_and_base_failure_is_fail_closed() -> None:
    assert (
        smoke.run_gb2_s20qpaq_answer_support_policy_steady_state_operations_continuation(
            {}
        )["status"]
        == "SKIPPED"
    )
    assert smoke.summary_line({"status": "SKIPPED"}).endswith("=skipped")
    assert (
        smoke.run_gb2_s20qpaq_answer_support_policy_steady_state_operations_continuation(
            {smoke.SMOKE_ENV: "1"}
        )["failure_code"]
        == "operator_approval_required"
    )

    review, receipt = _review_evidence()
    result = smoke.run_gb2_s20qpaq_answer_support_policy_steady_state_operations_continuation(
        _env(),
        review_report=review,
        review_receipt=receipt,
        base_runner=lambda *_args, **_kwargs: {
            "status": "FAIL",
            "failure_code": "forced",
        },
    )
    assert result["status"] == "FAIL"
    assert result["failure_detail"] == {
        "exception": "RuntimeError",
        "stage": "CONTINUATION_RUNTIME_ACCEPTANCE",
    }
    assert "=fail" in smoke.summary_line(result)


def test_review_report_receipt_and_policy_drift_fail_closed() -> None:
    review, receipt = _review_evidence()
    review["runtime_change_permitted"] = True
    result = smoke.run_gb2_s20qpaq_answer_support_policy_steady_state_operations_continuation(
        _env(),
        review_report=review,
        review_receipt=receipt,
        base_runner=_passing_base,
    )
    assert result["failure_detail"]["stage"] == "CONTINUATION_SOURCE_ADMISSION"

    review, receipt = _review_evidence()
    receipt["receipt_hash"] = "sha256:" + "0" * 64
    result = smoke.run_gb2_s20qpaq_answer_support_policy_steady_state_operations_continuation(
        _env(),
        review_report=review,
        review_receipt=receipt,
        base_runner=_passing_base,
    )
    assert result["status"] == "FAIL"

    assert smoke._mapping({}, "value") == {}
    with pytest.raises(TypeError):
        smoke._mapping([], "value")


def test_private_loader_and_cli_write_owner_private_evidence(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    path = tmp_path / "value.json"
    path.write_text('{"ok": true}', encoding="utf-8")
    path.chmod(0o600)
    assert smoke._load_private(path) == {"ok": True}
    path.chmod(0o644)
    with pytest.raises(PermissionError):
        smoke._load_private(path)

    output = tmp_path / "output.json"
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpaq_answer_support_policy_steady_state_operations_continuation",
        lambda: {
            "status": "PASS",
            "live_execution": {
                "sample_count": 12,
                "provider_p95_latency_ms": 100,
                "e2e_p95_latency_ms": 120,
            },
        },
    )
    assert smoke.main(["--output", str(output), "--summary"]) == 0
    assert "=pass" in capsys.readouterr().out
    assert output.stat().st_mode & 0o777 == 0o600

    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpaq_answer_support_policy_steady_state_operations_continuation",
        lambda: {"status": "SKIPPED"},
    )
    assert smoke.main(["--output", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "PASS"

    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpaq_answer_support_policy_steady_state_operations_continuation",
        lambda: {"status": "FAIL", "failure_code": "forced"},
    )
    assert smoke.main(["--output", str(output)]) == 1


def _review_evidence() -> tuple[dict, dict]:
    source = _report()
    design = _design(source)
    operator = build_policy_steady_state_operations_operator_decision(
        operator_id="codex-p-ap-operator",
        decided_at=DECIDED_AT,
        design=design,
        source_report=source,
    )
    manifest = decide_policy_steady_state_operations_review(
        design=design,
        source_report=source,
        operator_decision=operator,
    )
    receipt = {
        "receipt_schema_version": (
            "cx_answer_support_policy_steady_state_operations_"
            "operator_review_receipt.v1"
        ),
        "status": "PASS",
        "decision": manifest["decision"],
        "decision_status": manifest["decision_status"],
        "design_hash": design["design_hash"],
        "operator_decision_hash": operator["decision_hash"],
        "manifest_hash": manifest["manifest_hash"],
        "source_evidence_hash": manifest["source_evidence_hash"],
        "source_report_document_hash": manifest["source_report_document_hash"],
        "approved_scope": manifest["approved_scope"],
        "next_boundary": manifest["next_boundary"],
        "decided_at": operator["decided_at"],
        "steady_state_operations_continuation_approved": True,
        "runtime_changed": False,
        "rollback_contract_preserved": True,
        "production_cutover_permitted": False,
    }
    receipt["receipt_hash"] = semantic_sha256_hash_ref(receipt)
    review = {
        "evidence_schema_version": (
            "gb2_s20qpap_answer_support_policy_steady_state_"
            "operations_operator_review.v1"
        ),
        "slice_id": "GB2-CA00-S20Q-P-AP",
        **manifest,
        "decision_receipt_hash": receipt["receipt_hash"],
    }
    assert semantic_sha256_hash_ref(review) == (
        "sha256:92025d7f50af8a7c2ef546a07c5e313044a40f8f4be06a5afd9cdb1a1fb4e07c"
    )
    assert semantic_sha256_hash_ref(receipt) == (
        "sha256:66c1bb87f4d92161178dd1947b74c07801a636b7fa4800890a1d267707461788"
    )
    return review, receipt


def _passing_base(_env, **_kwargs) -> dict:
    return {
        "evidence_schema_version": (
            "gb2_s20qpao_answer_support_policy_steady_state_operations.v1"
        ),
        "slice_id": "GB2-CA00-S20Q-P-AO",
        "status": "PASS",
        "decision": "ANSWER_SUPPORT_POLICY_STEADY_STATE_OPERATIONS_ACCEPTED",
        "policy_hash": (
            "sha256:7fc019a786ce1ad7e6022f6a2e11daab8829d6ff32e0b4034048406f2a176b97"
        ),
        "checks": {"base_acceptance": True},
        "failed_checks": [],
        "live_execution": {
            "sample_count": 12,
            "provider_call_count": 12,
            "ready_count": 9,
            "low_confidence_count": 3,
            "elapsed_seconds": 33.0,
            "peak_in_flight": 4,
            "feedback_p95_latency_ms": 1.0,
            "provider_p95_latency_ms": 11000.0,
            "e2e_p95_latency_ms": 11100.0,
        },
        "evidence_hash": "sha256:" + "0" * 64,
        "production_cutover_permitted": False,
        "holdout_accessed": False,
    }


def _env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        smoke.APPROVED_ENV: "1",
        smoke.OPERATOR_ENV: "operator-one",
    }
