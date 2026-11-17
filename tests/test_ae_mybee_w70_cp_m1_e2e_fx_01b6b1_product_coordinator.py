from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
import run_mybee_w70_cp_m1_e2e_fx_01b6b1_storage_fit_audit as audit
from mybee_ax.orchestration import load_m1_transaction_preparation_registration
from nex_ae_api.m1_product_planning_coordinator import (
    M1_PRODUCT_COORDINATOR_ID,
    build_m1_product_planning_coordinator_registration,
    build_m1_product_planning_coordinator_registry,
)
from nex_ae_api.product_capabilities import (
    ProductCapabilityRegistry,
    load_product_capability_registry,
)
from nex_ae_api.product_planning_coordinators import (
    ProductPlanningCapabilityBinding,
    ProductPlanningCoordinatorError,
    ProductPlanningCoordinatorRegistry,
    build_product_planning_coordinator_registration,
    capability_binding,
)

ROOT = Path(__file__).resolve().parents[1]
CAPABILITY_REGISTRY = (
    ROOT
    / "deployment/environments/ae-product-capability-registry.mybee-m1.v2.json"
)
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


def _product_capabilities() -> ProductCapabilityRegistry:
    return load_product_capability_registry(
        {"NEX_AE_PRODUCT_CAPABILITY_REGISTRY_PATH": str(CAPABILITY_REGISTRY)}
    )


def _binding(
    capability_id: str = "DOMAIN.OBJECT.ACTION",
    capability_version: str = "1.0.0",
    registration_hash: str = HASH_A,
) -> ProductPlanningCapabilityBinding:
    return ProductPlanningCapabilityBinding(
        capability_id=capability_id,
        capability_version=capability_version,
        capability_registration_hash=registration_hash,
    )


def _registration(
    *,
    capability_id: str = "DOMAIN.OBJECT.ACTION",
    capability_version: str = "1.0.0",
    activation_status: str = "ACTIVE",
    coordinator_id: str | None = None,
):
    trigger = _binding(capability_id, capability_version)
    return build_product_planning_coordinator_registration(
        coordinator_id=coordinator_id or f"COORDINATOR.{capability_id}",
        coordinator_version="1.0.0",
        activation_status=activation_status,
        implementation_ref="example.module:Coordinator",
        trigger_capability=trigger,
        required_capabilities=(trigger,),
        preparation_adapter_source_identity="adapter:example:v1",
        materializer_source_identity="materializer:example:v1",
        initial_state="PREPARATION_PENDING",
        waiting_states=("WAITING_APPROVAL",),
        ready_state="READY",
        terminal_states=("FAILED", "CANCELLED"),
        required_operations=("DOMAIN.OBJECT.READ", "DOMAIN.OBJECT.WRITE"),
    )


def test_m1_registration_is_exact_capability_bound_and_contract_only() -> None:
    capabilities = _product_capabilities()
    preparation = load_m1_transaction_preparation_registration()

    first = build_m1_product_planning_coordinator_registration(
        product_capabilities=capabilities,
        preparation_registration=preparation,
    )
    replay = build_m1_product_planning_coordinator_registration(
        product_capabilities=capabilities,
        preparation_registration=preparation,
    )
    registry = build_m1_product_planning_coordinator_registry(
        product_capabilities=capabilities,
        preparation_registration=preparation,
    )

    assert first == replay
    assert first.coordinator_id == M1_PRODUCT_COORDINATOR_ID
    assert first.capability_id == "FINANCE.VOUCHER.APPROVE_AND_POST"
    assert first.activation_status == "CONTRACT_ONLY"
    assert first.initial_state == "PREPARATION_PENDING"
    assert first.waiting_states == (
        "WAITING_BUSINESS_APPROVAL",
        "WAITING_ACCOUNTING_APPROVAL",
    )
    assert first.ready_state == "READY_FOR_D04"
    assert {
        item.capability_id for item in first.required_capabilities
    } == {
        "FINANCE.VOUCHER.APPROVE_AND_POST",
        "PROJECT.WORK_CODE_SET.GET",
    }
    assert first.registration_hash.startswith("sha256:")
    assert registry.resolve(
        first.capability_id,
        first.capability_version,
        capability_registration_hash=(
            first.trigger_capability.capability_registration_hash
        ),
        required=True,
    ) == first
    with pytest.raises(
        ProductPlanningCoordinatorError,
        match="not active",
    ):
        registry.resolve(
            first.capability_id,
            first.capability_version,
            require_active=True,
            required=True,
        )


