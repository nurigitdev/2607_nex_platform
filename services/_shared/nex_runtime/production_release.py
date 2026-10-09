from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import UTC, datetime
from hashlib import sha256
import json
import re
from typing import Any


RELEASE_MANIFEST_SCHEMA_VERSION = "s150_release_evidence_manifest.v1"
SAFE_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
SAFE_RAW_DIGEST = re.compile(r"^[0-9a-f]{64}$")
SAFE_REVISION = re.compile(r"^[0-9a-f]{40}$")
SAFE_RELEASE_ID = re.compile(r"^rc:s149:[0-9a-f]{16}$")
SAFE_CONTROL_ID = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
MAX_FUTURE_SKEW_SECONDS = 300
MAX_WAIVER_LIFETIME_SECONDS = 30 * 24 * 3600
REQUIRED_APPROVAL_ROLES = frozenset(
    {"data_owner", "operations_owner", "release_manager", "security_owner"}
)
DERIVED_MANIFEST_FIELDS = frozenset(
    {"checks", "failed_checks", "next_slice", "slice", "status", "summary"}
)
FORBIDDEN_KEY_PARTS = (
    "api_key",
    "authorization",
    "cookie",
    "database_url",
    "password",
    "private_key",
    "private_payload",
    "prompt_content",
    "provider_endpoint",
    "secret",
    "source_document",
    "storage_path",
    "token",
)


def build_release_evidence_manifest(
    closure: Mapping[str, Any],
    *,
    source_revision: str,
    observed_at: datetime,
) -> dict[str, Any]:
    if closure.get("status") != "PASS":
        raise ValueError("S149 closure must pass")
    if not SAFE_REVISION.fullmatch(source_revision):
        raise ValueError("source_revision must be a full Git revision")
    if observed_at.tzinfo is None:
        raise ValueError("observed_at must be timezone-aware")

    binding = _mapping(closure.get("release_binding"))
    regression = _mapping(closure.get("full_regression"))
    handoff = _mapping(closure.get("s150_handoff"))
    summary = _mapping(closure.get("summary"))
    manifest = {
        "manifest_schema_version": RELEASE_MANIFEST_SCHEMA_VERSION,
        "requirement": "S150",
        "release_candidate_id": binding.get("release_candidate_id"),
        "release_set_digest": binding.get("release_set_digest"),
        "source_revision": source_revision,
        "observed_at": observed_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "dependency_evidence": [
            {
                "kind": "s149_admission",
                "digest": binding.get("admission_evidence_digest"),
            },
            {
                "kind": "full_regression",
                "digest": _normalized_digest(
                    binding.get("full_regression_evidence_digest")
                ),
            },
            {
                "kind": "s149_closure",
                "digest": canonical_digest(closure),
            },
        ],
        "full_regression": {
            "status": regression.get("status"),
            "passed_test_count": regression.get("passed_test_count"),
            "failed_test_count": regression.get("failed_test_count"),
            "statement_coverage": regression.get("statement_coverage"),
            "branch_coverage": regression.get("branch_coverage"),
        },
        "single_host_backlog_count": summary.get("backlog_count"),
        "external_notification_waiver": handoff.get(
            "external_notification_waiver"
        ),
        "production_go_eligible": handoff.get("production_go_eligible"),
        "production_deployment_approved": closure.get(
            "production_deployment_approved"
        ),
    }
    manifest["manifest_digest"] = canonical_digest(manifest)
    return manifest


