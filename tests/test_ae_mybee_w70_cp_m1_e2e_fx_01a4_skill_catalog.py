from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import httpx
import nex_ae_api.mybee_m1_skill_runtime as runtime_module
import pytest
from mybee_ax.integrations import (
    M1_D04_CAPABILITY_ID,
    M1_D12_CAPABILITY_ID,
    load_m1_signed_skill_release,
)
from nex_ae_api.mybee_m1_skill_runtime import (
    build_mybee_m1_operation_adapter_registry,
    build_mybee_m1_runtime_admission,
    build_mybee_m1_verified_skill_catalog,
)
from nex_ae_api.nsl_eos_project_work_code_read import (
    EosProjectWorkCodeReadError,
    HttpEosProjectWorkCodeReadAdapter,
)
from nex_ae_api.product_capabilities import (
    ProductCapabilityRegistry,
    load_product_capability_registry,
)
from nex_ae_api.product_skill_catalog import (
    ProductOperationAdapterContext,
    ProductOperationAdapterRegistration,
    ProductOperationAdapterRegistry,
    ProductOperationAdapterSet,
    ProductSkillCatalogError,
    VerifiedProductSkillCatalog,
)

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = (
    ROOT / "deployment/environments/ae-product-capability-registry.mybee-m1.v1.json"
)
ADMISSION_LOCK = ROOT / "deployment/locks/ae-mybee-m1-runtime-admission.v1.json"
TENANT = "VO00"
PROJECT_ID = "11111111-1111-4111-8111-111111111114"
HASH = "sha256:" + "a" * 64


def _environment() -> dict[str, str]:
    return {
        "NEX_AE_PRODUCT_CAPABILITY_REGISTRY_PATH": str(REGISTRY),
        "NEX_EOS_BASE_URL": "https://eos.example",
        "NEX_AE_TO_EOS_SERVICE_TOKEN": "service-token",
    }


def test_m1_verified_catalog_selects_exact_signed_d12_and_d04_skills() -> None:
    catalog = build_mybee_m1_verified_skill_catalog(_environment())

    assert [item.capability.capability_id for item in catalog.selections] == sorted(
        (M1_D04_CAPABILITY_ID, M1_D12_CAPABILITY_ID)
    )
    d04 = catalog.select(M1_D04_CAPABILITY_ID)
    d12 = catalog.select(M1_D12_CAPABILITY_ID)
    assert d04.release_skill.skill_id == "MYBEE.D04.JOURNAL_POSTING"
    assert d12.release_skill.skill_id == "MYBEE.D12.PROJECT_WORK_CODE_CONTEXT"
    assert d04.verified_skill.skill.semantic_hash == d04.release_skill.semantic_hash
    assert d12.verified_skill.skill.semantic_hash == d12.release_skill.semantic_hash
    assert d04.operation_adapter.operation_ids == (
        "FINANCE.VOUCHER.APPROVE_AND_POST",
        "FINANCE.JOURNAL.RECONCILE",
    )
    assert d12.operation_adapter.operation_ids == ("PROJECT.WORK_CODE_SET.GET",)
    assert catalog.catalog_hash.startswith("sha256:")


def test_m1_runtime_admission_lock_matches_verified_source_projection() -> None:
    observed = json.loads(ADMISSION_LOCK.read_text(encoding="utf-8"))

    assert observed == build_mybee_m1_runtime_admission(_environment())


def test_m1_operation_registry_is_order_independent_and_immutable() -> None:
    first = build_mybee_m1_operation_adapter_registry()
    second = ProductOperationAdapterRegistry(tuple(reversed(first.registrations)))
    assert first.to_projection() == second.to_projection()
    assert first.registry_hash == second.registry_hash


def test_verified_catalog_fails_closed_for_unknown_capability() -> None:
    catalog = build_mybee_m1_verified_skill_catalog(_environment())
    with pytest.raises(ProductSkillCatalogError) as captured:
        catalog.select("UNKNOWN.CAPABILITY.GET")
    assert captured.value.error_code == "PRODUCT_SKILL_CAPABILITY_NOT_ADMITTED"