def test_registry_resolves_exact_versions_and_fails_closed_on_drift() -> None:
    one = _registration()
    two = _registration(
        capability_id="DOMAIN.OTHER.READ",
        capability_version="2.0.0",
    )
    registry = ProductPlanningCoordinatorRegistry(
        (two, one),
        registry_id="product-coordinators",
        registry_version=3,
    )

    assert registry.registrations == (one, two)
    assert registry.resolve(one.capability_id, one.capability_version) == one
    assert registry.resolve("UNKNOWN.ACTION", "1.0.0") is None
    assert registry.source_identity.startswith(
        "nex-ae:product-planning-coordinator-registry:"
    )
    with pytest.raises(ProductPlanningCoordinatorError, match="not registered"):
        registry.resolve("UNKNOWN.ACTION", "1.0.0", required=True)
    with pytest.raises(ProductPlanningCoordinatorError, match="differs"):
        registry.resolve(
            one.capability_id,
            one.capability_version,
            capability_registration_hash=HASH_B,
            required=True,
        )
    with pytest.raises(ProductPlanningCoordinatorError, match="hash is invalid"):
        registry.resolve(
            one.capability_id,
            one.capability_version,
            capability_registration_hash="not-a-hash",
        )
    with pytest.raises(ProductPlanningCoordinatorError, match="must be unique"):
        ProductPlanningCoordinatorRegistry(
            (one, one),
            registry_id="duplicate",
            registry_version=1,
        )
    duplicate_identity = _registration(
        capability_id="DOMAIN.THIRD.READ",
        coordinator_id=one.coordinator_id,
    )
    with pytest.raises(ProductPlanningCoordinatorError, match="identities"):
        ProductPlanningCoordinatorRegistry(
            (one, duplicate_identity),
            registry_id="duplicate-identity",
            registry_version=1,
        )
    with pytest.raises(ProductPlanningCoordinatorError, match="registrations"):
        ProductPlanningCoordinatorRegistry(
            (object(),),
            registry_id="invalid-entry",
            registry_version=1,
        )
    with pytest.raises(ProductPlanningCoordinatorError, match="version"):
        ProductPlanningCoordinatorRegistry(
            (),
            registry_id="invalid-version",
            registry_version=True,
        )
    with pytest.raises(ProductPlanningCoordinatorError, match="does not match"):
        ProductPlanningCoordinatorRegistry(
            (replace(one, coordinator_version="2.0.0"),),
            registry_id="tampered",
            registry_version=1,
        )


