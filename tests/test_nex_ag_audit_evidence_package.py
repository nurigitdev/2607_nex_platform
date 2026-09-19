from __future__ import annotations

from copy import deepcopy

import pytest

from nex_ag.audit_correlation import build_audit_correlation_continuity_report
from nex_ag.audit_evidence_package import (
    AUDIT_EVIDENCE_MANIFEST_SCHEMA_VERSION,
    AUDIT_EVIDENCE_PACKAGE_SCHEMA_VERSION,
    AUDIT_EVIDENCE_VERIFICATION_SCHEMA_VERSION,
    MAX_AUDIT_EVIDENCE_EXPORTS,
    AuditEvidencePackageError,
    build_audit_evidence_package,
    verify_audit_evidence_package,
)
from nex_ag.audit_integrity import build_audit_event_integrity_report
from nex_runtime.operational_events import build_operational_event


GENERATED_AT = "2026-09-20T05:00:00Z"


def _event(*, trace_id: str | None = "trace-0864") -> dict[str, object]:
    return build_operational_event(
        service_id="nex-ag",
        event_type="ag.audit.packaged",
        severity="INFO",
        message="Package source message must stay private.",
        trace_id=trace_id,
        request_id="request-0864",
        subject_ref={"type": "audit_package", "id": "package-source-0864"},
        details={"token": "must-redact"},
        created_at="2026-09-20T04:00:00Z",
        event_id="event-0864",
    )


def _export(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "export_id": "export-0864",
        "trace_id": "trace-0864",
        "evidence_hash": "A" * 64,
        "evidence_item_count": 2,
        "export_status": "READY",
        "redaction_profile": "ag_redacted_manifest_v1",
        "evidence_manifest": {"private_body": "must-not-appear"},
        "operator_ref": {"operator_id": "employee-private"},
    }
    value.update(overrides)
    return value


def _reports(
    *,
    with_event: bool = True,
    with_export: bool = True,
    trace_id: str | None = "trace-0864",
) -> tuple[dict[str, object], dict[str, object]]:
    events = [_event(trace_id=trace_id)] if with_event else []
    integrity = build_audit_event_integrity_report(
        events,
        checked_at="2026-09-20T04:30:00Z",
    )
    correlation_exports = []
    if with_export:
        correlation_exports = [
            {
                "export_id": "export-0864",
                "trace_id": "trace-0864",
                "evidence_hash": "a" * 64,
            }
        ]
    correlation = build_audit_correlation_continuity_report(
        events,
        evidence_exports=correlation_exports,
        checked_at="2026-09-20T04:30:00Z",
    )
    return integrity, correlation


def _package(
    *,
    with_event: bool = True,
    with_export: bool = True,
    trace_id: str | None = "trace-0864",
) -> dict[str, object]:
    integrity, correlation = _reports(
        with_event=with_event,
        with_export=with_export,
        trace_id=trace_id,
    )
    return build_audit_evidence_package(
        integrity_report=integrity,
        correlation_report=correlation,
        evidence_exports=[_export()] if with_export else [],
        generated_at=GENERATED_AT,
    )


def test_package_is_deterministic_verifiable_sorted_and_redacted() -> None:
    integrity, correlation = _reports()
    second_export = _export(
        export_id="export-0864-b",
        evidence_hash="b" * 64,
        evidence_item_count=1,
    )
    correlation = build_audit_correlation_continuity_report(
        [_event()],
        evidence_exports=[
            {
                "export_id": "export-0864-b",
                "trace_id": "trace-0864",
                "evidence_hash": "b" * 64,
            },
            {
                "export_id": "export-0864",
                "trace_id": "trace-0864",
                "evidence_hash": "a" * 64,
            },
        ],
        checked_at="2026-09-20T04:30:00Z",
    )
    source_exports = [second_export, _export()]
    original = deepcopy(source_exports)

    result = build_audit_evidence_package(
        integrity_report=integrity,
        correlation_report=correlation,
        evidence_exports=source_exports,
        generated_at=GENERATED_AT,
    )
    repeated = build_audit_evidence_package(
        integrity_report=integrity,
        correlation_report=correlation,
        evidence_exports=list(reversed(source_exports)),
        generated_at="2026-09-20T06:00:00+01:00",
    )
    verification = verify_audit_evidence_package(result)

    assert result["package_schema_version"] == AUDIT_EVIDENCE_PACKAGE_SCHEMA_VERSION
    assert result["verification_status"] == "VERIFIED"
    assert result["manifest"]["manifest_schema_version"] == (
        AUDIT_EVIDENCE_MANIFEST_SCHEMA_VERSION
    )
    assert result["manifest"]["summary"] == {
        "report_count": 2,
        "evidence_export_count": 2,
        "evidence_item_count": 3,
    }
    assert [
        item["export_id"] for item in result["manifest"]["evidence_exports"]
    ] == ["export-0864", "export-0864-b"]
    assert result["manifest_hash"] == repeated["manifest_hash"]
    assert result["package_hash"] == repeated["package_hash"]
    assert result["package_id"] == repeated["package_id"]
    assert source_exports == original
    assert verification["verification_schema_version"] == (
        AUDIT_EVIDENCE_VERIFICATION_SCHEMA_VERSION
    )
    assert verification["verification_status"] == "VERIFIED"
    assert verification["issue_count"] == 0
    serialized = str(result)
    assert "Package source message must stay private" not in serialized
    assert "must-redact" not in serialized
    assert "must-not-appear" not in serialized
    assert "employee-private" not in serialized


