"""Fail-closed admission of W70 Tool contracts from canonical EOS OpenAPI."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

from .nex_tool_inventory import ToolIdentity, ToolInventory, load_tool_inventory

TOOL_CONTRACT_SCHEMA_VERSION = "nex.mybee.tool-contract-admission.v1"
TOOL_CONTRACT_ADMISSION_ID = "mybee.phase1.w70.eos-tool-contracts"
TOOL_CONTRACT_ADMISSION_VERSION = "1.0.0"
TOOL_CONTRACT_ADMISSION_STATUS = "SOURCE_ADMITTED_RUNTIME_UNCHANGED"

_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_TOOL_CONTRACT_ADMISSION_PATH = (
    _ROOT
    / "contracts/admissions/nex_eos/w70_tool_contract_admission.v1.json"
)
DEFAULT_EOS_OPENAPI_PATH = _ROOT / "contracts/openapi/nex-eos.openapi.yaml"
_INVENTORY_RELATIVE_PATH = "domains/mybee/skills/tool_inventory.v1.json"
_OPENAPI_RELATIVE_PATH = "contracts/openapi/nex-eos.openapi.yaml"

_ROOT_FIELDS = frozenset(
    {
        "schema_version",
        "admission_id",
        "admission_version",
        "revision",
        "status",
        "inventory",
        "openapi",
        "contracts",
        "release_attestation",
    }
)
_CONTRACT_FIELDS = frozenset(
    {
        "canonical_operation_id",
        "provider_operation_id",
        "method",
        "path",
        "openapi_operation_ref",
        "required_parameters",
        "optional_parameters",
        "request_body",
        "success_responses",
    }
)
_REQUEST_FIELDS = frozenset(
    {"required", "component_ref", "canonical_schema_ref", "typing_state"}
)
_RESPONSE_FIELDS = frozenset(
    {"status", "component_ref", "canonical_schema_ref", "typing_state"}
)
_TYPING_STATES = frozenset(
    {
        "CANONICAL_JSON_SCHEMA",
        "OPENAPI_INLINE_SCHEMA",
        "OPENAPI_PARAMETERS_ONLY",
        "OPENAPI_STATUS_ONLY",
    }
)
_ACTIVE_STATES = frozenset({"ACTIVE", "ACTIVE_COMPATIBILITY", "SHADOW"})


class ToolContractAdmissionError(ValueError):
    """Raised when the admitted Tool contract no longer matches EOS authority."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


@dataclass(frozen=True)
class ToolRequestContract:
    required_parameters: tuple[str, ...]
    optional_parameters: tuple[str, ...]
    required: bool | None
    component_ref: str | None
    canonical_schema_ref: str | None
    typing_state: str


@dataclass(frozen=True)
class ToolSuccessContract:
    status: str
    component_ref: str | None
    canonical_schema_ref: str | None
    typing_state: str


@dataclass(frozen=True)
class ToolContractAdmission:
    canonical_operation_id: str
    provider_operation_id: str
    method: str
    path: str
    openapi_operation_ref: str
    request: ToolRequestContract
    success_responses: tuple[ToolSuccessContract, ...]

    @property
    def fully_typed(self) -> bool:
        return all(
            response.typing_state != "OPENAPI_STATUS_ONLY"
            for response in self.success_responses
        )


@dataclass(frozen=True)
class ToolContractCatalog:
    admission_id: str
    admission_version: str
    revision: int
    status: str
    inventory_digest: str
    openapi_digest: str
    content_digest: str
    contracts: tuple[ToolContractAdmission, ...]
    _by_operation: Mapping[str, ToolContractAdmission]

    def get(self, canonical_operation_id: str) -> ToolContractAdmission:
        try:
            return self._by_operation[canonical_operation_id]
        except KeyError as exc:
            raise ToolContractAdmissionError(
                "TOOL_CONTRACT_NOT_ADMITTED", str(canonical_operation_id)
            ) from exc


def calculate_tool_contract_admission_digest(
    admission: Mapping[str, Any],
) -> str:
    return semantic_sha256_hash_ref(
        {key: value for key, value in admission.items() if key != "release_attestation"}
    )


