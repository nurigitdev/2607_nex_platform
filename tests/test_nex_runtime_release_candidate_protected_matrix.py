from __future__ import annotations

from datetime import UTC, datetime
import json

import pytest

import run_platform_release_candidate_protected_matrix as runner
import nex_runtime.release_candidate_protected_matrix as matrix
from nex_runtime.release_candidate import RELEASE_CANDIDATE_EVIDENCE_SCHEMA_VERSION
from nex_runtime.release_candidate_protected_matrix import (
    RELEASE_CANDIDATE_PROTECTED_MATRIX_SCHEMA_VERSION,
    build_release_candidate_protected_matrix,
)


NOW = datetime(2026, 10, 6, 5, 6, 7, tzinfo=UTC)


def gate(
    gate_id: str,
    metrics: dict[str, object],
    *,
    protected: bool = False,
) -> dict[str, object]:
    return {
        "evidence_schema_version": RELEASE_CANDIDATE_EVIDENCE_SCHEMA_VERSION,
        "gate_id": gate_id,
        "status": "PASS",
        "execution_mode": "protected" if protected else "deterministic",
        "actual_execution": protected,
        "private_payload_included": False,
        "observed_at": "2026-10-06T05:06:07Z",
        "evidence_digest": "a" * 64,
        "metrics": metrics,
    }


def sources() -> dict[str, dict[str, object]]:
    return {
        "admission": {"status": "PASS", "admitted": True},
        "golden": {
            "status": "PASS",
            "summary": {
                "required_scenario_count": 10,
                "passed_scenario_count": 10,
                "privacy_violation_count": 0,
            },
        },
        "postgres": {
            "status": "PASS",
            "gate_evidence": gate(
                "five_database_restart",
                {"database_count": 5, "restored_database_count": 5},
                protected=True,
            ),
        },
        "providers": {
            "status": "PASS",
            "gate_evidence": gate(
                "live_provider_matrix",
                {"provider_capability_count": 3, "failed_provider_count": 0},
                protected=True,
            ),
        },
        "operations": {
            "status": "PASS",
            "gate_evidence": [
                gate(
                    "korean_browser_journey",
                    {"viewport_count": 2, "passed_viewport_count": 2},
                    protected=True,
                ),
                gate(
                    "ag_trace_operations",
                    {"trace_stage_count": 8, "audit_export_count": 1},
                    protected=True,
                ),
            ],
        },
        "assurance": {
            "status": "PASS",
            "gate_evidence": [
                gate(
                    "contract_privacy",
                    {
                        "contract_validation_passed": True,
                        "privacy_violation_count": 0,
                    },
                ),
                gate(
                    "zero_residue",
                    {
                        "database_residue_count": 0,
                        "file_residue_count": 0,
                        "running_process_count": 0,
                    },
                    protected=True,
                ),
                gate(
                    "deployment_deferrals",
                    {
                        "deferral_count": 9,
                        "production_deployment_approved": False,
                    },
                ),
            ],
        },
    }


def build(value: dict[str, dict[str, object]]) -> dict[str, object]:
    return build_release_candidate_protected_matrix(
        value["admission"],
        value["golden"],
        value["postgres"],
        value["providers"],
        value["operations"],
        value["assurance"],
        observed_at=NOW,
    )


def test_builds_complete_protected_matrix_pending_only_full_gate() -> None:
    result = build(sources())

    assert result["schema_version"] == RELEASE_CANDIDATE_PROTECTED_MATRIX_SCHEMA_VERSION
    assert result["status"] == "PASS"
    assert result["readiness"] == "READY_FOR_FULL_GATE"
    assert result["failure_code"] is None
    assert all(result["checks"].values())
    assert result["summary"] == {
        "required_gate_count": 9,
        "passed_non_regression_gate_count": 8,
        "actual_protected_gate_count": 5,
        "pending_full_gate_count": 1,
        "privacy_violation_count": 0,
    }
    assert result["evaluation"]["status"] == "FAIL"
    assert result["evaluation"]["decision"] == "BLOCKED"
    assert result["evaluation"]["gate_checks"]["full_regression"]["status"] == "SKIPPED"
    assert all(
        value["passed"]
        for gate_id, value in result["evaluation"]["gate_checks"].items()
        if gate_id != "full_regression"
    )
    assert len(result["evidence"]) == 9


@pytest.mark.parametrize(
    ("source", "mutation", "check"),
    (
        ("admission", lambda value: value.update(admitted=False), "protected_admission_passed"),
        ("golden", lambda value: value.update(status="FAIL"), "all_source_runners_passed"),
        ("postgres", lambda value: value.update(status="FAIL"), "all_source_runners_passed"),
        ("providers", lambda value: value.update(status="FAIL"), "all_source_runners_passed"),
        ("operations", lambda value: value.update(status="FAIL"), "all_source_runners_passed"),
        ("assurance", lambda value: value.update(status="FAIL"), "all_source_runners_passed"),
        ("postgres", lambda value: value.update(gate_evidence={}), "gate_inventory_exact"),
        (
            "providers",
            lambda value: value["gate_evidence"].update(actual_execution=False),
            "five_protected_gates_actual",
        ),
        (
            "providers",
            lambda value: value["gate_evidence"]["metrics"].update(
                failed_provider_count=1
            ),
            "eight_non_regression_gates_passed",
        ),
    ),
)
def test_protected_matrix_fails_closed_for_source_or_gate_drift(
    source: str,
    mutation,
    check: str,
) -> None:
    value = sources()
    mutation(value[source])

    result = build(value)

    assert result["status"] == "FAIL"
    assert result["failure_code"] == "release_candidate_protected_matrix_failed"
    assert result["checks"][check] is False