def test_verified_catalog_rejects_missing_verified_skill_identity() -> None:
    release = replace(load_m1_signed_skill_release(), verified_skills=())
    with pytest.raises(ProductSkillCatalogError) as captured:
        VerifiedProductSkillCatalog(
            release=release,
            capability_registry=load_product_capability_registry(_environment()),
            operation_registry=build_mybee_m1_operation_adapter_registry(),
        )
    assert captured.value.error_code == "PRODUCT_VERIFIED_SKILL_REQUIRED"


def test_verified_catalog_rejects_capability_registration_drift() -> None:
    registry = load_product_capability_registry(_environment())
    registrations = list(registry.registrations)
    index = next(
        index
        for index, item in enumerate(registrations)
        if item.capability_id == M1_D12_CAPABILITY_ID
    )
    drifted = dict(registrations[index].capability)
    drifted_binding = dict(drifted["local_skill_binding"])
    drifted_binding["trust_policy_id"] = "policy://drifted"
    drifted["local_skill_binding"] = drifted_binding
    registrations[index] = replace(registrations[index], capability=drifted)

    with pytest.raises(ProductSkillCatalogError) as captured:
        VerifiedProductSkillCatalog(
            release=load_m1_signed_skill_release(),
            capability_registry=ProductCapabilityRegistry(registrations),
            operation_registry=build_mybee_m1_operation_adapter_registry(),
        )
    assert captured.value.error_code == "PRODUCT_SKILL_REGISTRATION_DRIFT"


def test_operation_registry_rejects_duplicate_capability_and_operation() -> None:
    base = build_mybee_m1_operation_adapter_registry().registrations[0]
    duplicate_capability = replace(base, adapter_id="duplicate")
    with pytest.raises(ProductSkillCatalogError) as captured:
        ProductOperationAdapterRegistry((base, duplicate_capability))
    assert captured.value.error_code == "PRODUCT_OPERATION_CAPABILITY_DUPLICATE"

    duplicate_operation = replace(
        base,
        capability_id="OTHER.CAPABILITY.GET",
        adapter_id="other",
    )
    with pytest.raises(ProductSkillCatalogError) as captured:
        ProductOperationAdapterRegistry((base, duplicate_operation))
    assert captured.value.error_code == "PRODUCT_OPERATION_ID_DUPLICATE"


@pytest.mark.parametrize(
    "registration",
    (
        ProductOperationAdapterRegistration(
            capability_id="A.B.GET",
            operation_semantics="READ",
            backend_profile="PROFILE",
            adapter_id="adapter",
            operation_ids=("A.B.GET",),
            factory=lambda _context: ProductOperationAdapterSet(),
        ),
    ),
)
def test_catalog_requires_an_adapter_for_every_signed_skill(registration) -> None:
    with pytest.raises(ProductSkillCatalogError) as captured:
        VerifiedProductSkillCatalog(
            release=load_m1_signed_skill_release(),
            capability_registry=load_product_capability_registry(_environment()),
            operation_registry=ProductOperationAdapterRegistry((registration,)),
        )
    assert captured.value.error_code == "PRODUCT_OPERATION_ADAPTER_REQUIRED"


def test_d12_operation_adapter_reads_authoritative_eos_projection() -> None:
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["request"] = request
        return httpx.Response(
            200,
            json={
                "tenant_id": TENANT,
                "project_id": PROJECT_ID,
                "revision": 3,
                "state": "APPROVED",
                "work_set_hash": HASH,
                "code_ids": ["FL0012005"],
            },
        )

    adapter = HttpEosProjectWorkCodeReadAdapter(
        base_url="https://eos.example",
        service_token="service-token",
        transport=httpx.MockTransport(handler),
    )
    result = adapter(
        {
            "tenant_id": TENANT,
            "requester_subject_id": "employee-100",
            "project_id": PROJECT_ID,
            "effective_on": "2026-11-15",
        }
    )

    assert type(result) is dict
    assert dict(result) == {
        "project_id": PROJECT_ID,
        "revision": 3,
        "state": "APPROVED",
        "work_set_hash": HASH,
    }
    request = observed["request"]
    assert request.headers["x-nex-tenant-id"] == TENANT
    assert request.headers["x-nex-subject-id"] == "employee-100"
    assert request.url.params["effective_on"] == "2026-11-15"