def load_tool_contract_catalog(
    path: Path = DEFAULT_TOOL_CONTRACT_ADMISSION_PATH,
    *,
    openapi_path: Path = DEFAULT_EOS_OPENAPI_PATH,
    inventory: ToolInventory | None = None,
) -> ToolContractCatalog:
    raw = _load_json(path)
    admission = _object(raw, "$")
    if set(admission) != _ROOT_FIELDS:
        raise ToolContractAdmissionError(
            "ADMISSION_FIELDS_INVALID", str(sorted(admission))
        )
    _require_header(admission)

    admitted_inventory = inventory or load_tool_inventory()
    inventory_digest = _require_source_ref(
        admission.get("inventory"),
        name="inventory",
        expected_path=_INVENTORY_RELATIVE_PATH,
        actual_digest=admitted_inventory.content_digest,
    )
    openapi_digest = _require_source_ref(
        admission.get("openapi"),
        name="openapi",
        expected_path=_OPENAPI_RELATIVE_PATH,
        actual_digest=_byte_hash_ref(openapi_path),
    )
    openapi = _load_openapi(openapi_path)
    operation_index = _operation_index(openapi)

    raw_contracts = admission.get("contracts")
    if not isinstance(raw_contracts, list) or not raw_contracts:
        raise ToolContractAdmissionError(
            "CONTRACTS_INVALID", "non-empty contracts array required"
        )
    inventory_by_operation = {
        item.canonical_operation_id: item for item in admitted_inventory.tools
    }
    contracts = tuple(
        _parse_contract(
            item,
            index=index,
            inventory_by_operation=inventory_by_operation,
            operation_index=operation_index,
            openapi=openapi,
        )
        for index, item in enumerate(raw_contracts)
    )
    operation_ids = [item.canonical_operation_id for item in contracts]
    if operation_ids != sorted(operation_ids) or len(set(operation_ids)) != len(
        operation_ids
    ):
        raise ToolContractAdmissionError(
            "CONTRACT_ORDER_OR_DUPLICATE_INVALID", str(operation_ids)
        )
    if set(operation_ids) != set(inventory_by_operation):
        raise ToolContractAdmissionError(
            "CONTRACT_INVENTORY_COVERAGE_INVALID",
            str(sorted(set(inventory_by_operation) ^ set(operation_ids))),
        )

    content_digest = _require_attestation(admission)
    return ToolContractCatalog(
        admission_id=TOOL_CONTRACT_ADMISSION_ID,
        admission_version=TOOL_CONTRACT_ADMISSION_VERSION,
        revision=1,
        status=TOOL_CONTRACT_ADMISSION_STATUS,
        inventory_digest=inventory_digest,
        openapi_digest=openapi_digest,
        content_digest=content_digest,
        contracts=contracts,
        _by_operation=MappingProxyType(
            {item.canonical_operation_id: item for item in contracts}
        ),
    )


def _require_header(admission: Mapping[str, Any]) -> None:
    expected = {
        "schema_version": TOOL_CONTRACT_SCHEMA_VERSION,
        "admission_id": TOOL_CONTRACT_ADMISSION_ID,
        "admission_version": TOOL_CONTRACT_ADMISSION_VERSION,
        "revision": 1,
        "status": TOOL_CONTRACT_ADMISSION_STATUS,
    }
    for field, value in expected.items():
        if admission.get(field) != value or (
            field == "revision" and isinstance(admission.get(field), bool)
        ):
            raise ToolContractAdmissionError(
                "ADMISSION_HEADER_INVALID", f"{field}={admission.get(field)!r}"
            )


def _require_source_ref(
    value: object,
    *,
    name: str,
    expected_path: str,
    actual_digest: str,
) -> str:
    reference = _object(value, name)
    if set(reference) != {"path", "sha256"}:
        raise ToolContractAdmissionError(
            "SOURCE_REF_FIELDS_INVALID", f"{name}={sorted(reference)}"
        )
    if reference.get("path") != expected_path:
        raise ToolContractAdmissionError(
            "SOURCE_REF_PATH_INVALID", f"{name}={reference.get('path')!r}"
        )
    if reference.get("sha256") != actual_digest:
        raise ToolContractAdmissionError(
            "SOURCE_REF_DIGEST_MISMATCH", name
        )
    return actual_digest


