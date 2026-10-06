from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from .release_candidate import (
    RELEASE_CANDIDATE_EVIDENCE_SCHEMA_VERSION,
    evaluate_release_candidate_evidence,
)
from .release_candidate_protected_matrix import (
    FULL_REGRESSION_GATE_ID,
    RELEASE_CANDIDATE_PROTECTED_MATRIX_SCHEMA_VERSION,
)


RELEASE_CANDIDATE_CLOSURE_SCHEMA_VERSION = "platform_release_candidate_closure.v1"
DEFAULT_STATEMENT_COVERAGE_MIN = 95.0
DEFAULT_BRANCH_COVERAGE_MIN = 85.0


def load_full_regression_evidence(
    junit_path: Path,
    coverage_path: Path,
    *,
    observed_at: datetime | None = None,
    statement_min: float = DEFAULT_STATEMENT_COVERAGE_MIN,
    branch_min: float = DEFAULT_BRANCH_COVERAGE_MIN,
) -> dict[str, Any]:
    counts = _junit_counts(junit_path)
    coverage = _coverage_totals(coverage_path)
    statement_coverage = _percent(
        coverage["covered_lines"], coverage["num_statements"]
    )
    branch_coverage = _percent(
        coverage["covered_branches"], coverage["num_branches"]
    )
    passed = (
        counts["passed"] > 0
        and counts["failed"] == 0
        and statement_coverage >= statement_min
        and branch_coverage >= branch_min
    )
    evidence = {
        "evidence_schema_version": RELEASE_CANDIDATE_EVIDENCE_SCHEMA_VERSION,
        "gate_id": FULL_REGRESSION_GATE_ID,
        "status": "PASS" if passed else "FAIL",
        "execution_mode": "deterministic",
        "actual_execution": False,
        "private_payload_included": False,
        "observed_at": _utc_timestamp(observed_at),
        "metrics": {
            "passed_test_count": counts["passed"],
            "failed_test_count": counts["failed"],
            "skipped_test_count": counts["skipped"],
            "total_test_count": counts["total"],
            "statement_coverage": round(statement_coverage, 4),
            "statement_coverage_min": float(statement_min),
            "branch_coverage": round(branch_coverage, 4),
            "branch_coverage_min": float(branch_min),
        },
    }
    evidence["evidence_digest"] = _digest(evidence)
    return evidence


def build_release_candidate_closure(
    protected_matrix: Mapping[str, Any],
    full_regression: Mapping[str, Any],
    *,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    records = _records(protected_matrix.get("evidence"))
    placeholder_count = sum(
        record.get("gate_id") == FULL_REGRESSION_GATE_ID for record in records
    )
    evidence = [
        record
        for record in records
        if record.get("gate_id") != FULL_REGRESSION_GATE_ID
    ]
    evidence.append(dict(full_regression))
    evaluation = evaluate_release_candidate_evidence(
        {
            "production_deployment_approved": False,
            "evidence": evidence,
        },
        evaluated_at=evaluated_at,
    )
    evaluation_summary = _mapping(evaluation.get("summary"))
    protected_checks = _mapping(protected_matrix.get("checks"))
    checks = {
        "protected_matrix_schema_valid": protected_matrix.get("schema_version")
        == RELEASE_CANDIDATE_PROTECTED_MATRIX_SCHEMA_VERSION,
        "protected_matrix_ready_for_full_gate": (
            protected_matrix.get("status") == "PASS"
            and protected_matrix.get("readiness") == "READY_FOR_FULL_GATE"
        ),
        "protected_matrix_checks_passed": bool(protected_checks)
        and all(value is True for value in protected_checks.values()),
        "one_full_regression_placeholder_replaced": placeholder_count == 1,
        "fresh_full_regression_passed": (
            full_regression.get("gate_id") == FULL_REGRESSION_GATE_ID
            and full_regression.get("status") == "PASS"
        ),
        "nine_release_candidate_gates_passed": (
            evaluation.get("status") == "PASS"
            and evaluation_summary.get("required_gate_count") == 9
            and evaluation_summary.get("passed_gate_count") == 9
        ),
        "five_protected_gates_are_actual": (
            evaluation_summary.get("actual_protected_gate_count") == 5
        ),
        "privacy_safe": evaluation_summary.get("privacy_violation_count") == 0,
        "production_deployment_not_approved": (
            _mapping(evaluation.get("checks")).get("release_candidate_only") is True
        ),
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    passed = not failed_checks
    return {
        "schema_version": RELEASE_CANDIDATE_CLOSURE_SCHEMA_VERSION,
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "platform_release_candidate_closure_failed",
        "readiness": "RELEASE_CANDIDATE" if passed else "BLOCKED",
        "production_deployment_approved": False,
        "checks": checks,
        "failed_checks": failed_checks,
        "evaluation": evaluation,
        "summary": {
            "required_gate_count": 9,
            "passed_gate_count": evaluation_summary.get("passed_gate_count", 0),
            "actual_protected_gate_count": evaluation_summary.get(
                "actual_protected_gate_count", 0
            ),
            "privacy_violation_count": evaluation_summary.get(
                "privacy_violation_count", 0
            ),
            "passed_test_count": _mapping(full_regression.get("metrics")).get(
                "passed_test_count", 0
            ),
        },
    }


def _junit_counts(path: Path) -> dict[str, int]:
    root = ET.parse(path).getroot()
    if root.tag not in {"testsuite", "testsuites"}:
        raise ValueError("JUnit root must be testsuite or testsuites")
    if "tests" in root.attrib:
        suites = (root,)
    else:
        suites = tuple(
            suite
            for suite in root.iter("testsuite")
            if not any(child.tag == "testsuite" for child in suite)
        )
        if not suites:
            raise ValueError("JUnit testsuites root must contain test suites")
    total = sum(_nonnegative_int(suite.attrib.get("tests"), "tests") for suite in suites)
    failures = sum(
        _nonnegative_int(suite.attrib.get("failures", "0"), "failures")
        for suite in suites
    )
    errors = sum(
        _nonnegative_int(suite.attrib.get("errors", "0"), "errors")
        for suite in suites
    )
    skipped = sum(
        _nonnegative_int(suite.attrib.get("skipped", "0"), "skipped")
        for suite in suites
    )
    failed = failures + errors
    passed = total - failed - skipped
    if total < 1 or passed < 0:
        raise ValueError("JUnit counts are inconsistent")
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
    }


def _coverage_totals(path: Path) -> dict[str, int]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    totals = _mapping(payload.get("totals"))
    names = (
        "covered_lines",
        "num_statements",
        "covered_branches",
        "num_branches",
    )
    values = {name: _nonnegative_int(totals.get(name), name) for name in names}
    if values["num_statements"] < 1 or values["num_branches"] < 1:
        raise ValueError("coverage totals must include statements and branches")
    if (
        values["covered_lines"] > values["num_statements"]
        or values["covered_branches"] > values["num_branches"]
    ):
        raise ValueError("coverage totals are inconsistent")
    return values


def _nonnegative_int(value: object, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a non-negative integer")
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a non-negative integer") from exc
    if parsed < 0 or str(value).strip() != str(parsed):
        raise ValueError(f"{name} must be a non-negative integer")
    return parsed


def _percent(numerator: int, denominator: int) -> float:
    return numerator / denominator * 100.0


def _records(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _utc_timestamp(value: datetime | None) -> str:
    observed_at = value or datetime.now(UTC)
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=UTC)
    return observed_at.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _digest(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
