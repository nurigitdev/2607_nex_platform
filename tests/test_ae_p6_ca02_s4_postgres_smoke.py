from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/smoke"))

import run_p6_ca02_s4_profile_routing_smoke as smoke


class _Repository:
    def __init__(self, profile: str) -> None:
        self.profile = profile

    def get(self, **_kwargs: Any) -> dict[str, Any]:
        return {
            "binding": {
                "backend_profile": self.profile,
                "nsl_execution_id": "66666666-6666-4666-8666-666666666666",
                "verified_artifact_ref": "AE:NSL_ARTIFACT:s4",
            }
        }

    def mark_invocation_started(self, **_kwargs: Any) -> dict[str, Any]:
        return {
            "binding": {"invocation_started_at": "2026-10-16T03:00:00Z"},
            "request": {
                "nsl_execution_id": "66666666-6666-4666-8666-666666666666"
            },
            "context_projection": {"projection_hash": "sha256:" + "1" * 64},
        }


class _Artifacts:
    def get(self, **_kwargs: Any) -> dict[str, str]:
        return {"artifact_ref": "AE:NSL_ARTIFACT:s4"}


def test_smoke_is_protected_and_rejects_non_test_database() -> None:
    skipped = smoke.run_p6_ca02_s4_profile_routing_smoke({})
    missing = smoke.run_p6_ca02_s4_profile_routing_smoke({smoke.SMOKE_ENV: "1"})
    rejected = smoke.run_p6_ca02_s4_profile_routing_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: "postgresql+psycopg://wrong@localhost/other",
        }
    )

    assert skipped["status"] == "SKIPPED"
    assert missing["failure_code"] == "database_url_missing"
    assert rejected["failure_code"] == "target_not_allowed"


def test_smoke_combines_both_exact_routes_and_cleanup(monkeypatch) -> None:
    migration = SimpleNamespace(
        planned=("2204_ae_nsl_backend_run", smoke.REQUIRED_MIGRATION),
        applied=(smoke.REQUIRED_MIGRATION,),
        skipped=("2204_ae_nsl_backend_run",),
    )
    calls = []

    def execute(_url, *, verifier):
        calls.append(verifier)
        return {
            "status": "PASS",
            "checks": {"durable_profile_routed_exactly": True},
            "cleanup_counts": {"remaining": 0},
        }

    monkeypatch.setattr(
        smoke, "run_service_migrations", lambda *args, **kwargs: migration
    )
    monkeypatch.setattr(smoke.p5_s5, "_execute_postgres_smoke", execute)
    database_url = (
        "postgresql+psycopg://nex_ae_user:secret@localhost/nex_ae_test"
    )

    evidence = smoke.run_p6_ca02_s4_profile_routing_smoke(
        {smoke.SMOKE_ENV: "1", smoke.DATABASE_ENV: database_url}
    )

    assert evidence["status"] == "PASS"
    assert evidence["actual_postgres"] is True
    assert evidence["remote_provider_required"] is False
    assert len(calls) == 2
    assert all(evidence["checks"].values())
    assert "p6_ca02_s4_postgres=pass" in smoke.summary_line(evidence)


@pytest.mark.parametrize(
    "profile",
    (
        smoke.NSL_V01_IN_PROCESS_BACKEND,
        smoke.NSL_V01_PROCESS_ISOLATED_BACKEND,
    ),
)
def test_profile_route_verifier_uses_durable_profile_without_fallback(
    profile: str,
) -> None:
    repository = _Repository(profile)

    checks = smoke._verify_profile_route(
        {
            "tenant_id": "tenant-p6-ca02-s4",
            "step_id": "33333333-3333-4333-8333-333333333333",
            "repository": repository,
            "artifact_repository": _Artifacts(),
            "bound": repository.get(),
        },
        expected_profile=profile,
    )

    assert all(checks.values())


def test_smoke_fails_closed_and_redacts_execution_error(monkeypatch) -> None:
    migration = SimpleNamespace(
        planned=(smoke.REQUIRED_MIGRATION,),
        applied=(),
        skipped=(smoke.REQUIRED_MIGRATION,),
    )
    monkeypatch.setattr(
        smoke, "run_service_migrations", lambda *args, **kwargs: migration
    )
    monkeypatch.setattr(
        smoke.p5_s5,
        "_execute_postgres_smoke",
        lambda *args, **kwargs: {
            "status": "FAIL",
            "checks": {},
            "cleanup_counts": {"remaining": 1},
        },
    )
    database_url = (
        "postgresql+psycopg://nex_ae_user:secret@localhost/nex_ae_test"
    )
    failed = smoke.run_p6_ca02_s4_profile_routing_smoke(
        {smoke.SMOKE_ENV: "1", smoke.DATABASE_ENV: database_url}
    )
    assert failed["status"] == "FAIL"

    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError(database_url)),
    )
    errored = smoke.run_p6_ca02_s4_profile_routing_smoke(
        {smoke.SMOKE_ENV: "1", smoke.DATABASE_ENV: database_url}
    )
    assert errored["failure_code"] == "execution_failed"
    assert "secret" not in errored["detail"]


def test_main_renders_summary_and_json(monkeypatch, capsys) -> None:
    evidence = {
        "status": "PASS",
        "actual_postgres": True,
        "checks": {"routing": True},
        "migration": {"latest_version": smoke.REQUIRED_MIGRATION},
    }
    monkeypatch.setattr(smoke, "load_env_file", lambda _path: None)
    monkeypatch.setattr(
        smoke, "run_p6_ca02_s4_profile_routing_smoke", lambda: evidence
    )

    assert smoke.main(["--summary"]) == 0
    assert "p6_ca02_s4_postgres=pass" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
