from __future__ import annotations

from dataclasses import dataclass
import os
from types import SimpleNamespace

import pytest
from nex_oa.federated_login import HttpOidcDocumentSource
from nex_oa.token_signing import InMemoryOaRsaSigningProvider
import run_oa_federated_postgres_loopback_smoke as runner


@dataclass
class _Migration:
    planned: tuple[str, ...] = (runner.REQUIRED_MIGRATION,)
    applied: tuple[str, ...] = (runner.REQUIRED_MIGRATION,)
    skipped: tuple[str, ...] = ()


def _workflow() -> dict:
    cleanup = {
        "provider_count": 0,
        "identity_count": 0,
        "membership_count": 0,
        "session_count": 0,
        "subject_count": 0,
        "tenant_count": 0,
    }
    return {
        "runtime_mode": "postgres",
        "database": runner.EXPECTED_DATABASE,
        "role": runner.EXPECTED_ROLE,
        "checks": {"runtime_postgres": True, "cleanup_residue_zero": True},
        "db_observations": {
            "migration_ledger_count": 1,
            "required_migration_count": 1,
            "provider_count": 1,
            "identity_count": 1,
            "membership_count": 1,
            "session_count": 1,
            "identity_digest_matches": True,
            "raw_external_subject_match_count": 0,
            "cleanup_residue": cleanup,
        },
        "loopback": {
            "transport": "trusted_local_tls",
            "request_count": 2,
            "discovery_count": 1,
            "jwks_count": 1,
        },
    }


def test_runner_is_opt_in_and_restricts_database_target() -> None:
    skipped = runner.run_oa_federated_postgres_loopback_smoke({})
    missing = runner.run_oa_federated_postgres_loopback_smoke(
        {runner.SMOKE_ENV: "1"}
    )
    denied = runner.run_oa_federated_postgres_loopback_smoke(
        {
            runner.SMOKE_ENV: "1",
            runner.DATABASE_ENV: "postgresql://other:secret@localhost/other",
        }
    )

    assert skipped["status"] == "SKIPPED"
    assert missing["failure_code"] == "database_url_missing"
    assert denied["failure_code"] == "target_not_allowed"
    assert runner._target_url_allowed(
        "postgresql+psycopg://nex_oa_user:secret@localhost/nex_oa_test"
    )
    assert not runner._target_url_allowed(
        "postgresql+psycopg://nex_oa_user:secret@localhost/nex_oa_dev"
    )


def test_run_orchestrates_migration_execution_and_redacts_url(monkeypatch) -> None:
    monkeypatch.setattr(runner, "run_service_migrations", lambda *args, **kwargs: _Migration())
    monkeypatch.setattr(
        runner,
        "_execute_federated_postgres_loopback_smoke",
        lambda **kwargs: _workflow(),
    )
    database_url = (
        "postgresql+psycopg://nex_oa_user:private@localhost/nex_oa_test"
    )
    evidence = runner.run_oa_federated_postgres_loopback_smoke(
        {runner.SMOKE_ENV: "1", runner.DATABASE_ENV: database_url}
    )

    assert evidence["status"] == "PASS"
    assert evidence["redacted_database_url"] != database_url
    assert "private" not in evidence["redacted_database_url"]
    assert evidence["summary"]["cleanup_residue_count"] == 0


def test_run_maps_configuration_and_execution_failures(monkeypatch) -> None:
    database_url = "postgresql://nex_oa_user:x@localhost/nex_oa_test"
    env = {runner.SMOKE_ENV: "1", runner.DATABASE_ENV: database_url}
    monkeypatch.setattr(
        runner,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("private")),
    )
    assert runner.run_oa_federated_postgres_loopback_smoke(env)[
        "failure_code"
    ] == "configuration_invalid"
    monkeypatch.setattr(runner, "run_service_migrations", lambda *args, **kwargs: _Migration())
    monkeypatch.setattr(
        runner,
        "_execute_federated_postgres_loopback_smoke",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("private")),
    )
    failure = runner.run_oa_federated_postgres_loopback_smoke(env)
    assert failure["failure_code"] == "execution_failed"
    assert failure["detail"] == "RuntimeError"


