from __future__ import annotations

import json

import run_gb2_s20qpal_answer_support_policy_steady_state_readiness as smoke
from test_nex_cx_retrieval_answer_support_policy_steady_state_readiness import (
    _base_design,
    _bind_design,
    _evidence,
)


def test_protected_readiness_uses_exact_review_evidence(tmp_path) -> None:
    report, receipt = _evidence()
    design = _bind_design(_base_design(), report, receipt)
    report_path = _write(tmp_path / "report.json", report)
    receipt_path = _write(tmp_path / "receipt.json", receipt)
    receipt_path.chmod(0o600)
    design_path = _write(tmp_path / "design.json", design)

    result = smoke.run_gb2_s20qpal_answer_support_policy_steady_state_readiness(
        {smoke.SMOKE_ENV: "1"},
        review_report_path=report_path,
        review_receipt_path=receipt_path,
        design_path=design_path,
    )

    assert result["status"] == "PASS"
    assert result["activation_status"] == "NOT_ACTIVATED"
    assert result["operations_profile"]["status"] == "READY_FOR_OPERATOR_DECISION"
    assert result["provider_calls"] == result["database_calls"] == 0
    assert result["holdout_accessed"] is False
    assert result["steady_state_activation_permitted"] is False
    assert "activation=NOT_ACTIVATED" in smoke.summary_line(result)


def test_runner_is_disabled_by_default_and_fails_closed_on_permissions(
    tmp_path,
) -> None:
    skipped = smoke.run_gb2_s20qpal_answer_support_policy_steady_state_readiness({})
    assert skipped["status"] == "SKIPPED"
    assert smoke.summary_line(skipped).endswith("=skipped")

    report, receipt = _evidence()
    design = _bind_design(_base_design(), report, receipt)
    report_path = _write(tmp_path / "report.json", report)
    receipt_path = _write(tmp_path / "receipt.json", receipt)
    receipt_path.chmod(0o644)
    design_path = _write(tmp_path / "design.json", design)
    result = smoke.run_gb2_s20qpal_answer_support_policy_steady_state_readiness(
        {smoke.SMOKE_ENV: "1"},
        review_report_path=report_path,
        review_receipt_path=receipt_path,
        design_path=design_path,
    )
    assert result["status"] == "FAIL"
    assert result["failure_type"] == "PermissionError"
    assert result["provider_calls"] == result["database_calls"] == 0
    assert result["steady_state_activation_permitted"] is False
    assert "=fail" in smoke.summary_line(result)


def test_runner_fails_closed_on_missing_or_malformed_evidence(tmp_path) -> None:
    missing = smoke.run_gb2_s20qpal_answer_support_policy_steady_state_readiness(
        {smoke.SMOKE_ENV: "1"},
        review_report_path=tmp_path / "missing.json",
        review_receipt_path=tmp_path / "missing-receipt.json",
        design_path=tmp_path / "missing-design.json",
    )
    assert missing["failure_type"] == "FileNotFoundError"

    malformed = tmp_path / "malformed.json"
    malformed.write_text("[]", encoding="utf-8")
    malformed.chmod(0o600)
    failed = smoke.run_gb2_s20qpal_answer_support_policy_steady_state_readiness(
        {smoke.SMOKE_ENV: "1"},
        review_report_path=malformed,
        review_receipt_path=malformed,
        design_path=malformed,
    )
    assert failed["failure_type"] == "TypeError"


def test_main_writes_terminal_evidence(tmp_path, monkeypatch, capsys) -> None:
    output = tmp_path / "output.json"
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpal_answer_support_policy_steady_state_readiness",
        lambda: {
            "status": "PASS",
            "decision": "READY",
            "activation_status": "NOT_ACTIVATED",
            "operations_profile": {"status": "READY_FOR_OPERATOR_DECISION"},
            "next_boundary": "OPERATOR_DECISION",
        },
    )
    assert smoke.main(["--output", str(output), "--summary"]) == 0
    assert "=pass" in capsys.readouterr().out
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "PASS"

    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpal_answer_support_policy_steady_state_readiness",
        lambda: {"status": "FAIL", "failure_code": "forced"},
    )
    assert smoke.main(["--output", str(output)]) == 1


def _write(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")
    return path
