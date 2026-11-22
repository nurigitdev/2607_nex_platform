from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from mybee_ax.domain.coa_candidate import (
    REQUIRED_FX_SEMANTIC_KEYS,
    VALIDATION_STATUS,
    CoaCandidateError,
    load_json_object,
    validate_coa_candidate,
    verify_coa_candidate_identity,
)

ROOT = Path(__file__).resolve().parents[2]
CANDIDATE_PATH = (
    ROOT
    / "docs/transition/MyBee_Phase1/NeX_MyBee_COA_Codebook_Candidate_v0.1.json"
)
DELTA_PATH = (
    ROOT / "docs/transition/MyBee_Phase1/NeX_MyBee_COA_CA01_Decision_Delta_v1.0.json"
)
CONFIG = ROOT / "domains/mybee/config/account_catalog"
SCHEMA_PATH = CONFIG / "unified_codebook_candidate.schema.json"
IDENTITY_PATH = CONFIG / "unified_codebook_candidate.identity.v1.json"
NEGATIVE_CASES_PATH = CONFIG / "coa_candidate_negative_cases.v1.json"


def _candidate() -> dict[str, Any]:
    return json.loads(CANDIDATE_PATH.read_text(encoding="utf-8"))


def _account(candidate: dict[str, Any], semantic_key: str) -> dict[str, Any]:
    return next(
        item
        for item in candidate["accounts"]
        if item["standard_account_key"] == semantic_key
    )


def _finding_codes(candidate: dict[str, Any], **kwargs: Any) -> set[str]:
    return {
        finding.code
        for finding in validate_coa_candidate(candidate, **kwargs).findings
    }


def test_coa_01_candidate_matches_schema_and_frozen_identity() -> None:
    candidate = _candidate()
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    identity = load_json_object(IDENTITY_PATH)

    jsonschema.Draft202012Validator(schema).validate(candidate)
    report = verify_coa_candidate_identity(candidate, identity)

    assert report.status == VALIDATION_STATUS
    assert report.is_structurally_valid is True
    assert report.runtime_seed_allowed is False
    assert report.total_nodes == 166
    assert report.findings == ()
    report.require_valid()


def test_coa_01_raw_source_hash_and_candidate_boundary_are_unchanged() -> None:
    delta = json.loads(DELTA_PATH.read_text(encoding="utf-8"))
    identity = json.loads(IDENTITY_PATH.read_text(encoding="utf-8"))
    source_hash = "sha256:" + hashlib.sha256(CANDIDATE_PATH.read_bytes()).hexdigest()

    assert source_hash == delta["authority"]["candidate_sha256"]
    assert source_hash == identity["candidate_file_sha256"]
    assert identity["accounting_owner_approved"] is False
    assert identity["runtime_seed_allowed"] is False
    assert identity["approved_proof_ref"] is None


def test_coa_01_candidate_has_complete_reviewer_identity_and_fx_set() -> None:
    candidate = _candidate()
    accounts = candidate["accounts"]
    identities = {
        item["standard_account_key"]: item["account_code"] for item in accounts
    }

    assert len(identities) == len(accounts) == 166
    assert REQUIRED_FX_SEMANTIC_KEYS <= identities.keys()
    assert sum(item["hierarchy_level"] == 4 for item in accounts) == 88
    assert all(
        1 <= int(item["account_code"][-3:]) <= 699
        for item in accounts
        if item["hierarchy_level"] == 4
    )


@pytest.mark.parametrize(
    "case",
    json.loads(NEGATIVE_CASES_PATH.read_text(encoding="utf-8"))["cases"],
    ids=lambda case: case["case_id"],
)
def test_coa_01_negative_mutation_matrix_fails_closed(case: dict[str, Any]) -> None:
    candidate = copy.deepcopy(_candidate())
    mutation = case["mutation"]
    kwargs: dict[str, Any] = {}
    target = (
        _account(candidate, case["target_key"]) if "target_key" in case else None
    )

    if mutation == "duplicate_code":
        assert target is not None
        target["account_code"] = _account(candidate, case["source_key"])["account_code"]
    elif mutation == "duplicate_semantic_key":
        assert target is not None
        target["standard_account_key"] = case["source_key"]
    elif mutation == "set_code":
        assert target is not None
        target["account_code"] = case["value"]
    elif mutation == "set_parent":
        assert target is not None
        target["parent_account_code"] = case["value"]
    elif mutation == "prior_identity_drift":
        assert target is not None
        kwargs["previous_code_identities"] = {
            target["account_code"]: case["value"]
        }
    elif mutation == "enable_runtime_seed":
        candidate["runtime_seed_allowed"] = True
    elif mutation == "set_category":
        assert target is not None
        target["category"] = case["value"]
    elif mutation == "remove_account":
        assert target is not None
        candidate["accounts"].remove(target)
    else:  # pragma: no cover - fixture schema guard
        raise AssertionError(f"unknown mutation: {mutation}")

    assert case["expected_finding"] in _finding_codes(candidate, **kwargs)


