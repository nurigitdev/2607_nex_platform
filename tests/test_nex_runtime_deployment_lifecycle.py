from __future__ import annotations

from dataclasses import replace

import pytest

from nex_runtime.deployment_artifacts import build_default_deployment_artifact_catalog
from nex_runtime.deployment_entrypoints import build_packaged_runtime_manifest
from nex_runtime.deployment_environments import resolve_environment_composition
from nex_runtime.deployment_lifecycle import (
    PACKAGED_LIFECYCLE_SCHEMA_VERSION,
    PackagedDeploymentLifecycleError,
    PackagedMigrationStep,
    PackagedProcessStep,
    build_packaged_deployment_lifecycle_plan,
    packaged_deployment_lifecycle_projection,
    validate_packaged_deployment_lifecycle_plan,
)

import run_platform_packaged_lifecycle as smoke


def _validation_context(profile: str = "test"):
    environment = smoke._synthetic_environment(profile)
    plan = build_packaged_deployment_lifecycle_plan(profile, environ=environment)
    return (
        plan,
        build_packaged_runtime_manifest(profile, environ=environment),
        build_default_deployment_artifact_catalog(),
        resolve_environment_composition(profile, environ=environment),
    )


def test_all_profiles_have_deterministic_dependency_lifecycle() -> None:
    plans = {
        profile: build_packaged_deployment_lifecycle_plan(
            profile, environ=smoke._synthetic_environment(profile)
        )
        for profile in ("local_mock", "local_live", "test", "staging_live", "production")
    }

    assert plans["local_mock"].migration_steps == ()
    assert [step.service_id for step in plans["test"].migration_steps] == [
        "nex-oa",
        "nex-mo",
        "nex-cx",
        "nex-ae-api",
        "nex-ag",
    ]
    assert all(
        step.command[:3] == ("python", "-m", "scripts.db.run_migrations")
        for step in plans["test"].migration_steps
    )
    assert all("--profile" in step.command for step in plans["test"].migration_steps)
    assert {step.database_environment_name for step in plans["test"].migration_steps} == {
        "NEX_OA_TEST_DATABASE_URL",
        "NEX_MO_TEST_DATABASE_URL",
        "NEX_CX_TEST_DATABASE_URL",
        "NEX_AE_TEST_DATABASE_URL",
        "NEX_AG_TEST_DATABASE_URL",
    }
    assert len(plans["test"].process_steps) == 13
    ordered = tuple(item for layer in plans["test"].start_layers for item in layer)
    assert plans["test"].stop_order == tuple(reversed(ordered))
    assert plans["production"].status == "BLOCKED"


def test_projection_is_metadata_only_and_freezes_rollback_policy() -> None:
    plan = build_packaged_deployment_lifecycle_plan(
        "production", environ=smoke._synthetic_environment("production")
    )
    projection = packaged_deployment_lifecycle_projection(plan)

    assert projection["schema_version"] == PACKAGED_LIFECYCLE_SCHEMA_VERSION
    assert projection["runtime_values_included"] is False
    assert projection["immutable_artifact_reference_count"] == 6
    assert len(projection["complete_artifact_set"]) == 6
    assert projection["mixed_artifact_set_allowed"] is False
    assert projection["database_downgrade_allowed"] is False
    assert projection["rollback_phases"] == [
        "STOP",
        "SELECT_PREVIOUS_COMPLETE_SET",
        "VERIFY_SCHEMA_COMPATIBILITY",
        "START",
        "READINESS",
    ]
    serialized = str(projection)
    assert "postgresql://" not in serialized
    assert "registry.example" not in serialized


def test_probe_modes_match_profile_and_process_kind() -> None:
    local = build_packaged_deployment_lifecycle_plan("local_mock", environ={})
    protected = build_packaged_deployment_lifecycle_plan(
        "test", environ=smoke._synthetic_environment("test")
    )

    assert {
        step.probe_mode for step in local.process_steps if step.kind in {"api", "web"}
    } == {"liveness"}
    assert {
        step.probe_mode
        for step in protected.process_steps
        if step.kind in {"api", "web"}
    } == {"readiness"}
    assert {
        step.probe_mode
        for step in protected.process_steps
        if step.kind in {"worker", "daemon"}
    } == {"process_alive_twice"}