def test_empty_package_and_failed_package_have_explicit_statuses() -> None:
    empty = _package(with_event=False, with_export=False)
    failed = _package(with_export=False, trace_id=None)

    assert empty["verification_status"] == "NO_EVIDENCE"
    assert empty["generated_at"] == GENERATED_AT
    assert failed["verification_status"] == "FAILED"
    assert verify_audit_evidence_package(empty)["verification_status"] == "VERIFIED"
    assert verify_audit_evidence_package(failed)["verification_status"] == "VERIFIED"


@pytest.mark.parametrize(
    ("mutator", "error_code"),
    [
        (
            lambda integrity, correlation: ("bad", correlation),
            "ag.audit_evidence.report_invalid",
        ),
        (
            lambda integrity, correlation: (
                {**integrity, "integrity_report_schema_version": "bad"},
                correlation,
            ),
            "ag.audit_evidence.report_schema_invalid",
        ),
        (
            lambda integrity, correlation: (
                {**integrity, "report_hash": "bad"},
                correlation,
            ),
            "ag.audit_evidence.report_metadata_invalid",
        ),
        (
            lambda integrity, correlation: (
                integrity,
                {**correlation, "event_integrity": {}},
            ),
            "ag.audit_evidence.report_link_mismatch",
        ),
    ],
)
def test_source_reports_are_validated(mutator: object, error_code: str) -> None:
    integrity, correlation = _reports(with_export=False)
    changed_integrity, changed_correlation = mutator(integrity, correlation)  # type: ignore[operator]

    with pytest.raises(AuditEvidencePackageError) as exc_info:
        build_audit_evidence_package(
            integrity_report=changed_integrity,  # type: ignore[arg-type]
            correlation_report=changed_correlation,
            evidence_exports=[],
            generated_at=GENERATED_AT,
        )

    assert exc_info.value.error_code == error_code


@pytest.mark.parametrize(
    ("exports", "error_code"),
    [
        ("bad", "ag.audit_evidence.exports_invalid"),
        (
            [_export(export_id=f"export-{index}") for index in range(MAX_AUDIT_EVIDENCE_EXPORTS + 1)],
            "ag.audit_evidence.exports_limit_exceeded",
        ),
        (["bad"], "ag.audit_evidence.export_invalid"),
        ([_export(export_id="")], "ag.audit_evidence.export_id_invalid"),
        (
            [_export(), _export()],
            "ag.audit_evidence.export_duplicate",
        ),
        ([_export(evidence_hash="bad")], "ag.audit_evidence.export_hash_invalid"),
        (
            [_export(evidence_item_count=True)],
            "ag.audit_evidence.export_item_count_invalid",
        ),
        (
            [_export(evidence_item_count=-1)],
            "ag.audit_evidence.export_item_count_invalid",
        ),
        (
            [_export(export_status=None)],
            "ag.audit_evidence.export_status_invalid",
        ),
        (
            [_export(redaction_profile="")],
            "ag.audit_evidence.redaction_profile_invalid",
        ),
    ],
)
def test_evidence_export_projection_is_strict(
    exports: object,
    error_code: str,
) -> None:
    integrity, correlation = _reports()

    with pytest.raises(AuditEvidencePackageError) as exc_info:
        build_audit_evidence_package(
            integrity_report=integrity,
            correlation_report=correlation,
            evidence_exports=exports,  # type: ignore[arg-type]
            generated_at=GENERATED_AT,
        )

    assert exc_info.value.error_code == error_code


