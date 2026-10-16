from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/smoke"))

import run_p6_ca02_s6_recovery_smoke as smoke
from sqlalchemy import text
from test_nex_ae_multi_step_engine import (
    EXECUTION_ID,
    STEP_1_ID,
    TENANT,
    _factory,
)


def test_smoke_is_protected_and_rejects_non_test_database() -> None:
    skipped = smoke.run_p6_ca02_s6_recovery_smoke({})
    missing = smoke.run_p6_ca02_s6_recovery_smoke({smoke.SMOKE_ENV: "1"})
    rejected = smoke.run_p6_ca02_s6_recovery_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: "postgresql+psycopg://wrong@localhost/other",
        }
    )

    assert skipped["status"] == "SKIPPED"
    assert missing["failure_code"] == "database_url_missing"
    assert rejected["failure_code"] == "target_not_allowed"


def test_smoke_combines_postgres_recovery_and_process_containment(
    monkeypatch,
) -> None:
    migration = SimpleNamespace(
        planned=("2204_ae_nsl_backend_run", smoke.REQUIRED_MIGRATION),
        applied=(),
        skipped=("2204_ae_nsl_backend_run", smoke.REQUIRED_MIGRATION),
    )
    monkeypatch.setattr(
        smoke, "run_service_migrations", lambda *args, **kwargs: migration
    )
    monkeypatch.setattr(
        smoke.p5_s5,
        "_execute_postgres_smoke",
        lambda *_args, **_kwargs: {
            "status": "PASS",
            "checks": {
                "expired_attempt_reclaimed": True,
                "stale_attempt_fenced": True,
                "stale_result_absent": True,
                "no_synthetic_backend_evidence": True,
                "recovered_attempt_terminalized": True,
                "recovery_zero_residue": True,
            },
            "cleanup_counts": {"remaining": 0},
        },
    )

    class _Runtime:
        def __init__(self, target, **_kwargs) -> None:
            self._target = target

        def execute(self, _payload: bytes) -> SimpleNamespace:
            status = (
                "TIMED_OUT" if self._target is smoke.p6_s5._sleep_target else "CRASHED"
            )
            return SimpleNamespace(status=status)

    monkeypatch.setattr(smoke, "ProcessIsolatedRuntime", _Runtime)
    database_url = "postgresql+psycopg://nex_ae_user:secret@localhost/nex_ae_test"

    evidence = smoke.run_p6_ca02_s6_recovery_smoke(
        {smoke.SMOKE_ENV: "1", smoke.DATABASE_ENV: database_url}
    )

    assert evidence["status"] == "PASS"
    assert evidence["actual_postgres"] is True
    assert evidence["isolation_evidence"] == {
        "timeout_status": "TIMED_OUT",
        "crash_status": "CRASHED",
    }
    assert all(evidence["checks"].values())

    monkeypatch.setattr(
        smoke.p5_s5,
        "_execute_postgres_smoke",
        lambda *_args, **_kwargs: {
            "status": "FAIL",
            "checks": {"forced_failure": False},
            "cleanup_counts": {"remaining": 0},
        },
    )
    failed = smoke.run_p6_ca02_s6_recovery_smoke(
        {smoke.SMOKE_ENV: "1", smoke.DATABASE_ENV: database_url}
    )
    assert failed["failure_code"] == "p6_ca02_s6_recovery_smoke_failed"


def test_smoke_fails_closed_and_redacts_execution_error(monkeypatch) -> None:
    database_url = "postgresql+psycopg://nex_ae_user:secret@localhost/nex_ae_test"
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError(database_url)),
    )

    evidence = smoke.run_p6_ca02_s6_recovery_smoke(
        {smoke.SMOKE_ENV: "1", smoke.DATABASE_ENV: database_url}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "execution_failed"
    assert "secret" not in evidence["failure_detail"]


def test_recovery_verifier_reclaims_fences_completes_and_cleans() -> None:
    factory = _factory()
    with factory.begin() as session:
        session.execute(
            text(
                "CREATE TABLE ae_nsl_backend_run ("
                "tenant_id TEXT NOT NULL, marker TEXT)"
            )
        )
    evidence = smoke._verify_lease_recovery(
        {
            "factory": factory,
            "tenant_id": TENANT,
            "execution": {"agent_execution_id": EXECUTION_ID},
            "executable_plan": {
                "steps": [
                    {
                        "executable_step_id": STEP_1_ID,
                        "output_contract_ref": "contract://nex/ae/chat-result/v1",
                    }
                ]
            },
            "now": "2026-10-14T09:00:00Z",
        }
    )

    assert all(evidence["checks"].values())
    assert evidence["row_counts"] == {
        "runtime_job_attempts": 2,
        "stale_step_results": 0,
        "synthetic_backend_runs": 0,
    }
    assert evidence["cleanup_counts"]["remaining"] == 0


def test_recovery_defensive_claim_failures_are_explicit(monkeypatch) -> None:
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyMultiStepEngine",
        lambda *_args: SimpleNamespace(schedule_next=lambda **_kwargs: None),
    )
    with pytest.raises(RuntimeError, match="did not schedule"):
        smoke._verify_lease_recovery(
            {
                "factory": object(),
                "tenant_id": TENANT,
                "execution": {"agent_execution_id": EXECUTION_ID},
                "executable_plan": {
                    "steps": [
                        {
                            "executable_step_id": STEP_1_ID,
                            "output_contract_ref": "contract://result",
                        }
                    ]
                },
                "now": "2026-10-14T09:00:00Z",
            }
        )

    first_missing = SimpleNamespace(claim=lambda **_kwargs: None)
    with pytest.raises(RuntimeError, match="first attempt"):
        smoke._exercise_lease_recovery(
            factory=object(),
            tenant_id=TENANT,
            base_time="2026-10-14T09:00:00Z",
            first_step={},
            job={},
            queue=first_missing,
            engine=object(),
        )

    claims = iter((SimpleNamespace(), None))
    second_missing = SimpleNamespace(claim=lambda **_kwargs: next(claims))
    begin_engine = SimpleNamespace(begin_claim=lambda **_kwargs: None)
    with pytest.raises(RuntimeError, match="reclaim"):
        smoke._exercise_lease_recovery(
            factory=object(),
            tenant_id=TENANT,
            base_time="2026-10-14T09:00:00Z",
            first_step={},
            job={},
            queue=second_missing,
            engine=begin_engine,
        )


def test_main_returns_failure_only_for_failed_evidence(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        smoke,
        "run_p6_ca02_s6_recovery_smoke",
        lambda _env: {"status": "PASS"},
    )
    assert smoke.main(["--summary"]) == 0
    assert "p6_ca02_s6_recovery=pass" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_p6_ca02_s6_recovery_smoke",
        lambda _env: {"status": "FAIL"},
    )
    assert smoke.main([]) == 1

    monkeypatch.setattr(smoke, "load_env_file", lambda _path: None)
    assert smoke.main(["--env-file", "ignored.env"]) == 1