@pytest.mark.parametrize(
    ("arguments", "error_code"),
    (
        ({}, "ae.nsl_eos_project_work_code.arguments_invalid"),
        (
            {
                "tenant_id": TENANT,
                "requester_subject_id": "employee-100",
                "project_id": "bad",
                "effective_on": None,
            },
            "ae.nsl_eos_project_work_code.arguments_invalid",
        ),
    ),
)
def test_d12_operation_adapter_rejects_invalid_arguments(arguments, error_code) -> None:
    adapter = HttpEosProjectWorkCodeReadAdapter(
        base_url="https://eos.example", service_token="service-token"
    )
    with pytest.raises(EosProjectWorkCodeReadError) as captured:
        adapter(arguments)
    assert captured.value.error_code == error_code


@pytest.mark.parametrize(
    ("status", "payload", "error_code"),
    (
        (503, {"error_code": "UNAVAILABLE"}, "ae.nsl_eos_project_work_code.rejected"),
        (
            200,
            {"project_id": PROJECT_ID},
            "ae.nsl_eos_project_work_code.response_invalid",
        ),
    ),
)
def test_d12_operation_adapter_rejects_untrusted_response(
    status, payload, error_code
) -> None:
    adapter = HttpEosProjectWorkCodeReadAdapter(
        base_url="https://eos.example",
        service_token="service-token",
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(status, json=payload)
        ),
    )
    with pytest.raises(EosProjectWorkCodeReadError) as captured:
        adapter(
            {
                "tenant_id": TENANT,
                "requester_subject_id": "employee-100",
                "project_id": PROJECT_ID,
                "effective_on": None,
            }
        )
    assert captured.value.error_code == error_code


def test_product_adapter_factories_build_registered_d12_and_d04_sets(
    monkeypatch,
) -> None:
    registry = build_mybee_m1_operation_adapter_registry()
    d12 = registry.resolve(M1_D12_CAPABILITY_ID, required=True)
    d12_set = d12.factory(ProductOperationAdapterContext(environ=_environment()))
    assert set(d12_set.tool_handlers) == {M1_D12_CAPABILITY_ID}

    monkeypatch.setattr(
        runtime_module,
        "build_default_eos_journal_execution_port",
        lambda **_values: "write",
    )
    monkeypatch.setattr(
        runtime_module,
        "build_default_eos_journal_verification_adapter",
        lambda **_values: "verify",
    )
    monkeypatch.setattr(
        runtime_module,
        "build_default_eos_journal_reconciliation_adapter",
        lambda **_values: "reconcile",
    )
    d04 = registry.resolve(M1_D04_CAPABILITY_ID, required=True)
    d04_set = d04.factory(
        ProductOperationAdapterContext(
            environ=_environment(),
            public_api=object(),
            result_type=object(),
            result_classification=SimpleNamespace(value="CONFIDENTIAL"),
        )
    )
    assert (d04_set.write_port, d04_set.verification_port) == ("write", "verify")
    assert d04_set.reconciliation_port == "reconcile"


def test_generic_catalog_has_no_mybee_capability_branches() -> None:
    source = (
        ROOT / "services/nex-ae-api/nex_ae_api/product_skill_catalog.py"
    ).read_text(encoding="utf-8")
    assert M1_D04_CAPABILITY_ID not in source
    assert M1_D12_CAPABILITY_ID not in source
