from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from mybee_ax.orchestration import load_m1_transaction_preparation_registration
from nex_ae_api.product_capabilities import load_product_capability_registry
from nex_ae_api.product_coordinator_activation import (
    DEFAULT_ACTIVATION_PATH,
    DEFAULT_ROLLBACK_PATH,
    build_activated_m1_product_planning_composition,
    build_product_coordinator_activation_documents,
    load_product_coordinator_activation,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]


def _capabilities():
    return load_product_capability_registry(
        {
            "NEX_AE_PRODUCT_CAPABILITY_REGISTRY_PATH": str(
                ROOT
                / "deployment/environments/"
                "ae-product-capability-registry.mybee-m1.v2.json"
            )
        }
    )


def _environment(**values: str) -> dict[str, str]:
    return {
        "NEX_EOS_BASE_URL": "https://eos.example",
        "NEX_AE_TO_EOS_SERVICE_TOKEN": "eos-service-token",
        "NEX_AE_MYBEE_EOS_TIMEOUT_SECONDS": "15",
        **values,
    }


def test_activation_and_rollback_locks_match_current_source_inventory() -> None:
    expected = build_product_coordinator_activation_documents(
        product_capabilities=_capabilities(),
        repository_root=ROOT,
    )
    committed = tuple(
        json.loads(path.read_text(encoding="utf-8"))
        for path in (DEFAULT_ACTIVATION_PATH, DEFAULT_ROLLBACK_PATH)
    )

    assert committed == expected
    activation, rollback = committed
    assert activation["activation_state"] == "ACTIVE"
    assert activation["migration_inventory"]["head"] == (
        "2517_ae_product_preparation_resume"
    )
    assert activation["runtime_assignment_handlers"] == [
        "EXECUTABLE_STEP",
        "PRODUCT_COORDINATOR",
    ]
    assert rollback["rollback_state"] == "CONTRACT_ONLY"
    assert rollback["history_preservation"] == (
        "PRESERVE_CHECKPOINT_WAIT_EVENT_JOB_PLAN"
    )


def test_activation_admission_is_hash_bound_and_secret_free() -> None:
    admitted = load_product_coordinator_activation(
        product_capabilities=_capabilities(),
        environ={},
        repository_root=ROOT,
    )

    assert admitted.coordinator_registry.registrations[0].activation_status == "ACTIVE"
    assert admitted.readiness["status"] == "READY"
    assert admitted.readiness["planning_policy_mode"] == (
        "PROVIDER_ASSISTED_REQUIRED"
    )
    serialized = json.dumps(dict(admitted.readiness), sort_keys=True)
    assert "token" not in serialized.lower()
    assert "amount" not in serialized.lower()
    assert admitted.readiness["content_included"] is False
    assert admitted.readiness["secret_included"] is False


