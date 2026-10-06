from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from nex_runtime.release_candidate import (
    RELEASE_CANDIDATE_GATE_SPECS,
    build_release_candidate_gate_matrix,
    evaluate_release_candidate_evidence,
)
import run_platform_release_candidate_gate_matrix as runner


NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


def _payload() -> dict:
    return runner.build_sample_release_candidate_evidence(observed_at=NOW)


def test_gate_matrix_freezes_nine_blocking_gates() -> None:
    matrix = build_release_candidate_gate_matrix()

    assert matrix["all_gates_blocking"] is True
    assert matrix["skipped_allowed"] is False
    assert len(matrix["gates"]) == 9
    assert [item["gate_id"] for item in matrix["gates"]] == [
        spec.gate_id for spec in RELEASE_CANDIDATE_GATE_SPECS
    ]
    assert sum(item["execution_mode"] == "protected" for item in matrix["gates"]) == 5


def test_complete_release_candidate_evidence_passes() -> None:
    result = evaluate_release_candidate_evidence(_payload(), evaluated_at=NOW)

    assert result["status"] == "PASS"
    assert result["decision"] == "RELEASE_CANDIDATE"
    assert all(result["checks"].values())
    assert all(item["passed"] for item in result["gate_checks"].values())
    assert result["summary"] == {
        "required_gate_count": 9,
        "observed_gate_count": 9,
        "passed_gate_count": 9,
        "protected_gate_count": 5,
        "actual_protected_gate_count": 5,
        "privacy_violation_count": 0,
    }


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["evidence"].pop(),
        lambda value: value["evidence"].append(deepcopy(value["evidence"][0])),
        lambda value: value["evidence"][0].update(status="SKIPPED"),
        lambda value: value["evidence"][0].update(evidence_digest="bad"),
        lambda value: value["evidence"][0].update(private_payload_included=True),
        lambda value: value["evidence"][1].update(actual_execution=False),
        lambda value: value["evidence"][0]["metrics"].update(passed_scenario_count=9),
        lambda value: value.update(production_deployment_approved=True),
    ],
)
def test_evidence_fails_closed_for_incomplete_or_invalid_gates(mutation) -> None:
    payload = _payload()
    mutation(payload)

    result = evaluate_release_candidate_evidence(payload, evaluated_at=NOW)

    assert result["status"] == "FAIL"
    assert result["decision"] == "BLOCKED"
    assert result["failed_checks"]


@pytest.mark.parametrize(
    ("observed_at", "expected_fresh"),
    [
        (NOW - timedelta(hours=25), False),
        (NOW + timedelta(minutes=6), False),
        (NOW + timedelta(minutes=5), True),
        (None, False),
        ("not-a-date", False),
        ("2026-10-06T12:00:00", False),
    ],
)
def test_freshness_is_bounded_and_timezone_aware(observed_at, expected_fresh) -> None:
    payload = _payload()
    value = (
        observed_at.isoformat().replace("+00:00", "Z")
        if isinstance(observed_at, datetime)
        else observed_at
    )
    payload["evidence"][0]["observed_at"] = value

    result = evaluate_release_candidate_evidence(payload, evaluated_at=NOW)

    assert result["gate_checks"]["golden_scenarios"]["conditions"]["fresh"] is expected_fresh
    assert (result["status"] == "PASS") is expected_fresh


@pytest.mark.parametrize(
    "gate_id",
    [spec.gate_id for spec in RELEASE_CANDIDATE_GATE_SPECS],
)
def test_each_gate_metric_fails_closed(gate_id: str) -> None:
    payload = _payload()
    record = next(item for item in payload["evidence"] if item["gate_id"] == gate_id)
    record["metrics"] = {}

    result = evaluate_release_candidate_evidence(payload, evaluated_at=NOW)

    assert result["gate_checks"][gate_id]["conditions"]["gate_metric_satisfied"] is False
    assert result["status"] == "FAIL"


def test_privacy_violation_is_reported_without_secret_value() -> None:
    payload = _payload()
    payload["evidence"][0]["password"] = "do-not-project-this"

    result = evaluate_release_candidate_evidence(payload, evaluated_at=NOW)

    assert result["status"] == "FAIL"
    assert result["checks"]["privacy_safe"] is False
    assert result["privacy_violations"] == ["$.evidence[0].password"]
    assert "do-not-project-this" not in str(result)


def test_malformed_evidence_and_configuration_fail_safely() -> None:
    malformed = evaluate_release_candidate_evidence(
        {"evidence": "bad", "production_deployment_approved": False},
        evaluated_at=NOW,
    )
    assert malformed["status"] == "FAIL"
    assert malformed["summary"]["observed_gate_count"] == 0

    with pytest.raises(ValueError):
        evaluate_release_candidate_evidence(_payload(), evaluated_at=NOW, max_age_hours=0)
    with pytest.raises(ValueError):
        evaluate_release_candidate_evidence(
            _payload(), evaluated_at=datetime(2026, 10, 6, 12, 0)
        )


def test_runner_summary_and_main(monkeypatch, capsys) -> None:
    result = runner.run_platform_release_candidate_gate_matrix()
    assert result["status"] == "PASS"
    assert runner.summary_line(result) == (
        "platform_release_candidate_gate_matrix=pass gates=9/9 "
        "protected=5/5 next=1394"
    )
    assert runner.summary_line({"status": "FAIL", "failed_checks": ["a"]}) == (
        "platform_release_candidate_gate_matrix=fail checks=1"
    )

    monkeypatch.setattr(runner, "run_platform_release_candidate_gate_matrix", lambda: result)
    assert runner.main(["--summary"]) == 0
    assert "next=1394" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        runner,
        "run_platform_release_candidate_gate_matrix",
        lambda: {"status": "FAIL", "failed_checks": []},
    )
    assert runner.main([]) == 1
