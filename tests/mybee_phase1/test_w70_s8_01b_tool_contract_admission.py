from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

import jsonschema
import pytest
import yaml
from mybee_ax.integrations.nex_tool_contracts import (
    DEFAULT_EOS_OPENAPI_PATH,
    DEFAULT_TOOL_CONTRACT_ADMISSION_PATH,
    TOOL_CONTRACT_ADMISSION_STATUS,
    ToolContractAdmissionError,
    calculate_tool_contract_admission_digest,
    load_tool_contract_catalog,
)
from mybee_ax.integrations.nex_tool_inventory import load_tool_inventory

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "contracts/schemas/common/tool_contract_admission.v1.schema.json"
NEGATIVE_ROOT = ROOT / "contracts/tests/negative/common"


def _admission_json() -> dict:
    return json.loads(DEFAULT_TOOL_CONTRACT_ADMISSION_PATH.read_text(encoding="utf-8"))


def _rehash(value: dict) -> dict:
    value["release_attestation"]["content_digest"] = (
        calculate_tool_contract_admission_digest(value)
    )
    return value


def _write_admission(tmp_path: Path, value: object) -> Path:
    path = tmp_path / "tool-contract-admission.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _error_for(
    tmp_path: Path,
    value: object,
    *,
    openapi_path: Path = DEFAULT_EOS_OPENAPI_PATH,
    inventory=None,
) -> ToolContractAdmissionError:
    with pytest.raises(ToolContractAdmissionError) as raised:
        load_tool_contract_catalog(
            _write_admission(tmp_path, value),
            openapi_path=openapi_path,
            inventory=inventory,
        )
    return raised.value


def _openapi_json() -> dict:
    return yaml.safe_load(DEFAULT_EOS_OPENAPI_PATH.read_text(encoding="utf-8"))


def _operation(openapi: dict, operation_id: str) -> dict:
    for path_item in openapi["paths"].values():
        for method, operation in path_item.items():
            if (
                method in {"get", "post", "put", "patch", "delete"}
                and operation.get("operationId") == operation_id
            ):
                return operation
    raise AssertionError(f"operation not found: {operation_id}")


def _write_openapi(tmp_path: Path, value: object) -> Path:
    path = tmp_path / "nex-eos.openapi.yaml"
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
    return path


def _bind_openapi(value: dict, path: Path) -> dict:
    value["openapi"]["sha256"] = "sha256:" + hashlib.sha256(
        path.read_bytes()
    ).hexdigest()
    return _rehash(value)


def test_w70_tool_contract_admission_matches_schema_sources_and_inventory() -> None:
    raw = _admission_json()
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    jsonschema.Draft202012Validator(schema).validate(raw)
    catalog = load_tool_contract_catalog()

    assert catalog.admission_id == "mybee.phase1.w70.eos-tool-contracts"
    assert catalog.admission_version == "1.0.0"
    assert catalog.revision == 1
    assert catalog.status == TOOL_CONTRACT_ADMISSION_STATUS
    assert catalog.content_digest == calculate_tool_contract_admission_digest(raw)
    assert catalog.content_digest == raw["release_attestation"]["content_digest"]
    assert len(catalog.contracts) == 18
    assert sum(item.fully_typed for item in catalog.contracts) == 11

    inventory = load_tool_inventory()
    assert catalog.inventory_digest == inventory.content_digest
    assert [item.canonical_operation_id for item in catalog.contracts] == sorted(
        item.canonical_operation_id for item in inventory.tools
    )

    with pytest.raises(ToolContractAdmissionError) as missing:
        catalog.get("FINANCE.NOT_ADMITTED.GET")
    assert missing.value.code == "TOOL_CONTRACT_NOT_ADMITTED"


