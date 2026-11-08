from __future__ import annotations

import json
from datetime import UTC, datetime

import run_gb2_s20qpx_interactive_slo_policy_decision as smoke
from nex_cx.retrieval_answer_support_interactive_slo_policy import DECISION
from test_nex_cx_retrieval_answer_support_interactive_slo_policy import _fixtures

NOW = datetime(2026, 11, 5, 8, 0, tzinfo=UTC)


def test_protected_policy_decision_selects_sync_c4_without_activation(tmp_path) -> None:
    fixtures = _fixtures()
    target = tmp_path / "decision.json"
    result = smoke.run_gb2_s20qpx_interactive_slo_policy_decision(
        _env(),
        design=fixtures["design"],
        capacity_design=fixtures["capacity_design"],
        control_design=fixtures["control_design"],
        capacity_receipt=fixtures["capacity_receipt"],
        control_receipt=fixtures["control_receipt"],
        clock=lambda: NOW,
        receipt_path=target,
    )
    assert result["status"] == "PASS"
    assert result["decision"] == DECISION
    assert (
        result["selected_policy"]["runtime_policy"][
            "maximum_in_flight_provider_requests"
        ]
        == 4
    )
    assert result["observed_capacity"]["selected_concurrency"] == 4
    assert result["execution_mode_selected"] is True
    assert result["provider_calls"] == 0
    assert result["database_calls"] == 0
    assert result["holdout_accessed"] is False
    assert result["runtime_activation_permitted"] is False
    assert result["production_cutover_permitted"] is False
    assert target.stat().st_mode & 0o777 == 0o600
    assert json.loads(target.read_text())["decision"] == DECISION
    assert "concurrency=4" in smoke.summary_line(result)


def test_runner_requires_explicit_decision_and_is_one_shot(tmp_path) -> None:
    assert (
        smoke.run_gb2_s20qpx_interactive_slo_policy_decision({})["status"] == "SKIPPED"
    )
    assert smoke.summary_line({"status": "SKIPPED"}).endswith("=skipped")
    assert (
        smoke.run_gb2_s20qpx_interactive_slo_policy_decision({smoke.SMOKE_ENV: "1"})[
            "failure_code"
        ]
        == "explicit_operator_policy_decision_required"
    )
    target = tmp_path / "used.json"
    target.write_text("{}", encoding="utf-8")
    assert (
        smoke.run_gb2_s20qpx_interactive_slo_policy_decision(
            _env(), receipt_path=target
        )["failure_code"]
        == "interactive_slo_policy_decision_already_recorded"
    )


def test_runner_consumes_source_failure_without_external_calls(tmp_path) -> None:
    fixtures = _fixtures()
    receipt = dict(fixtures["capacity_receipt"])
    receipt["status"] = "FAIL"
    result = smoke.run_gb2_s20qpx_interactive_slo_policy_decision(
        _env(),
        design=fixtures["design"],
        capacity_design=fixtures["capacity_design"],
        control_design=fixtures["control_design"],
        capacity_receipt=receipt,
        control_receipt=fixtures["control_receipt"],
        receipt_path=tmp_path / "failure.json",
    )
    assert result["status"] == "FAIL"
    assert result["failure_code"] == "interactive_slo_policy_decision_failed"
    assert result["provider_calls"] == 0
    assert result["database_calls"] == 0
    assert "=fail" in smoke.summary_line(result)


def test_runner_normalizes_naive_clock(tmp_path) -> None:
    fixtures = _fixtures()
    result = smoke.run_gb2_s20qpx_interactive_slo_policy_decision(
        _env(),
        design=fixtures["design"],
        capacity_design=fixtures["capacity_design"],
        control_design=fixtures["control_design"],
        capacity_receipt=fixtures["capacity_receipt"],
        control_receipt=fixtures["control_receipt"],
        clock=lambda: datetime(2026, 11, 5, 8, 0),  # noqa: DTZ001
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
        "run_gb2_s20qpx_interactive_slo_policy_decision",
        lambda: {"status": "PASS", "decision": DECISION},
    )
    assert smoke.main(["--output", str(output), "--summary"]) == 0
    assert "=pass" in capsys.readouterr().out
    output.write_text('{"status": "PASS"}\n', encoding="utf-8")
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpx_interactive_slo_policy_decision",
        lambda: {"status": "SKIPPED"},
    )
    assert smoke.main(["--output", str(output)]) == 0
    assert json.loads(output.read_text())["status"] == "PASS"
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpx_interactive_slo_policy_decision",
        lambda: {"status": "FAIL", "failure_code": "forced"},
    )
    assert smoke.main(["--output", str(output)]) == 1


def _env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        smoke.DECISION_ENV: DECISION,
        smoke.OPERATOR_ENV: "operator-one",
    }
