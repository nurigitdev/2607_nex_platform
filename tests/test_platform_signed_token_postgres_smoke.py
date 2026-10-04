from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from nex_oa.platform_signed_token_postgres_smoke import (
    EXPECTED_CLEANUP_KEYS,
    EXPECTED_CONSUMERS,
    EXPECTED_MIGRATION_COUNT,
    REQUIRED_MIGRATION,
    _booleans,
    _consumer_passed,
    _integers,
    _mapping,
    _strings,
    evaluate_platform_signed_token_postgres_smoke,
)
import run_platform_signed_token_postgres_smoke as runner


DATABASE_URL = (
    "postgresql+psycopg://nex_oa_user:private@127.0.0.1:5432/nex_oa_test"
)


def _migration() -> dict:
    planned = tuple(f"migration-{index}" for index in range(16)) + (
        REQUIRED_MIGRATION,
    )
    return {"planned": planned, "applied": (), "skipped": planned}


def _consumer() -> dict:
    return {
        "claim_status": "VALID",
        "caller_service_id": "nex-oa",
        "token_kind": "SIGNED",
        "rollout_profile": "SIGNED_ONLY",
        "mock_rejected": True,
        "accepted_signed_count": 2,
        "rejected_count": 1,
        "jwks_cache_status": "POPULATED",
    }


def _workflow() -> dict:
    return {
        "database": "nex_oa_test",
        "role": "nex_oa_user",
        "runtime_mode": "postgres",
        "checks": {
            "four_rs256_tokens_issued": True,
            "persisted_public_jwks_readback": True,
            "all_signed_consumers_accepted": True,
            "all_mock_tokens_rejected": True,
            "private_material_not_projected": True,
            "raw_tokens_not_projected": True,
        },
        "consumers": {
            service_id: _consumer() for service_id in EXPECTED_CONSUMERS
        },
        "db_observations": {
            "migration_ledger_count": EXPECTED_MIGRATION_COUNT,
            "required_migration_count": 1,
            "principal_count": 1,
            "credential_count": 1,
            "signing_key_count": 1,
            "private_jwk_member_count": 0,
            "private_reference_count": 1,
            "raw_token_match_count": 0,
            "raw_secret_match_count": 0,
            "issued_token_count": 4,
        },
        "cleanup_residue": {key: 0 for key in EXPECTED_CLEANUP_KEYS},
    }


def test_evaluator_accepts_actual_platform_loopback_evidence() -> None:
    result = evaluate_platform_signed_token_postgres_smoke(
        _migration(),
        _workflow(),
    )

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert all(result["consumer_checks"].values())
    assert result["database_readiness"] == (
        "ACTUAL_TEST_DATABASE_PLATFORM_TOKEN_VERIFIED"
    )
    assert result["summary"] == {
        "migration_count": 17,
        "consumer_count": 4,
        "passed_consumer_count": 4,
        "issued_token_count": 4,
        "cleanup_residue_count": 0,
    }


@pytest.mark.parametrize(
    "mutation",
    [
        "migration_plan",
        "migration_current",
        "migration_count",
        "database",
        "role",
        "runtime",
        "workflow_empty",
        "workflow_false",
        "consumer_missing",
        "consumer_failed",
        "rows",
        "private",
        "secret",
        "residue_keys",
        "residue_nonzero",
    ],
)
def test_evaluator_fails_closed_for_each_boundary(mutation: str) -> None:
    migration = _migration()
    workflow = _workflow()
    if mutation == "migration_plan":
        migration["planned"] = ()
    elif mutation == "migration_current":
        migration["skipped"] = ()
    elif mutation == "migration_count":
        workflow["db_observations"]["migration_ledger_count"] = 15
    elif mutation == "database":
        workflow["database"] = "nex_oa_dev"
    elif mutation == "role":
        workflow["role"] = "postgres"
    elif mutation == "runtime":
        workflow["runtime_mode"] = "memory"
    elif mutation == "workflow_empty":
        workflow["checks"] = {}
    elif mutation == "workflow_false":
        workflow["checks"]["four_rs256_tokens_issued"] = False
    elif mutation == "consumer_missing":
        workflow["consumers"].pop("nex-ag")
    elif mutation == "consumer_failed":
        workflow["consumers"]["nex-mo"]["mock_rejected"] = False
    elif mutation == "rows":
        workflow["db_observations"]["credential_count"] = 0
    elif mutation == "private":
        workflow["db_observations"]["private_jwk_member_count"] = 1
    elif mutation == "secret":
        workflow["db_observations"]["raw_secret_match_count"] = 1
    elif mutation == "residue_keys":
        workflow["cleanup_residue"].pop("signing_key_count")
    else:
        workflow["cleanup_residue"]["signing_key_count"] = 1

    result = evaluate_platform_signed_token_postgres_smoke(migration, workflow)

    assert result["status"] == "FAIL"
    assert result["failure_code"] == (
        "platform_signed_token_postgres_smoke_failed"
    )
    assert result["failed_checks"]


