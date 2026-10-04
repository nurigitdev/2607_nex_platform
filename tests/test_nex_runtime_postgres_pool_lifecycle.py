from __future__ import annotations

import json

import pytest
import run_platform_postgres_pool_lifecycle as smoke
from sqlalchemy import create_engine

from nex_runtime.database import build_session_factory
from nex_runtime.postgres_pool_lifecycle import (
    PlatformPostgresPoolLifecycle,
    PostgresPoolLifecycleError,
    _check_session_factory,
    _dispose_engines,
)
from nex_runtime.postgres_targets import POSTGRES_TEST_TARGETS


def valid_environment() -> dict[str, str]:
    return {
        target.test_database_env: (
            f"postgresql://{target.expected_role_name}:secret@127.0.0.1/"
            f"{target.expected_database_name}"
        )
        for target in POSTGRES_TEST_TARGETS
    }


class Engine:
    def __init__(self, name: str, *, fail_dispose: bool = False) -> None:
        self.name = name
        self.fail_dispose = fail_dispose
        self.dispose_count = 0

    def dispose(self) -> None:
        self.dispose_count += 1
        if self.fail_dispose:
            raise RuntimeError("private dispose detail")


def build_fake_lifecycle(
    *,
    engine_factory=None,
    session_factory_builder=lambda engine: object(),
    engine_checker=lambda engine: True,
    session_checker=lambda factory: True,
    environ=None,
):
    created: list[Engine] = []

    def default_engine_factory(database_url, *, pool_settings):
        engine = Engine(f"{pool_settings.service_id}:{pool_settings.workload}")
        created.append(engine)
        return engine

    lifecycle = PlatformPostgresPoolLifecycle.build(
        environ or valid_environment(),
        engine_factory=engine_factory or default_engine_factory,
        session_factory_builder=session_factory_builder,
        engine_checker=engine_checker,
        session_checker=session_checker,
    )
    return lifecycle, created


def test_builds_distinct_api_worker_pools_and_disposes_idempotently() -> None:
    lifecycle, engines = build_fake_lifecycle()
    status = lifecycle.public_status()

    assert status["state"] == "READY"
    assert status["service_count"] == 5
    assert status["pool_count"] == 10
    assert status["pending_disposal_count"] == 10
    assert len(lifecycle.handles) == 10
    assert len(lifecycle.engine_identity_tokens()) == 10
    assert [item["workload"] for item in status["pools"][:2]] == ["api", "worker"]
    assert status["pools"][0]["pool_size"] == 5
    assert status["pools"][1]["pool_size"] == 3
    assert status["evidence"]["record_count"] == 5
    assert "secret" not in str(status)
    assert "secret" not in repr(lifecycle.handles[0])

    disposed = lifecycle.dispose()
    assert disposed["state"] == "DISPOSED"
    assert disposed["pending_disposal_count"] == 0
    assert all(engine.dispose_count == 1 for engine in engines)
    assert lifecycle.dispose() == disposed
    assert all(engine.dispose_count == 1 for engine in engines)


def test_configuration_and_all_initialization_failures_are_normalized() -> None:
    with pytest.raises(PostgresPoolLifecycleError, match="configuration_invalid"):
        PlatformPostgresPoolLifecycle.build({})

    cases = (
        {
            "engine_factory": lambda *args, **kwargs: (_ for _ in ()).throw(
                RuntimeError("private")
            )
        },
        {
            "session_factory_builder": lambda engine: (_ for _ in ()).throw(
                RuntimeError("private")
            )
        },
        {"engine_checker": lambda engine: False},
        {"session_checker": lambda factory: False},
    )
    for case in cases:
        with pytest.raises(
            PostgresPoolLifecycleError, match="pool_initialization_failed"
        ) as failed:
            build_fake_lifecycle(**case)
        assert failed.value.service_id == "nex-oa"
        assert failed.value.workload == "api"

    bad_pool = valid_environment()
    bad_pool["NEX_OA_DB_POOL_SIZE"] = "0"
    with pytest.raises(
        PostgresPoolLifecycleError, match="pool_initialization_failed"
    ):
        build_fake_lifecycle(environ=bad_pool)


