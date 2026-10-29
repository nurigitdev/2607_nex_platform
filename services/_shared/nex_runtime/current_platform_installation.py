from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from .current_topology_closure import (
    build_current_topology_closure,
)
from .deployment_artifacts import build_current_deployment_artifact_catalog
from .deployment_entrypoints import build_current_packaged_runtime_manifest

CURRENT_PLATFORM_INSTALLATION_SCHEMA_VERSION = "gb2_current_platform_installation.v1"
CURRENT_COMPOSE_PATHS = (
    "deployment/compose/s143-staging.compose.yaml",
    "deployment/compose/s146-object-storage.override.yaml",
    "deployment/compose/canonical-platform.override.yaml",
    "deployment/compose/p9-wa.override.yaml",
)
CURRENT_JOURNEY_PROCESS_TO_SERVICE = {
    "nex-oa-api": "nex-oa",
    "nex-mo-api": "nex-mo",
    "nex-ae-api": "nex-ae-api",
    "nex-wc-api": "nex-wc",
    "nex-eos-api": "nex-eos",
    "nex-ae-web": "nex-ae-web",
    "nex-ae-agent-runtime-worker": "nex-ae-agent-runtime-worker",
    "nex-wc-event-delivery-worker": "nex-wc-event-delivery-worker",
    "nex-eos-outbox-publisher": "nex-eos-outbox-publisher",
}
CURRENT_ADDITIVE_PROCESS_TO_SERVICE = {
    "nex-wa-api": "nex-wa",
    "nex-wa-evidence-consumer": "nex-wa-evidence-consumer",
}
CURRENT_JOURNEY_WORKERS = {
    "nex-ae-agent-runtime-worker": (
        "nex-ae-api",
        "ae-product-agent-runtime-1",
        "ae.agent_runtime.worker",
    ),
    "nex-wc-event-delivery-worker": (
        "nex-wc",
        "wc-event-delivery-worker-1",
        "wc.event_delivery.worker",
    ),
    "nex-eos-outbox-publisher": (
        "nex-eos",
        "eos-outbox-publisher-1",
        "eos.outbox.publisher",
    ),
}


class CurrentPlatformInstallationError(ValueError):
    pass


def admit_current_platform_installation(root: Path) -> dict[str, Any]:
    """Admit the installed journey against current, not Demo, topology APIs."""

    closure = build_current_topology_closure(
        root,
        python_executable="python",
    )
    manifest = build_current_packaged_runtime_manifest(
        "local_mock",
        environ={},
        python_executable="python",
    )
    catalog = build_current_deployment_artifact_catalog()
    process_by_id = {item.process_id: item for item in manifest.processes}
    services, digests = _merged_compose_services(root)

    required_processes = {
        **CURRENT_JOURNEY_PROCESS_TO_SERVICE,
        **CURRENT_ADDITIVE_PROCESS_TO_SERVICE,
    }
    checks = {
        "current_topology_closed": closure["status"] == "PASS",
        "nine_artifacts_exact": len(catalog.artifacts) == 9,
        "twenty_processes_exact": len(process_by_id) == 20,
        "current_process_binding_exact": {
            item.process_id for item in catalog.process_bindings
        }
        == set(process_by_id),
        "journey_processes_installed": set(
            CURRENT_JOURNEY_PROCESS_TO_SERVICE.values()
        ).issubset(services),
        "additive_wa_processes_installed": set(
            CURRENT_ADDITIVE_PROCESS_TO_SERVICE.values()
        ).issubset(services),
        "packaged_commands_aligned": all(
            _compose_command_matches(
                process_by_id[process_id].command,
                services[service_id].get("command"),
            )
            for process_id, service_id in required_processes.items()
        ),
        "product_runtime_commands_only": all(
            "demo_runtime"
            not in json.dumps(services[service_id].get("command") or (), sort_keys=True)
            for service_id in required_processes.values()
        ),
        "product_ae_worker_profile": _product_ae_worker_profile(
            services["nex-ae-agent-runtime-worker"]
        ),
        "product_ae_image_contract_not_overridden": (
            _product_ae_image_contract_not_overridden(services["nex-ae-api"])
        ),
        "canonical_dependency_boundaries_present": all(
            (root / path).is_file()
            for path in (
                "services/_shared/nex_runtime/openbao_provisioning.py",
                "services/_shared/nex_runtime/object_storage_provisioning.py",
                "services/nex-mo/nex_mo/model_provider_admission.py",
            )
        ),
    }
    issues = tuple(name for name, passed in checks.items() if not passed)
    if issues:
        raise CurrentPlatformInstallationError(
            "current Platform installation admission failed: " + ",".join(issues)
        )
    return {
        "schema_version": CURRENT_PLATFORM_INSTALLATION_SCHEMA_VERSION,
        "status": "ADMITTED",
        "artifact_count": len(catalog.artifacts),
        "process_count": len(process_by_id),
        "journey_process_count": len(CURRENT_JOURNEY_PROCESS_TO_SERVICE),
        "additive_process_count": len(CURRENT_ADDITIVE_PROCESS_TO_SERVICE),
        "compose_layer_count": len(CURRENT_COMPOSE_PATHS),
        "compose_source_digests": digests,
        "checks": checks,
        "p8_demo_process_manifest_used": False,
        "manual_component_composition": False,
        "runtime_transition_fixture": False,
        "secret_included": False,
    }


