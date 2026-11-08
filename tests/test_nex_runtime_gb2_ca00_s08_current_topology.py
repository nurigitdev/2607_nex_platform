from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from nex_runtime.current_topology_closure import (
    PROMOTED_PROCESS_CAPABILITIES,
    PROMOTED_PROCESS_MODULES,
    build_current_topology_closure,
    synthetic_protected_environment,
)
from nex_runtime.deployment_artifacts import (
    DeploymentArtifactCatalog,
    build_current_deployment_artifact_catalog,
)
from nex_runtime.deployment_entrypoints import (
    PackagedEntrypointDefinition,
)
from nex_runtime.runtime_profiles import (
    CURRENT_SERVICE_ENDPOINT_ENV_NAMES,
    CURRENT_SIGNED_TRUST_ENV_NAMES,
    RuntimeProfileError,
    resolve_current_runtime_profile,
)

ROOT = Path(__file__).resolve().parents[1]


def test_current_topology_closure_is_exact_and_source_backed() -> None:
    result = build_current_topology_closure(
        ROOT,
        python_executable=str(ROOT / ".venv/bin/python"),
    )

    assert result["status"] == "PASS"
    assert result["issues"] == []
    assert result["artifact_count"] == 9
    assert result["process_count"] == 20
    assert result["endpoint_count"] == 9
    assert result["background_process_count"] == 11
    assert result["domain_work_process_count"] == 5
    assert result["lifecycle_only_process_count"] == 6
    assert len(result["responsibilities"]) == 20
    assert len(result["startup"]["local_order"]) == 20
    assert len(result["startup"]["protected_order"]) == 20
    assert all(result["command_source_checks"].values())
    assert result["content_included"] is False
    assert result["secret_included"] is False


def test_promoted_processes_bind_direct_real_work_entrypoints() -> None:
    result = build_current_topology_closure(ROOT)
    promoted = {item["process_id"]: item for item in result["promoted_processes"]}

    assert set(promoted) == set(PROMOTED_PROCESS_CAPABILITIES)
    for process_id, capability in PROMOTED_PROCESS_CAPABILITIES.items():
        assert promoted[process_id]["capability"] == capability
        assert promoted[process_id]["module"] == PROMOTED_PROCESS_MODULES[process_id]
        assert promoted[process_id]["command_valid"] is True
        assert promoted[process_id]["environment_valid"] is True
        assert promoted[process_id]["artifact_id"] in {
            "nex-ae-runtime",
            "nex-wc-runtime",
            "nex-eos-runtime",
        }


def test_current_protected_profile_requires_promoted_edges() -> None:
    environment = synthetic_protected_environment()
    resolved = resolve_current_runtime_profile("test", environ=environment)

    assert len(resolved.required_environment_names) == 33
    assert "NEX_WC_AE_BASE_URL" in CURRENT_SERVICE_ENDPOINT_ENV_NAMES
    assert {
        "NEX_WC_TO_AE_SERVICE_TOKEN",
        "NEX_EOS_TO_AE_SERVICE_TOKEN",
    }.issubset(CURRENT_SIGNED_TRUST_ENV_NAMES)

    for name in (
        "NEX_WC_AE_BASE_URL",
        "NEX_WC_TO_AE_SERVICE_TOKEN",
        "NEX_EOS_TO_AE_SERVICE_TOKEN",
    ):
        incomplete = dict(environment)
        incomplete.pop(name)
        with pytest.raises(RuntimeProfileError, match=name):
            resolve_current_runtime_profile("test", environ=incomplete)


def test_source_check_rejects_missing_or_invalid_entrypoint_sources(
    tmp_path: Path,
) -> None:
    result = build_current_topology_closure(tmp_path)

    assert result["status"] == "FAIL"
    assert "all_command_sources_exist" in result["issues"]
    assert not any(result["command_source_checks"].values())


def test_command_source_helper_handles_invalid_web_and_command_shapes(
    tmp_path: Path,
) -> None:
    from nex_runtime import current_topology_closure as closure

    catalog = build_current_deployment_artifact_catalog()
    web = PackagedEntrypointDefinition(
        process_id="nex-ae-web",
        artifact_id="nex-ae-web",
        entrypoint_id="web",
        owner="nex-ae-web",
        kind="web",
        command=("npm", "start", "--silent"),
        capability="static_serving",
        admitted_profiles=("local_mock",),
    )
    package = tmp_path / "apps/nex-ae-web/package.json"
    package.parent.mkdir(parents=True)
    package.write_text("not-json", encoding="utf-8")
    assert closure._command_source_exists(tmp_path, web, catalog) is False
    package.write_text(json.dumps({"scripts": {"test": "true"}}), encoding="utf-8")
    assert closure._command_source_exists(tmp_path, web, catalog) is False

    api = replace(
        web,
        process_id="nex-ae-api",
        artifact_id="nex-ae-runtime",
        entrypoint_id="api",
        owner="nex-ae-api",
        kind="api",
        command=("python",),
        capability="request_serving",
    )
    assert closure._command_source_exists(tmp_path, api, catalog) is False
    assert closure._direct_module(api) is None

    broken_catalog = DeploymentArtifactCatalog(
        schema_version=catalog.schema_version,
        artifacts=tuple(
            replace(item, source_roots=("missing",))
            if item.artifact_id == "nex-ae-runtime"
            else item
            for item in catalog.artifacts
        ),
        process_bindings=catalog.process_bindings,
    )
    valid_api = replace(
        api,
        command=("python", "-m", "uvicorn", "nex_ae_api.main:app"),
    )
    assert closure._command_source_exists(tmp_path, valid_api, broken_catalog) is False


def test_synthetic_environment_contains_no_raw_runtime_secret() -> None:
    environment = synthetic_protected_environment()

    assert set(environment) == {
        *resolve_current_runtime_profile(
            "test", environ=environment
        ).required_environment_names
    }
    assert all("nuri1004" not in value for value in environment.values())
