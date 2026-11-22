"""Fail-closed reader for the immutable MyBee D12 work-code catalog."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

CATALOG_SCHEMA_VERSION = "nex.mybee.work-code-catalog.v1"
CATALOG_ID = "mybee.fl.d12.project-governance"
CATALOG_STATUS = "SOURCE_ADMITTED_RUNTIME_INACTIVE"
DOMAIN_GROUP = "D12_PROJECT"
MAPPING_STATUS = "DECLARED_NOT_BOUND"
MANDATORY_D12_WORK_CODE_IDS = (
    "FL0012004",
    "FL0012005",
    "FL0012006",
    "FL0012013",
    "FL0012026",
)

_CODE_ID = re.compile(r"^FL[0-9]{7}$")
_SEMVER = re.compile(r"^[1-9][0-9]*\.[0-9]+\.[0-9]+$")
_LIFECYCLE_STAGES = frozenset(
    {
        "PROJECT_OPEN",
        "WORK_SET_APPROVAL",
        "PM_ASSIGNMENT",
        "PROGRESS_AGGREGATION",
        "PROJECT_CLOSE",
    }
)
_EXECUTION_PHASES = frozenset(
    {"PROJECT_ACTIVATION", "CONFIGURATION", "OPERATIONS", "CLOSURE"}
)

DEFAULT_CATALOG_PATH = (
    Path(__file__).resolve().parents[2] / "catalog/work_codes/catalog.v1.json"
)


class WorkCodeCatalogError(ValueError):
    """Raised when a work-code catalog violates its immutable release contract."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


@dataclass(frozen=True)
class WorkCode:
    code_id: str
    name_ko: str
    purpose: str
    domain_group: str
    owner_service: str
    lifecycle_stage: str
    execution_phase: str
    required_for_project_work_set: bool
    mapping_status: str
    api_operation_id: str | None
    nsl_tool_id: str | None


@dataclass(frozen=True)
class WorkCodeCatalog:
    catalog_id: str
    catalog_version: str
    revision: int
    status: str
    mapping_digest: str
    work_codes: tuple[WorkCode, ...]
    _by_code: Mapping[str, WorkCode]

    def get(self, code_id: str) -> WorkCode:
        try:
            return self._by_code[code_id]
        except KeyError as error:
            raise WorkCodeCatalogError("WORK_CODE_NOT_FOUND", code_id) from error


def calculate_catalog_digest(catalog: Mapping[str, Any]) -> str:
    """Return the shared semantic digest over the attested catalog payload."""

    payload = {
        key: value for key, value in catalog.items() if key != "release_attestation"
    }
    return semantic_sha256_hash_ref(payload)