def test_coa_01_cross_release_semantic_key_cannot_move_to_another_code() -> None:
    candidate = _candidate()
    cash = _account(candidate, "MB-COA-CASH-ON-HAND")
    prior = {"10101999": cash["standard_account_key"]}

    assert "SEMANTIC_KEY_CODE_DRIFT" in _finding_codes(
        candidate, previous_code_identities=prior
    )


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    (
        ("schema_version", "future", "CANDIDATE_SCHEMA_UNSUPPORTED"),
        ("status", "APPROVED", "CANDIDATE_STATUS_INVALID"),
        ("approved_proof_ref", "fake-proof", "CANDIDATE_APPROVAL_FABRICATED"),
        ("is_official_k_ifrs_account_code", True, "KIFRS_CODE_CLASSIFICATION_INVALID"),
        ("source_reference", "UNVERIFIED_SOURCE", "SOURCE_REFERENCE_INVALID"),
        ("rules", {}, "CODE_NAMESPACE_POLICY_INVALID"),
        ("accounts", {}, "ACCOUNT_SET_INVALID"),
    ),
)
def test_coa_01_top_level_contract_drift_is_rejected(
    field: str, value: object, expected: str
) -> None:
    candidate = _candidate()
    candidate[field] = value

    assert expected in _finding_codes(candidate)


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    (
        ("account_code", "BAD", "ACCOUNT_CODE_INVALID"),
        ("standard_account_key", "bad key", "SEMANTIC_KEY_INVALID"),
        ("account_code", "10001000", "ACCOUNT_HIERARCHY_CODE_INVALID"),
        ("hierarchy_level", 3, "ACCOUNT_HIERARCHY_LEVEL_INVALID"),
        ("normal_balance", "CR", "ACCOUNT_NORMAL_BALANCE_INVALID"),
        ("is_contra", "false", "ACCOUNT_CONTRA_INVALID"),
        ("is_postable_leaf_if_admitted", False, "ACCOUNT_POSTING_ELIGIBILITY_INVALID"),
        ("account_type", "ACCOUNT_GROUP", "ACCOUNT_TYPE_INVALID"),
        ("reporting_mapping_status", "MAPPED", "REPORTING_MAPPING_PREMATURE"),
        ("source_lineage", "OFFICIAL_KIFRS", "ACCOUNT_SOURCE_LINEAGE_INVALID"),
    ),
)
def test_coa_01_account_contract_drift_is_rejected(
    field: str, value: object, expected: str
) -> None:
    candidate = _candidate()
    _account(candidate, "MB-COA-CASH-ON-HAND")[field] = value

    assert expected in _finding_codes(candidate)


def test_coa_01_missing_parent_and_parent_category_drift_are_rejected() -> None:
    missing_parent = _candidate()
    missing_parent["accounts"] = [
        item
        for item in missing_parent["accounts"]
        if item["account_code"] != "10101000"
    ]
    assert "ACCOUNT_PARENT_MISSING" in _finding_codes(missing_parent)

    category_drift = _candidate()
    _account(category_drift, "MB-COA-FAM-10101")["category"] = "EXPENSE"
    codes = _finding_codes(category_drift)
    assert "ACCOUNT_CATEGORY_INVALID" in codes
    assert "ACCOUNT_PARENT_CATEGORY_MISMATCH" in codes


def test_coa_01_malformed_rows_and_statistics_are_rejected_without_crash() -> None:
    candidate = _candidate()
    candidate["accounts"].append("bad-row")
    candidate["statistics"] = {}

    codes = _finding_codes(candidate)
    assert "ACCOUNT_ROW_INVALID" in codes
    assert "CANDIDATE_STATISTICS_MISMATCH" in codes


@pytest.mark.parametrize(
    "field",
    (
        "status",
        "accounting_owner_approved",
        "runtime_seed_allowed",
        "approved_proof_ref",
        "candidate_semantic_hash",
        "identity_set_hash",
        "node_contract_hash",
        "total_nodes",
    ),
)
def test_coa_01_identity_manifest_drift_is_rejected(field: str) -> None:
    identity = dict(load_json_object(IDENTITY_PATH))
    identity[field] = "drift"

    with pytest.raises(CoaCandidateError) as raised:
        verify_coa_candidate_identity(_candidate(), identity)
    assert raised.value.code == "CANDIDATE_IDENTITY_MISMATCH"


def test_coa_01_invalid_candidate_cannot_be_identity_verified() -> None:
    candidate = _candidate()
    candidate["runtime_seed_allowed"] = True

    with pytest.raises(CoaCandidateError) as raised:
        verify_coa_candidate_identity(candidate, load_json_object(IDENTITY_PATH))
    assert raised.value.code == "CANDIDATE_SEED_PREMATURE"


def test_coa_01_json_loader_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(CoaCandidateError) as missing:
        load_json_object(tmp_path / "missing.json")
    assert missing.value.code == "COA_CANDIDATE_UNREADABLE"

    malformed = tmp_path / "malformed.json"
    malformed.write_text("{", encoding="utf-8")
    with pytest.raises(CoaCandidateError) as invalid:
        load_json_object(malformed)
    assert invalid.value.code == "COA_CANDIDATE_INVALID_JSON"

    array = tmp_path / "array.json"
    array.write_text("[]", encoding="utf-8")
    with pytest.raises(CoaCandidateError) as wrong_root:
        load_json_object(array)
    assert wrong_root.value.code == "COA_CANDIDATE_ROOT_INVALID"


def test_coa_01_schema_rejects_premature_seed_admission() -> None:
    candidate = _candidate()
    candidate["runtime_seed_allowed"] = True
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    assert list(jsonschema.Draft202012Validator(schema).iter_errors(candidate))


def test_coa_01_does_not_add_an_eos_migration() -> None:
    closure = (
        ROOT / "docs/slices/mybee_phase1_coa_01_unified_codebook_candidate_closure.md"
    ).read_text(encoding="utf-8")
    coa_01_named_migrations = sorted(
        path.name
        for path in (ROOT / "database/nex-eos/migrations").glob("*.sql")
        if "coa_01" in path.name.lower()
    )
    assert "database migrations: NONE" in closure
    assert coa_01_named_migrations == []
