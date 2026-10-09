from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

from nex_runtime.production_release import evaluate_release_approval_governance
import run_s150_approval_change_governance as runner


NOW = datetime(2026, 10, 9, 8, 0, tzinfo=UTC)
RELEASE_ID = "rc:s149:730196df68414600"
RELEASE_DIGEST = f"sha256:{'1' * 64}"
ROLES = ("release_manager", "operations_owner", "security_owner", "data_owner")


def _approval(role: str) -> dict:
    return {
        "role": role,
        "subject": f"{role}_subject",
        "decision": "APPROVE",
        "release_candidate_id": RELEASE_ID,
        "release_set_digest": RELEASE_DIGEST,
        "approved_at": (NOW - timedelta(hours=1)).isoformat(),
        "expires_at": (NOW + timedelta(hours=4)).isoformat(),
    }


def _document() -> dict:
    return {
        "decision_only": True,
        "deployment_execution_requested": False,
        "approvals": [_approval(role) for role in ROLES],
        "change_window": {
            "change_id": "change_20261009_01",
            "starts_at": (NOW - timedelta(minutes=5)).isoformat(),
            "ends_at": (NOW + timedelta(hours=1)).isoformat(),
            "rollback_deadline": (NOW + timedelta(hours=2)).isoformat(),
            "deployment_actor": "deployment_operator_subject",
        },
    }


def _evaluate(document: dict) -> dict:
    return evaluate_release_approval_governance(
        document,
        expected_release_candidate_id=RELEASE_ID,
        expected_release_set_digest=RELEASE_DIGEST,
        evaluated_at=NOW,
    )


def test_approval_governance_accepts_exact_roles_window_and_separation() -> None:
    result = _evaluate(_document())

    assert result["status"] == "PASS", result
    assert result["decision_readiness"] == "GO"
    assert all(result["gate_results"].values())
    assert result["missing_approval_roles"] == []


def test_approval_governance_preserves_missing_approvals_as_no_go() -> None:
    result = _evaluate(
        {
            "decision_only": True,
            "deployment_execution_requested": False,
            "approvals": [],
        }
    )

    assert result["status"] == "PASS"
    assert result["decision_readiness"] == "NO_GO"
    assert result["gate_results"] == {
        "approval_roles_complete": False,
        "production_deployment_separate": True,
    }
    assert result["missing_approval_roles"] == sorted(ROLES)


def test_approval_governance_rejects_malformed_and_drifted_approvals() -> None:
    document = _document()
    document["approvals"] = [
        "bad",
        {
            **_approval("release_manager"),
            "subject": "",
            "decision": "DENY",
            "release_candidate_id": "wrong",
            "release_set_digest": "wrong",
            "approved_at": (NOW + timedelta(hours=1)).isoformat(),
            "expires_at": (NOW - timedelta(hours=1)).isoformat(),
        },
        _approval("release_manager"),
        _approval("unknown_role"),
    ]
    result = _evaluate(document)

    assert result["status"] == "FAIL"
    assert result["decision_readiness"] == "NO_GO"
    assert {
        "approval[0].mapping",
        "approval[1].subject",
        "approval[1].decision",
        "approval[1].release_candidate_id",
        "approval[1].release_set_digest",
        "approval[1].validity_window",
        "approval[2].duplicate_role",
        "approval[3].role",
    }.issubset(result["errors"])


def test_approval_governance_rejects_bad_list_window_and_deployment_coupling() -> None:
    invalid_list = _evaluate(
        {
            "decision_only": False,
            "deployment_execution_requested": True,
            "approvals": {},
            "change_window": "bad",
        }
    )
    assert invalid_list["status"] == "FAIL"
    assert invalid_list["gate_results"]["production_deployment_separate"] is False
    assert {"approvals.list", "change_window.mapping"}.issubset(
        invalid_list["errors"]
    )

    bad_window = _document()
    bad_window["change_window"]["deployment_actor"] = "release_manager_subject"
    result = _evaluate(bad_window)
    assert result["status"] == "FAIL"
    assert result["change_window_valid"] is False
    assert "change_window.validity" in result["errors"]

    try:
        evaluate_release_approval_governance(
            {},
            expected_release_candidate_id=RELEASE_ID,
            expected_release_set_digest=RELEASE_DIGEST,
            evaluated_at=datetime(2026, 10, 9),
        )
    except ValueError as exc:
        assert "timezone-aware" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("ValueError was not raised")


