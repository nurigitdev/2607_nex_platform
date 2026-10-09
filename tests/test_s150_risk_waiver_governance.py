from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

from nex_runtime.production_release import evaluate_release_risk_governance
import run_s150_risk_waiver_governance as runner


NOW = datetime(2026, 10, 9, 7, 0, tzinfo=UTC)


def _closed_p0() -> dict:
    return {
        "risk_id": "release_recovery",
        "priority": "P0",
        "status": "CLOSED",
        "owner": "platform_operations",
        "evidence_digest": f"sha256:{'1' * 64}",
    }


def _open_p1() -> dict:
    return {
        "risk_id": "external_notification_delivery",
        "priority": "P1",
        "status": "OPEN",
        "owner": "ag_operations_owner",
    }


def _waiver() -> dict:
    return {
        "waiver_id": "external_notification_waiver",
        "risk_id": "external_notification_delivery",
        "owner": "ag_operations_owner",
        "approver": "release_manager",
        "issued_at": (NOW - timedelta(hours=1)).isoformat(),
        "expires_at": (NOW + timedelta(days=7)).isoformat(),
        "compensating_control": "local_ag_workbench_and_operator_watch",
        "rollback_trigger": "notification_or_operator_watch_unavailable",
        "review_cadence_hours": 24,
    }


def test_governance_accepts_closed_p0_and_valid_p1_waiver() -> None:
    result = evaluate_release_risk_governance(
        [_closed_p0(), _open_p1()],
        [_waiver()],
        evaluated_at=NOW,
    )

    assert result["status"] == "PASS", result
    assert result["decision_readiness"] == "GO"
    assert result["gate_results"] == {
        "no_open_p0": True,
        "p1_waivers_valid": True,
    }
    assert result["summary"]["valid_waiver_count"] == 1


def test_governance_keeps_missing_waiver_as_explicit_no_go() -> None:
    result = evaluate_release_risk_governance([_open_p1()], [], evaluated_at=NOW)

    assert result["status"] == "PASS"
    assert result["decision_readiness"] == "NO_GO"
    assert result["waiver_required_risk_ids"] == [
        "external_notification_delivery"
    ]
    assert result["gate_results"]["p1_waivers_valid"] is False


def test_governance_rejects_open_p0_and_invalid_waiver_fields() -> None:
    open_p0 = {**_closed_p0(), "status": "OPEN"}
    invalid = {
        **_waiver(),
        "waiver_id": "INVALID-ID",
        "owner": "same",
        "approver": "same",
        "issued_at": (NOW + timedelta(hours=1)).isoformat(),
        "expires_at": (NOW + timedelta(days=40)).isoformat(),
        "compensating_control": "",
        "rollback_trigger": "",
        "review_cadence_hours": True,
    }
    result = evaluate_release_risk_governance(
        [open_p0, _open_p1()],
        [invalid, _waiver()],
        evaluated_at=NOW,
    )

    assert result["status"] == "FAIL"
    assert result["decision_readiness"] == "NO_GO"
    assert result["open_p0_risk_ids"] == ["release_recovery"]
    assert {
        "waiver[0].waiver_id",
        "waiver[0].owner_approver_separation",
        "waiver[0].validity_window",
        "waiver[0].compensating_control",
        "waiver[0].rollback_trigger",
        "waiver[0].review_cadence_hours",
        "waiver[1].duplicate_risk",
    }.issubset(result["errors"])


def test_governance_rejects_malformed_risks_or_ineligible_waivers() -> None:
    malformed = [
        {
            "risk_id": "BAD-ID",
            "priority": "P2",
            "status": "UNKNOWN",
        },
        {
            "risk_id": "duplicate_risk",
            "priority": "P0",
            "status": "CLOSED",
            "evidence_digest": "bad",
        },
        {
            "risk_id": "duplicate_risk",
            "priority": "P0",
            "status": "CLOSED",
            "evidence_digest": f"sha256:{'2' * 64}",
        },
    ]
    waiver = {**_waiver(), "risk_id": "missing_risk"}
    result = evaluate_release_risk_governance(malformed, [waiver], evaluated_at=NOW)

    assert result["status"] == "FAIL"
    assert {
        "risk[0].risk_id",
        "risk[0].priority",
        "risk[0].status",
        "risk[1].evidence_digest",
        "risk[2].duplicate",
        "waiver[0].eligible_risk",
    }.issubset(result["errors"])

    try:
        evaluate_release_risk_governance([], [], evaluated_at=datetime(2026, 10, 9))
    except ValueError as exc:
        assert "timezone-aware" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("ValueError was not raised")


