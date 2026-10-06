from __future__ import annotations

from datetime import UTC, datetime
import json

import pytest

import run_platform_release_candidate_browser_ag_operations as runner
from nex_runtime.release_candidate_operations import (
    RELEASE_CANDIDATE_OPERATIONS_SCHEMA_VERSION,
    build_release_candidate_browser_ag_evidence,
)


def passing_browser() -> dict[str, object]:
    return {
        "status": "PASS",
        "actual_postgres": True,
        "actual_browser": True,
        "actual_service_processes": True,
        "provider_mode": "deterministic_mock",
        "remote_provider_required": False,
        "checks": {"browser": True, "redacted": True},
        "summary": {
            "viewport_count": 2,
            "journey_stage_count": 9,
            "service_process_count": 13,
            "database_count": 3,
        },
        "residue": {"oa": 0, "ae": 0, "cx": 0, "files": 0},
    }


def passing_ag() -> dict[str, object]:
    return {
        "status": "PASS",
        "actual_postgresql": True,
        "actual_service_api": True,
        "checks": {
            "ag_audit_survived_store_restart": True,
            "service_api_only_boundary": True,
            "private_payload_absent": True,
        },
        "summary": {
            "service_count": 5,
            "migration_count": 101,
            "stage_count": 8,
            "stage_family_count": 8,
        },
        "cleanup_residue": {"oa": 0, "ae": 0, "cx": 0, "mo": 0, "ag": 0},
    }


def test_builds_two_protected_metadata_only_release_gates() -> None:
    result = build_release_candidate_browser_ag_evidence(
        passing_browser(),
        passing_ag(),
        observed_at=datetime(2026, 10, 6, 3, 4, 5, tzinfo=UTC),
    )

    assert result["schema_version"] == RELEASE_CANDIDATE_OPERATIONS_SCHEMA_VERSION
    assert result["status"] == "PASS"
    assert result["failure_code"] is None
    gates = {item["gate_id"]: item for item in result["gate_evidence"]}
    browser = gates["korean_browser_journey"]
    assert browser["metrics"]["viewport_count"] == 2
    assert browser["metrics"]["passed_viewport_count"] == 2
    assert browser["actual_execution"] is True
    ag = gates["ag_trace_operations"]
    assert ag["metrics"]["trace_stage_count"] == 8
    assert ag["metrics"]["audit_export_count"] == 1
    assert ag["observed_at"] == "2026-10-06T03:04:05Z"
    assert all(item["private_payload_included"] is False for item in gates.values())
    assert all(len(item["evidence_digest"]) == 64 for item in gates.values())


@pytest.mark.parametrize(
    ("source", "mutation", "gate", "check"),
    (
        ("browser", lambda value: value.update(status="FAIL"), "korean_browser_journey", "source_passed"),
        ("browser", lambda value: value.update(actual_browser=False), "korean_browser_journey", "actual_browser_postgres_and_processes"),
        ("browser", lambda value: value.update(checks={}), "korean_browser_journey", "all_browser_checks_passed"),
        ("browser", lambda value: value["summary"].update(viewport_count=1), "korean_browser_journey", "two_viewports_completed"),
        ("browser", lambda value: value["summary"].update(journey_stage_count=8), "korean_browser_journey", "nine_journey_stages_completed"),
        ("browser", lambda value: value.update(provider_mode="live"), "korean_browser_journey", "deterministic_provider_isolation"),
        ("browser", lambda value: value["residue"].update(files=1), "korean_browser_journey", "browser_residue_free"),
        ("ag", lambda value: value.update(status="FAIL"), "ag_trace_operations", "source_passed"),
        ("ag", lambda value: value.update(actual_service_api=False), "ag_trace_operations", "actual_five_database_service_api_journey"),
        ("ag", lambda value: value.update(checks={}), "ag_trace_operations", "all_ag_checks_passed"),
        ("ag", lambda value: value["summary"].update(service_count=4), "ag_trace_operations", "five_services_observed"),
        ("ag", lambda value: value["summary"].update(stage_family_count=7), "ag_trace_operations", "eight_trace_families_observed"),
        ("ag", lambda value: value["checks"].update(ag_audit_survived_store_restart=False), "ag_trace_operations", "audit_survived_restart"),
        ("ag", lambda value: value["checks"].update(service_api_only_boundary=False), "ag_trace_operations", "service_api_only_boundary"),
        ("ag", lambda value: value["cleanup_residue"].update(ag=1), "ag_trace_operations", "ag_residue_free"),
    ),
)
def test_gates_fail_closed_for_incomplete_source_evidence(
    source: str,
    mutation,
    gate: str,
    check: str,
) -> None:
    sources = {"browser": passing_browser(), "ag": passing_ag()}
    mutation(sources[source])

    result = build_release_candidate_browser_ag_evidence(
        sources["browser"], sources["ag"]
    )
    gates = {item["gate_id"]: item for item in result["gate_evidence"]}

    assert result["status"] == "FAIL"
    assert result["failure_code"] == "release_candidate_browser_ag_operations_failed"
    assert gates[gate]["checks"][check] is False


