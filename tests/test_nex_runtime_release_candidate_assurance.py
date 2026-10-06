from __future__ import annotations

from datetime import UTC, datetime
import json
from types import SimpleNamespace

import pytest

import run_platform_release_candidate_assurance as runner
from nex_runtime.release_candidate_assurance import (
    DEPLOYMENT_DEFERRALS,
    RELEASE_CANDIDATE_ASSURANCE_SCHEMA_VERSION,
    build_release_candidate_assurance_evidence,
)


def passing_contract() -> dict[str, object]:
    return {
        "ok": True,
        "schema_count": 166,
        "example_count": 228,
        "negative_example_count": 196,
        "openapi_count": 7,
        "failures": [],
    }


def passing_golden() -> dict[str, object]:
    return {
        "status": "PASS",
        "privacy_violations": [],
        "scenario_checks": {
            scenario_id: {"passed": True}
            for scenario_id in (
                "GEN-E2E-006",
                "GEN-E2E-007",
                "GEN-E2E-008",
                "GEN-E2E-010",
            )
        },
    }


def passing_residue() -> dict[str, object]:
    return {
        "actual_execution": True,
        "database_count": 5,
        "database_residue_count": 0,
        "file_cleanup_probe": True,
        "file_residue_count": 0,
        "stopped_process_count": 13,
        "running_process_count": 0,
        "deployment_deferrals": list(DEPLOYMENT_DEFERRALS),
        "production_deployment_approved": False,
        "release_scope": "MVP_RELEASE_CANDIDATE",
    }


def test_builds_contract_residue_and_deferral_release_gates() -> None:
    result = build_release_candidate_assurance_evidence(
        passing_contract(),
        passing_golden(),
        passing_residue(),
        observed_at=datetime(2026, 10, 6, 4, 5, 6, tzinfo=UTC),
    )

    assert result["schema_version"] == RELEASE_CANDIDATE_ASSURANCE_SCHEMA_VERSION
    assert result["status"] == "PASS"
    assert result["failure_code"] is None
    assert result["checks"] == {
        "contract_privacy": True,
        "failure_recovery": True,
        "zero_residue": True,
        "deployment_deferrals": True,
    }
    gates = {item["gate_id"]: item for item in result["gate_evidence"]}
    assert gates["contract_privacy"]["metrics"]["contract_validation_passed"] is True
    assert gates["contract_privacy"]["metrics"]["privacy_violation_count"] == 0
    assert gates["zero_residue"]["actual_execution"] is True
    assert gates["zero_residue"]["metrics"]["running_process_count"] == 0
    assert gates["deployment_deferrals"]["metrics"] == {
        "deferral_count": 9,
        "production_deployment_approved": False,
    }
    assert all(item["observed_at"] == "2026-10-06T04:05:06Z" for item in gates.values())
    assert all(len(item["evidence_digest"]) == 64 for item in gates.values())


@pytest.mark.parametrize(
    ("source", "mutation", "gate", "check"),
    (
        ("contract", lambda value: value.update(ok=False), "contract_privacy", "contract_validation_passed"),
        ("contract", lambda value: value.update(schema_count=0), "contract_privacy", "schema_inventory_present"),
        ("contract", lambda value: value.update(example_count=0), "contract_privacy", "positive_examples_present"),
        ("contract", lambda value: value.update(negative_example_count=0), "contract_privacy", "negative_examples_present"),
        ("contract", lambda value: value.update(openapi_count=0), "contract_privacy", "openapi_inventory_present"),
        ("contract", lambda value: value.update(failures=["invalid"]), "contract_privacy", "contract_failures_absent"),
        ("golden", lambda value: value.update(status="FAIL"), "contract_privacy", "golden_scenarios_passed"),
        ("golden", lambda value: value["scenario_checks"].pop("GEN-E2E-006"), "contract_privacy", "failure_recovery_scenarios_passed"),
        ("golden", lambda value: value["scenario_checks"]["GEN-E2E-010"].update(passed=False), "contract_privacy", "privacy_export_scenario_passed"),
        ("golden", lambda value: value.update(privacy_violations=["prompt"]), "contract_privacy", "privacy_violations_absent"),
        ("residue", lambda value: value.update(actual_execution=False), "zero_residue", "protected_execution_observed"),
        ("residue", lambda value: value.update(database_count=4), "zero_residue", "five_database_cleanup_observed"),
        ("residue", lambda value: value.update(database_residue_count=1), "zero_residue", "database_residue_absent"),
        ("residue", lambda value: value.update(file_cleanup_probe=False), "zero_residue", "file_cleanup_probe_absent"),
        ("residue", lambda value: value.update(running_process_count=1), "zero_residue", "thirteen_processes_stopped"),
        ("residue", lambda value: value.update(deployment_deferrals=[]), "deployment_deferrals", "inventory_exact"),
        ("residue", lambda value: value.update(production_deployment_approved=True), "deployment_deferrals", "production_deployment_not_approved"),
        ("residue", lambda value: value.update(release_scope="PRODUCTION"), "deployment_deferrals", "release_candidate_scope_only"),
    ),
)
def test_assurance_fails_closed_for_incomplete_source_evidence(
    source: str,
    mutation,
    gate: str,
    check: str,
) -> None:
    sources = {
        "contract": passing_contract(),
        "golden": passing_golden(),
        "residue": passing_residue(),
    }
    mutation(sources[source])

    result = build_release_candidate_assurance_evidence(
        sources["contract"], sources["golden"], sources["residue"]
    )
    gates = {item["gate_id"]: item for item in result["gate_evidence"]}

    assert result["status"] == "FAIL"
    assert result["failure_code"] == "release_candidate_assurance_failed"
    assert gates[gate]["checks"][check] is False