@pytest.mark.parametrize(
    ("correlation_change", "export_change", "error_code"),
    [
        (
            {"evidence_exports": None},
            {},
            "ag.audit_evidence.correlation_exports_invalid",
        ),
        (
            {"evidence_exports": []},
            {},
            "ag.audit_evidence.export_not_correlated",
        ),
        (
            {
                "evidence_exports": [
                    {
                        "export_id": "export-0864",
                        "trace_id": "trace-0864",
                        "evidence_hash": "a" * 64,
                        "linked": False,
                    }
                ]
            },
            {},
            "ag.audit_evidence.export_not_correlated",
        ),
        (
            {},
            {"trace_id": "trace-other"},
            "ag.audit_evidence.export_correlation_mismatch",
        ),
        (
            {},
            {"evidence_hash": "b" * 64},
            "ag.audit_evidence.export_correlation_mismatch",
        ),
    ],
)
def test_correlation_export_link_is_required(
    correlation_change: dict[str, object],
    export_change: dict[str, object],
    error_code: str,
) -> None:
    integrity, correlation = _reports()
    correlation.update(correlation_change)

    with pytest.raises(AuditEvidencePackageError) as exc_info:
        build_audit_evidence_package(
            integrity_report=integrity,
            correlation_report=correlation,
            evidence_exports=[_export(**export_change)],
            generated_at=GENERATED_AT,
        )

    assert exc_info.value.error_code == error_code


@pytest.mark.parametrize(
    ("generated_at", "error_code"),
    [
        ("bad", "ag.audit_evidence.generated_at_invalid"),
        (
            "2026-09-20T05:00:00",
            "ag.audit_evidence.generated_at_timezone_required",
        ),
    ],
)
def test_generated_at_is_validated(generated_at: str, error_code: str) -> None:
    integrity, correlation = _reports(with_export=False)

    with pytest.raises(AuditEvidencePackageError) as exc_info:
        build_audit_evidence_package(
            integrity_report=integrity,
            correlation_report=correlation,
            evidence_exports=[],
            generated_at=generated_at,
        )

    assert exc_info.value.error_code == error_code
    assert str(exc_info.value)


def test_generated_at_defaults_to_current_utc() -> None:
    integrity, correlation = _reports(with_export=False)

    result = build_audit_evidence_package(
        integrity_report=integrity,
        correlation_report=correlation,
        evidence_exports=[],
    )

    assert result["generated_at"].endswith("Z")


def test_verifier_rejects_non_object_and_missing_shape() -> None:
    non_object = verify_audit_evidence_package("bad")
    missing = verify_audit_evidence_package({})
    malformed_with_id = verify_audit_evidence_package(
        {"package_id": "unverifiable-package"}
    )

    assert non_object["verification_status"] == "FAILED"
    assert non_object["issues"] == [
        {"issue_code": "package_not_object", "subject_id": None}
    ]
    assert {item["issue_code"] for item in missing["issues"]} == {
        "manifest_hash_invalid",
        "manifest_not_object",
        "package_hash_invalid",
        "package_id_invalid",
        "package_schema_version_invalid",
        "package_verification_status_invalid",
    }
    assert malformed_with_id["verification_status"] == "FAILED"
    assert malformed_with_id["package_id"] is None
    assert "package_id_invalid" not in {
        item["issue_code"] for item in malformed_with_id["issues"]
    }


def test_verifier_detects_manifest_and_package_tampering() -> None:
    package = _package()
    package["package_schema_version"] = "bad"
    package["package_id"] = "tampered"
    package["manifest_hash"] = "0" * 64
    package["package_hash"] = "1" * 64
    package["manifest"]["manifest_schema_version"] = "bad"
    package["manifest"]["reports"] = []
    package["manifest"]["evidence_exports"].append(
        deepcopy(package["manifest"]["evidence_exports"][0])
    )
    package["manifest"]["evidence_exports"][0]["evidence_hash"] = "bad"
    package["manifest"]["summary"]["evidence_export_count"] = 999
    package["manifest"]["redaction"]["credentials_included"] = True

    result = verify_audit_evidence_package(package)

    assert result["verification_status"] == "FAILED"
    assert result["package_id"] is None
    assert {item["issue_code"] for item in result["issues"]} == {
        "manifest_export_duplicate",
        "manifest_export_hash_invalid",
        "manifest_hash_mismatch",
        "manifest_redaction_invalid",
        "manifest_reports_invalid",
        "manifest_schema_version_invalid",
        "manifest_summary_mismatch",
        "package_hash_mismatch",
        "package_id_mismatch",
        "package_schema_version_invalid",
    }


def test_verifier_detects_invalid_top_level_hashes_status_and_exports_shape() -> None:
    package = _package()
    package["verification_status"] = "UNKNOWN"
    package["manifest_hash"] = "bad"
    package["package_hash"] = None
    package["manifest"]["evidence_exports"] = "bad"

    result = verify_audit_evidence_package(package)

    assert result["verification_status"] == "FAILED"
    assert {item["issue_code"] for item in result["issues"]} == {
        "manifest_exports_invalid",
        "manifest_hash_invalid",
        "manifest_hash_mismatch",
        "manifest_summary_mismatch",
        "package_hash_invalid",
        "package_hash_mismatch",
        "package_id_mismatch",
        "package_verification_status_invalid",
    }
