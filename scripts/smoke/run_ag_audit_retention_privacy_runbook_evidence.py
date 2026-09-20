#!/usr/bin/env python3
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any, Callable, Mapping


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
AG_PATH = ROOT / "services" / "nex-ag"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(AG_PATH))

from nex_ag.audit_retention import (  # noqa: E402
    InMemoryAgRetentionCandidateStore,
    _sha256_json,
    build_ag_audit_retention_policy,
)
from nex_ag.audit_retention_archive import (  # noqa: E402
    AgArchiveReceiptError,
    InMemoryAgArchiveReceiptStore,
    build_ag_archive_receipt,
)
from nex_ag.audit_retention_operations import (  # noqa: E402
    build_ag_audit_retention_operations_projection,
)
from nex_ag.audit_retention_purge import (  # noqa: E402
    AgRetentionPurgeError,
    InMemoryAgRetentionPurgeStore,
    execute_ag_retention_purge,
)


SCHEMA_VERSION = "ag_audit_retention_privacy_runbook.v1"
SLICE_ID = "0889"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
EVIDENCE_HOOK = "run_ag_audit_retention_privacy_runbook_evidence.py"
POSTGRES_EVIDENCE_PATH = "docs/slices/0888_ag_audit_retention_postgresql_smoke.md"
AS_OF = "2026-09-20T12:00:00Z"
SOURCE_TIME = "2024-01-01T00:00:00Z"
FORBIDDEN_VALUES = {
    "database_url": "postgresql+psycopg://private-retention-runbook",
    "raw_message": "private-retention-message-0889",
    "raw_detail": "private-retention-detail-0889",
    "object_reference": "archive://private-retention-object-0889",
    "confirmation": "private-retention-confirmation-0889",
    "concurrent_error": "private-retention-concurrent-error-0889",
}
FORBIDDEN_KEYS = {
    "authorization",
    "confirmation",
    "credential",
    "database_url",
    "details",
    "message",
    "object_ref",
    "password",
    "raw_payload",
    "secret",
    "storage_path",
}
REQUIRED_DOCS = tuple(
    f"docs/slices/{slice_id}_{name}.md"
    for slice_id, name in (
        ("0881", "ag_audit_retention_archive_purge_boundary_audit"),
        ("0882", "ag_audit_retention_archive_policy"),
        ("0883", "ag_audit_retention_candidate_read_model"),
        ("0884", "ag_archive_receipt_persistence_sealing"),
        ("0885", "ag_guarded_physical_purge_execution"),
        ("0886", "ag_audit_retention_operations_projection"),
        ("0887", "ag_audit_retention_contract_index_hardening"),
        ("0888", "ag_audit_retention_postgresql_smoke"),
    )
)


