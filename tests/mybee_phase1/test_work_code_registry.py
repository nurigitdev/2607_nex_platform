from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import jsonschema
import pytest
from mybee_ax.domain.work_codes import (
    CATALOG_STATUS,
    MANDATORY_D12_WORK_CODE_IDS,
    WorkCodeCatalogError,
    calculate_catalog_digest,
    load_work_code_catalog,
)

ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = ROOT / "domains/mybee/catalog/work_codes/catalog.v1.json"
SCHEMA_PATH = ROOT / "domains/mybee/catalog/work_codes/schema.json"


def _catalog_json() -> dict[str, object]:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def _write_catalog(tmp_path: Path, value: object) -> Path:
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def _error_for(tmp_path: Path, value: object) -> WorkCodeCatalogError:
    with pytest.raises(WorkCodeCatalogError) as raised:
        load_work_code_catalog(_write_catalog(tmp_path, value))
    return raised.value


def test_mb1_01_catalog_matches_schema_and_immutable_release_digest() -> None:
    raw = _catalog_json()
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    jsonschema.Draft202012Validator(schema).validate(raw)
    catalog = load_work_code_catalog()

    assert catalog.catalog_id == "mybee.fl.d12.project-governance"
    assert catalog.catalog_version == "1.0.0"
    assert catalog.revision == 1
    assert catalog.status == CATALOG_STATUS
    assert catalog.mapping_digest == calculate_catalog_digest(raw)
    assert catalog.mapping_digest == raw["release_attestation"]["content_digest"]


def test_mb1_01_catalog_publishes_exact_d12_mandatory_set_without_runtime_binding() -> (
    None
):
    catalog = load_work_code_catalog()

    assert (
        tuple(item.code_id for item in catalog.work_codes)
        == MANDATORY_D12_WORK_CODE_IDS
    )
    assert tuple(item.name_ko for item in catalog.work_codes) == (
        "프로젝트 개설",
        "업무 구성 확정",
        "PM 지정",
        "진행 보고 집계",
        "프로젝트 종결",
    )
    assert {item.domain_group for item in catalog.work_codes} == {"D12_PROJECT"}
    assert {item.owner_service for item in catalog.work_codes} == {"nex-eos"}
    assert all(item.required_for_project_work_set for item in catalog.work_codes)
    assert all(
        item.mapping_status == "DECLARED_NOT_BOUND" for item in catalog.work_codes
    )
    assert all(item.api_operation_id is None for item in catalog.work_codes)
    assert all(item.nsl_tool_id is None for item in catalog.work_codes)


def test_mb1_01_catalog_preserves_assignment_and_execution_timing() -> None:
    catalog = load_work_code_catalog()

    assert catalog.get("FL0012013").execution_phase == "OPERATIONS"
    assert catalog.get("FL0012026").execution_phase == "CLOSURE"
    assert catalog.get("FL0012026").lifecycle_stage == "PROJECT_CLOSE"

    with pytest.raises(WorkCodeCatalogError) as raised:
        catalog.get("FL9999999")
    assert raised.value.code == "WORK_CODE_NOT_FOUND"


def test_mb1_01_source_provenance_hashes_are_current_and_pdf_gap_is_explicit() -> None:
    raw = _catalog_json()
    provenance = raw["source_provenance"]

    assert provenance["pdf_page_reconciliation"] == "OPEN_G_SRC_PDF"
    for evidence in provenance["evidence"]:
        path = ROOT / evidence["path"]
        digest = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == evidence["sha256"]


def test_mb1_01_release_attestation_is_digest_bound_not_a_fake_runtime_signature() -> (
    None
):
    raw = _catalog_json()
    attestation = raw["release_attestation"]

    assert attestation == {
        "profile": "SOURCE_AUTHORITY_CONTENT_DIGEST_V1",
        "authority": "NEX_MYBEE_PHASE1_DESIGN_CLOSURE",
        "evidence_ref": "docs/slices/mybee_phase1_mb1_01_work_code_catalog.md",
        "content_digest": calculate_catalog_digest(raw),
        "runtime_signature_status": "DEFERRED_TO_ADMITTED_SKILL_PACK",
    }
    changed_attestation = copy.deepcopy(raw)
    changed_attestation["release_attestation"]["content_digest"] = "sha256:" + "0" * 64
    assert calculate_catalog_digest(changed_attestation) == calculate_catalog_digest(
        raw
    )


