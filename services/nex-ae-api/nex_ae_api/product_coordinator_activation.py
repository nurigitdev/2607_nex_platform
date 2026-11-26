from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from mybee_ax.orchestration import load_m1_transaction_preparation_registration
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy.orm import Session, sessionmaker

from nex_ae_api.accounting_allocation_product_coordinator import (
    load_accounting_allocation_coordinator_activation,
)
from nex_ae_api.m1_preparation_authority_source import (
    M1_PREPARATION_AUTHORITY_SOURCE_IDENTITY,
    HttpM1PreparationAuthoritySource,
)
from nex_ae_api.m1_product_planning_coordinator import (
    build_m1_product_planning_coordinator_registry,
)
from nex_ae_api.product_capabilities import ProductCapabilityRegistry
from nex_ae_api.product_planning_coordinators import (
    ProductPlanningCoordinatorRegistry,
)
from nex_ae_api.service_auth import resolve_ae_outbound_service_token

ROOT = Path(__file__).resolve().parents[3]
ACTIVATION_SCHEMA_VERSION = "ae.product_coordinator_activation.v1"
ROLLBACK_SCHEMA_VERSION = "ae.product_coordinator_rollback_receipt.v1"
DEFAULT_ACTIVATION_PATH = (
    ROOT / "deployment/locks/ae-mybee-m1-product-coordinator-activation.v6.json"
)
DEFAULT_ROLLBACK_PATH = (
    ROOT / "deployment/locks/ae-mybee-m1-product-coordinator-rollback.v6.json"
)
AUTHORITY_IMPLEMENTATION_REF = (
    "nex_ae_api.m1_preparation_authority_source:HttpM1PreparationAuthoritySource"
)
ASSIGNMENT_HANDLER_KINDS = ("EXECUTABLE_STEP", "PRODUCT_COORDINATOR")
PROCESS_IDENTITIES = (
    "nex-ae-api",
    "nex-ae-agent-runtime-worker",
)
_FORBIDDEN_DEPLOYMENT_KEYS = frozenset(
    {
        "tenant_id",
        "company_id",
        "project_id",
        "amount",
        "currency",
        "account_id",
        "ratio",
        "approval_policy_id",
    }
)


@dataclass(frozen=True)
class ProductCoordinatorActivationAdmission:
    coordinator_registry: ProductPlanningCoordinatorRegistry
    activation_lock: Mapping[str, Any]
    rollback_receipt: Mapping[str, Any]
    readiness: Mapping[str, Any]