def run_ag_audit_retention_privacy_runbook_evidence(
    root: Path = ROOT,
) -> dict[str, Any]:
    source = _source_record()
    candidate = _candidate(source)
    default_policy = build_ag_audit_retention_policy({})
    external_policy = build_ag_audit_retention_policy(
        {
            "NEX_AG_ARCHIVE_PROVIDER_MODE": "external",
            "NEX_AG_RETENTION_EXECUTE_ENABLED": "true",
            "NEX_AG_ARCHIVE_GRACE_DAYS": "1",
        }
    )
    mock_receipt = _receipt(candidate, provider_mode="mock", archived_at="2026-08-01T00:00:00Z")
    mock_store = _store(source=source, receipt=mock_receipt)
    mock_dry_run = _execute(
        store=mock_store,
        policy=default_policy,
        mode="DRY_RUN",
    )
    mock_execute = _execute(
        store=mock_store,
        policy=default_policy,
        mode="EXECUTE",
        confirmation=FORBIDDEN_VALUES["confirmation"],
    )

    missing_receipt = _execute(
        store=_store(source=source),
        policy=external_policy,
        mode="DRY_RUN",
    )
    grace_active = _execute(
        store=_store(
            source=source,
            receipt=_receipt(candidate, archived_at=AS_OF),
        ),
        policy=external_policy,
        mode="DRY_RUN",
    )
    due_receipt = _receipt(
        candidate,
        archived_at="2026-08-01T00:00:00Z",
    )
    hash_mismatch = _execute(
        store=_store(
            source={**source, "message": "changed-after-archive"},
            receipt=due_receipt,
        ),
        policy=external_policy,
        mode="DRY_RUN",
    )
    source_missing = _execute(
        store=_store(receipt=due_receipt),
        policy=external_policy,
        mode="DRY_RUN",
    )
    confirmation_required = _execute(
        store=_store(source=source, receipt=due_receipt),
        policy=external_policy,
        mode="EXECUTE",
        confirmation=FORBIDDEN_VALUES["confirmation"],
    )
    lifecycle_store = _store(source=source, receipt=due_receipt)
    purge_success = _execute(
        store=lifecycle_store,
        policy=external_policy,
        mode="EXECUTE",
        confirmation="PURGE",
    )
    idempotent_retry = _execute(
        store=lifecycle_store,
        policy=external_policy,
        mode="EXECUTE",
        confirmation="PURGE",
    )
    archive_not_recoverable = _capture_archive_error(
        lambda: build_ag_archive_receipt(
            candidate=candidate,
            provider_result={
                "provider_mode": "external",
                "content_sha256": candidate["content_sha256"],
                "object_ref": FORBIDDEN_VALUES["object_reference"],
                "receipt_sha256": _sha256_text("not-recoverable"),
                "recoverable": False,
            },
            archived_at="2026-08-01T00:00:00Z",
            grace_days=1,
        )
    )
    concurrent_change = _capture_purge_error(
        lambda: _execute(
            store=_ConcurrentChangeStore(due_receipt),
            policy=external_policy,
            mode="EXECUTE",
            confirmation="PURGE",
        )
    )
    projection_receipts = InMemoryAgArchiveReceiptStore()
    projection_receipts.save(due_receipt)
    projection = build_ag_audit_retention_operations_projection(
        policy=external_policy,
        candidate_store=InMemoryAgRetentionCandidateStore(
            event_records=[source]
        ),
        receipt_store=projection_receipts,
        as_of=AS_OF,
    )
    postgres_evidence = _postgres_evidence(
        _read_text(root / POSTGRES_EVIDENCE_PATH)
    )
    runbook = _runbook_actions()
    surfaces = {
        "default_policy": default_policy,
        "mock_dry_run": mock_dry_run,
        "mock_execute": mock_execute,
        "missing_receipt": missing_receipt,
        "archive_grace_active": grace_active,
        "source_hash_mismatch": hash_mismatch,
        "source_missing": source_missing,
        "confirmation_required": confirmation_required,
        "purge_success": purge_success,
        "idempotent_retry": idempotent_retry,
        "archive_not_recoverable": archive_not_recoverable,
        "concurrent_change": concurrent_change,
        "operations_projection": projection,
        "postgres_evidence": postgres_evidence,
        "runbook": runbook,
    }
    serialized = json.dumps(surfaces, ensure_ascii=False, sort_keys=True)
    forbidden_value_labels = _forbidden_value_labels(serialized)
    forbidden_key_paths = _forbidden_key_paths(surfaces)
    required_docs = [
        {"path": path, "present": (root / path).exists()} for path in REQUIRED_DOCS
    ]
    quality_gate_hook_present = EVIDENCE_HOOK in _read_text(
        root / QUALITY_GATE_PATH
    )
    checks = {
        "default_is_mock_and_execute_disabled": (
            default_policy["archive"]["provider_mode"] == "mock"
            and default_policy["purge"]["execute_enabled"] is False
            and default_policy["purge"]["dry_run_default"] is True
        ),
        "mock_never_authorizes_purge": (
            mock_dry_run["status"] == "BLOCKED"
            and mock_dry_run["reason"] == "receipt_not_sealed"
            and mock_execute["status"] == "BLOCKED"
            and mock_execute["reason"] == "execute_disabled"
        ),
        "receipt_and_recoverability_are_required": (
            missing_receipt["reason"] == "receipt_missing"
            and archive_not_recoverable["error_code"]
            == "ag.retention.external_archive_not_recoverable"
        ),
        "grace_and_source_rechecks_are_enforced": (
            grace_active["reason"] == "archive_grace_active"
            and hash_mismatch["reason"] == "source_hash_mismatch"
            and source_missing["reason"] == "source_missing"
        ),
        "confirmation_is_required_and_redacted": (
            confirmation_required["reason"] == "confirmation_required"
            and confirmation_required["confirmation_included"] is False
        ),
        "purge_is_idempotent": (
            purge_success["status"] == "PURGED"
            and purge_success["deleted_count"] == 1
            and idempotent_retry["status"] == "NOOP"
            and idempotent_retry["idempotent_noop"] is True
        ),
        "concurrent_change_is_normalized": (
            concurrent_change["error_code"]
            == "ag.retention.purge_concurrent_change"
            and concurrent_change["status_code"] == 409
        ),
        "projection_is_redacted": (
            projection["privacy"]
            == {
                "raw_payload_included": False,
                "object_reference_included": False,
                "credentials_included": False,
                "confirmation_included": False,
            }
        ),
        "postgres_evidence_is_complete": all(postgres_evidence.values()),
        "runbook_complete": set(runbook)
        == {
            "mock_or_execute_disabled",
            "archive_not_recoverable",
            "receipt_missing",
            "archive_grace_active",
            "source_hash_mismatch",
            "source_missing",
            "confirmation_required",
            "concurrent_change",
            "idempotent_retry",
            "migration_or_index_missing",
            "postgres_connectivity",
            "smoke_cleanup_failure",
        },
        "forbidden_values_absent": not forbidden_value_labels,
        "forbidden_keys_absent": not forbidden_key_paths,
        "docs_present": all(item["present"] for item in required_docs),
        "quality_gate_hook_present": quality_gate_hook_present,
    }
    passed = all(checks.values())
    evidence = {
        "runbook_schema_version": SCHEMA_VERSION,
        "status": "PASS" if passed else "FAIL",
        "failure_code": None
        if passed
        else "ag_audit_retention_privacy_runbook_failed",
        "slice": SLICE_ID,
        "surface_count": len(surfaces) - 1,
        "surfaces": surfaces,
        "required_docs": required_docs,
        "forbidden_value_labels": forbidden_value_labels,
        "forbidden_key_paths": forbidden_key_paths,
        "checks": checks,
    }
    _assert_no_forbidden_values(json.dumps(evidence, ensure_ascii=False))
    return evidence


