from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from nex_eos import (
    PROJECT_CREATE_OPERATION,
    create_eos_app,
    project_operation_payload_hash,
)
from nex_runtime import (
    CANONICAL_OPERATION_PATTERN,
    DEFAULT_OPERATION_REGISTRY,
    P8_CANONICAL_OPERATIONS,
    P8_OPERATION_ALIASES,
    CanonicalOperationRegistry,
    OperationNameError,
)

ROOT = Path(__file__).resolve().parents[1]


def test_default_registry_resolves_canonical_and_legacy_names() -> None:
    canonical = DEFAULT_OPERATION_REGISTRY.resolve("PROJECT.PROJECT.GET")
    alias = DEFAULT_OPERATION_REGISTRY.resolve("PROJECT.GET_PROJECT")

    assert canonical.to_projection() == {
        "requested_operation": "PROJECT.PROJECT.GET",
        "canonical_operation": "PROJECT.PROJECT.GET",
        "registry_version": "p8-s109.v1",
        "alias_applied": False,
    }
    assert alias.canonical_operation == "PROJECT.PROJECT.GET"
    assert alias.alias_applied is True
    assert all(
        CANONICAL_OPERATION_PATTERN.fullmatch(item)
        for item in P8_CANONICAL_OPERATIONS
    )
    assert dict(P8_OPERATION_ALIASES)["FINANCE.CREATE_VOUCHER_DRAFT"] == (
        "FINANCE.VOUCHER_DRAFT.CREATE"
    )


@pytest.mark.parametrize("value", (None, "PROJECT.GET", "project.project.get", "UNKNOWN.X.Y"))
def test_registry_rejects_unadmitted_or_noncanonical_names(value) -> None:
    with pytest.raises(OperationNameError):
        DEFAULT_OPERATION_REGISTRY.resolve(value)


@pytest.mark.parametrize(
    "kwargs",
    (
        {"canonical_operations": []},
        {"canonical_operations": ["PROJECT.GET"]},
        {
            "canonical_operations": ["PROJECT.PROJECT.GET"],
            "aliases": {"PROJECT.PROJECT.GET": "PROJECT.PROJECT.GET"},
        },
        {
            "canonical_operations": ["PROJECT.PROJECT.GET"],
            "aliases": {"PROJECT.GET_PROJECT": "PROJECT.PROJECT.UNKNOWN"},
        },
        {"version": ""},
    ),
)
def test_registry_configuration_fails_closed(kwargs) -> None:
    with pytest.raises(OperationNameError):
        CanonicalOperationRegistry(**kwargs)


def test_alias_resolution_precedes_payload_hashing() -> None:
    payload = {
        "schema_version": "eos_project_operation.v1",
        "tenant_id": "tenant-a",
        "requester_subject_id": "employee-a",
        "project_id": "92000000-0000-4000-8000-000000000001",
    }
    canonical = project_operation_payload_hash(
        payload, "FINANCE.VOUCHER_DRAFT.CREATE"
    )
    legacy = project_operation_payload_hash(payload, "FINANCE.CREATE_VOUCHER_DRAFT")
    assert legacy == canonical

    requested_payload = {**payload, "requested_operation": "PROJECT.GET_PROJECT"}
    assert project_operation_payload_hash(
        requested_payload, PROJECT_CREATE_OPERATION
    ) == project_operation_payload_hash(payload, PROJECT_CREATE_OPERATION)


def test_eos_project_openapi_uses_canonical_operation_ids() -> None:
    app = create_eos_app(
        environ={
            "NEX_EOS_SERVICE_ID": "nex-eos",
            "NEX_PROFILE": "test",
            "NEX_VERSION": "p8-s97",
            "NEX_BUILD_SHA": "test",
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
        }
    )
    project_operations = {
        operation["operationId"]
        for path, methods in app.openapi()["paths"].items()
        if path.startswith("/internal/v1/projects")
        for operation in methods.values()
    }
    nvt_project_operations = {
        operation["operationId"]
        for path, methods in app.openapi()["paths"].items()
        if path.startswith("/internal/v1/nvt-projects")
        for operation in methods.values()
    }
    assert project_operations == {
        "PROJECT.PROJECT.CREATE",
        "PROJECT.PROJECT.GET",
        "PROJECT.PROJECT.LIST",
        "PROJECT.PROJECT.DEACTIVATE",
        "PROJECT.PROJECT.VERIFY_BATCH",
        "PROJECT.MEMBERSHIP.ADD",
        "PROJECT.MEMBERSHIP.ADD_MANY",
        "PROJECT.MEMBERSHIP.REMOVE",
        "PROJECT.MEMBERSHIP.LIST",
    }
    assert nvt_project_operations == {
        "PROJECT.NVT_PROJECT.CREATE",
        "PROJECT.NVT_PROJECT.GET",
        "PROJECT.NVT_PROJECT.LIST",
        "PROJECT.NVT_PROJECT.UPDATE",
    }
    assert all(
        CANONICAL_OPERATION_PATTERN.fullmatch(item)
        for item in project_operations | nvt_project_operations
    )


def test_alias_contract_accepts_positive_and_rejects_negative_example() -> None:
    schema = json.loads(
        (ROOT / "contracts/schemas/common/canonical_operation_alias.v1.schema.json").read_text()
    )
    positive = json.loads(
        (ROOT / "contracts/examples/common/canonical_operation_alias.project_get.json").read_text()
    )
    negative = json.loads(
        (
            ROOT
            / "contracts/tests/negative/common/canonical_operation_alias.two_segment_canonical.json"
        ).read_text()
    )
    validator = Draft202012Validator(schema)
    assert list(validator.iter_errors(positive)) == []
    assert list(validator.iter_errors(negative))
