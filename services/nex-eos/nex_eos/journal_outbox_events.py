from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from nex_runtime.semantic_hashes import validate_hash_ref

JOURNAL_POSTED_EVENT_SCHEMA = "eos_journal_posted_event.v1"

_FIELDS = frozenset(
    {
        "schema_version",
        "tenant_id",
        "business_operation_id",
        "operation",
        "company_id",
        "journal_id",
        "journal_no",
        "journal_hash",
        "candidate_id",
        "candidate_revision",
        "accounting_acceptance_id",
        "accounting_period_id",
        "project_codes",
        "commit_state",
        "posted_at",
    }
)
_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}$")
_OPERATION = re.compile(r"^[A-Z][A-Z0-9_.]{0,127}$")
_PROJECT_CODE = re.compile(r"^[A-Z0-9]{4}[DMSOIG][0-9]{6}$")


class EosJournalOutboxEventError(ValueError):
    pass


def build_journal_posted_event_payload(
    *,
    tenant_id: object,
    business_operation_id: object,
    operation: object,
    result: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        raise EosJournalOutboxEventError("Journal Posting result must be an object")
    return admit_journal_posted_event(
        {
            "schema_version": JOURNAL_POSTED_EVENT_SCHEMA,
            "tenant_id": tenant_id,
            "business_operation_id": business_operation_id,
            "operation": operation,
            "company_id": result.get("company_id"),
            "journal_id": result.get("journal_id"),
            "journal_no": result.get("journal_no"),
            "journal_hash": result.get("journal_hash"),
            "candidate_id": result.get("candidate_id"),
            "candidate_revision": result.get("candidate_revision"),
            "accounting_acceptance_id": result.get("accounting_acceptance_id"),
            "accounting_period_id": result.get("accounting_period_id"),
            "project_codes": result.get("project_codes"),
            "commit_state": "COMMITTED",
            "posted_at": result.get("posted_at"),
        }
    )


def admit_journal_posted_event(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _FIELDS:
        raise EosJournalOutboxEventError(
            "Journal Posted event fields do not match the canonical contract"
        )
    if value.get("schema_version") != JOURNAL_POSTED_EVENT_SCHEMA:
        raise EosJournalOutboxEventError("Journal Posted event schema is invalid")
    if value.get("commit_state") != "COMMITTED":
        raise EosJournalOutboxEventError("Journal Posted event must be committed")
    candidate_revision = value.get("candidate_revision")
    if (
        isinstance(candidate_revision, bool)
        or not isinstance(candidate_revision, int)
        or candidate_revision < 1
    ):
        raise EosJournalOutboxEventError("candidate_revision must be positive")
    return {
        "schema_version": JOURNAL_POSTED_EVENT_SCHEMA,
        "tenant_id": _pattern("tenant_id", value.get("tenant_id"), _SCOPED_ID),
        "business_operation_id": _uuid(
            "business_operation_id", value.get("business_operation_id")
        ),
        "operation": _pattern("operation", value.get("operation"), _OPERATION),
        "company_id": _uuid("company_id", value.get("company_id")),
        "journal_id": _uuid("journal_id", value.get("journal_id")),
        "journal_no": _pattern("journal_no", value.get("journal_no"), _SCOPED_ID),
        "journal_hash": _hash("journal_hash", value.get("journal_hash")),
        "candidate_id": _uuid("candidate_id", value.get("candidate_id")),
        "candidate_revision": candidate_revision,
        "accounting_acceptance_id": _uuid(
            "accounting_acceptance_id", value.get("accounting_acceptance_id")
        ),
        "accounting_period_id": _uuid(
            "accounting_period_id", value.get("accounting_period_id")
        ),
        "project_codes": _project_codes(value.get("project_codes")),
        "commit_state": "COMMITTED",
        "posted_at": _timestamp("posted_at", value.get("posted_at")),
    }


def _project_codes(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or not value:
        raise EosJournalOutboxEventError("project_codes must be a non-empty array")
    codes = [_pattern("project_code", item, _PROJECT_CODE) for item in value]
    if codes != sorted(set(codes)):
        raise EosJournalOutboxEventError(
            "project_codes must be sorted and contain unique values"
        )
    return codes


def _pattern(field_name: str, value: object, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise EosJournalOutboxEventError(f"{field_name} has an invalid format")
    return value


def _uuid(field_name: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise EosJournalOutboxEventError(f"{field_name} must be a UUID") from exc


def _hash(field_name: str, value: object) -> str:
    try:
        return validate_hash_ref(value)
    except (TypeError, ValueError, AttributeError) as exc:
        raise EosJournalOutboxEventError(
            f"{field_name} must be a sha256 hash reference"
        ) from exc


def _timestamp(field_name: str, value: object) -> str:
    if not isinstance(value, str):
        raise EosJournalOutboxEventError(f"{field_name} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EosJournalOutboxEventError(
            f"{field_name} must be an ISO timestamp"
        ) from exc
    if parsed.tzinfo is None:
        raise EosJournalOutboxEventError(f"{field_name} must include a timezone")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
