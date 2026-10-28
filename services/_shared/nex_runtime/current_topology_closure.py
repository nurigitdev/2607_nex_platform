from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .deployment_artifacts import (
    DeploymentArtifactCatalog,
    build_current_deployment_artifact_catalog,
    validate_deployment_artifact_catalog,
)
from .deployment_entrypoints import (
    PACKAGED_DOMAIN_WORK_CAPABILITIES,
    PackagedEntrypointDefinition,
    build_current_packaged_runtime_manifest,
    build_packaged_entrypoint_definitions,
    packaged_entrypoints_projection,
)
from .process_manifest import (
    CURRENT_BACKGROUND_PROCESS_IDS,
    build_current_platform_runtime_manifest,
)
from .runtime_profiles import (
    CURRENT_SERVICE_ENDPOINT_ENV_NAMES,
    CURRENT_SIGNED_TRUST_ENV_NAMES,
    CURRENT_TEST_DATABASE_ENV_NAMES,
    current_runtime_profile_required_environment_names,
)
from .topology_graph import build_runtime_startup_plan

CURRENT_TOPOLOGY_CLOSURE_SCHEMA_VERSION = "gb2_current_topology_closure.v1"
PROMOTED_PROCESS_CAPABILITIES = {
    "nex-ae-agent-runtime-worker": "job_claiming",
    "nex-wc-event-delivery-worker": "event_delivering",
    "nex-eos-outbox-publisher": "outbox_publishing",
}
PROMOTED_PROCESS_MODULES = {
    "nex-ae-agent-runtime-worker": "nex_ae_api.agent_runtime_process",
    "nex-wc-event-delivery-worker": "nex_wc.event_delivery_process",
    "nex-eos-outbox-publisher": "nex_eos.outbox_publisher_process",
}
PROMOTED_REQUIRED_ENVIRONMENTS = {
    "nex-ae-agent-runtime-worker": frozenset({"NEX_AE_TEST_DATABASE_URL"}),
    "nex-wc-event-delivery-worker": frozenset(
        {
            "NEX_WC_TEST_DATABASE_URL",
            "NEX_WC_AE_BASE_URL",
            "NEX_WC_TO_AE_SERVICE_TOKEN",
        }
    ),
    "nex-eos-outbox-publisher": frozenset(
        {
            "NEX_EOS_TEST_DATABASE_URL",
            "NEX_AE_API_BASE_URL",
            "NEX_EOS_TO_AE_SERVICE_TOKEN",
        }
    ),
}


def build_current_topology_closure(
    root: Path,
    *,
    protected_environment: Mapping[str, str] | None = None,
    python_executable: str = "python",
) -> dict[str, Any]:
    local_manifest = build_current_platform_runtime_manifest(
        "local_mock", environ={}, python_executable=python_executable
    )
    local_packaged = build_current_packaged_runtime_manifest(
        "local_mock", environ={}, python_executable=python_executable
    )
    catalog = build_current_deployment_artifact_catalog()
    validate_deployment_artifact_catalog(catalog, local_manifest)
    entries = build_packaged_entrypoint_definitions(local_packaged, catalog)
    projection = packaged_entrypoints_projection(entries)
    local_plan = build_runtime_startup_plan(local_manifest)

    test_environment = dict(protected_environment or synthetic_protected_environment())
    test_manifest = build_current_platform_runtime_manifest(
        "test", environ=test_environment, python_executable=python_executable
    )
    test_plan = build_runtime_startup_plan(test_manifest)
    process_by_id = {item.process_id: item for item in test_manifest.processes}
    entry_by_id = {item.process_id: item for item in entries}
    binding_by_id = {item.process_id: item for item in catalog.process_bindings}
    command_sources = {
        item.process_id: _command_source_exists(root, item, catalog) for item in entries
    }
    responsibilities = _responsibility_projection(
        entries=entries,
        catalog=catalog,
        process_by_id=process_by_id,
    )
    promoted_environment_checks = {
        process_id: PROMOTED_REQUIRED_ENVIRONMENTS[process_id].issubset(
            process_by_id[process_id].environment_names
        )
        for process_id in PROMOTED_PROCESS_CAPABILITIES
    }
    promoted_command_checks = {
        process_id: _direct_module(entry_by_id[process_id])
        == PROMOTED_PROCESS_MODULES[process_id]
        for process_id in PROMOTED_PROCESS_CAPABILITIES
    }
    promoted_capability_checks = {
        process_id: entry_by_id[process_id].capability == capability
        and entry_by_id[process_id].capability != "lifecycle_only"
        for process_id, capability in PROMOTED_PROCESS_CAPABILITIES.items()
    }
    required_protected_names = set(
        current_runtime_profile_required_environment_names("test")
    )
    checks = {
        "nine_artifacts_exact": len(catalog.artifacts) == 9,
        "twenty_processes_exact": len(local_manifest.processes) == 20,
        "nine_endpoints_exact": len(local_manifest.endpoints) == 9,
        "artifact_binding_is_bijective": len(catalog.process_bindings) == 20
        and set(binding_by_id) == set(process_by_id),
        "packaged_entrypoint_is_bijective": projection["entrypoint_count"] == 20
        and set(entry_by_id) == set(process_by_id),
        "all_command_sources_exist": all(command_sources.values()),
        "all_commands_are_package_native": all(
            not any(value.endswith((".py", ".mjs")) for value in item.command)
            for item in entries
        ),
        "demo_runtime_not_referenced": "demo_runtime"
        not in json.dumps([list(item.command) for item in entries], sort_keys=True),
        "promoted_commands_are_direct": all(promoted_command_checks.values()),
        "promoted_capabilities_are_real_work": all(promoted_capability_checks.values()),
        "promoted_environment_contracts_complete": all(
            promoted_environment_checks.values()
        ),
        "current_profile_requires_wc_ae_endpoint": (
            "NEX_WC_AE_BASE_URL" in required_protected_names
        ),
        "current_profile_requires_promoted_signed_trust": {
            "NEX_WC_TO_AE_SERVICE_TOKEN",
            "NEX_EOS_TO_AE_SERVICE_TOKEN",
        }.issubset(required_protected_names),
        "local_startup_graph_covers_twenty": len(local_plan.ordered_process_ids) == 20,
        "protected_startup_graph_covers_twenty": len(test_plan.ordered_process_ids)
        == 20,
        "protected_dependencies_use_readiness": all(
            item.probe_mode == "readiness" for item in test_plan.dependency_probes
        ),
        "current_background_inventory_exact": set(CURRENT_BACKGROUND_PROCESS_IDS)
        == {
            item.process_id
            for item in local_manifest.processes
            if item.kind in {"worker", "daemon"}
        },
        "responsibility_inventory_complete": len(responsibilities) == 20
        and all(item["artifact_id"] and item["owner"] for item in responsibilities),
        "eight_database_owners_exact": len(
            {
                item["owner"]
                for item in responsibilities
                if item["database_environment"] is not None
            }
        )
        == 8,
    }
    return {
        "schema_version": CURRENT_TOPOLOGY_CLOSURE_SCHEMA_VERSION,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "issues": [name for name, passed in checks.items() if not passed],
        "artifact_count": len(catalog.artifacts),
        "process_count": len(local_manifest.processes),
        "endpoint_count": len(local_manifest.endpoints),
        "background_process_count": len(CURRENT_BACKGROUND_PROCESS_IDS),
        "domain_work_process_count": projection["domain_work_background_count"],
        "lifecycle_only_process_count": projection["lifecycle_only_background_count"],
        "promoted_processes": [
            {
                "process_id": process_id,
                "artifact_id": binding_by_id[process_id].artifact_id,
                "module": PROMOTED_PROCESS_MODULES[process_id],
                "capability": PROMOTED_PROCESS_CAPABILITIES[process_id],
                "command_valid": promoted_command_checks[process_id],
                "environment_valid": promoted_environment_checks[process_id],
            }
            for process_id in PROMOTED_PROCESS_CAPABILITIES
        ],
        "startup": {
            "local_layer_count": len(local_plan.layers),
            "protected_layer_count": len(test_plan.layers),
            "local_order": list(local_plan.ordered_process_ids),
            "protected_order": list(test_plan.ordered_process_ids),
        },
        "responsibilities": responsibilities,
        "command_source_checks": command_sources,
        "content_included": False,
        "secret_included": False,
    }