def _parse_contract(
    value: object,
    *,
    index: int,
    inventory_by_operation: Mapping[str, ToolIdentity],
    operation_index: Mapping[str, tuple[str, str, Mapping[str, Any]]],
    openapi: Mapping[str, Any],
) -> ToolContractAdmission:
    item = _object(value, f"contracts[{index}]")
    if set(item) != _CONTRACT_FIELDS:
        raise ToolContractAdmissionError(
            "CONTRACT_FIELDS_INVALID", str(sorted(item))
        )
    canonical = _text(item.get("canonical_operation_id"), "canonical_operation_id")
    provider = _text(item.get("provider_operation_id"), "provider_operation_id")
    identity = inventory_by_operation.get(canonical)
    if identity is None or identity.provider_operation_id != provider:
        raise ToolContractAdmissionError(
            "CONTRACT_IDENTITY_INVALID", f"{canonical}:{provider}"
        )
    try:
        actual_path, actual_method, operation = operation_index[provider]
    except KeyError as exc:
        raise ToolContractAdmissionError(
            "OPENAPI_OPERATION_MISSING", provider
        ) from exc
    method = _text(item.get("method"), "method")
    route_path = _text(item.get("path"), "path")
    if method != actual_method or route_path != actual_path:
        raise ToolContractAdmissionError(
            "OPENAPI_ROUTE_MISMATCH", f"{canonical}:{method}:{route_path}"
        )
    expected_ref = _operation_ref(actual_path, actual_method)
    if item.get("openapi_operation_ref") != expected_ref:
        raise ToolContractAdmissionError(
            "OPENAPI_REF_MISMATCH", canonical
        )
    _require_authority_metadata(identity, operation)

    required_parameters, optional_parameters = _parameters(operation)
    if item.get("required_parameters") != list(required_parameters) or item.get(
        "optional_parameters"
    ) != list(optional_parameters):
        raise ToolContractAdmissionError(
            "OPENAPI_PARAMETERS_MISMATCH", canonical
        )
    request = _request_contract(
        item.get("request_body"), operation=operation, openapi=openapi
    )
    responses = _success_contracts(
        item.get("success_responses"), operation=operation, openapi=openapi
    )
    if identity.activation_state in _ACTIVE_STATES and any(
        response.typing_state == "OPENAPI_STATUS_ONLY" for response in responses
    ):
        raise ToolContractAdmissionError(
            "ACTIVE_CONTRACT_UNTYPED", canonical
        )
    return ToolContractAdmission(
        canonical_operation_id=canonical,
        provider_operation_id=provider,
        method=method,
        path=route_path,
        openapi_operation_ref=expected_ref,
        request=ToolRequestContract(
            required_parameters=required_parameters,
            optional_parameters=optional_parameters,
            required=request.required,
            component_ref=request.component_ref,
            canonical_schema_ref=request.canonical_schema_ref,
            typing_state=request.typing_state,
        ),
        success_responses=responses,
    )


def _require_authority_metadata(
    identity: ToolIdentity, operation: Mapping[str, Any]
) -> None:
    if operation.get("x-nex-required-scopes") != [identity.service_scope]:
        raise ToolContractAdmissionError(
            "OPENAPI_SERVICE_SCOPE_MISMATCH", identity.canonical_operation_id
        )
    if (
        identity.oa_action != "NONE_SERVICE_TRUST_ONLY"
        and operation.get("x-nex-business-scope") != identity.oa_action
    ):
        raise ToolContractAdmissionError(
            "OPENAPI_OA_ACTION_MISMATCH", identity.canonical_operation_id
        )
    if identity.side_effect_free and operation.get("x-nex-side-effect-free") is not True:
        raise ToolContractAdmissionError(
            "OPENAPI_SIDE_EFFECT_METADATA_MISMATCH",
            identity.canonical_operation_id,
        )
    if not identity.side_effect_free and operation.get("x-nex-side-effect-free") is True:
        raise ToolContractAdmissionError(
            "OPENAPI_SIDE_EFFECT_METADATA_MISMATCH",
            identity.canonical_operation_id,
        )


