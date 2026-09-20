from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from contextlib import nullcontext

import pytest

import run_ag_mvp_acceptance_postgres_smoke as smoke
from nex_runtime import InMemoryOperationalEventStore
from run_migrations import MigrationError


DATABASE_URL = (
    "postgresql+psycopg://nex_ag_user:private@127.0.0.1:5432/nex_ag_test"
)
OBSERVED_AT = datetime(2026, 9, 20, 5, 0, tzinfo=UTC)


class _Url:
    @staticmethod
    def get_backend_name() -> str:
        return "postgresql"


class _Engine:
    url = _Url()

    def __init__(self) -> None:
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True


class _Result:
    def __init__(self, value: Any, *, rowcount: int | None = None) -> None:
        self._value = value
        self.rowcount = rowcount

    def scalar_one(self) -> Any:
        return self._value


class _Connection:
    def __init__(self, results: list[_Result]) -> None:
        self._results = results

    def execute(self, *_args: Any, **_kwargs: Any) -> _Result:
        return self._results.pop(0)


class _SqlEngine(_Engine):
    def __init__(self, results: list[_Result]) -> None:
        super().__init__()
        self.connection = _Connection(results)

    def connect(self):
        return nullcontext(self.connection)

    def begin(self):
        return nullcontext(self.connection)


def _migration() -> SimpleNamespace:
    return SimpleNamespace(
        service_id=smoke.SERVICE_ID,
        planned=(smoke.LATEST_MIGRATION,),
        applied=(),
        skipped=(smoke.LATEST_MIGRATION,),
    )


def _regression() -> dict[str, Any]:
    return {
        "passed_tests": 6228,
        "failed_tests": 0,
        "statement_percent": 98.84,
        "branch_percent": 96.43,
    }


def _context() -> dict[str, str]:
    return {
        "event_id": "ag-mvp-acceptance-smoke-unit",
        "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
        "request_id": "ag-mvp-acceptance-request-unit",
    }


def _env(tmp_path: Path) -> dict[str, str]:
    coverage = tmp_path / "coverage.json"
    pytest_log = tmp_path / "pytest.log"
    coverage.write_text(
        json.dumps(
            {
                "totals": {
                    "percent_statements_covered": 98.84,
                    "percent_branches_covered": 96.43,
                }
            }
        ),
        encoding="utf-8",
    )
    pytest_log.write_text("6228 passed, 1 warning in 1.23s\n", encoding="utf-8")
    return {
        smoke.SMOKE_ENV: "1",
        smoke.DATABASE_ENV: DATABASE_URL,
        smoke.COVERAGE_JSON_ENV: str(coverage),
        smoke.PYTEST_LOG_ENV: str(pytest_log),
    }


def test_smoke_requires_opt_in_database_and_regression_paths(tmp_path: Path) -> None:
    skipped = smoke.run_ag_mvp_acceptance_postgres_smoke({})
    database_missing = smoke.run_ag_mvp_acceptance_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}
    )
    evidence_missing = smoke.run_ag_mvp_acceptance_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.DATABASE_ENV: DATABASE_URL}
    )

    assert skipped["status"] == "SKIPPED"
    assert smoke.SMOKE_ENV in skipped["skip_reason"]
    assert "smoke=skipped" in smoke.summary_line(skipped)
    assert database_missing["failure_code"] == "database_url_missing"
    assert evidence_missing["failure_code"] == "regression_evidence_missing"


def test_smoke_redacts_migration_or_regression_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            MigrationError(f"cannot connect to {DATABASE_URL}")
        ),
    )

    evidence = smoke.run_ag_mvp_acceptance_postgres_smoke(_env(tmp_path))

    assert evidence["failure_code"] == "migration_or_regression_evidence_failed"
    assert DATABASE_URL not in evidence["detail"]
    assert "***" in evidence["detail"]


