from __future__ import annotations

import json
from datetime import UTC, datetime

import run_gb2_s20qpam_answer_support_policy_steady_state_operator_decision as smoke
from nex_cx.retrieval_answer_support_policy_steady_state_decision import DECISION
from test_nex_cx_retrieval_answer_support_policy_steady_state_decision import (
    _base_design,
    _bind_design,
    _readiness_report,
)


def test_protected_operator_decision_writes_private_one_shot_receipt(tmp_path) -> None:
    report = _readiness_report()
    design = _bind_design(_base_design(), report)
    receipt_path = tmp_path / "receipt.json"
    result = smoke.run_gb2_s20qpam_answer_support_policy_steady_state_operator_decision(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DECISION_ENV: DECISION,
            smoke.OPERATOR_ENV: "operator-one",
        },
        readiness_report=report,
        design=design,
        clock=lambda: datetime(2026, 11, 6, 12, 30, tzinfo=UTC),
        receipt_path=receipt_path,
    )

    assert result["status"] == "PASS"
    assert result["decision_status"] == "APPROVED_NOT_EXECUTED"
    assert result["steady_state_operations_approved"] is True
    assert result["steady_state_operations_activated"] is False
    assert result["provider_calls"] == result["database_calls"] == 0
    assert result["holdout_accessed"] is False
    assert receipt_path.stat().st_mode & 0o777 == 0o600
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["receipt_hash"] == result["decision_receipt_hash"]
    assert receipt["runtime_changed"] is False
    assert "approved_not_executed" in smoke.summary_line(result)

    replay = smoke.run_gb2_s20qpam_answer_support_policy_steady_state_operator_decision(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DECISION_ENV: DECISION,
            smoke.OPERATOR_ENV: "operator-one",
        },
        readiness_report=report,
        design=design,
        receipt_path=receipt_path,
    )
    assert replay["failure_code"] == "steady_state_operator_decision_already_recorded"


def test_runner_is_disabled_and_requires_explicit_decision(tmp_path) -> None:
    skipped = smoke.run_gb2_s20qpam_answer_support_policy_steady_state_operator_decision(
        {}
    )
    assert skipped["status"] == "SKIPPED"
    assert smoke.summary_line(skipped).endswith("=skipped")

    failed = smoke.run_gb2_s20qpam_answer_support_policy_steady_state_operator_decision(
        {smoke.SMOKE_ENV: "1"}, receipt_path=tmp_path / "receipt.json"
    )
    assert failed["failure_code"] == "explicit_steady_state_operator_decision_required"
    assert failed["steady_state_operations_approved"] is False
    assert "=fail" in smoke.summary_line(failed)


def test_runner_fails_closed_on_malformed_evidence(tmp_path) -> None:
    report = _readiness_report()
    design = _bind_design(_base_design(), report)
    report["runtime_change_permitted"] = True
    result = smoke.run_gb2_s20qpam_answer_support_policy_steady_state_operator_decision(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DECISION_ENV: DECISION,
            smoke.OPERATOR_ENV: "operator-one",
        },
        readiness_report=report,
        design=design,
        receipt_path=tmp_path / "receipt.json",
    )
    assert result["status"] == "FAIL"
    assert result["failure_detail"]["exception"] == "PolicySteadyStateDecisionError"
    assert result["runtime_change_executed"] is False


def test_runner_accepts_paths_and_normalizes_naive_clock(tmp_path) -> None:
    report = _readiness_report()
    design = _bind_design(_base_design(), report)
    report_path = tmp_path / "report.json"
    design_path = tmp_path / "design.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    design_path.write_text(json.dumps(design), encoding="utf-8")
    receipt_path = tmp_path / "receipt.json"
    result = smoke.run_gb2_s20qpam_answer_support_policy_steady_state_operator_decision(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DECISION_ENV: DECISION,
            smoke.OPERATOR_ENV: "operator-one",
            smoke.READINESS_REPORT_ENV: str(report_path),
            smoke.DESIGN_ENV: str(design_path),
        },
        clock=lambda: datetime(2026, 11, 6, 12, 30),
        receipt_path=receipt_path,
    )
    assert result["status"] == "PASS"
    assert json.loads(receipt_path.read_text(encoding="utf-8"))["decided_at"].endswith(
        "Z"
    )


def test_load_and_main_paths(tmp_path, monkeypatch, capsys) -> None:
    malformed = tmp_path / "array.json"
    malformed.write_text("[]", encoding="utf-8")
    try:
        smoke._load(malformed)
    except TypeError:
        pass
    else:  # pragma: no cover - assertion guard
        raise AssertionError("array evidence must fail")
    valid = tmp_path / "object.json"
    valid.write_text('{"status": "PASS"}', encoding="utf-8")
    assert smoke._load(valid) == {"status": "PASS"}

    output = tmp_path / "output.json"
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpam_answer_support_policy_steady_state_operator_decision",
        lambda: {
            "status": "PASS",
            "decision": DECISION,
            "decision_status": "APPROVED_NOT_EXECUTED",
        },
    )
    assert smoke.main(["--output", str(output), "--summary"]) == 0
    assert "=pass" in capsys.readouterr().out
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "PASS"

    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpam_answer_support_policy_steady_state_operator_decision",
        lambda: {"status": "FAIL", "failure_code": "forced"},
    )
    assert smoke.main(["--output", str(output)]) == 1

    output.write_text('{"preserved": true}\n', encoding="utf-8")
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpam_answer_support_policy_steady_state_operator_decision",
        lambda: {"status": "SKIPPED"},
    )
    assert smoke.main(["--output", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8")) == {"preserved": True}
