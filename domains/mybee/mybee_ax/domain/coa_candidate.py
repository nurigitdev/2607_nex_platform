"""Fail-closed structural and identity checks for the unapproved MyBee COA candidate."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

CANDIDATE_SCHEMA_VERSION = "nex.mybee.coa.design_candidate.v0.1"
CANDIDATE_STATUS = "DESIGN_CANDIDATE_NOT_APPROVED"
VALIDATION_STATUS = "STRUCTURE_VALIDATED_ACCOUNTING_APPROVAL_PENDING"
SOURCE_REFERENCE = "INTERNAL_DESIGN_CANDIDATE_ONLY"
SOURCE_LINEAGE = "INTERNAL_DESIGN_CANDIDATE_NOT_KIFRS_CODE"
REPORTING_MAPPING_STATUS = "MAPPING_PENDING"

_ACCOUNT_CODE = re.compile(r"^[1-9][0-9]{7}$")
_SEMANTIC_KEY = re.compile(r"^MB-COA-[A-Z0-9]+(?:-[A-Z0-9]+)*$")
_ROOT_CATEGORY = {
    "1": "ASSET",
    "2": "LIABILITY",
    "3": "EQUITY",
    "4": "REVENUE",
    "5": "EXPENSE",
    "6": "EXPENSE",
    "7": "REVENUE",
    "8": "EXPENSE",
    "9": "EXPENSE",
}
_NORMAL_BALANCE = {
    "ASSET": "DR",
    "LIABILITY": "CR",
    "EQUITY": "CR",
    "REVENUE": "CR",
    "EXPENSE": "DR",
}

REQUIRED_FX_SEMANTIC_KEYS = frozenset(
    {
        "MB-COA-BANK-FX-DEPOSIT",
        "MB-COA-ACCOUNTS-RECEIVABLE-FX",
        "MB-COA-ACCOUNTS-PAYABLE-FX",
        "MB-COA-OTHER-PAYABLES-FX",
        "MB-COA-FX-REALIZED-GAIN",
        "MB-COA-FX-REVALUATION-GAIN",
        "MB-COA-FX-REALIZED-LOSS",
        "MB-COA-FX-REVALUATION-LOSS",
    }
)


class CoaCandidateError(ValueError):
    """Raised when a candidate or its frozen identity cannot be admitted."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


@dataclass(frozen=True, order=True)
class CoaValidationFinding:
    code: str
    path: str
    detail: str


@dataclass(frozen=True)
class CoaCandidateValidationReport:
    status: str
    candidate_semantic_hash: str
    identity_set_hash: str
    node_contract_hash: str
    total_nodes: int
    findings: tuple[CoaValidationFinding, ...]

    @property
    def is_structurally_valid(self) -> bool:
        return not self.findings

    @property
    def runtime_seed_allowed(self) -> bool:
        return False

    def require_valid(self) -> None:
        if self.findings:
            first = self.findings[0]
            raise CoaCandidateError(first.code, f"{first.path}: {first.detail}")