def test_regression_evidence_parses_current_passing_files(tmp_path: Path) -> None:
    env = _env(tmp_path)

    evidence = smoke._load_regression_evidence(
        Path(env[smoke.COVERAGE_JSON_ENV]),
        Path(env[smoke.PYTEST_LOG_ENV]),
        now=datetime.now(UTC),
    )

    assert evidence == _regression()


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing", "missing"),
        ("stale", "stale"),
        ("invalid_coverage", "percentages"),
        ("no_pass_summary", "passing regression"),
        ("failed", "passing regression"),
    ],
)
def test_regression_evidence_fails_closed(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    env = _env(tmp_path)
    coverage = Path(env[smoke.COVERAGE_JSON_ENV])
    pytest_log = Path(env[smoke.PYTEST_LOG_ENV])
    now = datetime.now(UTC)
    if mutation == "missing":
        coverage.unlink()
    elif mutation == "stale":
        old = (now - timedelta(hours=25)).timestamp()
        os.utime(coverage, (old, old))
    elif mutation == "invalid_coverage":
        coverage.write_text(
            json.dumps(
                {
                    "totals": {
                        "percent_statements_covered": True,
                        "percent_branches_covered": 101,
                    }
                }
            ),
            encoding="utf-8",
        )
    elif mutation == "no_pass_summary":
        pytest_log.write_text("test session complete\n", encoding="utf-8")
    else:
        pytest_log.write_text(
            "6227 passed, 1 failed in 1.23s\n", encoding="utf-8"
        )

    with pytest.raises(ValueError, match=message):
        smoke._load_regression_evidence(coverage, pytest_log, now=now)


@pytest.mark.parametrize(
    ("runtime_ok", "expected"),
    [(True, "PASS"), (False, "FAIL")],
)
def test_smoke_orchestrates_runtime_result_and_disposal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    runtime_ok: bool,
    expected: str,
) -> None:
    engine = _Engine()
    monkeypatch.setattr(smoke, "run_service_migrations", lambda *_a, **_k: _migration())
    monkeypatch.setattr(smoke, "_load_regression_evidence", lambda *_a, **_k: _regression())
    monkeypatch.setattr(smoke, "build_engine", lambda _url: engine)
    monkeypatch.setattr(smoke, "build_session_factory", lambda _engine: object())
    monkeypatch.setattr(smoke, "SqlAlchemyOperationalEventStore", lambda _factory: object())
    monkeypatch.setattr(
        smoke,
        "_execute_smoke",
        lambda **_kwargs: {
            "smoke_schema_version": smoke.SCHEMA_VERSION,
            "status": "PENDING",
            "database": {"database": "nex_ag_test"},
            "regression": _regression(),
            "acceptance": {"status": "ACCEPTED"},
            "handoff": {"attestation_status": "BOUND"},
            "cleanup": {"deleted_rows": 1, "remaining_rows": 0},
            "checks": {"runtime": runtime_ok},
        },
    )

    evidence = smoke.run_ag_mvp_acceptance_postgres_smoke(_env(tmp_path))

    assert evidence["status"] == expected
    assert evidence["failure_code"] == (None if runtime_ok else "checks_failed")
    assert engine.disposed is True
    if runtime_ok:
        assert "database=nex_ag_test" in smoke.summary_line(evidence)
    else:
        assert "smoke=fail" in smoke.summary_line(evidence)


def test_smoke_fallback_cleanup_runs_after_execution_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    engine = _Engine()
    cleanup_calls: list[dict[str, str]] = []
    monkeypatch.setattr(smoke, "run_service_migrations", lambda *_a, **_k: _migration())
    monkeypatch.setattr(smoke, "_load_regression_evidence", lambda *_a, **_k: _regression())
    monkeypatch.setattr(smoke, "build_engine", lambda _url: engine)
    monkeypatch.setattr(smoke, "build_session_factory", lambda _engine: object())
    monkeypatch.setattr(smoke, "SqlAlchemyOperationalEventStore", lambda _factory: object())
    monkeypatch.setattr(
        smoke,
        "_execute_smoke",
        lambda **_kwargs: (_ for _ in ()).throw(
            RuntimeError(f"database failed {DATABASE_URL}")
        ),
    )
    monkeypatch.setattr(
        smoke,
        "_cleanup_owned_rows",
        lambda _engine, *, context: cleanup_calls.append(dict(context)) or {},
    )

    evidence = smoke.run_ag_mvp_acceptance_postgres_smoke(_env(tmp_path))

    assert evidence["failure_code"] == "smoke_execution_failed"
    assert DATABASE_URL not in evidence["detail"]
    assert len(cleanup_calls) == 1
    assert engine.disposed is True


def test_smoke_handles_engine_creation_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(smoke, "run_service_migrations", lambda *_a, **_k: _migration())
    monkeypatch.setattr(smoke, "_load_regression_evidence", lambda *_a, **_k: _regression())
    monkeypatch.setattr(
        smoke,
        "build_engine",
        lambda _url: (_ for _ in ()).throw(ValueError("engine unavailable")),
    )

    evidence = smoke.run_ag_mvp_acceptance_postgres_smoke(_env(tmp_path))

    assert evidence["failure_code"] == "smoke_execution_failed"