def _source_record() -> dict[str, Any]:
    return {
        "event_id": "event-0889",
        "service_id": "nex-ag",
        "event_type": "ag.audit_retention.runbook_source",
        "severity": "INFO",
        "trace_id": "a" * 32,
        "request_id": "request-0889",
        "subject_type": "retention_runbook",
        "subject_id": "source-0889",
        "message": FORBIDDEN_VALUES["raw_message"],
        "details": {"secret": FORBIDDEN_VALUES["raw_detail"]},
        "created_at": SOURCE_TIME,
    }


def _candidate(source: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "candidate_id": _sha256_text("operational_event:event-0889"),
        "source_kind": "operational_event",
        "source_id": "event-0889",
        "content_sha256": _sha256_json(source),
    }


def _receipt(
    candidate: Mapping[str, Any],
    *,
    provider_mode: str = "external",
    archived_at: str,
) -> dict[str, Any]:
    recoverable = provider_mode == "external"
    return build_ag_archive_receipt(
        candidate=candidate,
        provider_result={
            "provider_mode": provider_mode,
            "content_sha256": candidate["content_sha256"],
            "object_ref": FORBIDDEN_VALUES["object_reference"],
            "receipt_sha256": _sha256_text(f"{provider_mode}:receipt"),
            "recoverable": recoverable,
        },
        archived_at=archived_at,
        grace_days=1,
    )


def _store(
    *,
    source: Mapping[str, Any] | None = None,
    receipt: Mapping[str, Any] | None = None,
) -> InMemoryAgRetentionPurgeStore:
    receipt_store = InMemoryAgArchiveReceiptStore()
    if receipt is not None:
        receipt_store.save(receipt)
    records = (
        {("operational_event", "event-0889"): dict(source)}
        if source is not None
        else {}
    )
    return InMemoryAgRetentionPurgeStore(
        receipt_store=receipt_store,
        source_records=records,
    )


def _execute(
    *,
    store: Any,
    policy: Mapping[str, Any],
    mode: str,
    confirmation: str | None = None,
) -> dict[str, Any]:
    return execute_ag_retention_purge(
        store=store,
        policy=policy,
        source_kind="operational_event",
        source_id="event-0889",
        as_of=AS_OF,
        mode=mode,
        confirmation=confirmation,
    )


class _ConcurrentChangeStore:
    def __init__(self, receipt: Mapping[str, Any]) -> None:
        self.receipt = receipt

    def assess(self, **_: object) -> dict[str, Any]:
        return {
            "source_kind": "operational_event",
            "source_id": "event-0889",
            "as_of": AS_OF,
            "archive_id": self.receipt["archive_id"],
            "archive_status": "SEALED",
            "eligible": True,
            "idempotent_noop": False,
            "reason": "eligible",
        }

    def purge(self, **_: object) -> dict[str, Any]:
        raise AgRetentionPurgeError(
            error_code="ag.retention.purge_concurrent_change",
            detail=FORBIDDEN_VALUES["concurrent_error"],
            status_code=409,
        )


