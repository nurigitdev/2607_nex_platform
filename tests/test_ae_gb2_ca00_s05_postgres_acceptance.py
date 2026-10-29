from __future__ import annotations

from types import SimpleNamespace

import pytest
import run_gb2_ca00_s05_ae_agent_runtime_worker as smoke


def test_smoke_is_protected_and_opt_in() -> None:
    result = smoke.run_gb2_ca00_s05_ae_agent_runtime_worker({})

    assert result["status"] == "SKIPPED"
    assert result["actual_postgres"] is False


def test_smoke_rejects_missing_and_wrong_database_targets() -> None:
    missing = smoke.run_gb2_ca00_s05_ae_agent_runtime_worker({smoke.SMOKE_ENV: "1"})
    wrong = smoke.run_gb2_ca00_s05_ae_agent_runtime_worker(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: "postgresql://other:secret@localhost/other",
        }
    )

    assert missing["failure_code"] == "database_url_missing"
    assert wrong["failure_code"] == "target_not_allowed"
    assert "postgresql://other:secret" not in str(wrong)


def test_smoke_projects_migration_and_component_evidence(monkeypatch) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *_args, **_kwargs: type(
            "Migration",
            (),
            {
                "planned": ("a", "b"),
                "applied": ("b",),
                "skipped": ("a",),
            },
        )(),
    )
    monkeypatch.setattr(
        smoke,
        "_execute_protected_component",
        lambda _url: {
            "status": "PASS",
            "actual_postgres": True,
            "database": "nex_ae_test",
            "role": "nex_ae_user",
            "checks": {"worker": True},
            "row_counts": {"runtime_job": 2, "runtime_job_attempt": 2},
            "cleanup_counts": {"component_remaining": 0},
        },
    )

    result = smoke.run_gb2_ca00_s05_ae_agent_runtime_worker(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: (
                "postgresql://nex_ae_user:nuri1004@127.0.0.1/nex_ae_test"
            ),
        }
    )

    assert result["status"] == "PASS"
    assert result["evidence_classification"] == "PROTECTED_COMPONENT"
    assert result["checks"] == {"migration_current": True, "worker": True}
    assert result["migration"]["planned_count"] == 2
    assert "nuri1004" not in str(result)
    assert smoke.summary_line(result) == (
        "gb2_ca00_s05_ae_worker=pass classification=PROTECTED_COMPONENT "
        "checks=2/2 jobs=2 attempts=2 remaining=0"
    )


def test_smoke_fails_closed_and_redacts_password(monkeypatch) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("postgresql://nex_ae_user:secret@127.0.0.1/nex_ae_test")
        ),
    )
    result = smoke.run_gb2_ca00_s05_ae_agent_runtime_worker(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: (
                "postgresql://nex_ae_user:secret@127.0.0.1/nex_ae_test"
            ),
        }
    )

    assert result["status"] == "FAIL"
    assert result["failure_code"] == "execution_failed"
    assert "nex_ae_user:secret" not in str(result)
    assert "***" in result["detail"]


def test_target_and_summary_fail_paths() -> None:
    assert smoke._target_url_allowed(
        "postgresql+psycopg://nex_ae_user:x@localhost/nex_ae_test"
    )
    assert not smoke._target_url_allowed("sqlite:///nex_ae_test")
    assert smoke.summary_line({"status": "FAIL"}) == (
        "gb2_ca00_s05_ae_worker=fail classification=none "
        "checks=0/0 jobs=0 attempts=0 remaining=0"
    )


def _component_values() -> dict:
    return {
        "readiness": {
            "database": {
                "database_name": smoke.EXPECTED_DATABASE,
                "database_user": smoke.EXPECTED_ROLE,
            },
            "readiness_status": "READY",
            "checks": {"database": True, "worker": True},
        },
        "restart_readiness": {"readiness_status": "READY"},
        "dependency": SimpleNamespace(disposition="TERMINAL"),
        "executable_plan": {
            "steps": [
                {"executor_kind": "P4_CHAT_RAG_COMPATIBILITY"},
                {"executor_kind": "DETERMINISTIC_REPORT"},
            ]
        },
        "pending_job": {"state": "QUEUED", "attempt_no": 0},
        "pending_result_count": 0,
        "first_run": {"execution_count": 1, "succeeded_count": 1, "failed_count": 0},
        "restart_run": {"execution_count": 0},
        "jobs": (
            {"runtime_job_id": "job-1", "state": "DONE"},
            {"runtime_job_id": "job-2", "state": "DONE"},
        ),
        "attempts": (
            {"runtime_job_id": "job-1", "outcome": "DONE"},
            {"runtime_job_id": "job-2", "outcome": "DONE"},
        ),
        "heartbeat": {
            "status": "STOPPED",
            "metadata": {"process_id": smoke.PROCESS_ID},
        },
        "worker_id": "worker-1",
        "cleanup_counts": {"component_remaining": 0},
        "processes_closed": True,
    }


def test_component_evidence_accepts_db_less_canonical_orchestration() -> None:
    evidence = smoke._component_evidence(**_component_values())

    assert all(evidence["checks"].values())
    assert evidence["row_counts"] == {
        "runtime_job": 2,
        "runtime_job_attempt": 2,
        "heartbeat": 1,
    }
    assert evidence["process"]["restart_execution_count"] == 0


@pytest.mark.parametrize(
    ("mutation", "failed_check"),
    (
        (
            lambda value: value["readiness"]["database"].update(database_user="other"),
            "actual_database_identity",
        ),
        (
            lambda value: value["readiness"]["checks"].update(worker=False),
            "readiness_truthful",
        ),
        (
            lambda value: setattr(value["dependency"], "disposition", "RETRY"),
            "normal_admitted_setup",
        ),
        (
            lambda value: value.update(pending_job=None),
            "worker_unavailable_preserved_pending_job",
        ),
        (
            lambda value: value["first_run"].update(failed_count=1),
            "canonical_worker_claimed_assignment",
        ),
        (
            lambda value: value.update(
                jobs=({"runtime_job_id": "job-1", "state": "DONE"},)
            ),
            "runtime_jobs_settled",
        ),
        (
            lambda value: value["attempts"][1].update(runtime_job_id="job-1"),
            "attempts_exactly_once",
        ),
        (lambda value: value.update(heartbeat=None), "heartbeat_persisted"),
        (
            lambda value: value["restart_run"].update(execution_count=1),
            "restart_did_not_double_execute",
        ),
        (
            lambda value: value.update(processes_closed=False),
            "canonical_command_has_no_demo_dependency",
        ),
    ),
)
def test_component_evidence_rejects_runtime_drift(mutation, failed_check: str) -> None:
    values = _component_values()
    mutation(values)

    evidence = smoke._component_evidence(**values)

    assert evidence["checks"][failed_check] is False