def test_execute_smoke_accepts_only_after_confirmed_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "_database_observation",
        lambda *_a, **_k: {
            "backend": "postgresql",
            "database": "nex_ag_test",
            "migration_present": True,
            "probe_count": 1,
        },
    )
    monkeypatch.setattr(
        smoke,
        "_cleanup_owned_rows",
        lambda *_a, **_k: {"deleted_rows": 1, "remaining_rows": 0},
    )

    evidence = smoke._execute_smoke(
        engine=_Engine(),
        event_store=InMemoryOperationalEventStore(),
        migration=_migration(),
        regression=_regression(),
        context=_context(),
        observed_at=OBSERVED_AT,
    )

    assert all(evidence["checks"].values())
    assert evidence["acceptance"]["status"] == "ACCEPTED"
    assert evidence["acceptance"]["transition_status"] == "READY_FOR_CX"
    assert evidence["handoff"]["candidate_status"] == "SEALED"
    assert evidence["handoff"]["attestation_status"] == "BOUND"
    assert evidence["cleanup"]["remaining_rows"] == 0


def test_execute_smoke_blocks_binding_when_cleanup_is_unproven(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        smoke,
        "_database_observation",
        lambda *_a, **_k: {
            "backend": "postgresql",
            "database": "nex_ag_test",
            "migration_present": True,
            "probe_count": 1,
        },
    )
    monkeypatch.setattr(
        smoke,
        "_cleanup_owned_rows",
        lambda *_a, **_k: {"deleted_rows": 0, "remaining_rows": -1},
    )

    evidence = smoke._execute_smoke(
        engine=_Engine(),
        event_store=InMemoryOperationalEventStore(),
        migration=_migration(),
        regression=_regression(),
        context=_context(),
        observed_at=OBSERVED_AT,
    )

    assert evidence["checks"]["owned_rows_deleted"] is False
    assert evidence["checks"]["acceptance_api_accepted"] is False
    assert evidence["checks"]["attestation_bound_verified"] is False
    assert evidence["acceptance"]["status"] == "BLOCKED"
    assert evidence["handoff"]["attestation_status"] is None


def test_cleanup_failure_and_evidence_redaction_helpers() -> None:
    class _BrokenEngine:
        def begin(self):
            raise RuntimeError("unavailable")

    cleanup = smoke._cleanup_owned_rows(_BrokenEngine(), context=_context())
    serialized = json.dumps({"safe": True})
    smoke.assert_smoke_evidence_redacted(
        serialized,
        {},
    )
    smoke.assert_smoke_evidence_redacted(
        serialized,
        {smoke.DATABASE_ENV: DATABASE_URL},
    )

    assert cleanup == {"deleted_rows": 0, "remaining_rows": -1}
    with pytest.raises(AssertionError, match="leaked private data"):
        smoke.assert_smoke_evidence_redacted(
            smoke.RAW_MESSAGE,
            {smoke.DATABASE_ENV: DATABASE_URL},
        )


def test_database_observation_and_cleanup_execute_direct_sql() -> None:
    observation_engine = _SqlEngine(
        [_Result("nex_ag_test"), _Result(1), _Result(1)]
    )
    cleanup_engine = _SqlEngine(
        [_Result(None, rowcount=1), _Result(0)]
    )

    observation = smoke._database_observation(
        observation_engine,
        context=_context(),
    )
    cleanup = smoke._cleanup_owned_rows(cleanup_engine, context=_context())

    assert observation == {
        "backend": "postgresql",
        "database": "nex_ag_test",
        "migration_present": True,
        "probe_count": 1,
    }
    assert cleanup == {"deleted_rows": 1, "remaining_rows": 0}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, True),
        (100.0, True),
        (True, False),
        ("98", False),
        (-0.1, False),
        (100.1, False),
    ],
)
def test_coverage_percent_is_bounded_numeric(value: Any, expected: bool) -> None:
    assert smoke._coverage_percent(value) is expected


def test_main_returns_success_for_default_skip(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_ag_mvp_acceptance_postgres_smoke",
        lambda: {"status": "SKIPPED"},
    )

    assert smoke.main(["--summary"]) == 0
    assert "smoke=skipped" in capsys.readouterr().out


def test_main_returns_failure_and_prints_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_ag_mvp_acceptance_postgres_smoke",
        lambda: {"status": "FAIL", "failure_code": "unit"},
    )

    assert smoke.main([]) == 1
    assert '"failure_code": "unit"' in capsys.readouterr().out


def test_smoke_is_wired_to_quality_gate_and_slice_docs() -> None:
    quality = (smoke.ROOT / "scripts/quality/run_quality_gate.sh").read_text(
        encoding="utf-8"
    )
    docs_index = (smoke.ROOT / "docs/README.md").read_text(encoding="utf-8")
    service_readme = (smoke.ROOT / "services/nex-ag/README.md").read_text(
        encoding="utf-8"
    )
    slice_doc = smoke.ROOT / "docs/slices/0898_ag_mvp_acceptance_postgresql_smoke.md"

    assert "run_ag_mvp_acceptance_postgres_smoke.py --summary" in quality
    assert "0898_ag_mvp_acceptance_postgresql_smoke.md" in docs_index
    assert "Slice 0898" in service_readme
    assert slice_doc.is_file()
