from __future__ import annotations

import json
from pathlib import Path

import pytest

import run_ag_audit_retention_privacy_runbook_evidence as evidence


def test_privacy_runbook_passes_and_exercises_failure_surfaces() -> None:
    result = evidence.run_ag_audit_retention_privacy_runbook_evidence()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["surface_count"] == 14
    assert result["forbidden_value_labels"] == []
    assert result["forbidden_key_paths"] == []
    surfaces = result["surfaces"]
    assert surfaces["mock_dry_run"]["reason"] == "receipt_not_sealed"
    assert surfaces["archive_grace_active"]["reason"] == "archive_grace_active"
    assert surfaces["source_hash_mismatch"]["reason"] == "source_hash_mismatch"
    assert surfaces["concurrent_change"]["status_code"] == 409
    assert surfaces["idempotent_retry"]["status"] == "NOOP"


def test_privacy_runbook_fails_without_docs_postgres_evidence_and_hook(
    tmp_path: Path,
) -> None:
    result = evidence.run_ag_audit_retention_privacy_runbook_evidence(tmp_path)

    assert result["status"] == "FAIL"
    assert result["failure_code"] == "ag_audit_retention_privacy_runbook_failed"
    assert result["checks"]["docs_present"] is False
    assert result["checks"]["quality_gate_hook_present"] is False
    assert result["checks"]["postgres_evidence_is_complete"] is False


def test_error_capture_helpers_normalize_and_reject_success() -> None:
    archive = evidence._capture_archive_error(
        lambda: (_ for _ in ()).throw(
            evidence.AgArchiveReceiptError(
                error_code="ag.retention.archive_invalid",
                detail=evidence.FORBIDDEN_VALUES["object_reference"],
            )
        )
    )
    purge = evidence._capture_purge_error(
        lambda: (_ for _ in ()).throw(
            evidence.AgRetentionPurgeError(
                error_code="ag.retention.purge_concurrent_change",
                detail=evidence.FORBIDDEN_VALUES["concurrent_error"],
                status_code=409,
            )
        )
    )

    assert archive == {
        "error_code": "ag.retention.archive_invalid",
        "detail": "AG archive receipt was rejected safely.",
    }
    assert purge["status_code"] == 409
    assert evidence.FORBIDDEN_VALUES["concurrent_error"] not in str(purge)
    with pytest.raises(AssertionError, match="archive operation did not fail"):
        evidence._capture_archive_error(lambda: None)
    with pytest.raises(AssertionError, match="purge operation did not fail"):
        evidence._capture_purge_error(lambda: None)


def test_source_candidate_receipt_and_store_helpers_cover_safe_shapes() -> None:
    source = evidence._source_record()
    candidate = evidence._candidate(source)
    external = evidence._receipt(
        candidate,
        archived_at="2026-08-01T00:00:00Z",
    )
    mock = evidence._receipt(
        candidate,
        provider_mode="mock",
        archived_at="2026-08-01T00:00:00Z",
    )
    populated = evidence._store(source=source, receipt=external)
    empty = evidence._store()

    assert candidate["content_sha256"] == evidence._sha256_json(source)
    assert external["archive_status"] == "SEALED"
    assert mock["archive_status"] == "MOCKED"
    assert populated.source_records
    assert empty.source_records == {}
    assert len(evidence._sha256_text("value")) == 64


def test_postgres_evidence_and_runbook_actions_are_complete() -> None:
    complete = " ".join(
        (
            "live smoke: PASS",
            "database=nex_ag_test",
            "candidates=2 purged=2",
            "indexes=2",
            "migration_present=true",
            "cleaned=True",
            "event_residue=0 export_residue=0 receipt_residue=0",
        )
    )

    assert all(evidence._postgres_evidence(complete).values())
    assert not any(evidence._postgres_evidence("").values())
    runbook = evidence._runbook_actions()
    assert len(runbook) == 12
    assert runbook["receipt_missing"]["retryable"] is True
    assert runbook["source_hash_mismatch"]["retryable"] is False


def test_privacy_helpers_cover_nested_values_keys_and_missing_files(
    tmp_path: Path,
) -> None:
    serialized = (
        f"x={evidence.FORBIDDEN_VALUES['database_url']} "
        f"y={evidence.FORBIDDEN_VALUES['raw_detail']}"
    )

    assert evidence._forbidden_value_labels(serialized) == [
        "database_url",
        "raw_detail",
    ]
    assert evidence._forbidden_key_paths(
        {
            "safe": [
                {"authorization": "redacted"},
                {"nested": {"object_ref": "redacted"}},
                "leaf",
            ]
        }
    ) == ["safe[0].authorization", "safe[1].nested.object_ref"]
    with pytest.raises(ValueError, match="forbidden values"):
        evidence._assert_no_forbidden_values(serialized)
    assert evidence._read_text(tmp_path / "missing") == ""
    assert evidence._mapping({"ok": True}) == {"ok": True}
    assert evidence._mapping(None) == {}


def test_summary_line_reports_pass_and_failure() -> None:
    passed = evidence.summary_line(
        {
            "status": "PASS",
            "surface_count": 14,
            "checks": {
                "forbidden_values_absent": True,
                "postgres_evidence_is_complete": True,
                "runbook_complete": True,
            },
        }
    )
    failed = evidence.summary_line(
        {"status": "FAIL", "failure_code": "failed"}
    )

    assert "runbook=pass" in passed
    assert "privacy=True" in passed
    assert "postgres=True" in passed
    assert "runbook=fail" in failed


def test_main_prints_summary_json_and_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    passing = {
        "status": "PASS",
        "surface_count": 1,
        "checks": {
            "forbidden_values_absent": True,
            "postgres_evidence_is_complete": True,
            "runbook_complete": True,
        },
    }
    monkeypatch.setattr(
        evidence,
        "run_ag_audit_retention_privacy_runbook_evidence",
        lambda: passing,
    )

    assert evidence.main(["--summary"]) == 0
    assert "runbook=pass" in capsys.readouterr().out
    assert evidence.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        evidence,
        "run_ag_audit_retention_privacy_runbook_evidence",
        lambda: {"status": "FAIL", "failure_code": "test"},
    )
    assert evidence.main([]) == 1