def test_validation_reports_top_level_policy_drift() -> None:
    plan, manifest, catalog, composition = _validation_context("production")
    invalid = replace(
        plan,
        environment_class="test",
        status="LIMITED",
        reason_codes=("changed",),
        start_layers=(plan.start_layers[0], plan.start_layers[0]),
        stop_order=(),
        restart_phases=("START",),
        rollback_phases=("START",),
        complete_artifact_set=plan.complete_artifact_set[:-1],
        immutable_artifact_reference_count=0,
        mixed_artifact_set_allowed=True,
        database_downgrade_allowed=True,
        production_contact_allowed=True,
    )

    with pytest.raises(PackagedDeploymentLifecycleError) as raised:
        validate_packaged_deployment_lifecycle_plan(
            invalid,
            manifest=replace(manifest, profile="test"),
            catalog=catalog,
            composition=composition,
        )

    detail = str(raised.value)
    for expected in (
        "profile drift",
        "environment class drift",
        "composition admission drift",
        "process coverage",
        "stop order",
        "restart phases",
        "rollback phases",
        "artifact set coverage",
        "mixed artifact set",
        "database downgrade",
        "production contact",
        "reference count",
        "production lifecycle must remain blocked",
    ):
        assert expected in detail


def test_validation_reports_migration_and_process_step_drift() -> None:
    plan, manifest, catalog, composition = _validation_context()
    first_migration = replace(
        plan.migration_steps[0],
        order=9,
        artifact_id="nex-cx-runtime",
        database_environment_name="WRONG",
        command=("python", "script.py"),
    )
    first_process = plan.process_steps[0]
    invalid_process = replace(
        first_process,
        artifact_id="nex-cx-runtime",
        command=("wrong",),
        start_layer=9,
        probe_mode="liveness",
        probe_path="/wrong",
    )
    unknown_process = PackagedProcessStep(
        "unknown",
        "nex-oa-runtime",
        "nex-oa",
        "api",
        1,
        ("run",),
        "readiness",
        "/ready",
        2.0,
    )
    invalid = replace(
        plan,
        migration_steps=(first_migration, *plan.migration_steps[2:]),
        process_steps=(invalid_process, invalid_process, unknown_process),
    )

    with pytest.raises(PackagedDeploymentLifecycleError) as raised:
        validate_packaged_deployment_lifecycle_plan(
            invalid,
            manifest=manifest,
            catalog=catalog,
            composition=composition,
        )

    detail = str(raised.value)
    for expected in (
        "migration order drift",
        "migration step order drift",
        "migration artifact owner drift",
        "migration database environment drift",
        "migration command is not package relative",
        "process step count drift",
        "duplicate lifecycle process step",
        "unknown lifecycle process step",
        "process artifact drift",
        "process command drift",
        "process layer drift",
        "HTTP probe drift",
        "process step coverage",
    ):
        assert expected in detail


def test_validation_reports_background_probe_and_local_mock_migration_drift() -> None:
    plan, manifest, catalog, composition = _validation_context("local_mock")
    background_index = next(
        index
        for index, step in enumerate(plan.process_steps)
        if step.kind in {"worker", "daemon"}
    )
    process_steps = list(plan.process_steps)
    process_steps[background_index] = replace(
        process_steps[background_index],
        probe_mode="readiness",
        probe_path="/ready",
        probe_timeout_seconds=2.0,
    )
    invalid = replace(
        plan,
        migration_steps=(
            PackagedMigrationStep(
                1,
                "nex-oa",
                "nex-oa-runtime",
                "NEX_OA_DATABASE_URL",
                ("python", "-m", "scripts.db.run_migrations"),
            ),
        ),
        process_steps=tuple(process_steps),
    )

    with pytest.raises(PackagedDeploymentLifecycleError) as raised:
        validate_packaged_deployment_lifecycle_plan(
            invalid,
            manifest=manifest,
            catalog=catalog,
            composition=composition,
        )

    assert "local mock lifecycle must not run migrations" in str(raised.value)
    assert "background probe drift" in str(raised.value)
