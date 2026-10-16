from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import run_p6_s7_postgres_smoke as smoke

ROOT = Path(__file__).resolve().parents[1]


def test_p6_s7_postgres_smoke_is_protected_by_default() -> None:
    evidence = smoke.run_p6_s7_postgres_smoke({})

    assert evidence["status"] == "SKIPPED"
    assert evidence["actual_postgres"] is False
    assert smoke.SMOKE_ENV in evidence["skip_reason"]


@pytest.mark.parametrize(
    ("environment", "failure_code"),
    (
        ({smoke.SMOKE_ENV: "1"}, "database_url_missing"),
        (
            {
                smoke.SMOKE_ENV: "1",
                smoke.DATABASE_ENV: "postgresql://other:secret@127.0.0.1/other",
            },
            "target_not_allowed",
        ),
        (
            {
                smoke.SMOKE_ENV: "1",
                smoke.DATABASE_ENV: (
                    "postgresql+psycopg://nex_ae_user:secret@127.0.0.1/nex_ae_test"
                ),
            },
            "nsl_source_missing",
        ),
        (
            {
                smoke.SMOKE_ENV: "1",
                smoke.DATABASE_ENV: (
                    "postgresql+psycopg://nex_ae_user:secret@127.0.0.1/nex_ae_test"
                ),
                smoke.NSL_SOURCE_ENV: str(ROOT / "missing-nsl-source"),
            },
            "nsl_source_invalid",
        ),
    ),
)
def test_p6_s7_postgres_smoke_fails_closed_before_execution(
    environment: dict[str, str], failure_code: str
) -> None:
    evidence = smoke.run_p6_s7_postgres_smoke(environment)

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == failure_code
    assert evidence["actual_postgres"] is False


def test_p6_s7_summary_is_bounded() -> None:
    evidence = {
        "status": "PASS",
        "actual_postgres": True,
        "checks": {"one": True, "two": True},
        "migration": {"planned_count": 43},
        "row_counts": {
            "ae_step_result": 2,
            "ae_agent_result": 1,
            "timeline_events": 30,
        },
        "cleanup_counts": {"s7_remaining": 0},
    }

    line = smoke.summary_line(evidence)

    assert "checks=2/2" in line
    assert "step_results=2" in line
    assert "agent_results=1" in line
    assert "remaining=0" in line
    assert "secret" not in json.dumps(evidence)


def _mock_success_evidence() -> dict[str, Any]:
    return {
        "status": "PASS",
        "actual_postgres": True,
        "checks": {"profile": True},
        "row_counts": {"ae_step_result": 2},
        "cleanup_counts": {"remaining": 0, "s7_remaining": 0},
    }


def _mock_enabled_environment(source: Path) -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        smoke.DATABASE_ENV: (
            "postgresql+psycopg://nex_ae_user:secret@127.0.0.1/nex_ae_test"
        ),
        smoke.NSL_SOURCE_ENV: str(source),
    }


def test_p6_s7_smoke_uses_current_admission_lock_and_reports_failure(
    monkeypatch, tmp_path
) -> None:
    source = tmp_path / "nsl"
    source.mkdir()
    lock = {
        "source_revision": "1" * 40,
        "wheel_sha256": "sha256:" + "2" * 64,
    }
    lock_path = tmp_path / "lock.json"
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    migration = SimpleNamespace(
        planned=(smoke.REQUIRED_MIGRATION,),
        applied=(),
        skipped=(smoke.REQUIRED_MIGRATION,),
    )
    monkeypatch.setattr(smoke.p6_ca02_s3, "DEFAULT_LOCK", lock_path)
    monkeypatch.setattr(
        smoke.p6_ca02_s3, "_installed_package_evidence", lambda *_args: {}
    )
    monkeypatch.setattr(smoke, "run_service_migrations", lambda *a, **k: migration)
    profile_evidence = _mock_success_evidence()
    monkeypatch.setattr(
        smoke, "execute_p6_s7_postgres_profile", lambda **_kwargs: profile_evidence
    )

    passed = smoke.run_p6_s7_postgres_smoke(_mock_enabled_environment(source))
    assert passed["status"] == "PASS"
    assert passed["nsl_source_revision"] == lock["source_revision"]
    assert passed["migration"]["latest_version"] == smoke.REQUIRED_MIGRATION

    profile_evidence["checks"]["profile"] = False
    failed = smoke.run_p6_s7_postgres_smoke(_mock_enabled_environment(source))
    assert failed["failure_code"] == "p6_s7_postgres_smoke_failed"


