from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import run_oa_cross_service_trust_smoke as smoke
from nex_oa.mvp_cross_service_trust_smoke import (
    EXPECTED_CONSUMERS,
    EXPECTED_RESIDUE_KEYS,
    evaluate_oa_cross_service_trust_smoke,
)


def _consumer() -> dict[str, object]:
    return {
        "status_code": 200,
        "claim_status": "VALID",
        "token_kind": "SIGNED",
        "introspection_status": "ACTIVE",
        "rollout_profile": "SIGNED_ONLY",
        "mock_rejected": True,
        "revoked_denied": True,
        "revoked_error_code": "nex.token_introspection_inactive",
        "accepted_signed_count": 1,
        "introspected_count": 1,
        "rejected_count": 2,
    }


def _passing_workflow() -> dict[str, object]:
    return {
        "database": "nex_oa_test",
        "role": "nex_oa_user",
        "runtime_mode": "postgres",
        "checks": {
            "four_tokens_issued": True,
            "oa_runtime_restarted": True,
            "persisted_jwks_loaded": True,
            "all_sensitive_routes_introspected": True,
            "all_revoked_tokens_denied": True,
        },
        "consumers": {name: _consumer() for name in EXPECTED_CONSUMERS},
        "db_observations": {
            "migration_ledger_count": 17,
            "principal_count": 1,
            "credential_count": 1,
            "signing_key_count": 1,
            "revocation_count": 4,
            "revocation_digest_count": 4,
            "private_jwk_member_count": 0,
            "raw_token_match_count": 0,
            "raw_secret_match_count": 0,
            "issued_token_count": 4,
        },
        "cleanup_residue": {name: 0 for name in EXPECTED_RESIDUE_KEYS},
    }


def test_evaluator_accepts_complete_cross_service_evidence() -> None:
    result = evaluate_oa_cross_service_trust_smoke(
        {"planned": [f"migration-{index}" for index in range(17)]},
        _passing_workflow(),
    )

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert all(result["consumer_checks"].values())
    assert result["summary"] == {
        "migration_count": 17,
        "consumer_count": 4,
        "passed_consumer_count": 4,
        "issued_token_count": 4,
        "revoked_denial_count": 4,
        "cleanup_residue_count": 0,
    }


def test_evaluator_fails_closed_for_incomplete_evidence() -> None:
    result = evaluate_oa_cross_service_trust_smoke({"planned": []}, {})

    assert result["status"] == "FAIL"
    assert result["failure_code"] == "oa_cross_service_trust_smoke_failed"
    assert not any(result["consumer_checks"].values())


def test_direct_introspector_forwards_bound_context() -> None:
    class Validator:
        def introspect(self, token, **kwargs):
            return {"token": token, **kwargs}

    introspector = smoke._DirectOaTokenIntrospector(Validator(), now_epoch=42)
    result = introspector.introspect(
        "token",
        expected_audience="nex-cx",
        required_scopes=("service:call",),
    )

    assert result == {
        "token": "token",
        "expected_audience": "nex-cx",
        "required_scopes": ("service:call",),
        "now_epoch": 42,
    }


def test_protected_runner_skip_and_target_guards() -> None:
    skipped = smoke.run_oa_cross_service_trust_smoke({})
    assert skipped["status"] == "SKIPPED"

    missing = smoke.run_oa_cross_service_trust_smoke({smoke.SMOKE_ENV: "1"})
    assert missing["failure_code"] == "database_url_missing"

    rejected = smoke.run_oa_cross_service_trust_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: "postgresql://wrong@host/wrong",
        }
    )
    assert rejected["failure_code"] == "target_not_allowed"
    assert smoke._target_url_allowed("postgresql://nex_oa_user@host/nex_oa_test")
    assert not smoke._target_url_allowed("postgresql://[invalid")


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
    configured = smoke.run_oa_cross_service_trust_smoke(env)
    assert configured["failure_code"] == "configuration_invalid"

    class Migration:
        planned = tuple(f"migration-{index}" for index in range(17))
        applied = ()
        skipped = planned

    monkeypatch.setattr(smoke, "run_service_migrations", lambda *a, **k: Migration())
    monkeypatch.setattr(
        smoke,
        "_execute_cross_service_workflow",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("private")),
    )
    executed = smoke.run_oa_cross_service_trust_smoke(env)
    assert executed["failure_code"] == "execution_failed"
    assert executed["detail"] == "RuntimeError"


def test_build_stack_rejects_unavailable_database_runtime(monkeypatch) -> None:
    monkeypatch.setattr(smoke, "build_service_app", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        smoke,
        "attach_service_persistence_runtime",
        lambda *args, **kwargs: SimpleNamespace(
            api_session_factory=None,
            api_engine=None,
            worker_engine=None,
        ),
    )

    with pytest.raises(RuntimeError, match="platform trust runtime"):
        smoke._build_stack({})


def test_workflow_cleanup_tolerates_unavailable_runtime_engine(
    monkeypatch,
) -> None:
    class Signer:
        def generate_key(self, reference):
            return None

    class FailingPrincipals:
        def upsert_principal(self, payload):
            raise RuntimeError("setup failed")

    persistence = SimpleNamespace(api_engine=None, worker_engine=None)
    monkeypatch.setattr(smoke, "InMemoryOaRsaSigningProvider", Signer)
    monkeypatch.setattr(
        smoke,
        "_build_stack",
        lambda environ: {
            "persistence": persistence,
            "principals": FailingPrincipals(),
        },
    )

    with pytest.raises(RuntimeError, match="setup failed"):
        smoke._execute_cross_service_workflow(runtime_environ={})


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


def test_summary_and_main(monkeypatch, capsys) -> None:
    passing = {
        "status": "PASS",
        "summary": {
            "consumer_count": 4,
            "passed_consumer_count": 4,
            "issued_token_count": 4,
            "revoked_denial_count": 4,
            "cleanup_residue_count": 0,
        },
        "workflow": {"database": "nex_oa_test"},
    }
    assert smoke.summary_line(passing) == (
        "oa_cross_service_trust_postgres=pass database=nex_oa_test "
        "consumers=4/4 tokens=4 revoked_denials=4 residue=0 next=1299"
    )
    assert "skip" in smoke.summary_line({"status": "SKIPPED"})
    assert "code=failed" in smoke.summary_line(
        {"status": "FAIL", "failure_code": "failed"}
    )

    monkeypatch.setattr(smoke, "run_oa_cross_service_trust_smoke", lambda: passing)
    assert smoke.main(["--summary"]) == 0
    assert "next=1299" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"
    monkeypatch.setattr(
        smoke, "run_oa_cross_service_trust_smoke", lambda: {"status": "FAIL"}
    )
    assert smoke.main([]) == 1


@pytest.mark.skipif(
    smoke.os.getenv(smoke.SMOKE_ENV) != "1",
    reason=f"{smoke.SMOKE_ENV}=1 is required",
)
def test_actual_postgres_cross_service_trust_smoke() -> None:
    result = smoke.run_oa_cross_service_trust_smoke()

    assert result["status"] == "PASS", result
    assert result["workflow"]["database"] == "nex_oa_test"
    assert result["summary"]["passed_consumer_count"] == 4
    assert result["summary"]["revoked_denial_count"] == 4
    assert result["summary"]["cleanup_residue_count"] == 0
