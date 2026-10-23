from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from .semantic_hashes import semantic_sha256_hash_ref

GOLDEN_A_EVIDENCE_SCHEMA_VERSION = "p8_golden_a_evidence_package.v1"
GOLDEN_A_GATE = "P8.6_GOLDEN_A_CLOSED"
EXPECTED_MIGRATION_SERVICES = (
    "nex-ae-api",
    "nex-wc",
    "nex-oa",
    "nex-eos",
)

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HASH_REF = re.compile(r"^sha256:[0-9a-f]{64}$")
_SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._-]{0,255}$")
_MIGRATION = re.compile(r"^[0-9]{4}_[a-z0-9_]{3,120}$")
_RUN_ID = re.compile(r"^(p8-s67|full-gate):[0-9a-f]{16}$")
_VOUCHER_REF = re.compile(
    r"^eos\.voucher_draft:[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_FORBIDDEN_KEY_PARTS = (
    "api_key",
    "authorization",
    "credential",
    "database_url",
    "endpoint",
    "password",
    "private_key",
    "prompt",
    "raw_payload",
    "secret",
    "storage_path",
    "token",
)
_FORBIDDEN_VALUE_MARKERS = (
    "postgresql://",
    "postgresql+psycopg://",
    "http://",
    "https://",
    "bearer ",
    "-----begin ",
)

_TOP_LEVEL_FIELDS = frozenset(
    {
        "schema_version",
        "slice",
        "gate",
        "status",
        "platform",
        "nsl_release",
        "migration_heads",
        "test_evidence",
        "lineage",
        "outcome",
        "package_digest",
    }
)
_PLATFORM_FIELDS = frozenset({"commit", "tree"})
_NSL_RELEASE_FIELDS = frozenset(
    {"source_revision", "source_tree", "wheel_sha256", "release_admission_hash"}
)
_TEST_FIELDS = frozenset(
    {
        "protected_gate_id",
        "protected_run_id",
        "protected_evidence_digest",
        "actual_postgres",
        "actual_remote_provider",
        "full_gate_id",
        "full_gate_run_id",
        "full_gate_evidence_digest",
        "passed_test_count",
        "failed_test_count",
        "skipped_test_count",
        "statement_coverage",
        "branch_coverage",
    }
)
_LINEAGE_FIELDS = frozenset(
    {
        "business_operation_id",
        "nsl_execution_id",
        "approval_request_id",
        "approval_work_item_id",
        "voucher_ref",
    }
)
_OUTCOME_FIELDS = frozenset(
    {
        "commit_state",
        "verification_status",
        "business_mutation_count",
        "residue_count",
    }
)


def build_golden_a_evidence_package(
    *,
    platform: Mapping[str, Any],
    nsl_release: Mapping[str, Any],
    migration_heads: Mapping[str, Any],
    test_evidence: Mapping[str, Any],
    lineage: Mapping[str, Any],
    outcome: Mapping[str, Any],
) -> dict[str, Any]:
    package = {
        "schema_version": GOLDEN_A_EVIDENCE_SCHEMA_VERSION,
        "slice": "P8-S68",
        "gate": GOLDEN_A_GATE,
        "status": "PASS",
        "platform": dict(platform),
        "nsl_release": dict(nsl_release),
        "migration_heads": dict(migration_heads),
        "test_evidence": dict(test_evidence),
        "lineage": dict(lineage),
        "outcome": dict(outcome),
    }
    package["package_digest"] = semantic_sha256_hash_ref(package)
    validation = validate_golden_a_evidence_package(package)
    if validation["status"] != "PASS":
        raise ValueError(
            "Golden A evidence package is invalid: "
            + ", ".join(validation["failed_checks"])
        )
    return package


