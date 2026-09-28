from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

import run_ae_citation_repair_postgres_smoke as smoke
from run_migrations import MigrationError


AE_URL = "postgresql+psycopg://nex_ae_user:private@127.0.0.1:5432/nex_ae_test"
CX_URL = "postgresql+psycopg://nex_cx_user:private@127.0.0.1:5432/nex_cx_test"


def _migration(*, current: bool = True):
    return SimpleNamespace(
        planned=("001", "002"),
        applied=() if current else ("001",),
        skipped=("001", "002") if current else (),
    )


def _evidence(*, flow: bool = True):
    return {
        "execution_state": "EXECUTED",
        "database_identity": {
            "ae": {"database": smoke.AE_DATABASE, "role": smoke.AE_ROLE},
            "cx": {"database": smoke.CX_DATABASE, "role": smoke.CX_ROLE},
        },
        "checks": {"citation_repair_flow": flow},
        "row_counts": {"ae_chat": 1, "cx_execution": 1},
        "cleanup_counts": {"ae_remaining": 0, "cx_remaining": 0},
        "provider_call_count": 2,
    }


def _env():
    return {
        smoke.SMOKE_ENV: "1",
        smoke.AE_DATABASE_ENV: AE_URL,
        smoke.CX_DATABASE_ENV: CX_URL,
    }


def test_smoke_is_opt_in_and_requires_both_database_urls() -> None:
    skipped = smoke.run_ae_citation_repair_postgres_smoke({})
    missing = smoke.run_ae_citation_repair_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}
    )

    assert skipped["status"] == "SKIPPED"
    assert skipped["actual_postgres"] is False
    assert missing["failure_code"] == "database_url_missing"
    assert smoke.summary_line(skipped).endswith(f"reason={smoke.SMOKE_ENV}")


def test_smoke_rejects_non_test_database_and_roles() -> None:
    bad_ae = smoke.run_ae_citation_repair_postgres_smoke(
        {**_env(), smoke.AE_DATABASE_ENV: AE_URL.replace("nex_ae_test", "nex_ae_dev")}
    )
    bad_cx = smoke.run_ae_citation_repair_postgres_smoke(
        {**_env(), smoke.CX_DATABASE_ENV: CX_URL.replace("nex_cx_user", "postgres")}
    )

    assert bad_ae["failure_code"] == "ae_target_not_allowed"
    assert bad_cx["failure_code"] == "cx_target_not_allowed"


def test_smoke_runs_both_migrations_and_executor(monkeypatch) -> None:
    calls = []

    def migrate(service_id, **kwargs):
        calls.append((service_id, kwargs["profile"]))
        return _migration()

    monkeypatch.setattr(smoke, "run_service_migrations", migrate)
    result = smoke.run_ae_citation_repair_postgres_smoke(
        _env(), executor=lambda **kwargs: _evidence()
    )

    assert result["status"] == "PASS"
    assert calls == [("nex-ae-api", "test"), ("nex-cx", "test")]
    assert result["checks"]["ae_migration_current"] is True
    assert result["checks"]["cx_migration_current"] is True
    assert result["provider_mode"] == "deterministic-citation-repair-mock"
    assert result["remote_provider_required"] is False
    assert "private" not in str(result["databases"])


def test_smoke_fails_closed_and_redacts_errors(monkeypatch) -> None:
    monkeypatch.setattr(
        smoke, "run_service_migrations", lambda *args, **kwargs: _migration()
    )
    failed = smoke.run_ae_citation_repair_postgres_smoke(
        _env(), executor=lambda **kwargs: _evidence(flow=False)
    )
    assert failed["status"] == "FAIL"
    assert failed["failed_checks"] == ["citation_repair_flow"]

    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            MigrationError(f"failed {AE_URL} and {CX_URL}")
        ),
    )
    errored = smoke.run_ae_citation_repair_postgres_smoke(_env())
    assert errored["failure_code"] == "execution_failed"
    assert "private" not in errored["detail"]
    assert "***" in errored["detail"]

    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(Exception("private")),
    )
    assert smoke.run_ae_citation_repair_postgres_smoke(_env())["detail"] == (
        "Exception"
    )


def test_deterministic_clients_and_package_store_are_isolated() -> None:
    package = smoke._retrieval_package(
        probe="probe",
        tenant_id="tenant",
        owner_id="owner",
        private_evidence="private evidence",
    )
    store = smoke.StaticRetrievalPackageStore(package)
    retrieval = smoke.DeterministicRetrievalClient(package)
    provider = smoke.CitationRepairMockGenerationClient()
    first_package = store.get_retrieval_package(package["retrieval_package_id"])
    first_package["status"] = "CHANGED"

    assert store.get_retrieval_package("missing") is None
    assert store.get_retrieval_package(package["retrieval_package_id"])["status"] == (
        "READY"
    )
    assert retrieval.create_retrieval_context(
        {}, request_id="request", trace_id="trace"
    )["status"] == "READY"
    assert retrieval.call_count == 1

    payload = {"alias": "general-llm-default"}
    first = provider.create_generation(payload, request_id="request", trace_id="trace")
    second = provider.create_generation(payload, request_id="request", trace_id="trace")
    assert "[1]" not in first["output"]["text"]
    assert "[1]" in second["output"]["text"]
    assert provider.call_count == 2


def test_json_helper_summary_and_cli(monkeypatch, capsys) -> None:
    assert smoke._json_mapping('{"status": "READY"}') == {"status": "READY"}
    with pytest.raises(ValueError):
        smoke._json_mapping([])

    passing = {
        "status": "PASS",
        **_evidence(),
        "remote_provider_required": False,
    }
    line = smoke.summary_line(passing)
    assert "ae_citation_repair_postgres=pass" in line
    assert "provider_calls=2" in line
    assert "cleanup=0/0" in line

    monkeypatch.setattr(
        smoke, "run_ae_citation_repair_postgres_smoke", lambda: passing
    )
    assert smoke.main(["--summary"]) == 0
    assert "ae_citation_repair_postgres=pass" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        smoke,
        "run_ae_citation_repair_postgres_smoke",
        lambda: {"status": "FAIL"},
    )
    assert smoke.main([]) == 1


@pytest.mark.skipif(
    os.getenv(smoke.SMOKE_ENV) != "1",
    reason=f"{smoke.SMOKE_ENV}=1 is required for protected PostgreSQL smoke",
)
def test_actual_ae_citation_repair_postgres_smoke() -> None:
    result = smoke.run_ae_citation_repair_postgres_smoke()

    assert result["status"] == "PASS", result
    assert result["actual_postgres"] is True
    assert result["provider_call_count"] == 2
    assert result["cleanup_counts"]["ae_remaining"] == 0
    assert result["cleanup_counts"]["cx_remaining"] == 0
