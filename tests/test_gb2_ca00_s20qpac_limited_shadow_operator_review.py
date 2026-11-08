from __future__ import annotations

import json
from datetime import UTC, datetime

import run_gb2_s20qpac_limited_shadow_operator_review as smoke
from nex_cx.retrieval_answer_support_limited_review import DECISION
from test_nex_cx_retrieval_answer_support_limited_review import _design, _report

NOW = datetime(2026, 11, 5, 12, 30, tzinfo=UTC)


def test_protected_review_approves_only_an_unexecuted_second_window(tmp_path) -> None:
    report = _report()
    target = tmp_path / "decision.json"

    result = smoke.run_gb2_s20qpac_limited_shadow_operator_review(
        _env(),
        design=_design(report),
        source_report=report,
        clock=lambda: NOW,
        receipt_path=target,
    )

    assert result["status"] == "PASS"
    assert result["decision"] == DECISION
    assert result["decision_status"] == "APPROVED_NOT_EXECUTED"
    assert result["observed_metrics"]["sample_count"] == 12
    assert result["next_window"]["maximum_provider_samples"] == 30
    assert result["next_window"]["maximum_concurrency"] == 4
    assert result["continuation_decision_permitted"] is True
    assert result["continuation_execution_permitted"] is False
    assert result["user_visible_decision_change_permitted"] is False
    assert result["production_cutover_permitted"] is False
    assert result["provider_calls"] == result["database_calls"] == 0
    assert result["holdout_accessed"] is False
    assert target.stat().st_mode & 0o777 == 0o600
    receipt = json.loads(target.read_text(encoding="utf-8"))
    assert receipt["continuation_approved"] is True
    assert receipt["continuation_executed"] is False
    assert receipt["receipt_hash"] == result["decision_receipt_hash"]
    assert "next_cap=30" in smoke.summary_line(result)


def test_runner_requires_explicit_decision_and_is_one_shot(tmp_path) -> None:
    assert smoke.run_gb2_s20qpac_limited_shadow_operator_review({})[
        "status"
    ] == "SKIPPED"
    assert smoke.summary_line({"status": "SKIPPED"}).endswith("=skipped")
    assert smoke.run_gb2_s20qpac_limited_shadow_operator_review(
        {smoke.SMOKE_ENV: "1"}
    )["failure_code"] == "explicit_operator_continuation_decision_required"

    used = tmp_path / "used.json"
    used.write_text("{}", encoding="utf-8")
    assert smoke.run_gb2_s20qpac_limited_shadow_operator_review(
        _env(), receipt_path=used
    )["failure_code"] == "limited_shadow_operator_decision_already_recorded"


def test_runner_fails_closed_on_source_drift_without_external_calls(tmp_path) -> None:
    report = _report()
    design = _design(report)
    report["status"] = "FAIL"

    result = smoke.run_gb2_s20qpac_limited_shadow_operator_review(
        _env(),
        design=design,
        source_report=report,
        receipt_path=tmp_path / "failure.json",
    )

    assert result["status"] == "FAIL"
    assert result["failure_code"] == "limited_shadow_operator_review_failed"
    assert result["failure_detail"] == {
        "exception": "LimitedShadowReviewError"
    }
    assert result["provider_calls"] == result["database_calls"] == 0
    assert result["continuation_decision_permitted"] is False
    assert "=fail" in smoke.summary_line(result)


def test_runner_normalizes_naive_clock(tmp_path) -> None:
    report = _report()
    result = smoke.run_gb2_s20qpac_limited_shadow_operator_review(
        _env(),
        design=_design(report),
        source_report=report,
        clock=lambda: datetime(2026, 11, 5, 12, 30),  # noqa: DTZ001
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
        "run_gb2_s20qpac_limited_shadow_operator_review",
        lambda: {
            "status": "PASS",
            "decision": DECISION,
            "observed_metrics": {"sample_count": 12},
            "next_window": {"maximum_provider_samples": 30},
        },
    )
    assert smoke.main(["--output", str(output), "--summary"]) == 0
    assert "=pass" in capsys.readouterr().out

    output.write_text('{"status":"PASS"}\n', encoding="utf-8")
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpac_limited_shadow_operator_review",
        lambda: {"status": "SKIPPED"},
    )
    assert smoke.main(["--output", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "PASS"

    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpac_limited_shadow_operator_review",
        lambda: {"status": "FAIL", "failure_code": "forced"},
    )
    assert smoke.main(["--output", str(output)]) == 1


def _env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        smoke.DECISION_ENV: DECISION,
        smoke.OPERATOR_ENV: "operator-one",
    }