def validate_golden_a_evidence_package(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    package = dict(value) if isinstance(value, Mapping) else {}
    platform = _mapping(package.get("platform"))
    release = _mapping(package.get("nsl_release"))
    heads = _mapping(package.get("migration_heads"))
    tests = _mapping(package.get("test_evidence"))
    lineage = _mapping(package.get("lineage"))
    outcome = _mapping(package.get("outcome"))
    privacy_violations = _privacy_violations(package)
    expected_digest = semantic_sha256_hash_ref(
        {key: item for key, item in package.items() if key != "package_digest"}
    )
    checks = {
        "schema_exact": (
            set(package) == _TOP_LEVEL_FIELDS
            and package.get("schema_version") == GOLDEN_A_EVIDENCE_SCHEMA_VERSION
            and package.get("slice") == "P8-S68"
            and package.get("gate") == GOLDEN_A_GATE
            and package.get("status") == "PASS"
        ),
        "platform_identity_valid": (
            set(platform) == _PLATFORM_FIELDS
            and _matches(_HEX40, platform.get("commit"))
            and _matches(_HEX40, platform.get("tree"))
        ),
        "nsl_release_valid": (
            set(release) == _NSL_RELEASE_FIELDS
            and _matches(_HEX40, release.get("source_revision"))
            and _matches(_HEX40, release.get("source_tree"))
            and _matches(_HASH_REF, release.get("wheel_sha256"))
            and _matches(_HASH_REF, release.get("release_admission_hash"))
        ),
        "migration_heads_exact": (
            tuple(heads) == EXPECTED_MIGRATION_SERVICES
            and all(_matches(_MIGRATION, heads.get(service)) for service in heads)
        ),
        "protected_test_evidence_valid": (
            set(tests) == _TEST_FIELDS
            and tests.get("protected_gate_id") == "P8-S67"
            and _matches(_RUN_ID, tests.get("protected_run_id"))
            and _matches(_HASH_REF, tests.get("protected_evidence_digest"))
            and tests.get("actual_postgres") is True
            and tests.get("actual_remote_provider") is True
        ),
        "full_gate_evidence_valid": (
            set(tests) == _TEST_FIELDS
            and _matches(_SAFE_REF, tests.get("full_gate_id"))
            and _matches(_RUN_ID, tests.get("full_gate_run_id"))
            and _matches(_HASH_REF, tests.get("full_gate_evidence_digest"))
            and _positive_int(tests.get("passed_test_count"))
            and _nonnegative_int(tests.get("failed_test_count"))
            and tests.get("failed_test_count") == 0
            and _nonnegative_int(tests.get("skipped_test_count"))
            and _minimum_number(tests.get("statement_coverage"), 95.0)
            and _minimum_number(tests.get("branch_coverage"), 94.0)
        ),
        "lineage_valid": (
            set(lineage) == _LINEAGE_FIELDS
            and _uuid(lineage.get("business_operation_id"))
            and _matches(_SAFE_REF, lineage.get("nsl_execution_id"))
            and _matches(_SAFE_REF, lineage.get("approval_request_id"))
            and _uuid(lineage.get("approval_work_item_id"))
            and _matches(_VOUCHER_REF, lineage.get("voucher_ref"))
        ),
        "outcome_closed": (
            set(outcome) == _OUTCOME_FIELDS
            and outcome.get("commit_state") == "COMMITTED"
            and outcome.get("verification_status") == "VERIFIED"
            and _positive_int(outcome.get("business_mutation_count"))
            and outcome.get("business_mutation_count") == 1
            and _nonnegative_int(outcome.get("residue_count"))
            and outcome.get("residue_count") == 0
        ),
        "privacy_clean": not privacy_violations,
        "package_digest_valid": (
            _matches(_HASH_REF, package.get("package_digest"))
            and package.get("package_digest") == expected_digest
        ),
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    return {
        "status": "PASS" if not failed_checks else "FAIL",
        "checks": checks,
        "failed_checks": failed_checks,
        "privacy_violations": privacy_violations,
        "summary": {
            "check_count": len(checks),
            "passed_check_count": sum(bool(item) for item in checks.values()),
            "migration_head_count": len(heads),
            "business_mutation_count": outcome.get("business_mutation_count"),
            "residue_count": outcome.get("residue_count"),
        },
    }


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _matches(pattern: re.Pattern[str], value: object) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _uuid(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


def _positive_int(value: object) -> bool:
    return type(value) is int and value > 0


def _nonnegative_int(value: object) -> bool:
    return type(value) is int and value >= 0


def _minimum_number(value: object, minimum: float) -> bool:
    return type(value) in {int, float} and float(value) >= minimum


def _privacy_violations(value: object, *, path: str = "$") -> list[str]:
    violations: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            field = str(key).lower()
            current = f"{path}.{key}"
            if any(part in field for part in _FORBIDDEN_KEY_PARTS):
                violations.append(current)
            violations.extend(_privacy_violations(item, path=current))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            violations.extend(_privacy_violations(item, path=f"{path}[{index}]"))
    elif isinstance(value, str):
        lowered = value.lower()
        if any(marker in lowered for marker in _FORBIDDEN_VALUE_MARKERS):
            violations.append(path)
    return sorted(set(violations))
