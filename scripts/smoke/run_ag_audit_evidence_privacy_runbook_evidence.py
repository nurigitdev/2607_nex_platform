#!/usr/bin/env python3
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
AG_PATH = ROOT / "services" / "nex-ag"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(AG_PATH))

from nex_ag.audit_correlation import (  # noqa: E402
    build_audit_correlation_continuity_report,
)
from nex_ag.audit_evidence_operations import (  # noqa: E402
    build_audit_evidence_operations_projection,
)
from nex_ag.audit_evidence_package import (  # noqa: E402
    build_audit_evidence_package,
    verify_audit_evidence_package,
)
from nex_ag.audit_integrity import (  # noqa: E402
    build_audit_event_integrity_report,
    sha256_canonical_json,
)
from nex_ag.operator_reviews import OperatorEvidenceExportStore  # noqa: E402
from nex_runtime import (  # noqa: E402
    InMemoryOperationalEventStore,
    build_operational_event,
)


SCHEMA_VERSION = "ag_audit_evidence_privacy_runbook.v1"
SLICE_ID = "0869"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
EVIDENCE_HOOK = "run_ag_audit_evidence_privacy_runbook_evidence.py"
POSTGRES_EVIDENCE_PATH = (
    "docs/slices/0868_ag_audit_evidence_postgresql_smoke.md"
)
CHECKED_AT = "2026-09-20T10:00:00Z"
TRACE_ID = "a" * 32
FORBIDDEN_VALUES = {
    "database_password": "nuri1004",
    "database_url": (
        "postgresql+psycopg://nex_ag_user:nuri1004@127.0.0.1:5432/nex_ag_test"
    ),
    "raw_event_message": "private-audit-event-message-0869",
    "raw_event_credential": "private-audit-event-credential-0869",
    "raw_export_body": "private-audit-export-body-0869",
    "untrusted_package_id": "private-untrusted-package-id-0869",
}
FORBIDDEN_KEYS = {
    "authorization",
    "credential",
    "database_url",
    "details",
    "evidence_manifest",
    "message",
    "raw_body",
    "raw_payload",
    "raw_prompt",
    "secret",
    "storage_path",
}
REQUIRED_DOCS = tuple(
    f"docs/slices/{slice_id}_{name}.md"
    for slice_id, name in (
        ("0861", "ag_audit_integrity_evidence_boundary_audit"),
        ("0862", "ag_audit_event_integrity_contract"),
        ("0863", "ag_audit_trace_correlation_continuity"),
        ("0864", "ag_audit_evidence_package_builder"),
        ("0865", "ag_audit_evidence_protected_api"),
        ("0866", "ag_audit_integrity_operations_projection"),
        ("0867", "ag_audit_evidence_contract_hardening"),
        ("0868", "ag_audit_evidence_postgresql_smoke"),
    )
)