def build_product_coordinator_activation_documents(
    *,
    product_capabilities: ProductCapabilityRegistry,
    repository_root: Path = ROOT,
) -> tuple[dict[str, Any], dict[str, Any]]:
    preparation = load_m1_transaction_preparation_registration()
    active = build_m1_product_planning_coordinator_registry(
        product_capabilities=product_capabilities,
        preparation_registration=preparation,
        activation_status="ACTIVE",
    )
    contract = build_m1_product_planning_coordinator_registry(
        product_capabilities=product_capabilities,
        preparation_registration=preparation,
        activation_status="CONTRACT_ONLY",
    )
    registration = active.registrations[0]
    contract_registration = contract.registrations[0]
    migrations = _migration_inventory(repository_root)
    rollback = {
        "schema_version": ROLLBACK_SCHEMA_VERSION,
        "receipt_id": "mybee-m1-product-coordinator-contract-only",
        "receipt_version": 6,
        "rollback_state": "CONTRACT_ONLY",
        "coordinator_registry_hash": contract.registry_hash,
        "coordinator_registration_hash": contract_registration.registration_hash,
        "product_capability_registry_hash": product_capabilities.registry_hash,
        "checkpoint_schema_version": registration.checkpoint_schema_version,
        "migration_inventory_hash": migrations["inventory_hash"],
        "history_preservation": "PRESERVE_CHECKPOINT_WAIT_EVENT_JOB_PLAN",
        "content_included": False,
        "secret_included": False,
    }
    rollback["content_hash"] = semantic_sha256_hash_ref(rollback)
    activation = {
        "schema_version": ACTIVATION_SCHEMA_VERSION,
        "activation_id": "mybee-m1-product-coordinator-active-v6",
        "activation_state": "ACTIVE",
        "coordinator_registry": {
            "registry_id": active.registry_id,
            "registry_version": active.registry_version,
            "registry_hash": active.registry_hash,
        },
        "coordinator_registration": {
            "coordinator_id": registration.coordinator_id,
            "coordinator_version": registration.coordinator_version,
            "registration_hash": registration.registration_hash,
            "planning_policy_hash": semantic_sha256_hash_ref(
                registration.planning_policy.projection()
            ),
        },
        "product_capability_registry": {
            "registry_id": product_capabilities.registry_id,
            "registry_version": product_capabilities.registry_version,
            "registry_hash": product_capabilities.registry_hash,
        },
        "authority_resolver": {
            "source_identity": M1_PREPARATION_AUTHORITY_SOURCE_IDENTITY,
            "implementation_ref": AUTHORITY_IMPLEMENTATION_REF,
            "preparation_adapter_source_identity": (
                registration.preparation_adapter_source_identity
            ),
        },
        "materializer_source_identity": registration.materializer_source_identity,
        "skill_bundle_locks": [
            item.projection() for item in registration.installed_skill_bundle_locks
        ],
        "runtime_assignment_handlers": list(ASSIGNMENT_HANDLER_KINDS),
        "checkpoint_schema_version": registration.checkpoint_schema_version,
        "migration_inventory": migrations,
        "process_identities": list(PROCESS_IDENTITIES),
        "rollback_receipt": {
            "receipt_ref": (
                "deployment/locks/ae-mybee-m1-product-coordinator-rollback.v6.json"
            ),
            "receipt_hash": rollback["content_hash"],
        },
        "content_included": False,
        "secret_included": False,
    }
    activation["content_hash"] = semantic_sha256_hash_ref(activation)
    return activation, rollback


def load_product_coordinator_activation(
    *,
    product_capabilities: ProductCapabilityRegistry,
    environ: Mapping[str, str],
    repository_root: Path = ROOT,
) -> ProductCoordinatorActivationAdmission:
    activation_path = Path(
        str(
            environ.get("NEX_AE_PRODUCT_COORDINATOR_ACTIVATION_PATH")
            or DEFAULT_ACTIVATION_PATH
        )
    )
    rollback_path = Path(
        str(
            environ.get("NEX_AE_PRODUCT_COORDINATOR_ROLLBACK_PATH")
            or DEFAULT_ROLLBACK_PATH
        )
    )
    activation = _json_object(activation_path)
    rollback = _json_object(rollback_path)
    if _contains_forbidden_key(activation) or _contains_forbidden_key(rollback):
        raise ValueError("Product coordinator deployment lock contains business data.")
    expected_activation, expected_rollback = (
        build_product_coordinator_activation_documents(
            product_capabilities=product_capabilities,
            repository_root=repository_root,
        )
    )
    if activation != expected_activation:
        raise ValueError("Product coordinator activation lock has drifted.")
    if rollback != expected_rollback:
        raise ValueError("Product coordinator rollback receipt has drifted.")
    registry = build_m1_product_planning_coordinator_registry(
        product_capabilities=product_capabilities,
        preparation_registration=load_m1_transaction_preparation_registration(),
        activation_status="ACTIVE",
    )
    registration = registry.registrations[0]
    readiness = {
        "schema_version": "ae.product_coordinator_readiness.v1",
        "status": "READY",
        "activation_hash": activation["content_hash"],
        "rollback_receipt_hash": rollback["content_hash"],
        "coordinator_registry_hash": registry.registry_hash,
        "coordinator_registration_hash": registration.registration_hash,
        "product_capability_registry_hash": product_capabilities.registry_hash,
        "planning_policy_mode": registration.planning_policy.mode,
        "runtime_assignment_handlers": list(ASSIGNMENT_HANDLER_KINDS),
        "migration_inventory_hash": activation["migration_inventory"]["inventory_hash"],
        "content_included": False,
        "secret_included": False,
    }
    readiness["readiness_hash"] = semantic_sha256_hash_ref(readiness)
    return ProductCoordinatorActivationAdmission(
        coordinator_registry=registry,
        activation_lock=MappingProxyType(activation),
        rollback_receipt=MappingProxyType(rollback),
        readiness=MappingProxyType(readiness),
    )


