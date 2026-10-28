from __future__ import annotations

from pathlib import Path

import pytest
from nex_runtime import runtime_profiles as runtime_profiles_module
from nex_runtime.demo_oci_release import build_demo_deployment_artifact_catalog
from nex_runtime.deployment_artifacts import (
    build_current_deployment_artifact_catalog,
    build_default_deployment_artifact_catalog,
    validate_deployment_artifact_catalog,
)
from nex_runtime.deployment_entrypoints import build_current_packaged_runtime_manifest
from nex_runtime.deployment_environments import (
    CURRENT_ARTIFACT_REFERENCE_ENVIRONMENTS,
    resolve_current_environment_composition,
)
from nex_runtime.deployment_oci import (
    build_current_oci_definitions,
    validate_oci_containerfiles,
)
from nex_runtime.postgres_targets import (
    CURRENT_POSTGRES_TEST_TARGETS,
    current_service_ids_for_test_database_environments,
    resolve_postgres_test_targets,
)
from nex_runtime.process_manifest import build_current_platform_runtime_manifest
from nex_runtime.runtime_profiles import (
    CURRENT_SERVICE_ENDPOINT_ENV_NAMES,
    CURRENT_SIGNED_TRUST_ENV_NAMES,
    CURRENT_TEST_DATABASE_ENV_NAMES,
    RuntimeModes,
    RuntimeProfileError,
    current_runtime_profile_required_environment_names,
    resolve_current_runtime_profile,
)

ROOT = Path(__file__).resolve().parents[1]


def _protected_test_environment() -> dict[str, str]:
    names = (
        *CURRENT_TEST_DATABASE_ENV_NAMES,
        *CURRENT_SERVICE_ENDPOINT_ENV_NAMES,
        *CURRENT_SIGNED_TRUST_ENV_NAMES,
    )
    environment = {name: f"configured-{index}" for index, name in enumerate(names)}
    for index, name in enumerate(CURRENT_ARTIFACT_REFERENCE_ENVIRONMENTS.values()):
        environment[name] = f"registry.example/nex/{index}@sha256:{index:064x}"
    return environment


def test_deployment_baselines_are_additive_and_exact() -> None:
    historical = build_default_deployment_artifact_catalog()
    demo = build_demo_deployment_artifact_catalog()
    current = build_current_deployment_artifact_catalog()

    historical_ids = {item.artifact_id for item in historical.artifacts}
    demo_ids = {item.artifact_id for item in demo.artifacts}
    current_ids = {item.artifact_id for item in current.artifacts}

    assert len(historical.artifacts) == 6
    assert len(demo.artifacts) == 8
    assert len(current.artifacts) == 9
    assert demo_ids - historical_ids == {"nex-wc-runtime", "nex-eos-runtime"}
    assert current_ids - demo_ids == {"nex-wa-runtime"}
    assert len(current.process_bindings) == 19


def test_current_runtime_and_catalog_have_exact_process_coverage() -> None:
    manifest = build_current_platform_runtime_manifest(
        environ={}, python_executable="python"
    )
    catalog = build_current_deployment_artifact_catalog()

    validate_deployment_artifact_catalog(catalog, manifest)

    process_ids = {item.process_id for item in manifest.processes}
    assert len(manifest.endpoints) == 9
    assert len(process_ids) == 19
    assert {item.process_id for item in catalog.process_bindings} == process_ids
    assert {"nex-wc-api", "nex-eos-api", "nex-wa-api"}.issubset(process_ids)
    assert "nex-wa-evidence-consumer" in process_ids
    assert "nex-ae-agent-runtime-worker" in process_ids
    assert "nex-wc-event-delivery-worker" in process_ids


def test_current_packaged_entrypoints_reuse_promoted_service_modules() -> None:
    manifest = build_current_packaged_runtime_manifest(environ={})
    processes = {item.process_id: item for item in manifest.processes}

    assert processes["nex-wc-api"].command[3] == "nex_wc.main:app"
    assert processes["nex-eos-api"].command[3] == "nex_eos.main:app"
    assert processes["nex-wa-api"].command[3] == "nex_wa.main:app"
    assert processes["nex-wa-evidence-consumer"].command[1:3] == (
        "-m",
        "nex_wa.consumer_main",
    )
    assert processes["nex-ae-agent-runtime-worker"].command[1:] == (
        "-m",
        "nex_ae_api.agent_runtime_process",
        "--profile",
        "local_mock",
    )
    assert processes["nex-wc-event-delivery-worker"].command[1:] == (
        "-m",
        "nex_wc.event_delivery_process",
        "--profile",
        "local_mock",
    )


def test_current_oci_set_has_ninth_wa_target_and_valid_containerfiles() -> None:
    definitions = build_current_oci_definitions()

    validate_oci_containerfiles(ROOT, definitions)

    assert len(definitions) == 9
    wa = next(item for item in definitions if item.artifact_id == "nex-wa-runtime")
    assert wa.target == "wa-runtime"
    assert "services/nex-wa/nex_wa" in wa.context_paths


def test_current_protected_profile_and_environment_composition_are_complete() -> None:
    environment = _protected_test_environment()
    profile = resolve_current_runtime_profile("test", environ=environment)
    composition = resolve_current_environment_composition("test", environ=environment)

    assert len(profile.required_environment_names) == 30
    assert current_runtime_profile_required_environment_names("test") == (
        profile.required_environment_names
    )
    assert len(composition.required_artifact_environment_names) == 9
    assert len(composition.artifact_references) == 9
    assert composition.status == "LIMITED"


def test_current_profile_fails_closed_when_wa_database_is_missing() -> None:
    environment = _protected_test_environment()
    environment.pop("NEX_WA_TEST_DATABASE_URL")

    with pytest.raises(
        RuntimeProfileError,
        match="NEX_WA_TEST_DATABASE_URL",
    ):
        resolve_current_runtime_profile("test", environ=environment)

    with pytest.raises(RuntimeProfileError, match="unsupported runtime profile"):
        resolve_current_runtime_profile("preview", environ={})

    with pytest.raises(RuntimeProfileError, match="unsupported runtime profile"):
        current_runtime_profile_required_environment_names("preview")


def test_current_protected_profile_rejects_non_api_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        runtime_profiles_module.PROFILE_MODES,
        "test",
        RuntimeModes("postgres", "mock", "signed", "legacy"),
    )

    with pytest.raises(
        RuntimeProfileError,
        match="protected profiles require service API projections",
    ):
        resolve_current_runtime_profile("test", environ=_protected_test_environment())


def test_current_postgres_inventory_is_additive_and_explicitly_selectable() -> None:
    environment = {
        target.test_database_env: (
            "postgresql+psycopg://"
            f"{target.expected_role_name}:private@127.0.0.1/"
            f"{target.expected_database_name}"
        )
        for target in CURRENT_POSTGRES_TEST_TARGETS
    }
    service_ids = tuple(target.service_id for target in CURRENT_POSTGRES_TEST_TARGETS)

    resolved = resolve_postgres_test_targets(environment, service_ids=service_ids)

    assert len(resolved) == 8
    assert service_ids[-3:] == ("nex-wc", "nex-eos", "nex-wa")
    assert current_service_ids_for_test_database_environments(
        ("NEX_WA_TEST_DATABASE_URL", "NEX_WC_TEST_DATABASE_URL")
    ) == ("nex-wc", "nex-wa")
