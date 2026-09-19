from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Mapping

from nex_runtime.operational_events import (
    OperationalEventError,
    validate_operational_event,
)


AUDIT_EVENT_INTEGRITY_REPORT_SCHEMA_VERSION = "ag_audit_event_integrity_report.v1"
AUDIT_EVENT_INTEGRITY_ITEM_SCHEMA_VERSION = "ag_audit_event_integrity_item.v1"
AUDIT_INTEGRITY_HASH_ALGORITHM = "sha256_canonical_json"
MAX_AUDIT_INTEGRITY_EVENTS = 500
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class AuditIntegrityError(Exception):
    error_code: str
    detail: str
    status_code: int = 422

    def __str__(self) -> str:
        return self.detail


def build_audit_event_integrity_report(
    events: list[dict[str, Any]],
    *,
    expected_event_ids: list[str] | None = None,
    expected_event_hashes: Mapping[str, str] | None = None,
    checked_at: str | None = None,
) -> dict[str, Any]:
    if not isinstance(events, list):
        raise AuditIntegrityError(
            error_code="ag.audit_integrity.events_invalid",
            detail="events must be a list.",
        )
    if len(events) > MAX_AUDIT_INTEGRITY_EVENTS:
        raise AuditIntegrityError(
            error_code="ag.audit_integrity.events_limit_exceeded",
            detail=f"events cannot exceed {MAX_AUDIT_INTEGRITY_EVENTS} items.",
        )
    normalized_expected_ids = _expected_event_ids(expected_event_ids)
    normalized_expected_hashes = _expected_hashes(expected_event_hashes)
    observed_ids: set[str] = set()
    items: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    duplicate_count = 0
    invalid_count = 0
    hash_mismatch_count = 0

    for index, raw_event in enumerate(events):
        if not isinstance(raw_event, dict):
            invalid_count += 1
            issues.append(
                {
                    "issue_code": "event_not_object",
                    "source_index": index,
                    "event_id": None,
                }
            )
            continue
        event = deepcopy(raw_event)
        event_id = _optional_text(event.get("event_id"))
        if event_id is not None and event_id in observed_ids:
            duplicate_count += 1
            issues.append(
                {
                    "issue_code": "duplicate_event_id",
                    "source_index": index,
                    "event_id": event_id,
                }
            )
            continue
        try:
            validate_operational_event(event)
            _parse_timestamp(str(event["created_at"]), "created_at")
        except (OperationalEventError, AuditIntegrityError) as exc:
            invalid_count += 1
            issues.append(
                {
                    "issue_code": "event_invalid",
                    "source_index": index,
                    "event_id": event_id,
                    "error_code": exc.error_code,
                }
            )
            continue
        event_id = str(event["event_id"])
        observed_ids.add(event_id)
        event_hash = sha256_canonical_json(event)
        expected_hash = normalized_expected_hashes.get(event_id)
        item_status = "VALID"
        if expected_hash is not None and expected_hash != event_hash:
            item_status = "HASH_MISMATCH"
            hash_mismatch_count += 1
            issues.append(
                {
                    "issue_code": "event_hash_mismatch",
                    "source_index": index,
                    "event_id": event_id,
                    "expected_hash": expected_hash,
                    "observed_hash": event_hash,
                }
            )
        items.append(
            {
                "integrity_item_schema_version": (
                    AUDIT_EVENT_INTEGRITY_ITEM_SCHEMA_VERSION
                ),
                "event_id": event_id,
                "service_id": event["service_id"],
                "event_type": event["event_type"],
                "severity": event["severity"],
                "created_at": event["created_at"],
                "trace_id_present": _optional_text(event.get("trace_id"))
                is not None,
                "request_id_present": _optional_text(event.get("request_id"))
                is not None,
                "subject_ref_present": isinstance(event.get("subject_ref"), dict),
                "event_hash": event_hash,
                "integrity_status": item_status,
            }
        )

    missing_expected_ids = sorted(set(normalized_expected_ids) - observed_ids)
    issues.extend(
        {
            "issue_code": "expected_event_missing",
            "source_index": None,
            "event_id": event_id,
        }
        for event_id in missing_expected_ids
    )
    items.sort(
        key=lambda item: (
            _parse_timestamp(str(item["created_at"]), "created_at"),
            item["event_id"],
        )
    )
    issues.sort(
        key=lambda issue: (
            str(issue.get("event_id") or ""),
            str(issue.get("issue_code") or ""),
            -1 if issue.get("source_index") is None else int(issue["source_index"]),
        )
    )
    valid_count = len(items) - hash_mismatch_count
    integrity_status = "VERIFIED" if not issues else "FAILED"
    if not events and not normalized_expected_ids:
        integrity_status = "NO_EVENTS"
    verification_payload = {
        "hash_algorithm": AUDIT_INTEGRITY_HASH_ALGORITHM,
        "items": items,
        "issues": issues,
        "expected_event_ids": normalized_expected_ids,
    }
    return {
        "integrity_report_schema_version": (
            AUDIT_EVENT_INTEGRITY_REPORT_SCHEMA_VERSION
        ),
        "integrity_status": integrity_status,
        "checked_at": _normalized_checked_at(checked_at),
        "hash_algorithm": AUDIT_INTEGRITY_HASH_ALGORITHM,
        "report_hash": sha256_canonical_json(verification_payload),
        "summary": {
            "observed_count": len(events),
            "verified_item_count": len(items),
            "valid_count": valid_count,
            "invalid_count": invalid_count,
            "duplicate_event_id_count": duplicate_count,
            "missing_expected_count": len(missing_expected_ids),
            "hash_mismatch_count": hash_mismatch_count,
            "issue_count": len(issues),
        },
        "expected_events": {
            "event_ids": normalized_expected_ids,
            "expected_count": len(normalized_expected_ids),
            "all_present": not missing_expected_ids,
        },
        "items": items,
        "issues": issues,
        "redaction": {
            "event_details_included": False,
            "event_messages_included": False,
            "raw_payloads_included": False,
            "credentials_included": False,
            "storage_paths_included": False,
        },
    }


