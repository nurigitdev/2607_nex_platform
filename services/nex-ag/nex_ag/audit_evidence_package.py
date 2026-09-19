from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Mapping

from nex_ag.audit_correlation import AUDIT_CORRELATION_REPORT_SCHEMA_VERSION
from nex_ag.audit_integrity import (
    AUDIT_EVENT_INTEGRITY_REPORT_SCHEMA_VERSION,
    sha256_canonical_json,
)


AUDIT_EVIDENCE_PACKAGE_SCHEMA_VERSION = "ag_audit_evidence_package.v1"
AUDIT_EVIDENCE_MANIFEST_SCHEMA_VERSION = "ag_audit_evidence_manifest.v1"
AUDIT_EVIDENCE_VERIFICATION_SCHEMA_VERSION = (
    "ag_audit_evidence_package_verification.v1"
)
AUDIT_EVIDENCE_HASH_ALGORITHM = "sha256_canonical_json"
MAX_AUDIT_EVIDENCE_EXPORTS = 500
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class AuditEvidencePackageError(Exception):
    error_code: str
    detail: str
    status_code: int = 422

    def __str__(self) -> str:
        return self.detail


def build_audit_evidence_package(
    *,
    integrity_report: Mapping[str, Any],
    correlation_report: Mapping[str, Any],
    evidence_exports: list[Mapping[str, Any]],
    generated_at: str | None = None,
) -> dict[str, Any]:
    integrity_ref = _report_ref(
        integrity_report,
        report_type="event_integrity",
        schema_field="integrity_report_schema_version",
        expected_schema=AUDIT_EVENT_INTEGRITY_REPORT_SCHEMA_VERSION,
        status_field="integrity_status",
    )
    correlation_ref = _report_ref(
        correlation_report,
        report_type="correlation_continuity",
        schema_field="correlation_report_schema_version",
        expected_schema=AUDIT_CORRELATION_REPORT_SCHEMA_VERSION,
        status_field="continuity_status",
    )
    nested_integrity = correlation_report.get("event_integrity")
    if not isinstance(nested_integrity, Mapping) or (
        nested_integrity.get("report_hash") != integrity_ref["report_hash"]
    ):
        raise AuditEvidencePackageError(
            error_code="ag.audit_evidence.report_link_mismatch",
            detail="Correlation report must reference the integrity report hash.",
        )
    export_refs = _export_refs(evidence_exports)
    _assert_correlation_export_links(correlation_report, export_refs)
    verification_status = _package_status(
        integrity_ref["status"],
        correlation_ref["status"],
    )
    manifest = {
        "manifest_schema_version": AUDIT_EVIDENCE_MANIFEST_SCHEMA_VERSION,
        "hash_algorithm": AUDIT_EVIDENCE_HASH_ALGORITHM,
        "reports": [integrity_ref, correlation_ref],
        "evidence_exports": export_refs,
        "summary": {
            "report_count": 2,
            "evidence_export_count": len(export_refs),
            "evidence_item_count": sum(
                item["evidence_item_count"] for item in export_refs
            ),
        },
        "redaction": {
            "raw_payloads_included": False,
            "event_messages_included": False,
            "event_details_included": False,
            "evidence_bodies_included": False,
            "credentials_included": False,
            "storage_paths_included": False,
        },
    }
    manifest_hash = sha256_canonical_json(manifest)
    package_hash = _package_hash(verification_status, manifest_hash)
    return {
        "package_schema_version": AUDIT_EVIDENCE_PACKAGE_SCHEMA_VERSION,
        "package_id": f"ag-audit-package-{package_hash[:32]}",
        "verification_status": verification_status,
        "generated_at": _timestamp(generated_at),
        "hash_algorithm": AUDIT_EVIDENCE_HASH_ALGORITHM,
        "manifest": manifest,
        "manifest_hash": manifest_hash,
        "package_hash": package_hash,
    }