def test_w70_tool_contract_admission_preserves_typed_and_status_only_boundaries() -> None:
    catalog = load_tool_contract_catalog()

    legacy = catalog.get("FINANCE.VOUCHER_DRAFT.CREATE")
    assert legacy.method == "POST"
    assert legacy.request.typing_state == "CANONICAL_JSON_SCHEMA"
    assert legacy.request.canonical_schema_ref.endswith(
        "create_voucher_draft_command.v1.schema.json"
    )
    assert [response.status for response in legacy.success_responses] == ["200", "201"]
    assert legacy.fully_typed is True

    fx_resolve = catalog.get("FINANCE.FX_RATE.RESOLVE")
    assert fx_resolve.request.required is None
    assert fx_resolve.request.typing_state == "OPENAPI_PARAMETERS_ONLY"
    assert fx_resolve.request.required_parameters == (
        "header:X-NeX-Subject-Id",
        "header:X-NeX-Tenant-Id",
        "query:base_currency",
        "query:company_id",
        "query:desired_rate_date",
        "query:purpose",
        "query:quote_currency",
    )
    assert fx_resolve.request.optional_parameters == ("query:as_of",)
    assert fx_resolve.success_responses[0].typing_state == "OPENAPI_STATUS_ONLY"
    assert fx_resolve.fully_typed is False

    project = catalog.get("PROJECT.WORK_CODE_SET.APPROVE")
    assert project.request.typing_state == "OPENAPI_INLINE_SCHEMA"
    assert project.request.canonical_schema_ref == (
        "contracts/openapi/nex-eos.openapi.yaml#/components/schemas/"
        "ProjectWorkCodeSetApprovalCommand"
    )


def test_w70_external_contract_references_are_eos_owned_and_exist() -> None:
    catalog = load_tool_contract_catalog()
    references = {
        reference
        for contract in catalog.contracts
        for reference in (
            contract.request.canonical_schema_ref,
            *(item.canonical_schema_ref for item in contract.success_responses),
        )
        if reference is not None
    }

    for reference in references:
        if "#" in reference:
            assert reference.startswith("contracts/openapi/nex-eos.openapi.yaml#")
        else:
            assert reference.startswith("contracts/schemas/service/nex_eos/")
            assert (ROOT / reference).is_file()