def _capture_archive_error(operation: Callable[[], Any]) -> dict[str, Any]:
    try:
        operation()
    except AgArchiveReceiptError as exc:
        return {
            "error_code": exc.error_code,
            "detail": "AG archive receipt was rejected safely.",
        }
    raise AssertionError("archive operation did not fail")


def _capture_purge_error(operation: Callable[[], Any]) -> dict[str, Any]:
    try:
        operation()
    except AgRetentionPurgeError as exc:
        return {
            "error_code": exc.error_code,
            "detail": "AG retention purge failed safely.",
            "status_code": exc.status_code,
        }
    raise AssertionError("purge operation did not fail")


def _postgres_evidence(document: str) -> dict[str, bool]:
    return {
        "live_smoke_passed": "live smoke: PASS" in document,
        "test_database_selected": "database=nex_ag_test" in document,
        "two_candidates_purged": "candidates=2 purged=2" in document,
        "indexes_observed": "indexes=2" in document,
        "migration_observed": "migration_present=true" in document,
        "cleanup_verified": (
            "cleaned=True" in document
            and "event_residue=0 export_residue=0 receipt_residue=0" in document
        ),
    }


def _runbook_actions() -> dict[str, dict[str, Any]]:
    return {
        "mock_or_execute_disabled": {
            "retryable": False,
            "action": "keep dry-run and configure an approved external archive first",
        },
        "archive_not_recoverable": {
            "retryable": False,
            "action": "reject the receipt and verify archive retrieval before sealing",
        },
        "receipt_missing": {
            "retryable": True,
            "action": "archive the exact candidate and persist its receipt",
        },
        "archive_grace_active": {
            "retryable": True,
            "action": "wait until purge_after without changing the receipt",
        },
        "source_hash_mismatch": {
            "retryable": False,
            "action": "stop purge and reconcile the changed source with a new archive",
        },
        "source_missing": {
            "retryable": False,
            "action": "investigate deletion history before altering the tombstone",
        },
        "confirmation_required": {
            "retryable": True,
            "action": "repeat only after operator review with explicit confirmation",
        },
        "concurrent_change": {
            "retryable": True,
            "action": "reload source and receipt state before another dry-run",
        },
        "idempotent_retry": {
            "retryable": False,
            "action": "accept NOOP and preserve the PURGED tombstone",
        },
        "migration_or_index_missing": {
            "retryable": False,
            "action": "apply AG migrations and verify both retention indexes",
        },
        "postgres_connectivity": {
            "retryable": True,
            "action": "verify the test profile and redacted connection target",
        },
        "smoke_cleanup_failure": {
            "retryable": False,
            "action": "remove only smoke-owned sources and receipts, then verify zero residue",
        },
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _forbidden_value_labels(serialized: str) -> list[str]:
    return sorted(
        label for label, value in FORBIDDEN_VALUES.items() if value in serialized
    )


def _forbidden_key_paths(value: object, prefix: str = "") -> list[str]:
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if str(key).lower() in FORBIDDEN_KEYS:
                paths.append(path)
            paths.extend(_forbidden_key_paths(child, path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            paths.extend(_forbidden_key_paths(child, f"{prefix}[{index}]"))
    return paths


def _assert_no_forbidden_values(serialized: str) -> None:
    labels = _forbidden_value_labels(serialized)
    if labels:
        raise ValueError(f"privacy evidence contains forbidden values: {labels}")


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sha256_text(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def summary_line(evidence: Mapping[str, Any]) -> str:
    status = str(evidence.get("status") or "FAIL").lower()
    if status != "pass":
        return (
            "ag_audit_retention_privacy_runbook=fail "
            f"failure={evidence.get('failure_code') or 'unknown'}"
        )
    checks = _mapping(evidence.get("checks"))
    return (
        "ag_audit_retention_privacy_runbook=pass "
        f"surfaces={evidence.get('surface_count')} "
        f"privacy={checks.get('forbidden_values_absent')} "
        f"postgres={checks.get('postgres_evidence_is_complete')} "
        f"runbook={checks.get('runbook_complete')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_ag_audit_retention_privacy_runbook_evidence()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False)
    )
    return 1 if evidence.get("status") == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