def validate_release_evidence_manifest(
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    dependencies = manifest.get("dependency_evidence")
    records = (
        [dict(item) for item in dependencies if isinstance(item, Mapping)]
        if isinstance(dependencies, Sequence)
        and not isinstance(dependencies, (str, bytes))
        else []
    )
    kinds = [item.get("kind") for item in records]
    regression = _mapping(manifest.get("full_regression"))
    privacy_violations = _privacy_violations(manifest)
    expected_digest = canonical_digest(
        {
            key: value
            for key, value in manifest.items()
            if key != "manifest_digest" and key not in DERIVED_MANIFEST_FIELDS
        }
    )
    checks = {
        "schema_and_requirement_valid": (
            manifest.get("manifest_schema_version")
            == RELEASE_MANIFEST_SCHEMA_VERSION
            and manifest.get("requirement") == "S150"
        ),
        "release_identity_valid": bool(
            SAFE_RELEASE_ID.fullmatch(str(manifest.get("release_candidate_id") or ""))
        )
        and bool(
            SAFE_SHA256.fullmatch(str(manifest.get("release_set_digest") or ""))
        ),
        "source_revision_valid": bool(
            SAFE_REVISION.fullmatch(str(manifest.get("source_revision") or ""))
        ),
        "observed_at_valid": _parse_timestamp(manifest.get("observed_at")) is not None,
        "dependency_inventory_exact": kinds
        == ["s149_admission", "full_regression", "s149_closure"],
        "dependency_digests_valid": len(records) == 3
        and all(SAFE_SHA256.fullmatch(str(item.get("digest") or "")) for item in records),
        "full_regression_passed": (
            regression.get("status") == "PASS"
            and int(regression.get("passed_test_count") or 0) > 0
            and regression.get("failed_test_count") == 0
            and float(regression.get("statement_coverage") or 0) >= 95.0
            and float(regression.get("branch_coverage") or 0) >= 94.0
        ),
        "single_host_backlog_preserved": manifest.get(
            "single_host_backlog_count"
        )
        == 5,
        "go_guard_preserved": (
            manifest.get("external_notification_waiver")
            == "REQUIRED_NOT_GRANTED"
            and manifest.get("production_go_eligible") is False
            and manifest.get("production_deployment_approved") is False
        ),
        "privacy_clean": not privacy_violations,
        "manifest_digest_valid": manifest.get("manifest_digest") == expected_digest,
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    return {
        "status": "PASS" if not failed_checks else "FAIL",
        "checks": checks,
        "failed_checks": failed_checks,
        "privacy_violations": privacy_violations,
        "summary": {
            "check_count": len(checks),
            "passed_check_count": sum(checks.values()),
            "dependency_count": len(records),
            "backlog_count": int(manifest.get("single_host_backlog_count") or 0),
        },
    }


def evaluate_release_evidence_admission(
    manifest: Mapping[str, Any],
    *,
    expected_release_candidate_id: str,
    expected_release_set_digest: str,
    evaluated_at: datetime,
    max_age_hours: int = 24,
) -> dict[str, Any]:
    if evaluated_at.tzinfo is None:
        raise ValueError("evaluated_at must be timezone-aware")
    if (
        not isinstance(max_age_hours, int)
        or isinstance(max_age_hours, bool)
        or max_age_hours < 1
    ):
        raise ValueError("max_age_hours must be a positive integer")
    validation = validate_release_evidence_manifest(manifest)
    observed_at = _parse_timestamp(manifest.get("observed_at"))
    age_seconds = (
        (evaluated_at.astimezone(UTC) - observed_at).total_seconds()
        if observed_at is not None
        else None
    )
    dependencies = manifest.get("dependency_evidence")
    records = (
        [dict(item) for item in dependencies if isinstance(item, Mapping)]
        if isinstance(dependencies, Sequence)
        and not isinstance(dependencies, (str, bytes))
        else []
    )
    dependency_digests = [str(item.get("digest") or "") for item in records]
    checks = {
        "manifest_validation_passed": validation["status"] == "PASS",
        "release_candidate_id_exact": manifest.get("release_candidate_id")
        == expected_release_candidate_id,
        "release_set_digest_exact": manifest.get("release_set_digest")
        == expected_release_set_digest,
        "go_live_window_24h": age_seconds is not None
        and age_seconds >= -MAX_FUTURE_SKEW_SECONDS
        and age_seconds <= max_age_hours * 3600,
        "dependency_digests_unique": len(dependency_digests) == 3
        and len(set(dependency_digests)) == 3,
        "production_deployment_separate": manifest.get(
            "production_deployment_approved"
        )
        is False,
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    return {
        "status": "PASS" if not failed_checks else "FAIL",
        "checks": checks,
        "failed_checks": failed_checks,
        "manifest_validation": validation,
        "age_seconds": round(age_seconds, 3) if age_seconds is not None else None,
        "max_age_seconds": max_age_hours * 3600,
        "summary": {
            "check_count": len(checks),
            "passed_check_count": sum(checks.values()),
            "dependency_count": len(records),
            "max_age_hours": max_age_hours,
        },
    }


def evaluate_release_risk_governance(
    risks: Sequence[Mapping[str, Any]],
    waivers: Sequence[Mapping[str, Any]],
    *,
    evaluated_at: datetime,
) -> dict[str, Any]:
    if evaluated_at.tzinfo is None:
        raise ValueError("evaluated_at must be timezone-aware")
    now = evaluated_at.astimezone(UTC)
    errors: list[str] = []
    risk_by_id: dict[str, dict[str, Any]] = {}
    for index, risk in enumerate(risks):
        record = dict(risk)
        risk_id = str(record.get("risk_id") or "")
        priority = record.get("priority")
        status = record.get("status")
        if not SAFE_CONTROL_ID.fullmatch(risk_id):
            errors.append(f"risk[{index}].risk_id")
        elif risk_id in risk_by_id:
            errors.append(f"risk[{index}].duplicate")
        else:
            risk_by_id[risk_id] = record
        if priority not in {"P0", "P1"}:
            errors.append(f"risk[{index}].priority")
        if status not in {"OPEN", "CLOSED"}:
            errors.append(f"risk[{index}].status")
        if status == "CLOSED" and not SAFE_SHA256.fullmatch(
            str(record.get("evidence_digest") or "")
        ):
            errors.append(f"risk[{index}].evidence_digest")

    waiver_by_risk: dict[str, dict[str, Any]] = {}
    waiver_validity: dict[str, bool] = {}
    for index, waiver in enumerate(waivers):
        record = dict(waiver)
        risk_id = str(record.get("risk_id") or "")
        waiver_id = str(record.get("waiver_id") or "")
        prefix = f"waiver[{index}]"
        waiver_errors: list[str] = []
        if not SAFE_CONTROL_ID.fullmatch(waiver_id):
            waiver_errors.append("waiver_id")
        if risk_id in waiver_by_risk:
            waiver_errors.append("duplicate_risk")
        risk = risk_by_id.get(risk_id)
        if not risk or risk.get("priority") != "P1" or risk.get("status") != "OPEN":
            waiver_errors.append("eligible_risk")
        owner = str(record.get("owner") or "")
        approver = str(record.get("approver") or "")
        if not owner or not approver or owner == approver:
            waiver_errors.append("owner_approver_separation")
        issued_at = _parse_timestamp(record.get("issued_at"))
        expires_at = _parse_timestamp(record.get("expires_at"))
        if (
            issued_at is None
            or expires_at is None
            or issued_at > now
            or expires_at <= now
            or expires_at <= issued_at
            or (expires_at - issued_at).total_seconds() > MAX_WAIVER_LIFETIME_SECONDS
        ):
            waiver_errors.append("validity_window")
        if not str(record.get("compensating_control") or "").strip():
            waiver_errors.append("compensating_control")
        if not str(record.get("rollback_trigger") or "").strip():
            waiver_errors.append("rollback_trigger")
        cadence = record.get("review_cadence_hours")
        if not isinstance(cadence, int) or isinstance(cadence, bool) or cadence < 1:
            waiver_errors.append("review_cadence_hours")
        waiver_by_risk[risk_id] = record
        waiver_validity[risk_id] = not waiver_errors
        errors.extend(f"{prefix}.{name}" for name in waiver_errors)

    open_p0 = sorted(
        risk_id
        for risk_id, risk in risk_by_id.items()
        if risk.get("priority") == "P0" and risk.get("status") == "OPEN"
    )
    open_p1 = sorted(
        risk_id
        for risk_id, risk in risk_by_id.items()
        if risk.get("priority") == "P1" and risk.get("status") == "OPEN"
    )
    uncovered_p1 = [
        risk_id for risk_id in open_p1 if not waiver_validity.get(risk_id, False)
    ]
    gate_results = {
        "no_open_p0": not open_p0,
        "p1_waivers_valid": not uncovered_p1,
    }
    return {
        "status": "PASS" if not errors else "FAIL",
        "errors": sorted(errors),
        "gate_results": gate_results,
        "decision_readiness": "GO" if all(gate_results.values()) and not errors else "NO_GO",
        "open_p0_risk_ids": open_p0,
        "open_p1_risk_ids": open_p1,
        "waiver_required_risk_ids": uncovered_p1,
        "summary": {
            "risk_count": len(risks),
            "waiver_count": len(waivers),
            "open_p0_count": len(open_p0),
            "open_p1_count": len(open_p1),
            "valid_waiver_count": sum(waiver_validity.values()),
        },
    }


def evaluate_release_approval_governance(
    approval_document: Mapping[str, Any],
    *,
    expected_release_candidate_id: str,
    expected_release_set_digest: str,
    evaluated_at: datetime,
) -> dict[str, Any]:
    if evaluated_at.tzinfo is None:
        raise ValueError("evaluated_at must be timezone-aware")
    now = evaluated_at.astimezone(UTC)
    errors: list[str] = []
    raw_approvals = approval_document.get("approvals", [])
    if not isinstance(raw_approvals, Sequence) or isinstance(
        raw_approvals, (str, bytes)
    ):
        raw_approvals = []
        errors.append("approvals.list")
    approvals_by_role: dict[str, dict[str, Any]] = {}
    for index, approval in enumerate(raw_approvals):
        prefix = f"approval[{index}]"
        if not isinstance(approval, Mapping):
            errors.append(f"{prefix}.mapping")
            continue
        record = dict(approval)
        role = str(record.get("role") or "")
        if role not in REQUIRED_APPROVAL_ROLES:
            errors.append(f"{prefix}.role")
        elif role in approvals_by_role:
            errors.append(f"{prefix}.duplicate_role")
        else:
            approvals_by_role[role] = record
        if not str(record.get("subject") or "").strip():
            errors.append(f"{prefix}.subject")
        if record.get("decision") != "APPROVE":
            errors.append(f"{prefix}.decision")
        if record.get("release_candidate_id") != expected_release_candidate_id:
            errors.append(f"{prefix}.release_candidate_id")
        if record.get("release_set_digest") != expected_release_set_digest:
            errors.append(f"{prefix}.release_set_digest")
        approved_at = _parse_timestamp(record.get("approved_at"))
        expires_at = _parse_timestamp(record.get("expires_at"))
        if (
            approved_at is None
            or expires_at is None
            or approved_at > now
            or expires_at <= now
            or expires_at <= approved_at
        ):
            errors.append(f"{prefix}.validity_window")

    missing_roles = sorted(REQUIRED_APPROVAL_ROLES - approvals_by_role.keys())
    change_window = approval_document.get("change_window")
    change_window_valid = False
    if change_window is not None:
        if not isinstance(change_window, Mapping):
            errors.append("change_window.mapping")
        else:
            window = dict(change_window)
            starts_at = _parse_timestamp(window.get("starts_at"))
            ends_at = _parse_timestamp(window.get("ends_at"))
            rollback_deadline = _parse_timestamp(window.get("rollback_deadline"))
            release_manager = approvals_by_role.get("release_manager", {})
            deployment_actor = str(window.get("deployment_actor") or "")
            change_window_valid = bool(
                SAFE_CONTROL_ID.fullmatch(str(window.get("change_id") or ""))
                and starts_at is not None
                and ends_at is not None
                and rollback_deadline is not None
                and starts_at <= now < ends_at <= rollback_deadline
                and deployment_actor
                and deployment_actor != release_manager.get("subject")
            )
            if not change_window_valid:
                errors.append("change_window.validity")

    deployment_separate = (
        approval_document.get("decision_only") is True
        and approval_document.get("deployment_execution_requested") is False
    )
    gate_results = {
        "approval_roles_complete": not missing_roles
        and not any(error.startswith("approval[") for error in errors)
        and change_window_valid,
        "production_deployment_separate": deployment_separate,
    }
    return {
        "status": "PASS" if not errors else "FAIL",
        "errors": sorted(errors),
        "gate_results": gate_results,
        "decision_readiness": "GO" if all(gate_results.values()) and not errors else "NO_GO",
        "missing_approval_roles": missing_roles,
        "change_window_valid": change_window_valid,
        "summary": {
            "required_role_count": len(REQUIRED_APPROVAL_ROLES),
            "approved_role_count": len(approvals_by_role),
            "missing_role_count": len(missing_roles),
        },
    }


def canonical_digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{sha256(encoded).hexdigest()}"


def _normalized_digest(value: object) -> str:
    candidate = str(value or "")
    if SAFE_SHA256.fullmatch(candidate):
        return candidate
    if SAFE_RAW_DIGEST.fullmatch(candidate):
        return f"sha256:{candidate}"
    return candidate


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else None


def _privacy_violations(value: object, *, path: str = "$") -> list[str]:
    violations: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            name = str(key)
            child = f"{path}.{name}"
            if any(part in name.lower() for part in FORBIDDEN_KEY_PARTS):
                violations.append(child)
            violations.extend(_privacy_violations(item, path=child))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, item in enumerate(value):
            violations.extend(_privacy_violations(item, path=f"{path}[{index}]"))
    return violations


def _mapping(value: object) -> dict[str, Any]:
    return deepcopy(dict(value)) if isinstance(value, Mapping) else {}