def verify_audit_evidence_package(package: object) -> dict[str, Any]:
    issues: list[dict[str, str | None]] = []
    if not isinstance(package, Mapping):
        return _verification_result(
            package_id=None,
            expected_manifest_hash=None,
            observed_manifest_hash=None,
            expected_package_hash=None,
            observed_package_hash=None,
            issues=[_issue("package_not_object")],
        )

    package_id = _optional_text(package.get("package_id"))
    schema_version = package.get("package_schema_version")
    if schema_version != AUDIT_EVIDENCE_PACKAGE_SCHEMA_VERSION:
        issues.append(_issue("package_schema_version_invalid"))
    verification_status = _optional_text(package.get("verification_status"))
    if verification_status not in {"VERIFIED", "FAILED", "NO_EVIDENCE"}:
        issues.append(_issue("package_verification_status_invalid"))
    manifest = package.get("manifest")
    expected_manifest_hash = _normalized_hash(package.get("manifest_hash"))
    expected_package_hash = _normalized_hash(package.get("package_hash"))
    if expected_manifest_hash is None:
        issues.append(_issue("manifest_hash_invalid"))
    if expected_package_hash is None:
        issues.append(_issue("package_hash_invalid"))

    observed_manifest_hash: str | None = None
    observed_package_hash: str | None = None
    verified_package_id: str | None = None
    if not isinstance(manifest, Mapping):
        issues.append(_issue("manifest_not_object"))
    else:
        observed_manifest_hash = sha256_canonical_json(manifest)
        if expected_manifest_hash != observed_manifest_hash:
            issues.append(_issue("manifest_hash_mismatch"))
        issues.extend(_manifest_issues(manifest))
    if verification_status is not None and observed_manifest_hash is not None:
        observed_package_hash = _package_hash(
            verification_status,
            observed_manifest_hash,
        )
        if expected_package_hash != observed_package_hash:
            issues.append(_issue("package_hash_mismatch"))
        expected_id = f"ag-audit-package-{observed_package_hash[:32]}"
        if package_id != expected_id:
            issues.append(_issue("package_id_mismatch"))
        else:
            verified_package_id = package_id
    elif package_id is None:
        issues.append(_issue("package_id_invalid"))

    return _verification_result(
        package_id=verified_package_id,
        expected_manifest_hash=expected_manifest_hash,
        observed_manifest_hash=observed_manifest_hash,
        expected_package_hash=expected_package_hash,
        observed_package_hash=observed_package_hash,
        issues=issues,
    )


def _report_ref(
    report: Mapping[str, Any],
    *,
    report_type: str,
    schema_field: str,
    expected_schema: str,
    status_field: str,
) -> dict[str, str]:
    if not isinstance(report, Mapping):
        raise AuditEvidencePackageError(
            error_code="ag.audit_evidence.report_invalid",
            detail=f"{report_type} report must be an object.",
        )
    if report.get(schema_field) != expected_schema:
        raise AuditEvidencePackageError(
            error_code="ag.audit_evidence.report_schema_invalid",
            detail=f"{report_type} report schema is unsupported.",
        )
    report_hash = _normalized_hash(report.get("report_hash"))
    status = _optional_text(report.get(status_field))
    if report_hash is None or status is None:
        raise AuditEvidencePackageError(
            error_code="ag.audit_evidence.report_metadata_invalid",
            detail=f"{report_type} report hash and status are required.",
        )
    return {
        "report_type": report_type,
        "schema_version": expected_schema,
        "status": status,
        "report_hash": report_hash,
    }


