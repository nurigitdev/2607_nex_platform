from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import run_gb2_s20qpu_runtime_cutover_operator_decision as smoke
from nex_cx.retrieval_answer_support_cutover_decision import CUTOVER_DECISION
from test_nex_cx_retrieval_answer_support_cutover_decision import _fixtures

NOW = datetime(2026, 11, 5, 3, 0, tzinfo=UTC)


def test_protected_operator_decision_records_deferred_cutover(tmp_path) -> None:
    receipt, design = _fixtures()
    target = tmp_path / "decision.json"

    result = smoke.run_gb2_s20qpu_runtime_cutover_operator_decision(
        _env(),
        source_receipt=receipt,
        design=design,
        clock=lambda: NOW,
        decision_receipt_path=target,
    )

    assert result["status"] == "PASS"
    assert result["decision"] == CUTOVER_DECISION
    assert result["reason_codes"] == [
        "SHADOW_SAMPLE_COUNT_BELOW_MINIMUM",
        "PRODUCTION_LATENCY_SLO_NOT_FROZEN",
        "DISAGREEMENT_REQUIRES_EXTENDED_OBSERVATION",
    ]
    assert result["provider_calls"] == 0
    assert result["database_calls"] == 0
    assert result["holdout_accessed"] is False
    assert result["runtime_activation_permitted"] is False
    assert result["production_cutover_permitted"] is False
    assert target.stat().st_mode & 0o777 == 0o600
    assert json.loads(target.read_text())["decision"] == CUTOVER_DECISION
    assert "samples=6" in smoke.summary_line(result)
    assert "p95_ms=38912.964" in smoke.summary_line(result)


def test_runner_requires_explicit_deferral_and_is_one_shot(tmp_path) -> None:
    assert smoke.run_gb2_s20qpu_runtime_cutover_operator_decision({})[
        "status"
    ] == "SKIPPED"
    assert smoke.summary_line({"status": "SKIPPED"}).endswith("=skipped")
    assert smoke.run_gb2_s20qpu_runtime_cutover_operator_decision(
        {smoke.SMOKE_ENV: "1"}
    )["failure_code"] == "explicit_operator_deferral_required"

    receipt, design = _fixtures()
    target = tmp_path / "used.json"
    target.write_text("{}", encoding="utf-8")
    result = smoke.run_gb2_s20qpu_runtime_cutover_operator_decision(
        _env(),
        source_receipt=receipt,
        design=design,
        decision_receipt_path=target,
    )
    assert result["failure_code"] == "operator_decision_already_recorded"
    assert "already_recorded" in smoke.summary_line(result)


def test_runner_consumes_contract_failure_without_provider_access(tmp_path) -> None:
    receipt, design = _fixtures()
    receipt["status"] = "FAIL"
    result = smoke.run_gb2_s20qpu_runtime_cutover_operator_decision(
        _env(),
        source_receipt=receipt,
        design=design,
        decision_receipt_path=tmp_path / "failure.json",
    )

    assert result["status"] == "FAIL"
    assert result["failure_code"] == "runtime_cutover_operator_decision_failed"
    assert result["failure_detail"] == {
        "exception": "AnswerSupportCutoverDecisionError"
    }
    assert result["provider_calls"] == 0


def test_runner_normalizes_naive_clock(tmp_path) -> None:
    receipt, design = _fixtures()
    result = smoke.run_gb2_s20qpu_runtime_cutover_operator_decision(
        _env(),
        source_receipt=receipt,
        design=design,
        clock=lambda: datetime(2026, 11, 5, 3, 0),
        decision_receipt_path=tmp_path / "naive.json",
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
        "run_gb2_s20qpu_runtime_cutover_operator_decision",
        lambda: {"status": "PASS", "decision": CUTOVER_DECISION},
    )
    assert smoke.main(["--output", str(output), "--summary"]) == 0
    assert "=pass" in capsys.readouterr().out

    output.write_text('{"status":"PASS"}\n', encoding="utf-8")
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpu_runtime_cutover_operator_decision",
        lambda: {"status": "SKIPPED"},
    )
    assert smoke.main(["--output", str(output)]) == 0
    assert json.loads(output.read_text())["status"] == "PASS"

    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpu_runtime_cutover_operator_decision",
        lambda: {"status": "FAIL", "failure_code": "forced"},
    )
    assert smoke.main(["--output", str(output)]) == 1


def _env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        smoke.DECISION_ENV: CUTOVER_DECISION,
        smoke.OPERATOR_ENV: "operator-one",
    }