def test_invalid_shapes_counts_and_naive_timestamp_are_bounded() -> None:
    result = build_release_candidate_assurance_evidence(
        {"ok": True, "schema_count": True, "failures": "invalid"},
        {"scenario_checks": [], "privacy_violations": "invalid"},
        {
            "database_residue_count": True,
            "deployment_deferrals": "invalid",
        },
        observed_at=datetime(2026, 10, 6, 4, 5, 6),
    )
    assert result["status"] == "FAIL"
    gates = result["gate_evidence"]
    assert all(item["observed_at"].endswith("Z") for item in gates)
    assert gates[0]["metrics"]["schema_count"] == 0


def test_runner_is_opt_in_and_composes_actual_sources() -> None:
    skipped = runner.run_platform_release_candidate_assurance({})
    assert skipped["status"] == "SKIPPED"
    assert skipped["actual_protected_execution"] is False
    assert runner.summary_line(skipped).endswith("next=1399")

    contract = SimpleNamespace(**passing_contract())
    captured: dict[str, str] = {}

    def database_source(env):
        captured.update(env)
        return {
            "status": "PASS",
            "actual_postgresql": True,
            "summary": {"service_count": 5, "cleanup_residue_count": 0},
        }

    result = runner.run_platform_release_candidate_assurance(
        {runner.ENABLE_ENV: "1"},
        contract_runner=lambda root: contract,
        golden_runner=passing_golden,
        database_runner=database_source,
        process_runner=lambda: {
            "status": "PASS",
            "stopped_process_counts": {"STOPPED": 13},
        },
        file_runner=lambda: {
            "status": "PASS",
            "cleanup_confirmed": True,
            "residue_count": 0,
        },
    )

    assert captured[runner.AG_SMOKE_ENV] == "1"
    assert result["status"] == "PASS"
    assert result["actual_protected_execution"] is True
    assert result["next_slice"] == "1400"
    assert runner.summary_line(result) == (
        "platform_release_candidate_assurance=pass contracts=166 recovery=3 "
        "residue=0 deferrals=9 next=1400"
    )


def test_projection_file_probe_exception_and_main_branches(monkeypatch, capsys) -> None:
    projection = runner._contract_projection(passing_contract())
    assert projection["ok"] is True
    assert runner._run_file_cleanup_probe() == {
        "status": "PASS",
        "cleanup_confirmed": True,
        "residue_count": 0,
    }
    residue = runner._residue_projection(
        {"actual_postgresql": True, "summary": {"service_count": 5}},
        {"status": "PASS", "stopped_process_counts": {"STOPPED": 12, "FAILED": 1}},
        {"status": "FAIL", "cleanup_confirmed": False},
    )
    assert residue["actual_execution"] is False
    assert residue["database_residue_count"] == -1
    assert residue["file_residue_count"] == -1
    assert residue["running_process_count"] == 1

    result = runner.run_platform_release_candidate_assurance(
        {runner.ENABLE_ENV: "1"},
        contract_runner=lambda root: (_ for _ in ()).throw(
            RuntimeError("assurance-secret-value")
        ),
    )
    assert result["status"] == "FAIL"
    assert result["failure_code"] == "release_candidate_assurance_execution_failed"
    assert "assurance-secret-value" not in json.dumps(result)

    monkeypatch.setattr(
        runner,
        "run_platform_release_candidate_assurance",
        lambda: {"status": "SKIPPED"},
    )
    assert runner.main(["--summary"]) == 0
    assert "=skip" in capsys.readouterr().out
    monkeypatch.setattr(
        runner,
        "run_platform_release_candidate_assurance",
        lambda: {"status": "FAIL", "gate_evidence": []},
    )
    assert runner.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