def test_golden_gate_and_sequence_helpers_bound_invalid_shapes() -> None:
    value = sources()
    value["golden"] = {
        "status": "PASS",
        "summary": {
            "required_scenario_count": True,
            "passed_scenario_count": 10,
            "privacy_violation_count": 0,
        },
    }
    value["operations"]["gate_evidence"] = "invalid"
    result = build(value)
    assert result["status"] == "FAIL"
    assert result["evidence"][0]["metrics"]["scenario_count"] == 0
    assert matrix._sequence("invalid") == ()


def test_naive_timestamp_is_normalized() -> None:
    value = sources()
    result = build_release_candidate_protected_matrix(
        value["admission"],
        value["golden"],
        value["postgres"],
        value["providers"],
        value["operations"],
        value["assurance"],
        observed_at=datetime(2026, 10, 6, 5, 6, 7),
    )
    assert result["evidence"][0]["observed_at"].endswith("Z")


def test_runner_is_opt_in_executes_in_order_and_enables_sources(
    monkeypatch,
) -> None:
    skipped = runner.run_platform_release_candidate_protected_matrix({})
    assert skipped["status"] == "SKIPPED"
    assert skipped["actual_protected_execution"] is False
    assert runner.summary_line(skipped).endswith("next=1400")

    value = sources()
    captured: dict[str, dict[str, str]] = {}

    def admitted(env):
        captured["admission"] = dict(env)
        return value["admission"]

    def operations_source(env):
        captured["operations"] = dict(env)
        captured["operations_process_env"] = {
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": runner.os.environ.get(
                "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE", ""
            )
        }
        return value["operations"]

    def postgres_source(env):
        captured["postgres"] = dict(env)
        return value["postgres"]

    def assurance_source(env):
        captured["assurance"] = dict(env)
        return value["assurance"]

    monkeypatch.setenv("NEX_SERVICE_TOKEN_ROLLOUT_PROFILE", "SIGNED_ONLY")
    result = runner.run_platform_release_candidate_protected_matrix(
        {
            runner.ENABLE_ENV: "1",
            "NEX_MO_PROVIDER_MODE": "live",
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "SIGNED_ONLY",
        },
        admission_runner=admitted,
        golden_runner=lambda: value["golden"],
        postgres_runner=postgres_source,
        provider_runner=lambda env: value["providers"],
        operations_runner=operations_source,
        assurance_runner=assurance_source,
        observed_at=NOW,
    )

    assert captured["admission"][runner.postgres.ENABLE_ENV] == "1"
    assert captured["admission"][runner.providers.ENABLE_ENV] == "1"
    assert captured["admission"][runner.operations.ENABLE_ENV] == "1"
    assert captured["admission"][runner.assurance.ENABLE_ENV] == "1"
    assert captured["postgres"]["NEX_MO_PROVIDER_MODE"] == "mock"
    assert captured["operations"]["NEX_MO_PROVIDER_MODE"] == "live"
    assert (
        captured["operations"]["NEX_SERVICE_TOKEN_ROLLOUT_PROFILE"]
        == "TEST_MOCK"
    )
    assert (
        captured["assurance"]["NEX_SERVICE_TOKEN_ROLLOUT_PROFILE"]
        == "TEST_MOCK"
    )
    assert captured["operations_process_env"] == {
        "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK"
    }
    assert runner.os.environ["NEX_SERVICE_TOKEN_ROLLOUT_PROFILE"] == "SIGNED_ONLY"
    assert result["status"] == "PASS"
    assert result["actual_protected_execution"] is True
    assert result["next_slice"] == "1401"
    assert runner.summary_line(result) == (
        "platform_release_candidate_protected_matrix=pass gates=8/8 "
        "protected=5/5 pending_full=1 privacy=0 next=1401"
    )


def test_runner_admission_exception_and_main_branches(
    monkeypatch, capsys, tmp_path
) -> None:
    monkeypatch.delenv("NEX_S140_TEMP_PROFILE", raising=False)
    with runner._patched_environ({"NEX_S140_TEMP_PROFILE": "temporary"}):
        assert runner.os.environ["NEX_S140_TEMP_PROFILE"] == "temporary"
    assert "NEX_S140_TEMP_PROFILE" not in runner.os.environ

    blocked = runner.run_platform_release_candidate_protected_matrix(
        {runner.ENABLE_ENV: "1"},
        admission_runner=lambda env: {"status": "FAIL", "issues": ["profile"]},
    )
    assert blocked["failure_code"] == "release_candidate_protected_admission_failed"
    assert blocked["source_projection"]["issue_count"] == 1

    failed = runner.run_platform_release_candidate_protected_matrix(
        {runner.ENABLE_ENV: "1"},
        admission_runner=lambda env: (_ for _ in ()).throw(
            RuntimeError("matrix-secret-value")
        ),
    )
    assert failed["failure_code"] == "release_candidate_protected_matrix_execution_failed"
    assert "matrix-secret-value" not in json.dumps(failed)

    monkeypatch.setattr(
        runner,
        "run_platform_release_candidate_protected_matrix",
        lambda: {"status": "SKIPPED"},
    )
    output = tmp_path / "nested" / "protected.json"
    assert runner.main(["--summary", "--output", str(output)]) == 0
    assert "=skip" in capsys.readouterr().out
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "SKIPPED"
    assert not output.with_name(f".{output.name}.tmp").exists()
    monkeypatch.setattr(
        runner,
        "run_platform_release_candidate_protected_matrix",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