def run_ag_audit_evidence_privacy_runbook_evidence(
    root: Path = ROOT,
) -> dict[str, Any]:
    source_event = _source_event()
    original_event = deepcopy(source_event)
    source_export = _source_export()
    event_hash = sha256_canonical_json(source_event)
    verified_integrity = build_audit_event_integrity_report(
        [source_event],
        expected_event_ids=[source_event["event_id"]],
        expected_event_hashes={source_event["event_id"]: event_hash},
        checked_at=CHECKED_AT,
    )
    hash_mismatch = build_audit_event_integrity_report(
        [source_event],
        expected_event_hashes={source_event["event_id"]: "0" * 64},
        checked_at=CHECKED_AT,
    )
    duplicate = build_audit_event_integrity_report(
        [source_event, deepcopy(source_event)],
        checked_at=CHECKED_AT,
    )
    missing = build_audit_event_integrity_report(
        [source_event],
        expected_event_ids=["missing-event-0869"],
        checked_at=CHECKED_AT,
    )
    contiguous = build_audit_correlation_continuity_report(
        [source_event],
        evidence_exports=[source_export],
        expected_event_ids=[source_event["event_id"]],
        expected_trace_ids=[TRACE_ID],
        required_event_types=[source_event["event_type"]],
        checked_at=CHECKED_AT,
    )
    orphaned = build_audit_correlation_continuity_report(
        [source_event],
        evidence_exports=[
            {
                **source_export,
                "trace_id": "b" * 32,
            }
        ],
        expected_trace_ids=[TRACE_ID],
        checked_at=CHECKED_AT,
    )
    package = build_audit_evidence_package(
        integrity_report=verified_integrity,
        correlation_report=contiguous,
        evidence_exports=[source_export],
        generated_at=CHECKED_AT,
    )
    repeated_package = build_audit_evidence_package(
        integrity_report=verified_integrity,
        correlation_report=contiguous,
        evidence_exports=[source_export],
        generated_at="2026-09-20T19:00:00+09:00",
    )
    verified_package = verify_audit_evidence_package(package)
    tampered_package = deepcopy(package)
    tampered_package["manifest"]["summary"]["evidence_item_count"] = 999
    tamper_verification = verify_audit_evidence_package(tampered_package)
    untrusted_verification = verify_audit_evidence_package(
        {
            "package_id": FORBIDDEN_VALUES["untrusted_package_id"],
            "secret": FORBIDDEN_VALUES["raw_export_body"],
        }
    )
    event_source_failure = build_audit_evidence_operations_projection(
        event_store=_FailingEventStore(),  # type: ignore[arg-type]
        export_store=OperatorEvidenceExportStore(),
    )
    export_source_failure = build_audit_evidence_operations_projection(
        event_store=InMemoryOperationalEventStore(),
        export_store=_FailingExportStore(),
    )
    runbook = _runbook_actions()
    surfaces = {
        "verified_integrity": verified_integrity,
        "hash_mismatch": hash_mismatch,
        "duplicate_event": duplicate,
        "missing_event": missing,
        "contiguous_correlation": contiguous,
        "orphaned_export": orphaned,
        "package": package,
        "package_verification": verified_package,
        "manifest_tamper": tamper_verification,
        "untrusted_package": untrusted_verification,
        "event_source_failure": event_source_failure,
        "export_source_failure": export_source_failure,
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
    postgres_evidence = _read_text(root / POSTGRES_EVIDENCE_PATH)
    checks = {
        "verified_integrity_passes": (
            verified_integrity["integrity_status"] == "VERIFIED"
            and verified_integrity["summary"]["issue_count"] == 0
        ),
        "hash_mismatch_detected": (
            hash_mismatch["integrity_status"] == "FAILED"
            and _has_issue(hash_mismatch, "event_hash_mismatch")
        ),
        "duplicate_and_missing_detected": (
            _has_issue(duplicate, "duplicate_event_id")
            and _has_issue(missing, "expected_event_missing")
        ),
        "correlation_failure_detected": (
            contiguous["continuity_status"] == "CONTIGUOUS"
            and orphaned["continuity_status"] == "FAILED"
            and _has_issue(orphaned, "evidence_export_trace_orphaned")
        ),
        "package_is_deterministic": (
            package["manifest_hash"] == repeated_package["manifest_hash"]
            and package["package_hash"] == repeated_package["package_hash"]
            and package["package_id"] == repeated_package["package_id"]
        ),
        "valid_package_verifies": (
            verified_package["verification_status"] == "VERIFIED"
            and verified_package["issue_count"] == 0
        ),
        "manifest_tamper_rejected": (
            tamper_verification["verification_status"] == "FAILED"
            and tamper_verification["package_id"] is None
            and _has_issue(tamper_verification, "manifest_hash_mismatch")
        ),
        "untrusted_identifier_not_echoed": (
            untrusted_verification["verification_status"] == "FAILED"
            and untrusted_verification["package_id"] is None
        ),
        "source_failures_degrade_safely": (
            event_source_failure["integrity_status"] == "SOURCE_UNAVAILABLE"
            and export_source_failure["integrity_status"] == "SOURCE_UNAVAILABLE"
            and "private" not in json.dumps(
                [event_source_failure, export_source_failure]
            )
        ),
        "historical_event_not_mutated": source_event == original_event,
        "runbook_complete": set(runbook)
        == {
            "hash_mismatch",
            "duplicate_or_missing_event",
            "correlation_failure",
            "manifest_tamper",
            "untrusted_package",
            "source_unavailable",
            "historical_immutability",
            "postgres_rerun_cleanup",
            "external_notary_deferred",
        },
        "postgres_evidence_present": (
            "ag_audit_evidence_postgres_smoke=pass" in postgres_evidence
            and "cleaned=True" in postgres_evidence
            and "|0|0" in postgres_evidence
        ),
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
        else "ag_audit_evidence_privacy_runbook_failed",
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


def _source_event() -> dict[str, Any]:
    return build_operational_event(
        service_id="nex-ag",
        event_type="ag.audit_evidence.runbook_source",
        severity="WARNING",
        message=FORBIDDEN_VALUES["raw_event_message"],
        trace_id=TRACE_ID,
        request_id="request-0869",
        subject_ref={"type": "audit_runbook", "id": "source-0869"},
        details={
            "credential": FORBIDDEN_VALUES["raw_event_credential"],
            "raw_body": FORBIDDEN_VALUES["raw_export_body"],
        },
        created_at="2026-09-20T09:59:00Z",
        event_id="event-0869",
    )


def _source_export() -> dict[str, Any]:
    return {
        "export_id": "export-0869",
        "trace_id": TRACE_ID,
        "evidence_hash": sha256_canonical_json(
            {"raw_body": FORBIDDEN_VALUES["raw_export_body"]}
        ),
        "evidence_item_count": 1,
        "export_status": "READY",
        "redaction_profile": "ag_redacted_manifest_v1",
        "evidence_manifest": {
            "raw_body": FORBIDDEN_VALUES["raw_export_body"]
        },
    }


class _FailingEventStore:
    def list_events(self, **_: object) -> list[dict[str, Any]]:
        raise RuntimeError("private event source failure")


class _FailingExportStore:
    def list_exports(self, **_: object) -> list[dict[str, Any]]:
        raise RuntimeError("private export source failure")


def _has_issue(value: Mapping[str, Any], issue_code: str) -> bool:
    return any(
        isinstance(item, Mapping) and item.get("issue_code") == issue_code
        for item in value.get("issues", [])
    )


def _runbook_actions() -> dict[str, dict[str, Any]]:
    return {
        "hash_mismatch": {
            "retryable": False,
            "action": "quarantine the evidence set and compare trusted hashes",
        },
        "duplicate_or_missing_event": {
            "retryable": True,
            "action": "requery the immutable event source with the same trace",
        },
        "correlation_failure": {
            "retryable": True,
            "action": "inspect trace and request continuity before packaging",
        },
        "manifest_tamper": {
            "retryable": False,
            "action": "reject the package and retain only verification metadata",
        },
        "untrusted_package": {
            "retryable": False,
            "action": "do not echo identifiers or submitted package payloads",
        },
        "source_unavailable": {
            "retryable": True,
            "action": "restore event and export stores before retrying",
        },
        "historical_immutability": {
            "retryable": False,
            "action": "never rewrite source events to make verification pass",
        },
        "postgres_rerun_cleanup": {
            "retryable": True,
            "action": "confirm zero owned rows before rerunning protected smoke",
        },
        "external_notary_deferred": {
            "retryable": False,
            "action": "use canonical SHA-256 until external notarization is approved",
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


def summary_line(evidence: Mapping[str, Any]) -> str:
    status = str(evidence.get("status") or "FAIL").lower()
    if status != "pass":
        return (
            "ag_audit_evidence_privacy_runbook=fail "
            f"failure={evidence.get('failure_code') or 'unknown'}"
        )
    checks = _mapping(evidence.get("checks"))
    return (
        "ag_audit_evidence_privacy_runbook=pass "
        f"surfaces={evidence.get('surface_count')} "
        f"privacy={checks.get('forbidden_values_absent')} "
        f"tamper={checks.get('manifest_tamper_rejected')} "
        f"runbook={checks.get('runbook_complete')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_ag_audit_evidence_privacy_runbook_evidence()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False)
    )
    return 1 if evidence.get("status") == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