def test_tls_loopback_serves_oidc_discovery_and_jwks() -> None:
    signer = InMemoryOaRsaSigningProvider()
    jwk = signer.generate_key(runner.OIDC_KEY_REF)
    server = runner._TlsOidcLoopbackServer(jwk)
    server.start()
    try:
        source = HttpOidcDocumentSource(requester=server.request)
        discovery = source.fetch_json(server.discovery_url)
        keys = source.fetch_json(server.jwks_url)
        missing = server.request(
            f"{server.issuer}/missing",
            timeout=2,
            follow_redirects=False,
            headers={"Accept": "application/json"},
        )
    finally:
        server.stop()

    assert discovery["issuer"].startswith("https://127.0.0.1:")
    assert discovery["jwks_uri"].endswith(runner.JWKS_PATH)
    assert keys["keys"][0]["kid"] == runner.OIDC_KEY_ID
    assert missing.status_code == 404
    assert server.request_kinds == ["discovery", "jwks"]


def test_loopback_can_close_before_start() -> None:
    signer = InMemoryOaRsaSigningProvider()
    server = runner._TlsOidcLoopbackServer(
        signer.generate_key(runner.OIDC_KEY_REF)
    )

    server.stop()


def test_execution_fails_closed_without_postgres_runtime(monkeypatch) -> None:
    monkeypatch.setattr(
        runner,
        "attach_service_persistence_runtime",
        lambda *args, **kwargs: SimpleNamespace(
            api_session_factory=None,
            api_engine=None,
        ),
    )

    with pytest.raises(RuntimeError, match="runtime is unavailable"):
        runner._execute_federated_postgres_loopback_smoke(
            database_url="postgresql://nex_oa_user:x@localhost/nex_oa_test",
            runtime_environ={},
        )


def test_evaluation_fails_closed_for_missing_evidence() -> None:
    passing = runner._evaluate(
        {
            "planned": (runner.REQUIRED_MIGRATION,),
            "applied": (runner.REQUIRED_MIGRATION,),
            "skipped": (),
        },
        _workflow(),
    )
    failing = runner._evaluate({}, {})

    assert passing["status"] == "PASS"
    assert all(passing["checks"].values())
    assert failing["status"] == "FAIL"
    assert failing["failed_checks"]


@pytest.mark.skipif(
    os.environ.get(runner.SMOKE_ENV) != "1",
    reason=f"{runner.SMOKE_ENV} is not enabled",
)
def test_protected_actual_postgres_tls_loopback_smoke() -> None:
    evidence = runner.run_oa_federated_postgres_loopback_smoke()

    assert evidence["status"] == "PASS"
    assert all(evidence["checks"].values())
    assert evidence["workflow"]["database"] == runner.EXPECTED_DATABASE
    assert evidence["workflow"]["role"] == runner.EXPECTED_ROLE
    assert evidence["summary"]["loopback_request_count"] == 2
    assert evidence["summary"]["cleanup_residue_count"] == 0


def test_summary_and_main(monkeypatch, capsys) -> None:
    evidence = runner._evaluate(
        {
            "planned": (runner.REQUIRED_MIGRATION,),
            "applied": (runner.REQUIRED_MIGRATION,),
            "skipped": (),
        },
        _workflow(),
    )
    assert runner.summary_line(evidence) == (
        "oa_federated_postgres_loopback=pass migrations=1 "
        "tls_requests=2 rows=4 residue=0"
    )
    assert "skipped" in runner.summary_line(
        {"status": "SKIPPED", "skip_reason": "disabled"}
    )
    monkeypatch.setattr(
        runner, "run_oa_federated_postgres_loopback_smoke", lambda: evidence
    )
    assert runner.main(["--summary"]) == 0
    assert "oa_federated_postgres_loopback=pass" in capsys.readouterr().out
    monkeypatch.setattr(
        runner,
        "run_oa_federated_postgres_loopback_smoke",
        lambda: {"status": "FAIL"},
    )
    assert runner.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
