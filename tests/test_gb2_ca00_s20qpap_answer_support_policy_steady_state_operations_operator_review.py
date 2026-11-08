from __future__ import annotations

import json
from datetime import UTC, datetime

import run_gb2_s20qpap_answer_support_policy_steady_state_operations_operator_review as smoke
from nex_cx.retrieval_answer_support_policy_steady_state_operations_review import (
    DECISION,
)
from test_nex_cx_retrieval_answer_support_policy_steady_state_operations_review import (
    _design,
    _report,
)

NOW = datetime(2026, 11, 6, 18, 30, tzinfo=UTC)


def test_protected_review_approves_only_steady_state_continuation(tmp_path) -> None:
    report = _report()
    target = tmp_path / "decision.json"

    result = smoke.run_gb2_s20qpap_answer_support_policy_steady_state_operations_operator_review(
        _env(),
        design=_design(report),
        source_report=report,
        clock=lambda: NOW,
        receipt_path=target,
    )

    assert result["status"] == "PASS"
    assert result["decision"] == DECISION
    assert result["decision_status"] == "APPROVED_CONTINUATION_NOT_PRODUCTION"
    assert result["observed_metrics"]["sample_count"] == 12
    assert result["controlled_continuation_permitted"] is True
    assert result["runtime_change_permitted"] is False
    assert result["rollback_contract_preserved"] is True
    assert result["production_cutover_permitted"] is False
    assert result["provider_calls"] == result["database_calls"] == 0
    assert result["holdout_accessed"] is False
    assert target.stat().st_mode & 0o777 == 0o600
    receipt = json.loads(target.read_text(encoding="utf-8"))
    assert receipt["steady_state_operations_continuation_approved"] is True
    assert receipt["runtime_changed"] is False
    assert receipt["rollback_contract_preserved"] is True
    assert receipt["production_cutover_permitted"] is False
    assert receipt["receipt_hash"] == result["decision_receipt_hash"]
    assert "samples=12" in smoke.summary_line(result)


def test_runner_requires_explicit_decision_and_is_one_shot(tmp_path) -> None:
    assert (
        smoke.run_gb2_s20qpap_answer_support_policy_steady_state_operations_operator_review(
            {}
        )["status"]
        == "SKIPPED"
    )
    assert smoke.summary_line({"status": "SKIPPED"}).endswith("=skipped")
    assert (
        smoke.run_gb2_s20qpap_answer_support_policy_steady_state_operations_operator_review(
            {smoke.SMOKE_ENV: "1"}
        )["failure_code"]
        == "explicit_policy_steady_state_operations_review_required"
    )

    used = tmp_path / "used.json"
    used.write_text("{}", encoding="utf-8")
    assert (
        smoke.run_gb2_s20qpap_answer_support_policy_steady_state_operations_operator_review(
            _env(), receipt_path=used
        )["failure_code"]
        == "policy_steady_state_operations_review_already_recorded"
    )


def test_runner_fails_closed_on_source_drift_without_external_calls(tmp_path) -> None:
    report = _report()
    design = _design(report)
    report["status"] = "FAIL"

    result = smoke.run_gb2_s20qpap_answer_support_policy_steady_state_operations_operator_review(
        _env(),
        design=design,
        source_report=report,
        receipt_path=tmp_path / "failure.json",
    )

    assert result["status"] == "FAIL"
    assert result["failure_code"] == (
        "policy_steady_state_operations_operator_review_failed"
    )
    assert result["failure_detail"] == {
        "exception": "PolicySteadyStateOperationsReviewError"
    }
    assert result["provider_calls"] == result["database_calls"] == 0
    assert result["controlled_continuation_permitted"] is False
    assert result["rollback_contract_preserved"] is True
    assert "=fail" in smoke.summary_line(result)


def test_runner_requires_private_source_report(tmp_path) -> None:
    source = tmp_path / "source.json"
    source.write_text(json.dumps(_report()), encoding="utf-8")
    source.chmod(0o644)
    result = smoke.run_gb2_s20qpap_answer_support_policy_steady_state_operations_operator_review(
        {
            **_env(),
            smoke.SOURCE_REPORT_ENV: str(source),
        },
        design=_design(_report()),
        receipt_path=tmp_path / "receipt.json",
    )
    assert result["status"] == "FAIL"
    assert result["failure_detail"] == {"exception": "PermissionError"}
    assert smoke._is_private(source) is False


def test_runner_loads_owner_private_source_report(tmp_path) -> None:
    report = _report()
    source = tmp_path / "source.json"
    source.write_text(json.dumps(report), encoding="utf-8")
    source.chmod(0o600)

    result = smoke.run_gb2_s20qpap_answer_support_policy_steady_state_operations_operator_review(
        {
            **_env(),
            smoke.SOURCE_REPORT_ENV: str(source),
        },
        design=_design(report),
        receipt_path=tmp_path / "receipt.json",
    )

    assert smoke._is_private(source) is True
    assert result["status"] == "PASS"


def test_runner_normalizes_naive_clock(tmp_path) -> None:
    report = _report()
    result = smoke.run_gb2_s20qpap_answer_support_policy_steady_state_operations_operator_review(
        _env(),
        design=_design(report),
        source_report=report,
        clock=lambda: datetime(2026, 11, 6, 18, 30),  # noqa: DTZ001
        receipt_path=tmp_path / "naive.json",
    )
    assert result["status"] == "PASS"


def test_runner_helpers_and_cli_preserve_private_terminal_evidence(
    tmp_path, monkeypatch, capsys
) -> None:
    value = tmp_path / "value.json"
    value.write_text('{"ok": true}', encoding="utf-8")
    assert smoke._load(value) == {"ok": True}
    value.write_text("[]", encoding="utf-8")
    try:
        smoke._load(value)
    except TypeError:
        pass
    else:
        raise AssertionError("list JSON must fail")

    output = tmp_path / "output.json"
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpap_answer_support_policy_steady_state_operations_operator_review",
        lambda: {
            "status": "PASS",
            "decision": DECISION,
            "observed_metrics": {"sample_count": 12},
            "next_boundary": (
                "ANSWER_SUPPORT_POLICY_STEADY_STATE_OPERATIONS_CONTINUATION"
            ),
        },
    )
    assert smoke.main(["--output", str(output), "--summary"]) == 0
    assert "=pass" in capsys.readouterr().out
    assert output.stat().st_mode & 0o777 == 0o600

    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpap_answer_support_policy_steady_state_operations_operator_review",
        lambda: {"status": "SKIPPED"},
    )
    assert smoke.main(["--output", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "PASS"

    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpap_answer_support_policy_steady_state_operations_operator_review",
        lambda: {"status": "FAIL", "failure_code": "forced"},
    )
    assert smoke.main(["--output", str(output)]) == 1


def _env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        smoke.DECISION_ENV: DECISION,
        smoke.OPERATOR_ENV: "operator-one",
    }