def test_evaluator_helpers_accept_only_safe_shapes() -> None:
    assert _mapping({"ok": True}) == {"ok": True}
    assert _mapping(None) == {}
    assert _strings([1, "two"]) == ("1", "two")
    assert _strings("unsafe") == ()
    assert _booleans({"yes": True, "truthy": 1}) == {
        "yes": True,
        "truthy": False,
    }
    assert _integers({"one": "1", "bad": "x", "bool": True}) == {"one": 1}
    assert _consumer_passed(None) is False


def test_runner_requires_opt_in_and_exact_target() -> None:
    assert runner.run_platform_signed_token_postgres_smoke({})["status"] == "SKIPPED"
    assert runner.run_platform_signed_token_postgres_smoke(
        {runner.SMOKE_ENV: "1"}
    )["failure_code"] == "database_url_missing"
    wrong = runner.run_platform_signed_token_postgres_smoke(
        {
            runner.SMOKE_ENV: "1",
            runner.DATABASE_ENV: DATABASE_URL.replace(
                "nex_oa_test", "nex_oa_dev"
            ),
        }
    )
    assert wrong["failure_code"] == "target_not_allowed"
    assert runner._target_url_allowed(DATABASE_URL) is True
    assert runner._target_url_allowed("not-a-url") is False


def test_runner_migrates_executes_evaluates_and_redacts(monkeypatch) -> None:
    migration = SimpleNamespace(**_migration())
    monkeypatch.setattr(
        runner,
        "run_service_migrations",
        lambda *args, **kwargs: migration,
    )
    monkeypatch.setattr(
        runner,
        "_execute_platform_loopback",
        lambda **kwargs: _workflow(),
    )

    result = runner.run_platform_signed_token_postgres_smoke(
        {runner.SMOKE_ENV: "1", runner.DATABASE_ENV: DATABASE_URL}
    )

    assert result["status"] == "PASS"
    assert result["redacted_database_url"] == (
        "postgresql+psycopg://nex_oa_user:***@127.0.0.1:5432/nex_oa_test"
    )
    assert result["migration"]["planned_count"] == 17
    assert result["next_slice"] == "1281"
    assert "private" not in result["redacted_database_url"]


def test_runner_contains_configuration_and_execution_failures(monkeypatch) -> None:
    env = {runner.SMOKE_ENV: "1", runner.DATABASE_ENV: DATABASE_URL}
    monkeypatch.setattr(
        runner,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            runner.MigrationError("bad")
        ),
    )
    assert runner.run_platform_signed_token_postgres_smoke(env)[
        "failure_code"
    ] == "configuration_invalid"
    monkeypatch.setattr(
        runner,
        "run_service_migrations",
        lambda *args, **kwargs: SimpleNamespace(
            planned=(), applied=(), skipped=()
        ),
    )
    monkeypatch.setattr(
        runner,
        "_execute_platform_loopback",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("private")),
    )
    failed = runner.run_platform_signed_token_postgres_smoke(env)
    assert failed["failure_code"] == "execution_failed"
    assert failed["detail"] == "RuntimeError"


def test_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = evaluate_platform_signed_token_postgres_smoke(
        _migration(), _workflow()
    )
    assert runner.summary_line(passing) == (
        "platform_signed_token_postgres_smoke=pass database=nex_oa_test "
        "consumers=4/4 tokens=4 residue=0 next=1281"
    )
    skipped = {"status": "SKIPPED", "skip_reason": "disabled"}
    failed = {"status": "FAIL", "failure_code": "failed"}
    assert "=skip " in runner.summary_line(skipped)
    assert "=fail " in runner.summary_line(failed)

    monkeypatch.setattr(
        runner,
        "run_platform_signed_token_postgres_smoke",
        lambda: skipped,
    )
    assert runner.main(["--summary"]) == 0
    assert "=skip " in capsys.readouterr().out
    monkeypatch.setattr(
        runner,
        "run_platform_signed_token_postgres_smoke",
        lambda: failed,
    )
    assert runner.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out


@pytest.mark.skipif(
    os.getenv(runner.SMOKE_ENV) != "1",
    reason=f"set {runner.SMOKE_ENV}=1 for protected PostgreSQL smoke",
)
def test_protected_actual_nex_oa_test_platform_loopback() -> None:
    evidence = runner.run_platform_signed_token_postgres_smoke()

    assert evidence["status"] == "PASS", evidence
    assert evidence["workflow"]["database"] == "nex_oa_test"
    assert evidence["workflow"]["role"] == "nex_oa_user"
    assert evidence["summary"]["passed_consumer_count"] == 4
    assert evidence["summary"]["cleanup_residue_count"] == 0