@pytest.mark.parametrize(
    "fixture_name",
    (
        "tool_contract_admission.lowercase_method.json",
        "tool_contract_admission.non_success_status.json",
        "tool_contract_admission.skill_local_schema.json",
    ),
)
def test_w70_tool_contract_structural_negative_examples_are_rejected(
    fixture_name: str,
) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    fixture = json.loads((NEGATIVE_ROOT / fixture_name).read_text(encoding="utf-8"))

    assert list(jsonschema.Draft202012Validator(schema).iter_errors(fixture))


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    (
        ("root_fields", "ADMISSION_FIELDS_INVALID"),
        ("header", "ADMISSION_HEADER_INVALID"),
        ("revision_bool", "ADMISSION_HEADER_INVALID"),
        ("inventory_fields", "SOURCE_REF_FIELDS_INVALID"),
        ("inventory_path", "SOURCE_REF_PATH_INVALID"),
        ("inventory_digest", "SOURCE_REF_DIGEST_MISMATCH"),
        ("openapi_fields", "SOURCE_REF_FIELDS_INVALID"),
        ("openapi_path", "SOURCE_REF_PATH_INVALID"),
        ("openapi_digest", "SOURCE_REF_DIGEST_MISMATCH"),
        ("contracts_empty", "CONTRACTS_INVALID"),
        ("contract_fields", "CONTRACT_FIELDS_INVALID"),
        ("identity", "CONTRACT_IDENTITY_INVALID"),
        ("route", "OPENAPI_ROUTE_MISMATCH"),
        ("openapi_ref", "OPENAPI_REF_MISMATCH"),
        ("parameters", "OPENAPI_PARAMETERS_MISMATCH"),
        ("request_missing", "REQUEST_BODY_MISSING"),
        ("request_fields", "REQUEST_BODY_INVALID"),
        ("request_mismatch", "REQUEST_BODY_MISMATCH"),
        ("responses_empty", "SUCCESS_RESPONSES_INVALID"),
        ("responses_mismatch", "SUCCESS_RESPONSES_MISMATCH"),
        ("order", "CONTRACT_ORDER_OR_DUPLICATE_INVALID"),
        ("coverage", "CONTRACT_INVENTORY_COVERAGE_INVALID"),
        ("attestation_fields", "ATTESTATION_FIELDS_INVALID"),
        ("attestation_digest", "ADMISSION_DIGEST_MISMATCH"),
        ("blank_text", "TEXT_REQUIRED"),
    ),
)
def test_w70_tool_contract_loader_fails_closed_for_admission_drift(
    tmp_path: Path, mutation: str, expected_code: str
) -> None:
    value = copy.deepcopy(_admission_json())
    request_index = next(
        index for index, item in enumerate(value["contracts"]) if item["request_body"]
    )
    if mutation == "root_fields":
        value["unexpected"] = True
    elif mutation == "header":
        value["status"] = "ACTIVE"
    elif mutation == "revision_bool":
        value["revision"] = True
    elif mutation == "inventory_fields":
        value["inventory"]["unexpected"] = True
    elif mutation == "inventory_path":
        value["inventory"]["path"] = "other.json"
    elif mutation == "inventory_digest":
        value["inventory"]["sha256"] = "sha256:" + "0" * 64
    elif mutation == "openapi_fields":
        value["openapi"]["unexpected"] = True
    elif mutation == "openapi_path":
        value["openapi"]["path"] = "other.yaml"
    elif mutation == "openapi_digest":
        value["openapi"]["sha256"] = "sha256:" + "0" * 64
    elif mutation == "contracts_empty":
        value["contracts"] = []
    elif mutation == "contract_fields":
        value["contracts"][0]["unexpected"] = True
    elif mutation == "identity":
        value["contracts"][0]["provider_operation_id"] = "OTHER"
    elif mutation == "route":
        value["contracts"][0]["method"] = "GET"
    elif mutation == "openapi_ref":
        value["contracts"][0]["openapi_operation_ref"] = "#/other"
    elif mutation == "parameters":
        value["contracts"][0]["required_parameters"] = ["query:other"]
    elif mutation == "request_missing":
        value["contracts"][request_index]["request_body"] = None
    elif mutation == "request_fields":
        value["contracts"][request_index]["request_body"]["unexpected"] = True
    elif mutation == "request_mismatch":
        value["contracts"][request_index]["request_body"]["required"] = False
    elif mutation == "responses_empty":
        value["contracts"][0]["success_responses"] = []
    elif mutation == "responses_mismatch":
        value["contracts"][0]["success_responses"][0]["status"] = "299"
    elif mutation == "order":
        value["contracts"].reverse()
    elif mutation == "coverage":
        value["contracts"].pop()
    elif mutation == "attestation_fields":
        value["release_attestation"]["unexpected"] = True
    elif mutation == "attestation_digest":
        value["release_attestation"]["content_digest"] = "sha256:" + "0" * 64
        error = _error_for(tmp_path, value)
        assert error.code == expected_code
        return
    elif mutation == "blank_text":
        value["contracts"][0]["method"] = ""
    error = _error_for(tmp_path, _rehash(value))
    assert error.code == expected_code


