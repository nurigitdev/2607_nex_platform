from __future__ import annotations

import json

import run_gb2_s20qpas_answer_support_policy_steady_state_operations_continuation_closure as smoke
from nex_cx.retrieval_answer_support_policy_steady_state_continuation_closure import (
    DECISION,
)
from test_nex_cx_retrieval_answer_support_policy_steady_state_continuation_closure import (
    _design,
    _sources,
)


def test_protected_closure_freezes_baseline_without_external_calls() -> None:
    report, receipt = _sources()
    result = (
        smoke.run_gb2_s20qpas_answer_support_policy_steady_state_continuation_closure(
            _env(),
            design=_design(report, receipt),
            operator_review_report=report,
            operator_review_receipt=receipt,
        )
    )

    assert result["status"] == "PASS"
    assert result["decision"] == DECISION
    assert result["closure_status"] == "CLOSED_CONTROLLED_OPERATIONS_BASELINE"
    assert result["baseline_status"] == "FROZEN"
    assert result["runtime_disposition"] == (
        "CONTINUE_CONTROLLED_STEADY_STATE_OPERATIONS"
    )
    assert result["corrective_chain_closed"] is True
    assert result["provider_calls"] == result["database_calls"] == 0
    assert result["holdout_accessed"] is False
    assert result["runtime_changed"] is False
    assert result["rollback_contract_preserved"] is True
    assert result["production_cutover_permitted"] is False
    assert "baseline=FROZEN" in smoke.summary_line(result)


def test_runner_skip_and_source_drift_fail_closed() -> None:
    skipped = (
        smoke.run_gb2_s20qpas_answer_support_policy_steady_state_continuation_closure(
            {}
        )
    )
    assert skipped["status"] == "SKIPPED"
    assert smoke.summary_line(skipped).endswith("=skipped")

    report, receipt = _sources()
    design = _design(report, receipt)
    report["status"] = "FAIL"
    result = (
        smoke.run_gb2_s20qpas_answer_support_policy_steady_state_continuation_closure(
            _env(),
            design=design,
            operator_review_report=report,
            operator_review_receipt=receipt,
        )
    )
    assert result["status"] == "FAIL"
    assert result["failure_code"] == ("policy_steady_state_continuation_closure_failed")
    assert result["failure_detail"] == {
        "exception": "PolicySteadyStateContinuationClosureError"
    }
    assert result["provider_calls"] == result["database_calls"] == 0
    assert result["corrective_chain_closed"] is False
    assert result["rollback_contract_preserved"] is True
    assert "=fail" in smoke.summary_line(result)
    assert "failure_detail" not in smoke._failure("without_detail")


def test_runner_requires_both_source_documents_to_be_owner_private(tmp_path) -> None:
    report, receipt = _sources()
    report_path = tmp_path / "report.json"
    receipt_path = tmp_path / "receipt.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    report_path.chmod(0o644)
    receipt_path.chmod(0o600)

    result = (
        smoke.run_gb2_s20qpas_answer_support_policy_steady_state_continuation_closure(
            {
                **_env(),
                smoke.REPORT_ENV: str(report_path),
                smoke.RECEIPT_ENV: str(receipt_path),
            },
            design=_design(report, receipt),
        )
    )
    assert result["status"] == "FAIL"
    assert result["failure_detail"] == {"exception": "PermissionError"}

    report_path.chmod(0o600)
    receipt_path.chmod(0o644)
    result = (
        smoke.run_gb2_s20qpas_answer_support_policy_steady_state_continuation_closure(
            {
                **_env(),
                smoke.REPORT_ENV: str(report_path),
                smoke.RECEIPT_ENV: str(receipt_path),
            },
            design=_design(report, receipt),
        )
    )
    assert result["status"] == "FAIL"
    assert result["failure_detail"] == {"exception": "PermissionError"}


def test_runner_loads_private_sources_and_helpers(tmp_path) -> None:
    report, receipt = _sources()
    report_path = tmp_path / "report.json"
    receipt_path = tmp_path / "receipt.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    report_path.chmod(0o600)
    receipt_path.chmod(0o600)

    result = (
        smoke.run_gb2_s20qpas_answer_support_policy_steady_state_continuation_closure(
            {
                **_env(),
                smoke.REPORT_ENV: str(report_path),
                smoke.RECEIPT_ENV: str(receipt_path),
            },
            design=_design(report, receipt),
        )
    )
    assert result["status"] == "PASS"

    value = tmp_path / "value.json"
    value.write_text("[]", encoding="utf-8")
    try:
        smoke._load(value)
    except TypeError:
        pass
    else:
        raise AssertionError("list JSON must fail")


def test_cli_writes_private_evidence_and_preserves_existing_on_skip(
    tmp_path, monkeypatch, capsys
) -> None:
    output = tmp_path / "output.json"
    passing = {
        "status": "PASS",
        "decision": DECISION,
        "baseline_status": "FROZEN",
        "next_boundary": (
            "ANSWER_SUPPORT_POLICY_CONTROLLED_STEADY_STATE_BASELINE_MAINTENANCE"
        ),
    }
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpas_answer_support_policy_steady_state_continuation_closure",
        lambda: passing,
    )
    assert smoke.main(["--output", str(output), "--summary"]) == 0
    assert "=pass" in capsys.readouterr().out
    assert output.stat().st_mode & 0o777 == 0o600

    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpas_answer_support_policy_steady_state_continuation_closure",
        lambda: {"status": "SKIPPED"},
    )
    assert smoke.main(["--output", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "PASS"

    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpas_answer_support_policy_steady_state_continuation_closure",
        lambda: {"status": "FAIL", "failure_code": "forced"},
    )
    assert smoke.main(["--output", str(output)]) == 1


def _env() -> dict[str, str]:
    return {smoke.SMOKE_ENV: "1"}