def test_runner_skip_no_go_pass_and_fail_closed_inputs(tmp_path: Path) -> None:
    admission = tmp_path / "admission.json"
    waivers = tmp_path / "waivers.json"
    output = tmp_path / "risk.json"
    admission.write_text(
        json.dumps(
            {
                "status": "PASS",
                "release_candidate_id": "rc:s149:730196df68414600",
                "release_set_digest": f"sha256:{'1' * 64}",
            }
        ),
        encoding="utf-8",
    )

    skipped = runner.run_risk_waiver_governance(
        admission_path=admission,
        waiver_path=waivers,
        output_path=output,
        environ={},
        evaluated_at=NOW,
    )
    assert skipped["status"] == "SKIPPED"

    current = runner.run_risk_waiver_governance(
        admission_path=admission,
        waiver_path=waivers,
        output_path=output,
        environ={runner.ACTIVATION_ENV: "1"},
        evaluated_at=NOW,
    )
    assert current["status"] == "PASS"
    assert current["decision_readiness"] == "NO_GO"
    assert current["gate_results"]["no_open_p0"] is True
    assert current["gate_results"]["p1_waivers_valid"] is False
    assert json.loads(output.read_text())["decision_readiness"] == "NO_GO"

    waivers.write_text(json.dumps({"waivers": [_waiver()]}), encoding="utf-8")
    ready = runner.run_risk_waiver_governance(
        admission_path=admission,
        waiver_path=waivers,
        output_path=output,
        environ={runner.ACTIVATION_ENV: "1"},
        evaluated_at=NOW,
    )
    assert ready["decision_readiness"] == "GO"

    invalid_waiver = {**_waiver(), "approver": "ag_operations_owner"}
    waivers.write_text(
        json.dumps({"waivers": [invalid_waiver]}), encoding="utf-8"
    )
    invalid_output = tmp_path / "invalid-risk.json"
    invalid = runner.run_risk_waiver_governance(
        admission_path=admission,
        waiver_path=waivers,
        output_path=invalid_output,
        environ={runner.ACTIVATION_ENV: "1"},
        evaluated_at=NOW,
    )
    assert invalid["status"] == "FAIL"
    assert not invalid_output.exists()

    waivers.write_text(json.dumps({"waivers": {}}), encoding="utf-8")
    assert runner.run_risk_waiver_governance(
        admission_path=admission,
        waiver_path=waivers,
        output_path=output,
        environ={runner.ACTIVATION_ENV: "1"},
        evaluated_at=NOW,
    )["status"] == "FAIL"

    admission.write_text(json.dumps({"status": "FAIL"}), encoding="utf-8")
    assert runner.run_risk_waiver_governance(
        admission_path=admission,
        waiver_path=waivers,
        output_path=output,
        environ={runner.ACTIVATION_ENV: "1"},
        evaluated_at=NOW,
    )["status"] == "FAIL"


def test_runner_helpers_value_error_and_main(monkeypatch, tmp_path: Path, capsys) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("[]", encoding="utf-8")
    assert runner._load_json(bad) == {}
    bad.write_text("bad", encoding="utf-8")
    assert runner._load_json(bad) == {}
    assert runner.summary_line({"status": "SKIPPED"}) == "s150_risk_governance=skipped"
    assert runner.summary_line({"status": "FAIL"}) == "s150_risk_governance=fail"
    passing = {
        "status": "PASS",
        "decision_readiness": "NO_GO",
        "gate_results": {"p1_waivers_valid": False},
        "summary": {"open_p0_count": 0, "open_p1_count": 1},
    }
    assert "readiness=NO_GO" in runner.summary_line(passing)

    admission = tmp_path / "admission.json"
    admission.write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
    invalid_clock = runner.run_risk_waiver_governance(
        admission_path=admission,
        waiver_path=tmp_path / "missing.json",
        output_path=tmp_path / "output.json",
        environ={runner.ACTIVATION_ENV: "1"},
        evaluated_at=datetime(2026, 10, 9),
    )
    assert invalid_clock["status"] == "FAIL"

    monkeypatch.setattr(runner, "run_risk_waiver_governance", lambda **kwargs: passing)
    assert runner.main(["--summary"]) == 0
    assert "s150_risk_governance=pass" in capsys.readouterr().out
    monkeypatch.setattr(
        runner,
        "run_risk_waiver_governance",
        lambda **kwargs: {"status": "FAIL"},
    )
    assert runner.main([]) == 1