def synthetic_protected_environment() -> dict[str, str]:
    required = (
        *CURRENT_TEST_DATABASE_ENV_NAMES,
        *CURRENT_SERVICE_ENDPOINT_ENV_NAMES,
        *CURRENT_SIGNED_TRUST_ENV_NAMES,
    )
    environment = {
        name: f"gb2-s08-configured-{index}" for index, name in enumerate(required)
    }
    for index, name in enumerate(CURRENT_TEST_DATABASE_ENV_NAMES, start=1):
        environment[name] = (
            f"postgresql+psycopg://service{index}:fixture@db/service{index}_test"
        )
    for index, name in enumerate(CURRENT_SERVICE_ENDPOINT_ENV_NAMES, start=1):
        environment[name] = f"http://service-{index}.internal:{8100 + index}"
    return environment


def _responsibility_projection(
    *,
    entries: tuple[PackagedEntrypointDefinition, ...],
    catalog: DeploymentArtifactCatalog,
    process_by_id: Mapping[str, Any],
) -> list[dict[str, Any]]:
    bindings = {item.process_id: item for item in catalog.process_bindings}
    return [
        {
            "process_id": entry.process_id,
            "owner": entry.owner,
            "artifact_id": bindings[entry.process_id].artifact_id,
            "capability": entry.capability,
            "domain_work_enabled": entry.capability
            in PACKAGED_DOMAIN_WORK_CAPABILITIES,
            "database_environment": next(
                (
                    name
                    for name in process_by_id[entry.process_id].environment_names
                    if name.endswith("_DATABASE_URL")
                ),
                None,
            ),
            "cross_service_database_access": False,
        }
        for entry in entries
    ]


def _direct_module(entry: PackagedEntrypointDefinition) -> str | None:
    if len(entry.command) >= 3 and entry.command[1] == "-m":
        return entry.command[2]
    return None


def _command_source_exists(
    root: Path,
    entry: PackagedEntrypointDefinition,
    catalog: DeploymentArtifactCatalog,
) -> bool:
    artifact = next(
        item for item in catalog.artifacts if item.artifact_id == entry.artifact_id
    )
    if entry.kind == "web":
        package = root / "apps/nex-ae-web/package.json"
        try:
            payload = json.loads(package.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return False
        return bool((payload.get("scripts") or {}).get("start"))
    module = _command_module(entry)
    if module is None:
        return False
    module_parts = module.split(".")
    for source_root in artifact.source_roots:
        package_root = root / source_root
        candidates = [package_root / Path(*module_parts)]
        if package_root.name == module_parts[0]:
            candidates.append(package_root / Path(*module_parts[1:]))
        if any(
            candidate.with_suffix(".py").is_file()
            or (candidate / "__init__.py").is_file()
            for candidate in candidates
        ):
            return True
    return False


def _command_module(entry: PackagedEntrypointDefinition) -> str | None:
    if entry.kind == "api":
        try:
            return entry.command[3].split(":", maxsplit=1)[0]
        except IndexError:
            return None
    return _direct_module(entry)