def _request_contract(
    value: object,
    *,
    operation: Mapping[str, Any],
    openapi: Mapping[str, Any],
) -> ToolRequestContract:
    expected = _expected_request(operation, openapi)
    if value is None:
        if expected is not None:
            raise ToolContractAdmissionError(
                "REQUEST_BODY_MISSING", str(operation.get("operationId"))
            )
        return ToolRequestContract((), (), None, None, None, "OPENAPI_PARAMETERS_ONLY")
    item = _object(value, "request_body")
    if set(item) != _REQUEST_FIELDS or expected is None:
        raise ToolContractAdmissionError(
            "REQUEST_BODY_INVALID", str(operation.get("operationId"))
        )
    if dict(item) != expected:
        raise ToolContractAdmissionError(
            "REQUEST_BODY_MISMATCH", str(operation.get("operationId"))
        )
    return ToolRequestContract(
        (),
        (),
        bool(item["required"]),
        str(item["component_ref"]),
        str(item["canonical_schema_ref"]),
        str(item["typing_state"]),
    )


def _success_contracts(
    value: object,
    *,
    operation: Mapping[str, Any],
    openapi: Mapping[str, Any],
) -> tuple[ToolSuccessContract, ...]:
    if not isinstance(value, list) or not value:
        raise ToolContractAdmissionError(
            "SUCCESS_RESPONSES_INVALID", str(operation.get("operationId"))
        )
    expected = _expected_success_responses(operation, openapi)
    if value != expected:
        raise ToolContractAdmissionError(
            "SUCCESS_RESPONSES_MISMATCH", str(operation.get("operationId"))
        )
    return tuple(
        ToolSuccessContract(
            status=str(item["status"]),
            component_ref=item["component_ref"],
            canonical_schema_ref=item["canonical_schema_ref"],
            typing_state=str(item["typing_state"]),
        )
        for item in expected
    )


def _expected_request(
    operation: Mapping[str, Any], openapi: Mapping[str, Any]
) -> dict[str, Any] | None:
    request_body = operation.get("requestBody")
    if request_body is None:
        return None
    body = _object(request_body, "requestBody")
    schema = _object(
        _object(
            _object(body.get("content"), "requestBody.content").get(
                "application/json"
            ),
            "requestBody.application/json",
        ).get("schema"),
        "requestBody.schema",
    )
    component_ref, canonical_ref, typing_state = _schema_identity(schema, openapi)
    return {
        "required": body.get("required") is True,
        "component_ref": component_ref,
        "canonical_schema_ref": canonical_ref,
        "typing_state": typing_state,
    }


def _expected_success_responses(
    operation: Mapping[str, Any], openapi: Mapping[str, Any]
) -> list[dict[str, Any]]:
    responses = _object(operation.get("responses"), "responses")
    expected: list[dict[str, Any]] = []
    for status in sorted(str(key) for key in responses if str(key).startswith("2")):
        response = _object(responses[status], f"responses.{status}")
        content = response.get("content")
        if content is None:
            expected.append(
                {
                    "status": status,
                    "component_ref": None,
                    "canonical_schema_ref": None,
                    "typing_state": "OPENAPI_STATUS_ONLY",
                }
            )
            continue
        schema = _object(
            _object(
                _object(content, f"responses.{status}.content").get(
                    "application/json"
                ),
                f"responses.{status}.application/json",
            ).get("schema"),
            f"responses.{status}.schema",
        )
        component_ref, canonical_ref, typing_state = _schema_identity(schema, openapi)
        expected.append(
            {
                "status": status,
                "component_ref": component_ref,
                "canonical_schema_ref": canonical_ref,
                "typing_state": typing_state,
            }
        )
    if not expected:
        raise ToolContractAdmissionError(
            "OPENAPI_SUCCESS_RESPONSE_MISSING", str(operation.get("operationId"))
        )
    return expected