def test_runner_skip_current_no_go_ready_and_fail_closed(tmp_path: Path) -> None:
    risk = tmp_path / "risk.json"
    approvals = tmp_path / "approvals.json"
    output = tmp_path / "approval-result.json"
    risk.write_text(
        json.dumps(
            {
                "status": "PASS",
                "release_candidate_id": RELEASE_ID,
                "release_set_digest": RELEASE_DIGEST,
            }
        ),
        encoding="utf-8",
    )

    skipped = runner.run_approval_change_governance(
        risk_path=risk,
        approval_path=approvals,
        output_path=output,
        environ={},
        evaluated_at=NOW,
    )
    assert skipped["status"] == "SKIPPED"

    current = runner.run_approval_change_governance(
        risk_path=risk,
        approval_path=approvals,
        output_path=output,
        environ={runner.ACTIVATION_ENV: "1"},
        evaluated_at=NOW,
    )
    assert current["status"] == "PASS"
    assert current["decision_readiness"] == "NO_GO"
    assert current["implicit_deployment_performed"] is False
    assert json.loads(output.read_text())["decision_readiness"] == "NO_GO"

    approvals.write_text(json.dumps(_document()), encoding="utf-8")
    ready = runner.run_approval_change_governance(
        risk_path=risk,
        approval_path=approvals,
        output_path=output,
        environ={runner.ACTIVATION_ENV: "1"},
        evaluated_at=NOW,
    )
    assert ready["decision_readiness"] == "GO"

    invalid = _document()
    invalid["change_window"] = "bad"
    approvals.write_text(json.dumps(invalid), encoding="utf-8")
    invalid_output = tmp_path / "invalid.json"
    failed = runner.run_approval_change_governance(
        risk_path=risk,
        approval_path=approvals,
        output_path=invalid_output,
        environ={runner.ACTIVATION_ENV: "1"},
        evaluated_at=NOW,
    )
    assert failed["status"] == "FAIL"
    assert not invalid_output.exists()

    risk.write_text(json.dumps({"status": "FAIL"}), encoding="utf-8")
    assert runner.run_approval_change_governance(
        risk_path=risk,
        approval_path=approvals,
        output_path=output,
        environ={runner.ACTIVATION_ENV: "1"},
        evaluated_at=NOW,
    )["status"] == "FAIL"


def test_runner_helpers_clock_and_main(monkeypatch, tmp_path: Path, capsys) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("[]", encoding="utf-8")
    assert runner._load_json(bad) == {}
    bad.write_text("bad", encoding="utf-8")
    assert runner._load_json(bad) == {}
    assert runner.summary_line({"status": "SKIPPED"}) == "s150_approval_governance=skipped"
    assert runner.summary_line({"status": "FAIL"}) == "s150_approval_governance=fail"
    passing = {
        "status": "PASS",
        "decision_readiness": "NO_GO",
        "change_window_valid": False,
        "gate_results": {"production_deployment_separate": True},
        "summary": {"approved_role_count": 0, "required_role_count": 4},
    }
    assert "roles=0/4" in runner.summary_line(passing)

    risk = tmp_path / "risk.json"
    risk.write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
    invalid_clock = runner.run_approval_change_governance(
        risk_path=risk,
        approval_path=tmp_path / "missing.json",
        output_path=tmp_path / "output.json",
        environ={runner.ACTIVATION_ENV: "1"},
        evaluated_at=datetime(2026, 10, 9),
    )
    assert invalid_clock["status"] == "FAIL"

    monkeypatch.setattr(runner, "run_approval_change_governance", lambda **kwargs: passing)
    assert runner.main(["--summary"]) == 0
    assert "s150_approval_governance=pass" in capsys.readouterr().out
    monkeypatch.setattr(
        runner,
        "run_approval_change_governance",
        lambda **kwargs: {"status": "FAIL"},
    )
    assert runner.main([]) == 1