def test_w70_tool_contract_loader_blocks_active_status_only_contract(
    tmp_path: Path,
) -> None:
    inventory = load_tool_inventory()
    tools = tuple(
        replace(item, activation_state="ACTIVE")
        if item.canonical_operation_id == "FINANCE.FX_RATE.RESOLVE"
        else item
        for item in inventory.tools
    )
    activated = replace(
        inventory,
        tools=tools,
        _by_operation=MappingProxyType(
            {item.canonical_operation_id: item for item in tools}
        ),
    )

    error = _error_for(tmp_path, _admission_json(), inventory=activated)
    assert error.code == "ACTIVE_CONTRACT_UNTYPED"


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    (
        ("duplicate_operation", "OPENAPI_OPERATION_DUPLICATE"),
        ("missing_operation", "OPENAPI_OPERATION_MISSING"),
        ("service_scope", "OPENAPI_SERVICE_SCOPE_MISMATCH"),
        ("oa_action", "OPENAPI_OA_ACTION_MISMATCH"),
        ("side_effect", "OPENAPI_SIDE_EFFECT_METADATA_MISMATCH"),
        ("parameter_schema", "OPENAPI_PARAMETER_SCHEMA_MISSING"),
        ("request_component", "OPENAPI_COMPONENT_REF_REQUIRED"),
        ("canonical_schema", "CANONICAL_SCHEMA_REF_INVALID"),
        ("success_response", "OPENAPI_SUCCESS_RESPONSE_MISSING"),
    ),
)
def test_w70_tool_contract_loader_fails_closed_for_openapi_drift(
    tmp_path: Path, mutation: str, expected_code: str
) -> None:
    openapi = _openapi_json()
    admission = copy.deepcopy(_admission_json())
    first = admission["contracts"][0]
    target = _operation(openapi, first["provider_operation_id"])
    if mutation == "duplicate_operation":
        operation_ids = [
            operation.get("operationId")
            for path_item in openapi["paths"].values()
            for method, operation in path_item.items()
            if method in {"get", "post", "put", "patch", "delete"}
            and operation.get("operationId")
        ]
        target["operationId"] = operation_ids[1]
    elif mutation == "missing_operation":
        target["operationId"] = "REMOVED.FROM.ADMISSION"
    elif mutation == "service_scope":
        target["x-nex-required-scopes"] = ["other:scope"]
    elif mutation == "oa_action":
        target["x-nex-business-scope"] = "other:action"
    elif mutation == "side_effect":
        target["x-nex-side-effect-free"] = True
    elif mutation == "parameter_schema":
        target["parameters"][0].pop("schema")
    elif mutation == "request_component":
        target["requestBody"]["content"]["application/json"]["schema"] = {
            "type": "object"
        }
    elif mutation == "canonical_schema":
        request_ref = target["requestBody"]["content"]["application/json"]["schema"]
        component = request_ref["$ref"].rsplit("/", 1)[-1]
        openapi["components"]["schemas"][component][
            "x-nex-canonical-json-schema"
        ] = "schemas/service/nex_ae_api/not-owned.json"
    elif mutation == "success_response":
        target["responses"] = {"400": {"description": "failure"}}
    openapi_path = _write_openapi(tmp_path, openapi)
    error = _error_for(
        tmp_path,
        _bind_openapi(admission, openapi_path),
        openapi_path=openapi_path,
    )
    assert error.code == expected_code


def test_w70_tool_contract_loader_rejects_io_yaml_and_root_failures(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(ToolContractAdmissionError) as unreadable:
        load_tool_contract_catalog(missing)
    assert unreadable.value.code == "ADMISSION_UNREADABLE"

    malformed = tmp_path / "malformed.json"
    malformed.write_text("{", encoding="utf-8")
    with pytest.raises(ToolContractAdmissionError) as invalid_json:
        load_tool_contract_catalog(malformed)
    assert invalid_json.value.code == "ADMISSION_INVALID_JSON"
    assert _error_for(tmp_path, []).code == "OBJECT_REQUIRED"

    bad_openapi = tmp_path / "bad-openapi.yaml"
    bad_openapi.write_text("paths: [", encoding="utf-8")
    admission = copy.deepcopy(_admission_json())
    with pytest.raises(ToolContractAdmissionError) as invalid_yaml:
        load_tool_contract_catalog(
            _write_admission(tmp_path, _bind_openapi(admission, bad_openapi)),
            openapi_path=bad_openapi,
        )
    assert invalid_yaml.value.code == "OPENAPI_INVALID_YAML"

    missing_openapi = tmp_path / "missing-openapi.yaml"
    with pytest.raises(ToolContractAdmissionError) as openapi_unreadable:
        load_tool_contract_catalog(
            _write_admission(tmp_path, _admission_json()),
            openapi_path=missing_openapi,
        )
    assert openapi_unreadable.value.code == "OPENAPI_UNREADABLE"
