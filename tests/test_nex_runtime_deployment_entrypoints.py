from __future__ import annotations

from dataclasses import replace

import pytest

from nex_runtime.deployment_artifacts import (
    build_default_deployment_artifact_catalog,
)
from nex_runtime.deployment_entrypoints import (
    PACKAGED_BACKGROUND_MODULE,
    PACKAGED_ENTRYPOINTS_SCHEMA_VERSION,
    PackagedEntrypointError,
    _packaged_command,
    build_packaged_entrypoint_definitions,
    build_packaged_runtime_manifest,
    packaged_entrypoints_projection,
    validate_packaged_entrypoints,
)
from nex_runtime.topology import RuntimeProcess


def _test_profile_environment() -> dict[str, str]:
    environment = {
        "NEX_OA_TEST_DATABASE_URL": "postgresql://oa:test@db/oa_test",
        "NEX_AG_TEST_DATABASE_URL": "postgresql://ag:test@db/ag_test",
        "NEX_AE_TEST_DATABASE_URL": "postgresql://ae:test@db/ae_test",
        "NEX_CX_TEST_DATABASE_URL": "postgresql://cx:test@db/cx_test",
        "NEX_MO_TEST_DATABASE_URL": "postgresql://mo:test@db/mo_test",
        "NEX_OA_BASE_URL": "http://oa:8101",
        "NEX_AG_BASE_URL": "http://ag:8102",
        "NEX_AE_API_BASE_URL": "http://ae:8103",
        "NEX_CX_BASE_URL": "http://cx:8104",
        "NEX_MO_BASE_URL": "http://mo:8105",
        "NEX_AE_WEB_BASE_URL": "http://web:5173",
    }
    for name in (
        "NEX_OA_INTROSPECTION_SERVICE_TOKEN",
        "NEX_AE_TO_OA_SERVICE_TOKEN",
        "NEX_AE_TO_CX_SERVICE_TOKEN",
        "NEX_CX_TO_MO_SERVICE_TOKEN",
        "NEX_AG_TO_OA_SERVICE_TOKEN",
        "NEX_AG_TO_AE_SERVICE_TOKEN",
        "NEX_AG_TO_CX_SERVICE_TOKEN",
        "NEX_AG_TO_MO_SERVICE_TOKEN",
    ):
        environment[name] = "test-token"
    return environment


def test_packaged_manifest_covers_all_processes_without_source_commands() -> None:
    manifest = build_packaged_runtime_manifest(
        "local_mock", environ={}, python_executable="python"
    )
    definitions = build_packaged_entrypoint_definitions(manifest)
    projection = packaged_entrypoints_projection(definitions)

    assert projection["schema_version"] == PACKAGED_ENTRYPOINTS_SCHEMA_VERSION
    assert projection["entrypoint_count"] == 13
    assert projection["background_entrypoint_count"] == 7
    assert projection["job_claiming_background_count"] == 1
    assert projection["lifecycle_only_background_count"] == 6
    assert all(
        not any(value.endswith((".py", ".mjs")) for value in entry.command)
        for entry in definitions
    )
    background = [entry for entry in definitions if entry.kind in {"worker", "daemon"}]
    assert all(entry.command[1:3] == ("-m", PACKAGED_BACKGROUND_MODULE) for entry in background)
    assert all(entry.admitted_profiles == ("local_mock", "test") for entry in background)
    assert next(entry for entry in definitions if entry.kind == "web").command == (
        "npm",
        "start",
        "--silent",
    )


def test_packaged_test_manifest_preserves_exact_profile() -> None:
    manifest = build_packaged_runtime_manifest(
        "test",
        environ=_test_profile_environment(),
        python_executable="python3",
    )
    background = [
        process for process in manifest.processes if process.kind in {"worker", "daemon"}
    ]

    assert all(process.command[0] == "python3" for process in background)
    assert all(process.command[-1] == "test" for process in background)
    assert next(process for process in manifest.processes if process.kind == "api").command[1:3] == (
        "-m",
        "uvicorn",
    )


def test_packaged_entrypoint_validation_reports_definition_drift() -> None:
    manifest = build_packaged_runtime_manifest("local_mock", environ={})
    catalog = build_default_deployment_artifact_catalog()
    definitions = build_packaged_entrypoint_definitions(manifest, catalog)
    first = definitions[0]
    broken = replace(
        first,
        artifact_id="nex-cx-runtime",
        entrypoint_id="wrong",
        capability="unknown",
        admitted_profiles=(),
        command=("python", "scripts/dev/run.py"),
    )

    with pytest.raises(PackagedEntrypointError) as raised:
        validate_packaged_entrypoints(
            manifest,
            catalog,
            (broken, broken, *definitions[2:]),
        )

    detail = str(raised.value)
    assert "duplicate packaged entrypoint" in detail
    assert "packaged artifact binding drift" in detail
    assert "packaged semantic entrypoint drift" in detail
    assert "packaged entrypoint owner drift" in detail
    assert "unsupported packaged capability" in detail
    assert "invalid packaged profile admission" in detail
    assert "source-tree packaged command" in detail
    assert "packaged command drift" in detail
    assert "process has no packaged entrypoint" in detail


def test_packaged_entrypoint_validation_reports_unknown_and_bad_background() -> None:
    manifest = build_packaged_runtime_manifest("local_mock", environ={})
    catalog = build_default_deployment_artifact_catalog()
    definitions = build_packaged_entrypoint_definitions(manifest, catalog)
    background = next(entry for entry in definitions if entry.kind == "worker")
    bad_background = replace(background, command=("python", "wrong"))
    unknown = replace(definitions[0], process_id="unknown-process")

    with pytest.raises(PackagedEntrypointError) as raised:
        validate_packaged_entrypoints(
            manifest,
            catalog,
            (
                bad_background,
                unknown,
                *(entry for entry in definitions if entry.process_id != background.process_id),
            ),
        )

    detail = str(raised.value)
    assert "invalid background packaged command" in detail
    assert "packaged entrypoint has no artifact binding" in detail
    assert "unknown packaged entrypoint" in detail


def test_packaged_entrypoint_validation_normalizes_catalog_failure() -> None:
    manifest = build_packaged_runtime_manifest("local_mock", environ={})
    catalog = replace(
        build_default_deployment_artifact_catalog(),
        schema_version="wrong",
    )

    with pytest.raises(PackagedEntrypointError, match="schema_version"):
        validate_packaged_entrypoints(manifest, catalog)


def test_packaged_command_rejects_unknown_process_kind() -> None:
    process = RuntimeProcess("unknown", "owner", "unknown", ("ignored",))

    with pytest.raises(PackagedEntrypointError, match="unsupported packaged process"):
        _packaged_command(process, profile="local_mock", python_executable="python")