@pytest.mark.parametrize(
    ("case", "expected_code"),
    (
        ("schema", "SCHEMA_UNSUPPORTED"),
        ("catalog_id", "CATALOG_ID_INVALID"),
        ("version", "CATALOG_VERSION_INVALID"),
        ("revision", "CATALOG_REVISION_INVALID"),
        ("status", "CATALOG_STATUS_INVALID"),
        ("owner", "CATALOG_OWNER_INVALID"),
        ("mandatory", "MANDATORY_CODE_SET_INVALID"),
        ("codes_type", "WORK_CODES_INVALID"),
        ("code_id", "WORK_CODE_ID_INVALID"),
        ("blank_text", "CATALOG_FIELD_INVALID"),
        ("boundary", "WORK_CODE_BOUNDARY_INVALID"),
        ("lifecycle", "WORK_CODE_LIFECYCLE_INVALID"),
        ("optional", "WORK_CODE_NOT_MANDATORY"),
        ("mapping", "RUNTIME_MAPPING_PREMATURE"),
        ("order", "WORK_CODE_ORDER_OR_SET_INVALID"),
        ("attestation", "RELEASE_ATTESTATION_INVALID"),
        ("digest", "CATALOG_DIGEST_MISMATCH"),
    ),
)
def test_mb1_01_loader_fails_closed_for_catalog_drift(
    tmp_path: Path, case: str, expected_code: str
) -> None:
    raw = copy.deepcopy(_catalog_json())
    if case == "schema":
        raw["schema_version"] = "future"
    elif case == "catalog_id":
        raw["catalog_id"] = "other"
    elif case == "version":
        raw["catalog_version"] = "v1"
    elif case == "revision":
        raw["revision"] = 0
    elif case == "status":
        raw["status"] = "ACTIVE"
    elif case == "owner":
        raw["owner"]["business_state"] = "nex-wc"
    elif case == "mandatory":
        raw["mandatory_code_ids"].reverse()
    elif case == "codes_type":
        raw["work_codes"] = {}
    elif case == "code_id":
        raw["work_codes"][0]["code_id"] = "BAD"
    elif case == "blank_text":
        raw["work_codes"][0]["purpose"] = " "
    elif case == "boundary":
        raw["work_codes"][0]["owner_service"] = "nex-ae-api"
    elif case == "lifecycle":
        raw["work_codes"][0]["execution_phase"] = "UNKNOWN"
    elif case == "optional":
        raw["work_codes"][0]["required_for_project_work_set"] = False
    elif case == "mapping":
        raw["work_codes"][0]["consumer_mapping"]["status"] = "ACTIVE"
    elif case == "order":
        raw["work_codes"].reverse()
    elif case == "attestation":
        raw["release_attestation"]["authority"] = "OTHER"
    elif case == "digest":
        raw["work_codes"][0]["purpose"] = "tampered"

    assert _error_for(tmp_path, raw).code == expected_code


@pytest.mark.parametrize(
    ("value", "expected_code"),
    (
        ([], "CATALOG_FIELD_INVALID"),
        ({"schema_version": None}, "SCHEMA_UNSUPPORTED"),
    ),
)
def test_mb1_01_loader_rejects_non_catalog_roots(
    tmp_path: Path, value: object, expected_code: str
) -> None:
    assert _error_for(tmp_path, value).code == expected_code


def test_mb1_01_loader_reports_unreadable_and_invalid_json(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(WorkCodeCatalogError) as unreadable:
        load_work_code_catalog(missing)
    assert unreadable.value.code == "CATALOG_UNREADABLE"

    invalid = tmp_path / "invalid.json"
    invalid.write_text("{", encoding="utf-8")
    with pytest.raises(WorkCodeCatalogError) as malformed:
        load_work_code_catalog(invalid)
    assert malformed.value.code == "CATALOG_INVALID_JSON"


def test_mb1_01_schema_rejects_a_premature_api_or_tool_binding() -> None:
    raw = _catalog_json()
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    raw["work_codes"][0]["consumer_mapping"]["api_operation_id"] = (
        "PROJECT.WORK_CODE_SET.APPROVE"
    )

    errors = list(jsonschema.Draft202012Validator(schema).iter_errors(raw))
    assert errors
