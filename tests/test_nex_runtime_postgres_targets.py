from __future__ import annotations

from dataclasses import replace

import pytest
import run_platform_postgres_test_targets as smoke

import nex_runtime.postgres_targets as targets_module
from nex_runtime.postgres_targets import (
    CX_VECTOR_RUNTIME_DATABASE_ENV,
    CX_VECTOR_TEST_DATABASE_ENV,
    POSTGRES_TEST_TARGETS,
    PostgresTargetConfigError,
    PostgresTestTarget,
    build_postgres_test_runtime_overlay,
    postgres_test_targets_public_projection,
    resolve_postgres_test_targets,
    service_ids_for_test_database_environments,
)
from nex_runtime.runtime_process_adapters import build_runtime_process_environment
from nex_runtime.topology import PlatformRuntimeManifest, RuntimeModes, RuntimeProcess


def valid_environment() -> dict[str, str]:
    return {
        target.test_database_env: (
            f"postgresql+psycopg://{target.expected_role_name}:secret@127.0.0.1/"
            f"{target.expected_database_name}"
        )
        for target in POSTGRES_TEST_TARGETS
    }


def manifest(*, profile: str, environment_names: tuple[str, ...]):
    return PlatformRuntimeManifest(
        "platform_runtime_manifest.v1",
        profile,
        RuntimeModes("postgres", "mock", "signed", "api"),
        (),
        (
            RuntimeProcess(
                "nex-cx-api",
                "nex-cx",
                "worker",
                ("python", "worker.py"),
                environment_names=environment_names,
            ),
        ),
    )


def test_resolves_five_targets_and_projects_no_database_urls() -> None:
    resolved = resolve_postgres_test_targets(valid_environment())
    projection = postgres_test_targets_public_projection(resolved)

    assert [item.target.service_id for item in resolved] == [
        item.service_id for item in POSTGRES_TEST_TARGETS
    ]
    assert projection["service_count"] == 5
    assert projection["database_urls_exposed"] is False
    assert all(item["drivername"] == "postgresql+psycopg" for item in projection["targets"])
    assert "secret" not in str(projection)
    assert "secret" not in repr(resolved[0])


def test_runtime_overlay_maps_test_urls_and_optional_vector_url() -> None:
    environ = valid_environment()
    environ[CX_VECTOR_TEST_DATABASE_ENV] = (
        "postgresql://vector_user:secret@127.0.0.1/nex_vector_test"
    )

    overlay = build_postgres_test_runtime_overlay(environ)

    assert len(overlay) == 6
    for target in POSTGRES_TEST_TARGETS:
        assert overlay[target.runtime_database_env] == environ[target.test_database_env]
    assert overlay[CX_VECTOR_RUNTIME_DATABASE_ENV] == environ[CX_VECTOR_TEST_DATABASE_ENV]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing", "missing_or_placeholder"),
        ("placeholder", "missing_or_placeholder"),
        ("driver", "url_invalid"),
        ("database", "database_name_mismatch"),
        ("role", "database_role_mismatch"),
    ],
)
def test_target_resolution_fails_closed(mutation, message) -> None:
    environ = valid_environment()
    target = POSTGRES_TEST_TARGETS[0]
    if mutation == "missing":
        environ.pop(target.test_database_env)
    elif mutation == "placeholder":
        environ[target.test_database_env] = (
            "postgresql://nex_oa_user:<password>@localhost/nex_oa_test"
        )
    elif mutation == "driver":
        environ[target.test_database_env] = "sqlite:///nex_oa_test.db"
    elif mutation == "database":
        environ[target.test_database_env] = (
            "postgresql://nex_oa_user:secret@localhost/nex_oa_dev"
        )
    else:
        environ[target.test_database_env] = (
            "postgresql://wrong_user:secret@localhost/nex_oa_test"
        )

    with pytest.raises(PostgresTargetConfigError, match=message):
        resolve_postgres_test_targets(environ)


def test_url_parser_failure_is_normalized(monkeypatch) -> None:
    from sqlalchemy.exc import SQLAlchemyError

    def fail_parse(value):
        raise SQLAlchemyError("private parser detail")

    monkeypatch.setattr(targets_module, "make_url", fail_parse)
    with pytest.raises(PostgresTargetConfigError, match="url_invalid"):
        resolve_postgres_test_targets(valid_environment(), service_ids=("nex-oa",))


def test_service_selection_and_duplicate_guards(monkeypatch) -> None:
    environ = valid_environment()
    assert service_ids_for_test_database_environments(
        ("NEX_CX_TEST_DATABASE_URL", "UNRELATED")
    ) == ("nex-cx",)
    assert len(resolve_postgres_test_targets(environ, service_ids=("nex-cx",))) == 1

    with pytest.raises(PostgresTargetConfigError, match="service_ids_duplicate"):
        resolve_postgres_test_targets(
            environ, service_ids=("nex-cx", "nex-cx")
        )
    with pytest.raises(PostgresTargetConfigError, match="service_id_unknown"):
        resolve_postgres_test_targets(environ, service_ids=("unknown",))

    duplicate = replace(POSTGRES_TEST_TARGETS[0], service_id="duplicate")
    monkeypatch.setattr(
        targets_module,
        "POSTGRES_TEST_TARGETS",
        (POSTGRES_TEST_TARGETS[0], duplicate),
    )
    with pytest.raises(PostgresTargetConfigError, match="service_local"):
        targets_module.resolve_postgres_test_targets(
            environ, service_ids=("nex-oa", "duplicate")
        )


@pytest.mark.parametrize(
    "database_url",
    ["sqlite:///vector.db", "postgresql://vector:<password>@localhost/vector"],
)
def test_optional_vector_url_must_be_non_placeholder_postgres(database_url) -> None:
    environ = valid_environment()
    environ[CX_VECTOR_TEST_DATABASE_ENV] = database_url

    with pytest.raises(PostgresTargetConfigError, match="cx_vector"):
        build_postgres_test_runtime_overlay(environ)


def test_child_environment_receives_active_alias_only_for_test_profile() -> None:
    environ = valid_environment()
    selected = manifest(
        profile="test",
        environment_names=("NEX_CX_TEST_DATABASE_URL",),
    )

    child = build_runtime_process_environment(selected, environ=environ)

    assert child["NEX_CX_DATABASE_URL"] == environ["NEX_CX_TEST_DATABASE_URL"]
    assert child["NEX_PROFILE"] == "test"

    local = build_runtime_process_environment(
        manifest(profile="local_mock", environment_names=()),
        environ={},
    )
    assert "NEX_CX_DATABASE_URL" not in local


def test_smoke_report_summary_and_main(monkeypatch, capsys) -> None:
    report = smoke.build_report()

    assert report["status"] == "PASS"
    assert smoke.summary_line(report) == (
        "platform_postgres_test_targets=pass services=5 aliases=5 next=1325"
    )
    assert smoke.summary_line({"status": "FAIL"}) == (
        "platform_postgres_test_targets=fail"
    )
    assert smoke.main(["--summary"]) == 0
    assert "aliases=5" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(smoke, "build_report", lambda: {"status": "FAIL"})
    assert smoke.main([]) == 1
