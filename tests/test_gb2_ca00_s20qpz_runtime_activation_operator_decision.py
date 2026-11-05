from __future__ import annotations

import json
from datetime import UTC, datetime

import run_gb2_s20qpz_runtime_activation_operator_decision as smoke
from nex_cx.retrieval_answer_support_runtime_activation_decision import DECISION
from test_nex_cx_retrieval_answer_support_runtime_activation_decision import (
    _fixtures,
)

NOW = datetime(2026, 11, 5, 9, 0, tzinfo=UTC)


def test_protected_decision_approves_activation_without_installing_or_cutover(
    tmp_path,
) -> None:
    target = tmp_path / "decision.json"
    result = smoke.run_gb2_s20qpz_runtime_activation_operator_decision(
        _env(),
        clock=lambda: NOW,
        receipt_path=target,
        **_fixtures(),
    )
    assert result["status"] == "PASS"
    assert result["decision"] == DECISION
    assert result["activation_status"] == "APPROVED_NOT_ACTIVATED"
    assert result["observed_execution"]["peak_in_flight"] == 4
    assert result["runtime_activation_permitted"] is True
    assert result["runtime_activated"] is False
    assert result["user_visible_decision_change_permitted"] is False
    assert result["production_cutover_permitted"] is False
    assert result["provider_calls"] == result["database_calls"] == 0
    assert result["holdout_accessed"] is False
    assert target.stat().st_mode & 0o777 == 0o600
    receipt = json.loads(target.read_text(encoding="utf-8"))
    assert receipt["runtime_activation_approved"] is True
    assert receipt["runtime_activated"] is False
    assert "approved_not_activated" in smoke.summary_line(result)


def test_runner_requires_explicit_decision_and_is_one_shot(tmp_path) -> None:
    assert smoke.run_gb2_s20qpz_runtime_activation_operator_decision({})["status"] == (
        "SKIPPED"
    )
    assert smoke.summary_line({"status": "SKIPPED"}).endswith("=skipped")
    assert (
        smoke.run_gb2_s20qpz_runtime_activation_operator_decision(
            {smoke.SMOKE_ENV: "1"}
        )["failure_code"]
        == "explicit_runtime_activation_operator_decision_required"
    )
    used = tmp_path / "used.json"
    used.write_text("{}", encoding="utf-8")
    assert (
        smoke.run_gb2_s20qpz_runtime_activation_operator_decision(
            _env(), receipt_path=used
        )["failure_code"]
        == "runtime_activation_operator_decision_already_recorded"
    )


def test_runner_fails_closed_on_source_drift_without_external_calls(tmp_path) -> None:
    fixtures = _fixtures()
    report = dict(fixtures["e2e_report"])
    report["status"] = "FAIL"
    result = smoke.run_gb2_s20qpz_runtime_activation_operator_decision(
        _env(),
        receipt_path=tmp_path / "failure.json",
        **{**fixtures, "e2e_report": report},
    )
    assert result["status"] == "FAIL"
    assert result["failure_code"] == "runtime_activation_operator_decision_failed"
    assert result["provider_calls"] == result["database_calls"] == 0
    assert result["runtime_activation_permitted"] is False
    assert "=fail" in smoke.summary_line(result)


def test_runner_normalizes_naive_clock(tmp_path) -> None:
    result = smoke.run_gb2_s20qpz_runtime_activation_operator_decision(
        _env(),
        clock=lambda: datetime(2026, 11, 5, 9, 0),  # noqa: DTZ001
        receipt_path=tmp_path / "naive.json",
        **_fixtures(),
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
        "run_gb2_s20qpz_runtime_activation_operator_decision",
        lambda: {
            "status": "PASS",
            "decision": DECISION,
            "observed_metrics": {"e2e_p95_latency_ms": 1.0},
        },
    )
    assert smoke.main(["--output", str(output), "--summary"]) == 0
    assert "=pass" in capsys.readouterr().out
    output.write_text('{"status":"PASS"}\n', encoding="utf-8")
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpz_runtime_activation_operator_decision",
        lambda: {"status": "SKIPPED"},
    )
    assert smoke.main(["--output", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "PASS"
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpz_runtime_activation_operator_decision",
        lambda: {"status": "FAIL", "failure_code": "forced"},
    )
    assert smoke.main(["--output", str(output)]) == 1


def _env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        smoke.DECISION_ENV: DECISION,
        smoke.OPERATOR_ENV: "operator-one",
    }