def sha256_canonical_json(value: Any) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def _expected_event_ids(value: list[str] | None) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise AuditIntegrityError(
            error_code="ag.audit_integrity.expected_event_ids_invalid",
            detail="expected_event_ids must be a list when supplied.",
        )
    result: list[str] = []
    for item in value:
        normalized = _optional_text(item)
        if normalized is None:
            raise AuditIntegrityError(
                error_code="ag.audit_integrity.expected_event_id_invalid",
                detail="expected event IDs must be non-empty strings.",
            )
        if normalized not in result:
            result.append(normalized)
    return sorted(result)


def _expected_hashes(value: Mapping[str, str] | None) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise AuditIntegrityError(
            error_code="ag.audit_integrity.expected_hashes_invalid",
            detail="expected_event_hashes must be an object when supplied.",
        )
    result: dict[str, str] = {}
    for event_id, event_hash in value.items():
        normalized_id = _optional_text(event_id)
        normalized_hash = _optional_text(event_hash)
        if normalized_id is None or normalized_hash is None:
            raise AuditIntegrityError(
                error_code="ag.audit_integrity.expected_hash_invalid",
                detail="expected event hash entries require non-empty strings.",
            )
        normalized_hash = normalized_hash.lower()
        if _SHA256_PATTERN.fullmatch(normalized_hash) is None:
            raise AuditIntegrityError(
                error_code="ag.audit_integrity.expected_hash_invalid",
                detail="expected event hashes must be lowercase SHA-256 hex.",
            )
        result[normalized_id] = normalized_hash
    return result


def _normalized_checked_at(value: str | None) -> str:
    if value is None:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")
    _parse_timestamp(value, "checked_at")
    return value


def _parse_timestamp(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AuditIntegrityError(
            error_code=f"ag.audit_integrity.{field_name}_invalid",
            detail=f"{field_name} must be an ISO-8601 datetime.",
        ) from exc
    if parsed.tzinfo is None:
        raise AuditIntegrityError(
            error_code=f"ag.audit_integrity.{field_name}_timezone_required",
            detail=f"{field_name} must include a timezone.",
        )
    return parsed


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None
