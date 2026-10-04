from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import run_oa_identity_session_authorization_restart_smoke as smoke
from nex_oa.mvp_identity_restart_smoke import (
    EXPECTED_RESIDUE_KEYS,
    evaluate_oa_identity_restart_smoke,
)


def _passing_workflow() -> dict[str, object]:
    row_counts = {
        "tenant_count": 1,
        "subject_count": 1,
        "membership_count": 1,
        "credential_count": 1,
        "session_count": 1,
        "role_count": 1,
        "group_count": 1,
        "group_member_count": 1,
        "group_role_count": 1,
        "authz_event_count": 4,
        "raw_password_match_count": 0,
        "password_hash_count": 1,
        "migration_ledger_count": 17,
    }
    return {
        "database": "nex_oa_test",
        "role": "nex_oa_user",
        "runtime_mode": "postgres",
        "checks": {
            "credential_verified_after_restart": True,
            "membership_loaded_after_restart": True,
            "session_active_after_restart": True,
            "authorization_loaded_after_restart": True,
        },
        "db_observations": row_counts,
        "cleanup_residue": {name: 0 for name in EXPECTED_RESIDUE_KEYS},
    }


def test_evaluator_accepts_complete_restart_evidence() -> None:
    result = evaluate_oa_identity_restart_smoke(
        {"planned": [f"migration-{index}" for index in range(17)]},
        _passing_workflow(),
    )

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "migration_count": 17,
        "restart_read_count": 4,
        "persisted_row_class_count": 10,
        "cleanup_residue_count": 0,
    }


def test_evaluator_fails_closed_for_incomplete_evidence() -> None:
    result = evaluate_oa_identity_restart_smoke({"planned": []}, {})

    assert result["status"] == "FAIL"
    assert result["failure_code"] == "oa_identity_restart_smoke_failed"
    assert result["failed_checks"]


def test_protected_runner_skip_and_target_guards() -> None:
    skipped = smoke.run_oa_identity_session_authorization_restart_smoke({})
    assert skipped["status"] == "SKIPPED"

    missing = smoke.run_oa_identity_session_authorization_restart_smoke(
        {smoke.SMOKE_ENV: "1"}
    )
    assert missing["failure_code"] == "database_url_missing"

    rejected = smoke.run_oa_identity_session_authorization_restart_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: (
                "postgresql+psycopg://wrong@127.0.0.1/wrong"
            ),
        }
    )
    assert rejected["failure_code"] == "target_not_allowed"
    assert smoke._target_url_allowed("postgresql://nex_oa_user@host/nex_oa_test")
    assert not smoke._target_url_allowed("postgresql://bad host/%")
    assert not smoke._target_url_allowed("postgresql://[invalid")


def test_restart_cleanup_tolerates_unavailable_runtime_engine(monkeypatch) -> None:
    class FailingMemberships:
        def ensure_membership(self, payload):
            raise RuntimeError("setup failed")

    persistence = SimpleNamespace(api_engine=None, worker_engine=None)
    monkeypatch.setattr(
        smoke,
        "_build_stack",
        lambda environ: {
            "persistence": persistence,
            "memberships": FailingMemberships(),
        },
    )

    with pytest.raises(RuntimeError, match="setup failed"):
        smoke._execute_restart_workflow(
            database_url="postgresql://unused",
            runtime_environ={},
        )


def test_runtime_disposal_skips_duplicate_engine() -> None:
    class Engine:
        def __init__(self) -> None:
            self.dispose_count = 0

        def dispose(self) -> None:
            self.dispose_count += 1

    engine = Engine()

    smoke._dispose_runtime(
        SimpleNamespace(api_engine=engine, worker_engine=engine)
    )

    assert engine.dispose_count == 1


def test_runner_classifies_configuration_and_execution_failures(
    monkeypatch,
) -> None:
    env = {
        smoke.SMOKE_ENV: "1",
        smoke.DATABASE_ENV: "postgresql://nex_oa_user@host/nex_oa_test",
    }
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("bad")),
    )
    configured = smoke.run_oa_identity_session_authorization_restart_smoke(env)
    assert configured["failure_code"] == "configuration_invalid"

    class Migration:
        planned = tuple(f"migration-{index}" for index in range(17))
        applied = ()
        skipped = planned

    monkeypatch.setattr(smoke, "run_service_migrations", lambda *a, **k: Migration())
    monkeypatch.setattr(
        smoke,
        "_execute_restart_workflow",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("private")),
    )
    executed = smoke.run_oa_identity_session_authorization_restart_smoke(env)
    assert executed["failure_code"] == "execution_failed"
    assert executed["detail"] == "RuntimeError"


def test_summary_and_main(monkeypatch, capsys) -> None:
    passing = {
        "status": "PASS",
        "summary": {
            "migration_count": 17,
            "restart_read_count": 4,
            "persisted_row_class_count": 10,
            "cleanup_residue_count": 0,
        },
        "workflow": {"database": "nex_oa_test"},
    }
    assert smoke.summary_line(passing) == (
        "oa_identity_restart_postgres=pass database=nex_oa_test "
        "migrations=17 restart_reads=4 rows=10 residue=0 next=1296"
    )
    assert "skip" in smoke.summary_line({"status": "SKIPPED"})
    assert "code=failed" in smoke.summary_line(
        {"status": "FAIL", "failure_code": "failed"}
    )

    monkeypatch.setattr(
        smoke,
        "run_oa_identity_session_authorization_restart_smoke",
        lambda: passing,
    )
    assert smoke.main(["--summary"]) == 0
    assert "next=1296" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"
    monkeypatch.setattr(
        smoke,
        "run_oa_identity_session_authorization_restart_smoke",
        lambda: {"status": "FAIL"},
    )
    assert smoke.main([]) == 1


@pytest.mark.skipif(
    smoke.os.getenv(smoke.SMOKE_ENV) != "1",
    reason=f"{smoke.SMOKE_ENV}=1 is required",
)
def test_actual_postgres_restart_smoke() -> None:
    result = smoke.run_oa_identity_session_authorization_restart_smoke()

    assert result["status"] == "PASS", result
    assert result["workflow"]["database"] == "nex_oa_test"
    assert result["summary"]["restart_read_count"] == 4
    assert result["summary"]["cleanup_residue_count"] == 0