def _export_refs(value: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise AuditEvidencePackageError(
            error_code="ag.audit_evidence.exports_invalid",
            detail="evidence_exports must be a list.",
        )
    if len(value) > MAX_AUDIT_EVIDENCE_EXPORTS:
        raise AuditEvidencePackageError(
            error_code="ag.audit_evidence.exports_limit_exceeded",
            detail=f"evidence_exports cannot exceed {MAX_AUDIT_EVIDENCE_EXPORTS} items.",
        )
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value_index, value_item in enumerate(value):
        if not isinstance(value_item, Mapping):
            raise AuditEvidencePackageError(
                error_code="ag.audit_evidence.export_invalid",
                detail=f"evidence_exports[{value_index}] must be an object.",
            )
        export_id = _required_text(value_item.get("export_id"), "export_id")
        if export_id in seen:
            raise AuditEvidencePackageError(
                error_code="ag.audit_evidence.export_duplicate",
                detail=f"Duplicate evidence export ID: {export_id}",
            )
        seen.add(export_id)
        evidence_hash = _normalized_hash(value_item.get("evidence_hash"))
        if evidence_hash is None:
            raise AuditEvidencePackageError(
                error_code="ag.audit_evidence.export_hash_invalid",
                detail=f"Evidence export hash is invalid: {export_id}",
            )
        item_count = value_item.get("evidence_item_count")
        if not isinstance(item_count, int) or isinstance(item_count, bool) or item_count < 0:
            raise AuditEvidencePackageError(
                error_code="ag.audit_evidence.export_item_count_invalid",
                detail=f"Evidence item count is invalid: {export_id}",
            )
        refs.append(
            {
                "export_id": export_id,
                "trace_id": _optional_text(value_item.get("trace_id")),
                "evidence_hash": evidence_hash,
                "evidence_item_count": item_count,
                "export_status": _required_text(
                    value_item.get("export_status"),
                    "export_status",
                ),
                "redaction_profile": _required_text(
                    value_item.get("redaction_profile"),
                    "redaction_profile",
                ),
            }
        )
    return sorted(refs, key=lambda item: item["export_id"])


def _assert_correlation_export_links(
    report: Mapping[str, Any],
    export_refs: list[dict[str, Any]],
) -> None:
    report_exports = report.get("evidence_exports")
    if not isinstance(report_exports, list):
        raise AuditEvidencePackageError(
            error_code="ag.audit_evidence.correlation_exports_invalid",
            detail="Correlation report evidence exports must be a list.",
        )
    correlation_by_id = {
        item.get("export_id"): item
        for item in report_exports
        if isinstance(item, Mapping) and _optional_text(item.get("export_id"))
    }
    for item in export_refs:
        linked = correlation_by_id.get(item["export_id"])
        if not isinstance(linked, Mapping) or linked.get("linked") is not True:
            raise AuditEvidencePackageError(
                error_code="ag.audit_evidence.export_not_correlated",
                detail=f"Evidence export is not linked to a trace: {item['export_id']}",
            )
        if (
            _optional_text(linked.get("trace_id")) != item["trace_id"]
            or _normalized_hash(linked.get("evidence_hash"))
            != item["evidence_hash"]
        ):
            raise AuditEvidencePackageError(
                error_code="ag.audit_evidence.export_correlation_mismatch",
                detail=f"Evidence export correlation differs: {item['export_id']}",
            )


def _package_status(
    integrity_status: str,
    correlation_status: str,
) -> str:
    if integrity_status == "NO_EVENTS" and correlation_status == "NO_CORRELATION":
        return "NO_EVIDENCE"
    if integrity_status == "VERIFIED" and correlation_status == "CONTIGUOUS":
        return "VERIFIED"
    return "FAILED"


def _manifest_issues(manifest: Mapping[str, Any]) -> list[dict[str, str | None]]:
    issues: list[dict[str, str | None]] = []
    if manifest.get("manifest_schema_version") != AUDIT_EVIDENCE_MANIFEST_SCHEMA_VERSION:
        issues.append(_issue("manifest_schema_version_invalid"))
    reports = manifest.get("reports")
    exports = manifest.get("evidence_exports")
    summary = manifest.get("summary")
    redaction = manifest.get("redaction")
    if not isinstance(reports, list) or len(reports) != 2:
        issues.append(_issue("manifest_reports_invalid"))
    if not isinstance(exports, list):
        issues.append(_issue("manifest_exports_invalid"))
        exports = []
    export_ids = [
        item.get("export_id")
        for item in exports
        if isinstance(item, Mapping)
    ]
    if len(export_ids) != len(set(export_ids)):
        issues.append(_issue("manifest_export_duplicate"))
    if any(
        not isinstance(item, Mapping)
        or _normalized_hash(item.get("evidence_hash")) is None
        for item in exports
    ):
        issues.append(_issue("manifest_export_hash_invalid"))
    if not isinstance(summary, Mapping) or (
        summary.get("report_count") != 2
        or summary.get("evidence_export_count") != len(exports)
        or summary.get("evidence_item_count")
        != sum(
            item.get("evidence_item_count", 0)
            for item in exports
            if isinstance(item, Mapping)
            and isinstance(item.get("evidence_item_count"), int)
        )
    ):
        issues.append(_issue("manifest_summary_mismatch"))
    if not isinstance(redaction, Mapping) or any(
        redaction.get(field) is not False
        for field in (
            "raw_payloads_included",
            "event_messages_included",
            "event_details_included",
            "evidence_bodies_included",
            "credentials_included",
            "storage_paths_included",
        )
    ):
        issues.append(_issue("manifest_redaction_invalid"))
    return issues


def _verification_result(
    *,
    package_id: str | None,
    expected_manifest_hash: str | None,
    observed_manifest_hash: str | None,
    expected_package_hash: str | None,
    observed_package_hash: str | None,
    issues: list[dict[str, str | None]],
) -> dict[str, Any]:
    return {
        "verification_schema_version": AUDIT_EVIDENCE_VERIFICATION_SCHEMA_VERSION,
        "verification_status": "VERIFIED" if not issues else "FAILED",
        "package_id": package_id,
        "expected_manifest_hash": expected_manifest_hash,
        "observed_manifest_hash": observed_manifest_hash,
        "expected_package_hash": expected_package_hash,
        "observed_package_hash": observed_package_hash,
        "issues": issues,
        "issue_count": len(issues),
    }


def _package_hash(status: str, manifest_hash: str) -> str:
    return sha256_canonical_json(
        {
            "package_schema_version": AUDIT_EVIDENCE_PACKAGE_SCHEMA_VERSION,
            "verification_status": status,
            "manifest_hash": manifest_hash,
        }
    )


def _issue(issue_code: str) -> dict[str, str | None]:
    return {"issue_code": issue_code, "subject_id": None}


def _required_text(value: object, field: str) -> str:
    normalized = _optional_text(value)
    if normalized is None:
        raise AuditEvidencePackageError(
            error_code=f"ag.audit_evidence.{field}_invalid",
            detail=f"{field} must be a non-empty string.",
        )
    return normalized


def _normalized_hash(value: object) -> str | None:
    normalized = _optional_text(value)
    if normalized is None:
        return None
    normalized = normalized.lower()
    return normalized if _SHA256_PATTERN.fullmatch(normalized) else None


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _timestamp(value: str | None) -> str:
    if value is None:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AuditEvidencePackageError(
            error_code="ag.audit_evidence.generated_at_invalid",
            detail="generated_at must be an ISO-8601 datetime.",
        ) from exc
    if parsed.tzinfo is None:
        raise AuditEvidencePackageError(
            error_code="ag.audit_evidence.generated_at_timezone_required",
            detail="generated_at must include a timezone.",
        )
    return value


__all__ = [
    "AUDIT_EVIDENCE_HASH_ALGORITHM",
    "AUDIT_EVIDENCE_MANIFEST_SCHEMA_VERSION",
    "AUDIT_EVIDENCE_PACKAGE_SCHEMA_VERSION",
    "AUDIT_EVIDENCE_VERIFICATION_SCHEMA_VERSION",
    "MAX_AUDIT_EVIDENCE_EXPORTS",
    "AuditEvidencePackageError",
    "build_audit_evidence_package",
    "verify_audit_evidence_package",
]
