from __future__ import annotations

import json

import pytest

import run_s130_oa_mvp_platform_trust_acceptance as runner


def _postgres_artifact(**summary: int) -> dict[str, object]:
    return {
        "status": "PASS",
        "workflow": {"database": "nex_oa_test", "role": "nex_oa_user"},
        "summary": {
            "migration_count": 17,
            "cleanup_residue_count": 0,
            **summary,
        },
    }


def _artifacts() -> dict[str, dict[str, object]]:
    return {
        "policy_traceability": {"status": "PASS"},
        "failure_audit": {
            "status": "PASS",
            "summary": {"raw_material_exposure_count": 0},
        },
        "identity_restart": _postgres_artifact(restart_read_count=4),
        "key_rotation": _postgres_artifact(jwks_key_count=2),
        "revocation_restart": _postgres_artifact(runtime_restart_count=2),
        "cross_service": _postgres_artifact(
            passed_consumer_count=4,
            revoked_denial_count=4,
        ),
        "contracts_privacy": {
            "status": "PASS",
            "summary": {"privacy_violation_count": 0},
        },
    }


def test_evaluator_accepts_all_pre_full_gate_evidence() -> None:
    result = runner._evaluate_evidence_pack(_artifacts())

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["gate_evaluation"]["status"] == "BLOCKED"
    assert result["gate_evaluation"]["failed_gates"] == ["full_gate"]
    assert result["summary"] == {
        "artifact_count": 7,
        "passed_artifact_count": 7,
        "actual_postgres_smoke_count": 4,
        "passed_gate_count": 7,
        "gate_count": 8,
        "cleanup_residue_count": 0,
    }


def test_evaluator_fails_closed_for_missing_artifact() -> None:
    artifacts = _artifacts()
    artifacts.pop("cross_service")

    result = runner._evaluate_evidence_pack(artifacts)

    assert result["status"] == "FAIL"
    assert result["failed_checks"]
    assert result["next_slice"] == "blocked"


def test_safe_evidence_redacts_exception_detail() -> None:
    result = runner._safe_evidence(
        "sample",
        lambda: (_ for _ in ()).throw(RuntimeError("secret")),
    )

    assert result == {
        "status": "ERROR",
        "failure_code": "sample_execution_failed",
        "detail": "RuntimeError",
    }


def test_protected_runner_skip_and_target_guards() -> None:
    skipped = runner.run_s130_oa_mvp_platform_trust_acceptance({})
    assert skipped["status"] == "SKIPPED"

    missing = runner.run_s130_oa_mvp_platform_trust_acceptance(
        {runner.SMOKE_ENV: "1"}
    )
    assert missing["failure_code"] == "database_url_missing"

    rejected = runner.run_s130_oa_mvp_platform_trust_acceptance(
        {
            runner.SMOKE_ENV: "1",
            runner.DATABASE_ENV: "postgresql://wrong@host/wrong",
        }
    )
    assert rejected["failure_code"] == "target_not_allowed"
    assert runner._target_url_allowed(
        "postgresql://nex_oa_user@host/nex_oa_test"
    )
    assert not runner._target_url_allowed("postgresql://[invalid")


def test_runner_executes_evidence_pack(monkeypatch) -> None:
    monkeypatch.setattr(runner, "_execute_evidence_pack", lambda env: _artifacts())

    result = runner.run_s130_oa_mvp_platform_trust_acceptance(
        {
            runner.SMOKE_ENV: "1",
            runner.DATABASE_ENV: (
                "postgresql://nex_oa_user@host/nex_oa_test"
            ),
        }
    )

    assert result["status"] == "PASS"
    assert result["next_slice"] == "1301"


def test_summary_and_main(monkeypatch, capsys) -> None:
    passing = runner._evaluate_evidence_pack(_artifacts())
    assert runner.summary_line(passing) == (
        "s130_oa_mvp_acceptance=pass artifacts=7/7 postgres=4 "
        "gates=7/8 residue=0 next=1301"
    )
    assert "skip" in runner.summary_line({"status": "SKIPPED"})
    assert "code=failed" in runner.summary_line(
        {"status": "FAIL", "failure_code": "failed"}
    )

    monkeypatch.setattr(
        runner,
        "run_s130_oa_mvp_platform_trust_acceptance",
        lambda: passing,
    )
    assert runner.main(["--summary"]) == 0
    assert "next=1301" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"
    monkeypatch.setattr(
        runner,
        "run_s130_oa_mvp_platform_trust_acceptance",
        lambda: {"status": "FAIL"},
    )
    assert runner.main([]) == 1


@pytest.mark.skipif(
    runner.os.getenv(runner.SMOKE_ENV) != "1",
    reason=f"{runner.SMOKE_ENV}=1 is required",
)
def test_actual_postgres_integrated_acceptance() -> None:
    result = runner.run_s130_oa_mvp_platform_trust_acceptance()

    assert result["status"] == "PASS", result
    assert result["summary"]["passed_artifact_count"] == 7
    assert result["summary"]["actual_postgres_smoke_count"] == 4
    assert result["summary"]["passed_gate_count"] == 7
    assert result["summary"]["cleanup_residue_count"] == 0