def load_json_object(path: Path) -> Mapping[str, Any]:
    """Read a JSON object while preserving a typed fail-closed error boundary."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise CoaCandidateError("COA_CANDIDATE_UNREADABLE", str(path)) from error
    except json.JSONDecodeError as error:
        raise CoaCandidateError("COA_CANDIDATE_INVALID_JSON", str(path)) from error
    if not isinstance(value, dict):
        raise CoaCandidateError("COA_CANDIDATE_ROOT_INVALID", "object required")
    return value


def validate_coa_candidate(
    candidate: Mapping[str, Any],
    *,
    previous_code_identities: Mapping[str, str] | None = None,
) -> CoaCandidateValidationReport:
    """Validate one design candidate without granting source or seed approval."""

    findings: list[CoaValidationFinding] = []

    def add(code: str, path: str, detail: str) -> None:
        findings.append(CoaValidationFinding(code=code, path=path, detail=detail))

    if candidate.get("schema_version") != CANDIDATE_SCHEMA_VERSION:
        add("CANDIDATE_SCHEMA_UNSUPPORTED", "$.schema_version", "unexpected version")
    if candidate.get("status") != CANDIDATE_STATUS:
        add("CANDIDATE_STATUS_INVALID", "$.status", "candidate must remain unapproved")
    if candidate.get("runtime_seed_allowed") is not False:
        add(
            "CANDIDATE_SEED_PREMATURE",
            "$.runtime_seed_allowed",
            "unapproved candidate cannot be seeded",
        )
    if candidate.get("approved_proof_ref") is not None:
        add(
            "CANDIDATE_APPROVAL_FABRICATED",
            "$.approved_proof_ref",
            "approval evidence is not available",
        )
    if candidate.get("is_official_k_ifrs_account_code") is not False:
        add(
            "KIFRS_CODE_CLASSIFICATION_INVALID",
            "$.is_official_k_ifrs_account_code",
            "MyBee codes are not official K-IFRS account numbers",
        )
    if candidate.get("source_reference") != SOURCE_REFERENCE:
        add(
            "SOURCE_REFERENCE_INVALID",
            "$.source_reference",
            "only the explicitly unapproved design source is accepted",
        )

    rules = candidate.get("rules")
    expected_rules = {
        "new_account_pattern": "^[1-9][0-9]{7}$",
        "segment_widths": [1, 2, 2, 3],
        "standard_leaf_suffix": "001-699",
        "product_reserve_suffix": "700-799",
        "tenant_extension_suffix": "800-999",
        "nonpostable_parent_suffix": "000",
    }
    if rules != expected_rules:
        add("CODE_NAMESPACE_POLICY_INVALID", "$.rules", "namespace rules drifted")

    raw_accounts = candidate.get("accounts")
    if not isinstance(raw_accounts, list):
        add("ACCOUNT_SET_INVALID", "$.accounts", "array required")
        raw_accounts = []

    accounts: list[Mapping[str, Any]] = []
    by_code: dict[str, Mapping[str, Any]] = {}
    by_key: dict[str, str] = {}
    identity_rows: list[dict[str, str]] = []
    contract_rows: list[Mapping[str, Any]] = []

    for index, value in enumerate(raw_accounts):
        path = f"$.accounts[{index}]"
        if not isinstance(value, dict):
            add("ACCOUNT_ROW_INVALID", path, "object required")
            continue
        account = value
        accounts.append(account)
        contract_rows.append(account)
        code = account.get("account_code")
        semantic_key = account.get("standard_account_key")
        if not isinstance(code, str) or _ACCOUNT_CODE.fullmatch(code) is None:
            add("ACCOUNT_CODE_INVALID", f"{path}.account_code", str(code))
            continue
        if (
            not isinstance(semantic_key, str)
            or _SEMANTIC_KEY.fullmatch(semantic_key) is None
        ):
            add(
                "SEMANTIC_KEY_INVALID",
                f"{path}.standard_account_key",
                str(semantic_key),
            )
            continue
        if code in by_code:
            add("ACCOUNT_CODE_DUPLICATE", f"{path}.account_code", code)
        else:
            by_code[code] = account
        if semantic_key in by_key:
            add("SEMANTIC_KEY_DUPLICATE", f"{path}.standard_account_key", semantic_key)
        else:
            by_key[semantic_key] = code
        identity_rows.append(
            {"account_code": code, "standard_account_key": semantic_key}
        )
        _validate_account_row(account, path=path, add=add)

    for index, account in enumerate(accounts):
        code = account.get("account_code")
        if not isinstance(code, str) or _ACCOUNT_CODE.fullmatch(code) is None:
            continue
        level = _hierarchy_level(code)
        if level is None:
            continue
        expected_parent = _expected_parent(code, level)
        declared_parent = account.get("parent_account_code")
        if declared_parent != expected_parent:
            add(
                "ACCOUNT_PARENT_MISMATCH",
                f"$.accounts[{index}].parent_account_code",
                f"expected {expected_parent!r}",
            )
            continue
        if expected_parent is not None:
            parent = by_code.get(expected_parent)
            if parent is None:
                add("ACCOUNT_PARENT_MISSING", f"$.accounts[{index}]", expected_parent)
            elif parent.get("category") != account.get("category"):
                add(
                    "ACCOUNT_PARENT_CATEGORY_MISMATCH",
                    f"$.accounts[{index}].category",
                    str(account.get("category")),
                )

    _validate_statistics(candidate.get("statistics"), accounts, add=add)
    missing_fx = sorted(REQUIRED_FX_SEMANTIC_KEYS.difference(by_key))
    for semantic_key in missing_fx:
        add("REQUIRED_FX_ACCOUNT_MISSING", "$.accounts", semantic_key)

    if previous_code_identities is not None:
        _validate_previous_identities(
            by_code=by_code,
            by_key=by_key,
            previous=previous_code_identities,
            add=add,
        )

    identity_rows.sort(
        key=lambda item: (item["account_code"], item["standard_account_key"])
    )
    contract_rows.sort(key=lambda item: str(item.get("account_code", "")))
    ordered_findings = tuple(sorted(set(findings)))
    return CoaCandidateValidationReport(
        status=VALIDATION_STATUS if not ordered_findings else "REJECTED",
        candidate_semantic_hash=semantic_sha256_hash_ref(candidate),
        identity_set_hash=semantic_sha256_hash_ref(identity_rows),
        node_contract_hash=semantic_sha256_hash_ref(contract_rows),
        total_nodes=len(accounts),
        findings=ordered_findings,
    )


def verify_coa_candidate_identity(
    candidate: Mapping[str, Any], identity: Mapping[str, Any]
) -> CoaCandidateValidationReport:
    """Bind a valid candidate to its immutable, still-unapproved identity manifest."""

    report = validate_coa_candidate(candidate)
    report.require_valid()
    expected = {
        "status": VALIDATION_STATUS,
        "accounting_owner_approved": False,
        "runtime_seed_allowed": False,
        "approved_proof_ref": None,
        "candidate_semantic_hash": report.candidate_semantic_hash,
        "identity_set_hash": report.identity_set_hash,
        "node_contract_hash": report.node_contract_hash,
        "total_nodes": report.total_nodes,
    }
    for field, value in expected.items():
        if identity.get(field) != value:
            raise CoaCandidateError(
                "CANDIDATE_IDENTITY_MISMATCH",
                f"{field}: expected {value!r}, got {identity.get(field)!r}",
            )
    return report


def _validate_account_row(
    account: Mapping[str, Any],
    *,
    path: str,
    add: Callable[[str, str, str], None],
) -> None:
    code = account["account_code"]
    level = _hierarchy_level(code)
    if level is None:
        add("ACCOUNT_HIERARCHY_CODE_INVALID", f"{path}.account_code", code)
        return
    if account.get("hierarchy_level") != level:
        add("ACCOUNT_HIERARCHY_LEVEL_INVALID", f"{path}.hierarchy_level", code)

    category = account.get("category")
    expected_category = _ROOT_CATEGORY[code[0]]
    if category != expected_category:
        add(
            "ACCOUNT_CATEGORY_INVALID",
            f"{path}.category",
            f"expected {expected_category}",
        )
    contra = account.get("is_contra")
    if type(contra) is not bool:
        add("ACCOUNT_CONTRA_INVALID", f"{path}.is_contra", str(contra))
    elif category in _NORMAL_BALANCE:
        normal = _NORMAL_BALANCE[category]
        expected_balance = _opposite(normal) if contra else normal
        if account.get("normal_balance") != expected_balance:
            add(
                "ACCOUNT_NORMAL_BALANCE_INVALID",
                f"{path}.normal_balance",
                f"expected {expected_balance}",
            )

    is_leaf = level == 4
    if account.get("is_postable_leaf_if_admitted") is not is_leaf:
        add(
            "ACCOUNT_POSTING_ELIGIBILITY_INVALID",
            f"{path}.is_postable_leaf_if_admitted",
            code,
        )
    if (account.get("account_type") == "ACCOUNT_GROUP") is is_leaf:
        add("ACCOUNT_TYPE_INVALID", f"{path}.account_type", code)
    if account.get("reporting_mapping_status") != REPORTING_MAPPING_STATUS:
        add("REPORTING_MAPPING_PREMATURE", f"{path}.reporting_mapping_status", code)
    if account.get("source_lineage") != SOURCE_LINEAGE:
        add("ACCOUNT_SOURCE_LINEAGE_INVALID", f"{path}.source_lineage", code)

    if is_leaf:
        suffix = int(code[-3:])
        if not 1 <= suffix <= 699:
            add("STANDARD_LEAF_SUFFIX_RESERVED", f"{path}.account_code", code)


def _validate_statistics(
    statistics: object,
    accounts: Sequence[Mapping[str, Any]],
    *,
    add: Callable[[str, str, str], None],
) -> None:
    actual = {
        "major_roots": sum(item.get("hierarchy_level") == 1 for item in accounts),
        "groups": sum(item.get("hierarchy_level") == 2 for item in accounts),
        "families": sum(item.get("hierarchy_level") == 3 for item in accounts),
        "leaf_accounts": sum(item.get("hierarchy_level") == 4 for item in accounts),
        "total_nodes": len(accounts),
    }
    if statistics != actual:
        add("CANDIDATE_STATISTICS_MISMATCH", "$.statistics", str(actual))


def _validate_previous_identities(
    *,
    by_code: Mapping[str, Mapping[str, Any]],
    by_key: Mapping[str, str],
    previous: Mapping[str, str],
    add: Callable[[str, str, str], None],
) -> None:
    previous_by_key = {semantic_key: code for code, semantic_key in previous.items()}
    for code, semantic_key in previous.items():
        current = by_code.get(code)
        if current is not None and current.get("standard_account_key") != semantic_key:
            add("CODE_SEMANTIC_DRIFT", "$.accounts", code)
    for semantic_key, previous_code in previous_by_key.items():
        current_code = by_key.get(semantic_key)
        if current_code is not None and current_code != previous_code:
            add("SEMANTIC_KEY_CODE_DRIFT", "$.accounts", semantic_key)


def _hierarchy_level(code: str) -> int | None:
    if code[1:] == "0000000":
        return 1
    if code[1:3] != "00" and code[3:] == "00000":
        return 2
    if code[1:3] != "00" and code[3:5] != "00" and code[5:] == "000":
        return 3
    if code[1:3] != "00" and code[3:5] != "00" and code[5:] != "000":
        return 4
    return None


def _expected_parent(code: str, level: int) -> str | None:
    if level == 1:
        return None
    if level == 2:
        return code[0] + "0000000"
    if level == 3:
        return code[:3] + "00000"
    return code[:5] + "000"


def _opposite(balance: str) -> str:
    return "CR" if balance == "DR" else "DR"