def _schema_identity(
    schema: Mapping[str, Any], openapi: Mapping[str, Any]
) -> tuple[str, str, str]:
    component_ref = schema.get("$ref")
    if not isinstance(component_ref, str) or not component_ref.startswith(
        "#/components/schemas/"
    ):
        raise ToolContractAdmissionError(
            "OPENAPI_COMPONENT_REF_REQUIRED", str(component_ref)
        )
    component_name = component_ref.rsplit("/", 1)[-1]
    components = _object(
        _object(openapi.get("components"), "components").get("schemas"),
        "components.schemas",
    )
    component = _object(components.get(component_name), component_ref)
    canonical = component.get("x-nex-canonical-json-schema")
    if canonical is None:
        return (
            component_ref,
            f"{_OPENAPI_RELATIVE_PATH}{component_ref}",
            "OPENAPI_INLINE_SCHEMA",
        )
    if (
        not isinstance(canonical, str)
        or not canonical.startswith("schemas/service/nex_eos/")
        or not (_ROOT / "contracts" / canonical).is_file()
    ):
        raise ToolContractAdmissionError(
            "CANONICAL_SCHEMA_REF_INVALID", str(canonical)
        )
    return component_ref, f"contracts/{canonical}", "CANONICAL_JSON_SCHEMA"


def _parameters(operation: Mapping[str, Any]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    parameters = operation.get("parameters", [])
    if not isinstance(parameters, list):
        raise ToolContractAdmissionError(
            "OPENAPI_PARAMETERS_INVALID", str(operation.get("operationId"))
        )
    required: list[str] = []
    optional: list[str] = []
    for parameter in parameters:
        item = _object(parameter, "parameter")
        location = _text(item.get("in"), "parameter.in")
        name = _text(item.get("name"), "parameter.name")
        if not isinstance(item.get("schema"), Mapping):
            raise ToolContractAdmissionError(
                "OPENAPI_PARAMETER_SCHEMA_MISSING", f"{location}:{name}"
            )
        target = required if item.get("required") is True else optional
        target.append(f"{location}:{name}")
    if len(set(required + optional)) != len(required + optional):
        raise ToolContractAdmissionError(
            "OPENAPI_PARAMETER_DUPLICATE", str(operation.get("operationId"))
        )
    return tuple(sorted(required)), tuple(sorted(optional))


def _operation_index(
    openapi: Mapping[str, Any],
) -> Mapping[str, tuple[str, str, Mapping[str, Any]]]:
    index: dict[str, tuple[str, str, Mapping[str, Any]]] = {}
    paths = _object(openapi.get("paths"), "paths")
    for route_path, path_item in paths.items():
        for method, operation in _object(path_item, str(route_path)).items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            item = _object(operation, f"{route_path}:{method}")
            operation_id = item.get("operationId")
            if not isinstance(operation_id, str):
                continue
            if operation_id in index:
                raise ToolContractAdmissionError(
                    "OPENAPI_OPERATION_DUPLICATE", operation_id
                )
            index[operation_id] = (str(route_path), method.upper(), item)
    return MappingProxyType(index)


def _operation_ref(path: str, method: str) -> str:
    escaped = path.replace("~", "~0").replace("/", "~1")
    return f"#/paths/{escaped}/{method.lower()}"


def _require_attestation(admission: Mapping[str, Any]) -> str:
    attestation = _object(admission.get("release_attestation"), "release_attestation")
    if set(attestation) != {"content_digest"}:
        raise ToolContractAdmissionError(
            "ATTESTATION_FIELDS_INVALID", str(sorted(attestation))
        )
    expected = calculate_tool_contract_admission_digest(admission)
    if attestation.get("content_digest") != expected:
        raise ToolContractAdmissionError(
            "ADMISSION_DIGEST_MISMATCH", str(attestation.get("content_digest"))
        )
    return expected


def _load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ToolContractAdmissionError("ADMISSION_UNREADABLE", str(path)) from exc
    except json.JSONDecodeError as exc:
        raise ToolContractAdmissionError("ADMISSION_INVALID_JSON", str(path)) from exc


def _load_openapi(path: Path) -> Mapping[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ToolContractAdmissionError("OPENAPI_UNREADABLE", str(path)) from exc
    except yaml.YAMLError as exc:
        raise ToolContractAdmissionError("OPENAPI_INVALID_YAML", str(path)) from exc
    return _object(value, "openapi")


def _byte_hash_ref(path: Path) -> str:
    try:
        value = path.read_bytes()
    except OSError as exc:
        raise ToolContractAdmissionError("OPENAPI_UNREADABLE", str(path)) from exc
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _object(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ToolContractAdmissionError("OBJECT_REQUIRED", field)
    return value


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ToolContractAdmissionError("TEXT_REQUIRED", field)
    return value