def _merged_compose_services(root: Path) -> tuple[dict[str, Any], dict[str, str]]:
    services: dict[str, Any] = {}
    digests: dict[str, str] = {}
    for relative in CURRENT_COMPOSE_PATHS:
        path = root / relative
        try:
            text = path.read_text(encoding="utf-8")
            payload = yaml.safe_load(text)
        except (OSError, yaml.YAMLError) as exc:
            raise CurrentPlatformInstallationError(
                f"current Compose source is unavailable: {relative}"
            ) from exc
        if not isinstance(payload, Mapping) or not isinstance(
            payload.get("services"), Mapping
        ):
            raise CurrentPlatformInstallationError(
                f"current Compose services are invalid: {relative}"
            )
        for service_id, service in payload["services"].items():
            previous = services.get(str(service_id), {})
            services[str(service_id)] = _deep_merge(previous, service)
        from .semantic_hashes import sha256_text

        digests[relative] = f"sha256:{sha256_text(text)}"
    return services, digests


def _deep_merge(base: object, overlay: object) -> object:
    if not isinstance(base, Mapping) or not isinstance(overlay, Mapping):
        return overlay
    merged = dict(base)
    for key, value in overlay.items():
        merged[key] = _deep_merge(merged.get(key), value)
    return merged


def _compose_command_matches(packaged: tuple[str, ...], compose: object) -> bool:
    if packaged[:2] == ("npm", "start") and compose is None:
        return True
    if not isinstance(compose, list) or not all(
        isinstance(item, str) for item in compose
    ):
        return False
    observed = tuple(compose)
    if len(packaged) >= 4 and packaged[1:3] == ("-m", "uvicorn"):
        return len(observed) >= 4 and observed[1:4] == packaged[1:4]
    if packaged[:2] == ("npm", "start"):
        return observed[:2] == packaged[:2]
    if "--profile" in packaged and "--profile" in observed:
        packaged = packaged[: packaged.index("--profile")]
        observed = observed[: observed.index("--profile")]
    return observed == packaged


def _product_ae_worker_profile(service: Mapping[str, Any]) -> bool:
    command = tuple(service.get("command") or ())
    environment = service.get("environment")
    serialized = json.dumps(service, sort_keys=True)
    return (
        command[:3] == ("python", "-m", "nex_ae_api.agent_runtime_process")
        and command[-2:] == ("--profile", "staging_live")
        and isinstance(environment, Mapping)
        and "LOCAL_SKILL"
        in str(environment.get("NEX_AE_AGENT_WORKER_EXECUTOR_KINDS") or "")
        and "NEX_AE_DEMO_" not in serialized
        and "nex_ae_api.demo_runtime" not in serialized
    )


def _product_ae_image_contract_not_overridden(service: Mapping[str, Any]) -> bool:
    environment = service.get("environment")
    if not isinstance(environment, Mapping):
        return False
    return (
        environment.get("NEX_AE_FINANCE_GOLDEN_A_AUTHORITY_PROFILE_PATH")
        == "/app/deployment/product/config/finance-golden-a-vo00.v1.json"
        and environment.get("NEX_AE_PRODUCT_CAPABILITY_REGISTRY_PATH")
        == ("/app/deployment/product/config/ae-product-capability-registry.v1.json")
    )