def build_activated_m1_product_planning_composition(
    *,
    sessions: sessionmaker[Session],
    product_capabilities: ProductCapabilityRegistry,
    environ: Mapping[str, str],
    product_runtime: Any | None = None,
):
    """Assemble one active Product coordinator from immutable installed locks."""

    from nex_ae_api.product_planning_runtime import (
        build_installed_accounting_allocation_coordinator_runtime,
        build_installed_m1_product_coordinator_runtime,
        build_installed_product_planning_composition,
    )
    from nex_ae_api.product_runtime_profile import (
        build_installed_product_skill_runtime,
    )

    admission = load_product_coordinator_activation(
        product_capabilities=product_capabilities,
        environ=environ,
    )
    runtime = product_runtime or build_installed_product_skill_runtime(
        sessions, environ
    )
    allocation_admission = load_accounting_allocation_coordinator_activation(
        product_capabilities=product_capabilities,
        environ=environ,
    )
    preparation = getattr(runtime, "transaction_preparation", None)
    if preparation is None:
        raise ValueError("Installed Product transaction preparation is unavailable.")
    registration = admission.coordinator_registry.registrations[0]
    token = resolve_ae_outbound_service_token(
        environ.get("NEX_AE_TO_EOS_SERVICE_TOKEN"),
        audience="nex-eos",
        environ=environ,
    )
    authority = HttpM1PreparationAuthoritySource(
        eos_base_url=str(environ.get("NEX_EOS_BASE_URL") or ""),
        service_token=token,
        coordinator_registration=registration,
        preparation_registration=preparation.adapter.registration,
        timeout_seconds=float(
            str(environ.get("NEX_AE_MYBEE_EOS_TIMEOUT_SECONDS") or "15")
        ),
    )
    coordinator_runtime = build_installed_m1_product_coordinator_runtime(
        sessions=sessions,
        registration=registration,
        transaction_preparation=preparation,
        authority_source=authority,
        materializer=runtime,
    )
    allocation_runtime = build_installed_accounting_allocation_coordinator_runtime(
        sessions=sessions,
        registration=allocation_admission.registration,
        materializer=runtime,
    )
    combined_registry = ProductPlanningCoordinatorRegistry(
        (
            *admission.coordinator_registry.registrations,
            allocation_admission.registration,
        ),
        registry_id="ae-product-coordinators-mybee-accounting",
        registry_version=4,
    )
    combined_registry.require_product_capabilities(product_capabilities)
    return build_installed_product_planning_composition(
        sessions=sessions,
        coordinator_registry=combined_registry,
        runtimes=(coordinator_runtime, allocation_runtime),
    )


def _migration_inventory(repository_root: Path) -> dict[str, Any]:
    migration_root = repository_root / "database/nex-ae-api/migrations"
    files = tuple(sorted(migration_root.glob("*.sql")))
    if not files:
        raise ValueError("AE migration inventory is unavailable.")
    entries = [
        {
            "name": path.name,
            "sha256": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in files
    ]
    inventory = {
        "service_id": "nex-ae-api",
        "head": files[-1].stem,
        "count": len(entries),
        "entries": entries,
    }
    inventory["inventory_hash"] = semantic_sha256_hash_ref(inventory)
    return inventory


def _json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain a JSON object.")
    return value


def _contains_forbidden_key(value: object) -> bool:
    if isinstance(value, Mapping):
        return bool(_FORBIDDEN_DEPLOYMENT_KEYS.intersection(value)) or any(
            _contains_forbidden_key(item) for item in value.values()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_key(item) for item in value)
    return False