def test_registration_contract_rejects_inconsistent_or_ambiguous_inputs() -> None:
    trigger = _binding()
    other = _binding("DOMAIN.OTHER.READ", registration_hash=HASH_B)
    valid = _registration()
    assert valid.required_operations == (
        "DOMAIN.OBJECT.READ",
        "DOMAIN.OBJECT.WRITE",
    )
    assert valid.projection()["registration_hash"] == valid.registration_hash

    common = {
        "coordinator_id": "COORDINATOR.TEST",
        "coordinator_version": "1.0.0",
        "activation_status": "ACTIVE",
        "implementation_ref": "example.module:Coordinator",
        "trigger_capability": trigger,
        "required_capabilities": (trigger,),
        "preparation_adapter_source_identity": "adapter:test:v1",
        "materializer_source_identity": "materializer:test:v1",
        "initial_state": "PENDING",
        "waiting_states": ("WAITING_APPROVAL",),
        "ready_state": "READY",
        "terminal_states": ("FAILED",),
        "required_operations": ("DOMAIN.OBJECT.READ",),
    }
    with pytest.raises(ProductPlanningCoordinatorError, match="activation"):
        build_product_planning_coordinator_registration(
            **{**common, "activation_status": "ENABLED"}
        )
    with pytest.raises(ProductPlanningCoordinatorError, match="trigger"):
        build_product_planning_coordinator_registration(
            **{**common, "trigger_capability": object()}
        )
    with pytest.raises(ProductPlanningCoordinatorError, match="required capabilities"):
        build_product_planning_coordinator_registration(
            **{**common, "required_capabilities": ()}
        )
    with pytest.raises(ProductPlanningCoordinatorError, match="required capabilities"):
        build_product_planning_coordinator_registration(
            **{**common, "required_capabilities": (object(),)}
        )
    with pytest.raises(ProductPlanningCoordinatorError, match="inconsistent"):
        build_product_planning_coordinator_registration(
            **{**common, "required_capabilities": (other,)}
        )
    with pytest.raises(ProductPlanningCoordinatorError, match="distinct"):
        build_product_planning_coordinator_registration(
            **{**common, "ready_state": "PENDING"}
        )
    with pytest.raises(ProductPlanningCoordinatorError, match="uppercase"):
        build_product_planning_coordinator_registration(
            **{**common, "initial_state": "pending"}
        )
    with pytest.raises(ProductPlanningCoordinatorError, match="waiting_states"):
        build_product_planning_coordinator_registration(
            **{**common, "waiting_states": ()}
        )
    with pytest.raises(ProductPlanningCoordinatorError, match="waiting_states"):
        build_product_planning_coordinator_registration(
            **{**common, "waiting_states": ("WAITING", "WAITING")}
        )
    with pytest.raises(ProductPlanningCoordinatorError, match="operations"):
        build_product_planning_coordinator_registration(
            **{**common, "required_operations": ()}
        )
    with pytest.raises(ProductPlanningCoordinatorError, match="coordinator_id"):
        build_product_planning_coordinator_registration(
            **{**common, "coordinator_id": " "}
        )
    with pytest.raises(ProductPlanningCoordinatorError, match="requires a version"):
        ProductPlanningCoordinatorRegistry(
            (valid,),
            registry_id="invalid-version",
            registry_version=0,
        )


def test_capability_binding_and_registry_admission_detect_product_drift() -> None:
    binding = capability_binding(
        SimpleNamespace(
            capability_id="DOMAIN.OBJECT.ACTION",
            capability_version="1.0.0",
            registration_hash=HASH_A,
        )
    )
    assert binding == _binding()
    with pytest.raises(ProductPlanningCoordinatorError, match="invalid"):
        capability_binding(SimpleNamespace(capability_id="MISSING"))

    registration = _registration()
    registry = ProductPlanningCoordinatorRegistry(
        (registration,),
        registry_id="product-coordinators",
        registry_version=1,
    )
    matching_product_registry = SimpleNamespace(
        resolve=lambda capability_id, required: SimpleNamespace(
            capability_id=capability_id,
            capability_version="1.0.0",
            registration_hash=HASH_A,
        )
    )
    registry.require_product_capabilities(matching_product_registry)

    drifted_product_registry = SimpleNamespace(
        resolve=lambda capability_id, required: SimpleNamespace(
            capability_id=capability_id,
            capability_version="2.0.0",
            registration_hash=HASH_B,
        )
    )
    with pytest.raises(ProductPlanningCoordinatorError, match="differs"):
        registry.require_product_capabilities(drifted_product_registry)
    unavailable_registry = SimpleNamespace(
        resolve=lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyError("missing"))
    )
    with pytest.raises(ProductPlanningCoordinatorError, match="unavailable"):
        registry.require_product_capabilities(unavailable_registry)


