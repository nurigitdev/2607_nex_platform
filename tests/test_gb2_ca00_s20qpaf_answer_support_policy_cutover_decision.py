from __future__ import annotations

import json
from datetime import UTC, datetime

import run_gb2_s20qpaf_answer_support_policy_cutover_decision as smoke
from nex_cx.retrieval_answer_support_policy_cutover_decision import DECISION
from test_nex_cx_retrieval_answer_support_policy_cutover_decision import (
    _bundle,
    _design,
    _review_evidence,
)

NOW = datetime(2026, 11, 6, 13, 30, tzinfo=UTC)


def test_protected_decision_approves_but_does_not_execute_cutover(tmp_path) -> None:
    receipt, report = _review_evidence()
    bundle = _bundle()
    target = tmp_path / "decision.json"

    result = smoke.run_gb2_s20qpaf_answer_support_policy_cutover_decision(
        _env(),
        design=_design(receipt, report, bundle),
        review_receipt=receipt,
        review_report=report,
        activation_bundle=bundle,
        clock=lambda: NOW,
        receipt_path=target,
    )

    assert result["status"] == "PASS"
    assert result["decision"] == DECISION
    assert result["decision_status"] == "APPROVED_NOT_EXECUTED"
    assert result["policy_cutover_permitted"] is True
    assert result["policy_cutover_executed"] is False
    assert result["runtime_change_executed"] is False
    assert result["user_visible_policy_change_approved"] is True
    assert result["user_visible_policy_change_executed"] is False
    assert result["production_cutover_permitted"] is False
    assert result["provider_calls"] == result["database_calls"] == 0
    assert result["holdout_accessed"] is False
    assert target.stat().st_mode & 0o777 == 0o600
    saved = json.loads(target.read_text(encoding="utf-8"))
    assert saved["policy_cutover_approved"] is True
    assert saved["policy_cutover_executed"] is False
    assert saved["receipt_hash"] == result["decision_receipt_hash"]
    assert "approved_not_executed" in smoke.summary_line(result)


def test_runner_requires_explicit_decision_and_is_one_shot(tmp_path) -> None:
    assert (
        smoke.run_gb2_s20qpaf_answer_support_policy_cutover_decision({})["status"]
        == "SKIPPED"
    )
    assert smoke.summary_line({"status": "SKIPPED"}).endswith("=skipped")
    assert (
        smoke.run_gb2_s20qpaf_answer_support_policy_cutover_decision(
            {smoke.SMOKE_ENV: "1"}
        )["failure_code"]
        == "explicit_policy_cutover_operator_decision_required"
    )

    used = tmp_path / "used.json"
    used.write_text("{}", encoding="utf-8")
    assert (
        smoke.run_gb2_s20qpaf_answer_support_policy_cutover_decision(
            _env(), receipt_path=used
        )["failure_code"]
        == "policy_cutover_operator_decision_already_recorded"
    )


def test_runner_fails_closed_on_source_drift_without_external_calls(tmp_path) -> None:
    receipt, report = _review_evidence()
    bundle = _bundle()
    design = _design(receipt, report, bundle)
    report["status"] = "FAIL"

    result = smoke.run_gb2_s20qpaf_answer_support_policy_cutover_decision(
        _env(),
        design=design,
        review_receipt=receipt,
        review_report=report,
        activation_bundle=bundle,
        receipt_path=tmp_path / "failure.json",
    )

    assert result["status"] == "FAIL"
    assert result["failure_code"] == "policy_cutover_operator_decision_failed"
    assert result["failure_detail"] == {"exception": "PolicyCutoverDecisionError"}
    assert result["provider_calls"] == result["database_calls"] == 0
    assert result["policy_cutover_permitted"] is False
    assert "=fail" in smoke.summary_line(result)


def test_runner_normalizes_naive_clock(tmp_path) -> None:
    receipt, report = _review_evidence()
    bundle = _bundle()
    result = smoke.run_gb2_s20qpaf_answer_support_policy_cutover_decision(
        _env(),
        design=_design(receipt, report, bundle),
        review_receipt=receipt,
        review_report=report,
        activation_bundle=bundle,
        clock=lambda: datetime(2026, 11, 6, 13, 30),  # noqa: DTZ001
        receipt_path=tmp_path / "naive.json",
    )
    assert result["status"] == "PASS"


def test_runner_helpers_and_cli_preserve_terminal_evidence(
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
        "run_gb2_s20qpaf_answer_support_policy_cutover_decision",
        lambda: {
            "status": "PASS",
            "decision": DECISION,
            "selected_policy_hash": "sha256:" + "1" * 64,
        },
    )
    assert smoke.main(["--output", str(output), "--summary"]) == 0
    assert "=pass" in capsys.readouterr().out

    output.write_text('{"status":"PASS"}\n', encoding="utf-8")
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpaf_answer_support_policy_cutover_decision",
        lambda: {"status": "SKIPPED"},
    )
    assert smoke.main(["--output", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "PASS"

    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpaf_answer_support_policy_cutover_decision",
        lambda: {"status": "FAIL", "failure_code": "forced"},
    )
    assert smoke.main(["--output", str(output)]) == 1


def _env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        smoke.DECISION_ENV: DECISION,
        smoke.OPERATOR_ENV: "operator-one",
    }