def test_p6_s7_smoke_contains_and_redacts_execution_error(
    monkeypatch, tmp_path
) -> None:
    source = tmp_path / "nsl"
    source.mkdir()
    lock_path = tmp_path / "lock.json"
    lock_path.write_text(json.dumps({"source_revision": "1" * 40}), encoding="utf-8")
    database_url = "postgresql+psycopg://nex_ae_user:private@127.0.0.1/nex_ae_test"
    monkeypatch.setattr(smoke.p6_ca02_s3, "DEFAULT_LOCK", lock_path)
    monkeypatch.setattr(
        smoke.p6_ca02_s3, "_installed_package_evidence", lambda *_args: {}
    )
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError(database_url)),
    )
    environment = _mock_enabled_environment(source)
    environment[smoke.DATABASE_ENV] = database_url

    evidence = smoke.run_p6_s7_postgres_smoke(environment)

    assert evidence["failure_code"] == "execution_failed"
    assert "private" not in evidence["detail"]


def test_p6_s7_main_renders_both_modes_and_failure(monkeypatch, capsys) -> None:
    passed = _mock_success_evidence()
    passed["migration"] = {"planned_count": 44}
    monkeypatch.setattr(smoke, "load_env_file", lambda _path: None)
    monkeypatch.setattr(smoke, "run_p6_s7_postgres_smoke", lambda: passed)
    assert smoke.main(["--summary"]) == 0
    assert "p6_s7_postgres=pass" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(smoke, "run_p6_s7_postgres_smoke", lambda: {"status": "FAIL"})
    assert smoke.main(["--summary"]) == 1


def _protected_profile_arguments() -> tuple[str, Path]:
    if os.environ.get(smoke.SMOKE_ENV) != "1":
        pytest.skip(f"{smoke.SMOKE_ENV}=1 is required")
    database_url = os.environ.get(smoke.DATABASE_ENV, "")
    source = os.environ.get(smoke.NSL_SOURCE_ENV, "")
    if not database_url or not source:
        pytest.skip("protected P6-S7 database and NSL source are required")
    return database_url, Path(source)


def test_p6_s7_postgres_e2e_fails_closed_when_final_step_is_missing(
    monkeypatch,
) -> None:
    database_url, source = _protected_profile_arguments()
    original = smoke.SqlAlchemyMultiStepEngine.schedule_next
    calls = 0

    def schedule_next(self, **kwargs):
        nonlocal calls
        calls += 1
        return None if calls == 2 else original(self, **kwargs)

    monkeypatch.setattr(smoke.SqlAlchemyMultiStepEngine, "schedule_next", schedule_next)
    with pytest.raises(RuntimeError, match="finalization step was not claimable"):
        smoke.execute_p6_s7_postgres_profile(
            database_url=database_url,
            nsl_source=source,
            backend_profile=smoke.NSL_V01_PROCESS_ISOLATED_BACKEND,
        )


def test_p6_s7_postgres_e2e_fails_closed_when_step_result_is_missing(
    monkeypatch,
) -> None:
    database_url, source = _protected_profile_arguments()
    monkeypatch.setattr(smoke, "load_step_result_by_step", lambda *a, **k: None)

    with pytest.raises(RuntimeError, match="parity evidence is incomplete"):
        smoke.execute_p6_s7_postgres_profile(
            database_url=database_url,
            nsl_source=source,
            backend_profile=smoke.NSL_V01_PROCESS_ISOLATED_BACKEND,
        )


def test_p6_s7_postgres_e2e_fails_closed_when_backend_run_is_missing(
    monkeypatch,
) -> None:
    database_url, source = _protected_profile_arguments()
    original = smoke.SqlAlchemyNSLBackendRunRepository.get
    calls = 0

    def get(self, **kwargs):
        nonlocal calls
        calls += 1
        return None if calls == 3 else original(self, **kwargs)

    monkeypatch.setattr(smoke.SqlAlchemyNSLBackendRunRepository, "get", get)
    with pytest.raises(RuntimeError, match="artifact or backend run is incomplete"):
        smoke.execute_p6_s7_postgres_profile(
            database_url=database_url,
            nsl_source=source,
            backend_profile=smoke.NSL_V01_PROCESS_ISOLATED_BACKEND,
        )


def test_p6_s7_actual_postgres_smoke() -> None:
    evidence = smoke.run_p6_s7_postgres_smoke()

    if evidence["status"] == "SKIPPED":
        pytest.skip(evidence["skip_reason"])
    assert evidence["status"] == "PASS", evidence
    assert evidence["actual_postgres"] is True
    assert all(evidence["checks"].values())
    assert evidence["cleanup_counts"]["s7_remaining"] == 0