def test_reused_engine_is_rejected_and_created_engines_are_cleaned() -> None:
    engine = Engine("shared")

    with pytest.raises(PostgresPoolLifecycleError) as failed:
        build_fake_lifecycle(engine_factory=lambda *args, **kwargs: engine)

    assert failed.value.workload == "worker"
    assert engine.dispose_count == 1


def test_disposal_failure_continues_and_can_be_retried() -> None:
    lifecycle, engines = build_fake_lifecycle()
    engines[4].fail_dispose = True

    with pytest.raises(PostgresPoolLifecycleError, match="pool_disposal_failed"):
        lifecycle.dispose()

    assert lifecycle.public_status()["state"] == "DISPOSE_FAILED"
    assert lifecycle.public_status()["pending_disposal_count"] == 1
    assert all(engine.dispose_count == 1 for engine in engines)

    engines[4].fail_dispose = False
    assert lifecycle.dispose()["state"] == "DISPOSED"
    assert engines[4].dispose_count == 2


def test_cleanup_helper_deduplicates_and_ignores_dispose_failure() -> None:
    good = Engine("good")
    bad = Engine("bad", fail_dispose=True)

    _dispose_engines((good, bad, good))

    assert good.dispose_count == 1
    assert bad.dispose_count == 1


def test_default_session_checker_executes_select_one() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        assert _check_session_factory(build_session_factory(engine)) is True
    finally:
        engine.dispose()


class FakeLifecycle:
    build_count = 0

    def __init__(self, generation: int) -> None:
        self.generation = generation
        self.disposed = False

    @classmethod
    def build(cls, env):
        cls.build_count += 1
        return cls(cls.build_count)

    def engine_identity_tokens(self):
        start = self.generation * 10
        return frozenset(range(start, start + 10))

    def public_status(self):
        return {"service_count": 5, "pool_count": 10}

    def dispose(self):
        self.disposed = True
        return {"pending_disposal_count": 0}


def test_smoke_success_failure_cleanup_summary_and_main(monkeypatch, capsys) -> None:
    assert smoke.run_smoke({})["status"] == "SKIPPED"

    FakeLifecycle.build_count = 0
    monkeypatch.setattr(smoke, "PlatformPostgresPoolLifecycle", FakeLifecycle)
    passing = smoke.run_smoke({smoke.SMOKE_ENV: "1"})
    assert passing["status"] == "PASS"
    assert passing["fresh_engine_count"] == 10
    assert smoke.summary_line(passing) == (
        "platform_postgres_pool_lifecycle=pass services=5 pools=10 "
        "fresh=10 next=1327"
    )

    class FailingLifecycle(FakeLifecycle):
        @classmethod
        def build(cls, env):
            raise PostgresPoolLifecycleError(
                "pool_initialization_failed", "nex-cx", "worker"
            )

    monkeypatch.setattr(smoke, "PlatformPostgresPoolLifecycle", FailingLifecycle)
    failed = smoke.run_smoke({smoke.SMOKE_ENV: "1"})
    assert "code=pool_initialization_failed" in smoke.summary_line(failed)
    assert smoke.summary_line({"status": "SKIPPED"}).endswith("=skip")

    class BadDispose:
        def dispose(self):
            raise PostgresPoolLifecycleError("pool_disposal_failed")

    smoke._best_effort_dispose(None, BadDispose())

    monkeypatch.setattr(smoke, "run_smoke", lambda: passing)
    assert smoke.main(["--summary"]) == 0
    assert "pools=10" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"
    monkeypatch.setattr(smoke, "run_smoke", lambda: failed)
    assert smoke.main([]) == 1


@pytest.mark.skipif(
    smoke.os.getenv(smoke.SMOKE_ENV) != "1",
    reason=f"{smoke.SMOKE_ENV}=1 is required",
)
def test_actual_platform_postgres_pool_lifecycle() -> None:
    result = smoke.run_smoke()

    assert result["status"] == "PASS", result
    assert result["pool_count"] == 10
    assert result["fresh_engine_count"] == 10
    assert result["disposed_pool_count"] == 20