def test_m1_registration_rejects_capability_and_preparation_drift() -> None:
    capabilities = _product_capabilities()
    d04 = capabilities.resolve("FINANCE.VOUCHER.APPROVE_AND_POST", required=True)
    d12 = capabilities.resolve("PROJECT.WORK_CODE_SET.GET", required=True)
    assert d04 is not None and d12 is not None
    drifted_d04 = replace(
        d04,
        capability={**d04.capability, "operation_semantics": "READ"},
    )
    drifted_registry = ProductCapabilityRegistry(
        (drifted_d04, d12),
        registry_id="drifted",
        registry_version=1,
    )
    preparation = load_m1_transaction_preparation_registration()

    with pytest.raises(ProductPlanningCoordinatorError, match="active READ/WRITE"):
        build_m1_product_planning_coordinator_registration(
            product_capabilities=drifted_registry,
            preparation_registration=preparation,
        )
    with pytest.raises(ProductPlanningCoordinatorError, match="operations"):
        build_m1_product_planning_coordinator_registration(
            product_capabilities=capabilities,
            preparation_registration=replace(preparation, operations=()),
        )


def test_source_backed_storage_fit_audit_stops_before_semantic_overload() -> None:
    result = audit.audit_storage_fit(ROOT)

    assert result["audit_status"] == "PASS", result
    assert result["storage_fit"] == "NOT_FIT"
    assert result["entry_decision"] == (
        "STOP_FOR_CONTROLLED_PERSISTENCE_DECISION"
    )
    assert result["coordinator_activation"] == "CONTRACT_ONLY"
    assert result["product_value_residue"] == []
    assert all(result["checks"].values())
    assert result["durable_storage_fit"]["wait_registration"]["fit"] is False
    assert result["durable_storage_fit"]["external_event_inbox"]["fit"] is False
    assert result["durable_storage_fit"]["step_result"]["fit"] is False
    assert result["durable_storage_fit"]["runtime_job_payload"]["fit"] is False
    assert result["required_follow_up"]["slice"] == (
        "CP-M1-E2E-FX-01B.6B.1A"
    )
    assert (
        result["required_follow_up"]["migration_authorized_by_current_slice"]
        is False
    )
    assert result["remote_provider_required"] is False
    assert result["database_contacted"] is False
    assert result["issues"] == []


def test_storage_fit_audit_detects_schema_drift_and_fixture_residue(
    tmp_path: Path,
) -> None:
    _copy_audit_sources(tmp_path)
    wait_types = tmp_path / audit.WAIT_TYPES
    wait_types.write_text(
        wait_types.read_text(encoding="utf-8").replace(
            "'WORK_RESULT', 'NSL_APPROVAL'",
            "'WORK_RESULT', 'NSL_APPROVAL', 'BUSINESS_FORMAL'",
        ),
        encoding="utf-8",
    )
    m1_registration = tmp_path / audit.M1_REGISTRATION
    m1_registration.write_text(
        m1_registration.read_text(encoding="utf-8")
        + '\nFIXED_TENANT = "VO00"\n',
        encoding="utf-8",
    )

    result = audit.audit_storage_fit(tmp_path)

    assert result["audit_status"] == "FAIL"
    assert result["checks"]["wait_types_are_work_result_or_nsl_only"] is False
    assert result["checks"]["generic_contract_has_no_fixture_business_values"] is False
    assert result["product_value_residue"] == ["vo00"]
    assert set(result["issues"]) >= {
        "product coordinator contract contains fixture business values",
        (
            "source-backed storage invariant changed: "
            "wait_types_are_work_result_or_nsl_only"
        ),
    }


def test_storage_fit_audit_reports_missing_source(tmp_path: Path) -> None:
    result = audit.audit_storage_fit(tmp_path)

    assert result["audit_status"] == "FAIL"
    assert result["storage_fit"] == "NOT_FIT"
    assert result["issues"]
    assert any(
        item.startswith("required source is unavailable:")
        for item in result["issues"]
    )


def _copy_audit_sources(target: Path) -> None:
    for relative in (
        audit.COORDINATOR_CONTRACT,
        audit.M1_REGISTRATION,
        audit.BACKGROUND_PLANNING,
        audit.M1_MATERIALIZER,
        audit.WAIT_FOUNDATION,
        audit.WAIT_TYPES,
        audit.WAIT_NSL_BINDING,
        audit.EVENT_FOUNDATION,
        audit.EVENT_TYPES,
        audit.AGENT_PLAN,
        audit.EXECUTABLE_PLAN,
        audit.STEP_RESULT,
        audit.RUNTIME_JOB,
    ):
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            (ROOT / relative).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