@pytest.mark.parametrize(
    ("target", "field", "value", "message"),
    (
        ("activation", "activation_state", "CONTRACT_ONLY", "activation lock"),
        ("activation", "runtime_assignment_handlers", [], "activation lock"),
        ("activation", "tenant_id", "VO00", "business data"),
        ("rollback", "rollback_state", "ACTIVE", "rollback receipt"),
    ),
)
def test_activation_admission_rejects_lock_drift(
    tmp_path: Path,
    target: str,
    field: str,
    value,
    message: str,
) -> None:
    activation = json.loads(DEFAULT_ACTIVATION_PATH.read_text(encoding="utf-8"))
    rollback = json.loads(DEFAULT_ROLLBACK_PATH.read_text(encoding="utf-8"))
    selected = activation if target == "activation" else rollback
    selected[field] = value
    activation_path = tmp_path / "activation.json"
    rollback_path = tmp_path / "rollback.json"
    activation_path.write_text(json.dumps(activation), encoding="utf-8")
    rollback_path.write_text(json.dumps(rollback), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_product_coordinator_activation(
            product_capabilities=_capabilities(),
            environ=_environment(
                NEX_AE_PRODUCT_COORDINATOR_ACTIVATION_PATH=str(activation_path),
                NEX_AE_PRODUCT_COORDINATOR_ROLLBACK_PATH=str(rollback_path),
            ),
            repository_root=ROOT,
        )


def test_activation_admission_rejects_source_migration_drift(tmp_path: Path) -> None:
    migration_root = tmp_path / "database/nex-ae-api/migrations"
    migration_root.mkdir(parents=True)
    (migration_root / "0001_drift.sql").write_text("select 1;\n", encoding="utf-8")

    with pytest.raises(ValueError, match="activation lock"):
        load_product_coordinator_activation(
            product_capabilities=_capabilities(),
            environ={},
            repository_root=tmp_path,
        )


def test_activation_document_builder_requires_migration_inventory(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="migration inventory"):
        build_product_coordinator_activation_documents(
            product_capabilities=_capabilities(),
            repository_root=tmp_path,
        )


def test_activation_loader_rejects_non_object_document(tmp_path: Path) -> None:
    invalid = tmp_path / "activation.json"
    invalid.write_text("[]\n", encoding="utf-8")
    with pytest.raises(TypeError, match="JSON object"):
        load_product_coordinator_activation(
            product_capabilities=_capabilities(),
            environ=_environment(
                NEX_AE_PRODUCT_COORDINATOR_ACTIVATION_PATH=str(invalid)
            ),
            repository_root=ROOT,
        )


def test_activated_factory_installs_exact_runtime_without_business_defaults() -> None:
    preparation = load_m1_transaction_preparation_registration()
    runtime = SimpleNamespace(
        transaction_preparation=SimpleNamespace(
            adapter=SimpleNamespace(registration=preparation)
        ),
        materialize_transaction_plan=lambda **_values: None,
    )
    sessions = sessionmaker(create_engine("sqlite+pysqlite:///:memory:"))

    composition = build_activated_m1_product_planning_composition(
        sessions=sessions,
        product_capabilities=_capabilities(),
        environ=_environment(),
        product_runtime=runtime,
    )

    registration = composition.coordinator_registry.registrations[0]
    assert registration.activation_status == "ACTIVE"
    assert composition.runtime_registry.identities == (
        (registration.coordinator_id, registration.coordinator_version),
    )
    assert composition.assignment_handler is not None
    assert composition.event_admission is not None
    assert composition.public_router is not None


def test_activated_factory_requires_product_preparation_runtime() -> None:
    sessions = sessionmaker(create_engine("sqlite+pysqlite:///:memory:"))
    with pytest.raises(ValueError, match="transaction preparation"):
        build_activated_m1_product_planning_composition(
            sessions=sessions,
            product_capabilities=_capabilities(),
            environ=_environment(),
            product_runtime=SimpleNamespace(
                materialize_transaction_plan=lambda **_values: None
            ),
        )


def test_canonical_compose_and_oci_admit_both_product_processes() -> None:
    compose = (ROOT / "deployment/compose/canonical-platform.override.yaml").read_text(
        encoding="utf-8"
    )
    image_builder = (
        ROOT / "scripts/deployment/build_canonical_platform_ae_runtime_image.py"
    ).read_text(encoding="utf-8")
    containerfile = (
        ROOT / "deployment/oci/canonical-platform-ae-runtime.Containerfile"
    ).read_text(encoding="utf-8")

    assert compose.count("NEX_AE_PRODUCT_COORDINATOR_ACTIVATION_PATH:") == 2
    assert compose.count("NEX_AE_PRODUCT_COORDINATOR_ROLLBACK_PATH:") == 2
    assert "nex_ae_api.agent_runtime_process" in compose
    assert "product-coordinator-activation.v1.json" in image_builder
    assert "product-coordinator-rollback.v1.json" in image_builder
    assert "NEX_AE_PRODUCT_COORDINATOR_ACTIVATION_PATH=" in containerfile
    assert "NEX_AE_PRODUCT_COORDINATOR_ROLLBACK_PATH=" in containerfile


def test_committed_activation_copy_is_immutable_under_test_mutation() -> None:
    original = json.loads(DEFAULT_ACTIVATION_PATH.read_text(encoding="utf-8"))
    mutated = deepcopy(original)
    mutated["coordinator_registration"]["registration_hash"] = "sha256:" + "0" * 64
    assert mutated != original