def _require_object(value: object, *, path: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise WorkCodeCatalogError("CATALOG_FIELD_INVALID", f"{path} must be object")
    return value


def _require_text(value: object, *, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorkCodeCatalogError("CATALOG_FIELD_INVALID", f"{path} must be text")
    return value


def _parse_work_code(value: object, *, index: int) -> WorkCode:
    item = _require_object(value, path=f"work_codes[{index}]")
    code_id = _require_text(item.get("code_id"), path=f"work_codes[{index}].code_id")
    if _CODE_ID.fullmatch(code_id) is None:
        raise WorkCodeCatalogError("WORK_CODE_ID_INVALID", code_id)

    domain_group = _require_text(
        item.get("domain_group"), path=f"work_codes[{index}].domain_group"
    )
    owner_service = _require_text(
        item.get("owner_service"), path=f"work_codes[{index}].owner_service"
    )
    lifecycle_stage = _require_text(
        item.get("lifecycle_stage"), path=f"work_codes[{index}].lifecycle_stage"
    )
    execution_phase = _require_text(
        item.get("execution_phase"), path=f"work_codes[{index}].execution_phase"
    )
    if domain_group != DOMAIN_GROUP or owner_service != "nex-eos":
        raise WorkCodeCatalogError("WORK_CODE_BOUNDARY_INVALID", code_id)
    if (
        lifecycle_stage not in _LIFECYCLE_STAGES
        or execution_phase not in _EXECUTION_PHASES
    ):
        raise WorkCodeCatalogError("WORK_CODE_LIFECYCLE_INVALID", code_id)
    if item.get("required_for_project_work_set") is not True:
        raise WorkCodeCatalogError("WORK_CODE_NOT_MANDATORY", code_id)

    mapping = _require_object(
        item.get("consumer_mapping"), path=f"work_codes[{index}].consumer_mapping"
    )
    mapping_status = _require_text(
        mapping.get("status"), path=f"work_codes[{index}].consumer_mapping.status"
    )
    api_operation_id = mapping.get("api_operation_id")
    nsl_tool_id = mapping.get("nsl_tool_id")
    if (
        mapping_status != MAPPING_STATUS
        or api_operation_id is not None
        or nsl_tool_id is not None
    ):
        raise WorkCodeCatalogError("RUNTIME_MAPPING_PREMATURE", code_id)

    return WorkCode(
        code_id=code_id,
        name_ko=_require_text(item.get("name_ko"), path=f"work_codes[{index}].name_ko"),
        purpose=_require_text(item.get("purpose"), path=f"work_codes[{index}].purpose"),
        domain_group=domain_group,
        owner_service=owner_service,
        lifecycle_stage=lifecycle_stage,
        execution_phase=execution_phase,
        required_for_project_work_set=True,
        mapping_status=mapping_status,
        api_operation_id=None,
        nsl_tool_id=None,
    )


def load_work_code_catalog(path: Path = DEFAULT_CATALOG_PATH) -> WorkCodeCatalog:
    """Load and verify the source-admitted catalog without activating runtime behavior."""

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise WorkCodeCatalogError("CATALOG_UNREADABLE", str(path)) from error
    except json.JSONDecodeError as error:
        raise WorkCodeCatalogError("CATALOG_INVALID_JSON", str(path)) from error
    catalog = _require_object(raw, path="$")

    if catalog.get("schema_version") != CATALOG_SCHEMA_VERSION:
        raise WorkCodeCatalogError(
            "SCHEMA_UNSUPPORTED", str(catalog.get("schema_version"))
        )
    if catalog.get("catalog_id") != CATALOG_ID:
        raise WorkCodeCatalogError("CATALOG_ID_INVALID", str(catalog.get("catalog_id")))
    version = _require_text(catalog.get("catalog_version"), path="catalog_version")
    if _SEMVER.fullmatch(version) is None:
        raise WorkCodeCatalogError("CATALOG_VERSION_INVALID", version)
    revision = catalog.get("revision")
    if type(revision) is not int or revision < 1:
        raise WorkCodeCatalogError("CATALOG_REVISION_INVALID", str(revision))
    if catalog.get("status") != CATALOG_STATUS:
        raise WorkCodeCatalogError("CATALOG_STATUS_INVALID", str(catalog.get("status")))

    owner = _require_object(catalog.get("owner"), path="owner")
    if owner != {
        "domain_policy": "nex-mybee-ax",
        "business_state": "nex-eos",
        "workflow": "nex-wc",
    }:
        raise WorkCodeCatalogError("CATALOG_OWNER_INVALID", str(dict(owner)))

    mandatory = catalog.get("mandatory_code_ids")
    if mandatory != list(MANDATORY_D12_WORK_CODE_IDS):
        raise WorkCodeCatalogError("MANDATORY_CODE_SET_INVALID", str(mandatory))
    raw_codes = catalog.get("work_codes")
    if not isinstance(raw_codes, list):
        raise WorkCodeCatalogError("WORK_CODES_INVALID", "array required")
    work_codes = tuple(
        _parse_work_code(item, index=index) for index, item in enumerate(raw_codes)
    )
    code_ids = tuple(item.code_id for item in work_codes)
    if code_ids != MANDATORY_D12_WORK_CODE_IDS:
        raise WorkCodeCatalogError("WORK_CODE_ORDER_OR_SET_INVALID", str(code_ids))

    attestation = _require_object(
        catalog.get("release_attestation"), path="release_attestation"
    )
    if (
        attestation.get("profile") != "SOURCE_AUTHORITY_CONTENT_DIGEST_V1"
        or attestation.get("authority") != "NEX_MYBEE_PHASE1_DESIGN_CLOSURE"
        or attestation.get("runtime_signature_status")
        != "DEFERRED_TO_ADMITTED_SKILL_PACK"
    ):
        raise WorkCodeCatalogError(
            "RELEASE_ATTESTATION_INVALID", str(dict(attestation))
        )
    expected_digest = _require_text(
        attestation.get("content_digest"), path="release_attestation.content_digest"
    )
    actual_digest = calculate_catalog_digest(catalog)
    if expected_digest != actual_digest:
        raise WorkCodeCatalogError("CATALOG_DIGEST_MISMATCH", actual_digest)

    by_code = MappingProxyType({item.code_id: item for item in work_codes})
    return WorkCodeCatalog(
        catalog_id=CATALOG_ID,
        catalog_version=version,
        revision=revision,
        status=CATALOG_STATUS,
        mapping_digest=actual_digest,
        work_codes=work_codes,
        _by_code=by_code,
    )