def test_invalid_shapes_and_naive_time_are_bounded() -> None:
    result = build_release_candidate_browser_ag_evidence(
        {"actual_postgres": True, "checks": [], "residue": []},
        {"actual_postgresql": True, "checks": [], "cleanup_residue": []},
        observed_at=datetime(2026, 10, 6, 3, 4, 5),
    )
    assert result["status"] == "FAIL"
    gates = result["gate_evidence"]
    assert all(item["observed_at"].endswith("Z") for item in gates)
    assert all(item["metrics"]["residue_count"] == 0 for item in gates)


def test_runner_is_opt_in_and_enables_both_protected_sources() -> None:
    skipped = runner.run_platform_release_candidate_browser_ag_operations({})
    assert skipped["status"] == "SKIPPED"
    assert skipped["actual_browser_execution"] is False
    assert runner.summary_line(skipped).endswith("next=1398")

    captured: list[dict[str, str]] = []

    def browser_source(env):
        captured.append(dict(env))
        return passing_browser()

    result = runner.run_platform_release_candidate_browser_ag_operations(
        {runner.ENABLE_ENV: "1"},
        browser_runner=browser_source,
        ag_runner=lambda env: passing_ag(),
    )

    assert captured[0][runner.browser.SMOKE_ENV] == "1"
    assert captured[0][runner.ag.SMOKE_ENV] == "1"
    assert result["status"] == "PASS"
    assert result["source_projection"] == {
        "browser_status": "PASS",
        "ag_status": "PASS",
    }
    assert result["next_slice"] == "1399"
    assert runner.summary_line(result) == (
        "platform_release_candidate_browser_ag=pass viewports=2/2 "
        "trace_families=8 audit=1 residue=0 next=1399"
    )


def test_runner_bounds_exception_and_main_exit(monkeypatch, capsys) -> None:
    result = runner.run_platform_release_candidate_browser_ag_operations(
        {runner.ENABLE_ENV: "1"},
        browser_runner=lambda env: passing_browser(),
        ag_runner=lambda env: (_ for _ in ()).throw(
            RuntimeError("browser-secret-value")
        ),
    )
    assert result["status"] == "FAIL"
    assert result["failure_code"] == (
        "release_candidate_browser_ag_operations_execution_failed"
    )
    assert "browser-secret-value" not in json.dumps(result)
    assert result["source_projection"]["browser_status"] == "PASS"
    assert result["source_projection"]["ag_status"] == "NOT_RUN"

    monkeypatch.setattr(
        runner,
        "run_platform_release_candidate_browser_ag_operations",
        lambda: {"status": "SKIPPED"},
    )
    assert runner.main(["--summary"]) == 0
    assert "=skip" in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_platform_release_candidate_browser_ag_operations",
        lambda: {"status": "FAIL", "gate_evidence": []},
    )
    assert runner.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
