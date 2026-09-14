from __future__ import annotations

import pytest

import run_ag_operator_review_escalation_dispatch_daemon_privacy_regression as smoke


def test_dispatch_daemon_privacy_regression_passes() -> None:
    evidence = smoke.run_ag_operator_review_escalation_dispatch_daemon_privacy_regression()

    assert evidence["status"] == "PASS"
    assert evidence["smoke_schema_version"] == smoke.SCHEMA_VERSION
    assert evidence["surface_count"] == 7
    assert all(evidence["checks"].values())
    summary = smoke.summary_line(evidence)
    assert "privacy_regression=pass" in summary
    assert "forbidden_absent=True" in summary


def test_dispatch_daemon_privacy_regression_main_json_and_summary(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_ag_operator_review_escalation_dispatch_daemon_privacy_regression",
        lambda: {
            "smoke_schema_version": smoke.SCHEMA_VERSION,
            "status": "PASS",
            "surface_count": 1,
            "checks": {"forbidden_values_absent": True},
        },
    )

    assert smoke.main(["--summary"]) == 0
    assert "privacy_regression=pass" in capsys.readouterr().out

    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out


def test_dispatch_daemon_privacy_regression_failure_summary(monkeypatch) -> None:
    monkeypatch.setattr(
        smoke,
        "run_ag_operator_review_escalation_dispatch_daemon_privacy_regression",
        lambda: {"status": "FAIL", "failure_code": "checks_failed"},
    )

    assert smoke.main(["--summary"]) == 1
    assert "failure=checks_failed" in smoke.summary_line(
        {"status": "FAIL", "failure_code": "checks_failed"}
    )


def test_dispatch_daemon_privacy_regression_detects_forbidden_values() -> None:
    assert smoke._forbidden_values_absent("safe text") is True
    assert smoke._forbidden_values_absent(smoke.FORBIDDEN_VALUES[0]) is False

    with pytest.raises(ValueError):
        smoke._assert_no_forbidden_values(smoke.FORBIDDEN_VALUES[1])
