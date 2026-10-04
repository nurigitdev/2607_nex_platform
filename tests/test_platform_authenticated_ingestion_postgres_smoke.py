from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/smoke"))

import run_platform_authenticated_ingestion_postgres_smoke as smoke  # noqa: E402


def _database() -> dict[str, object]:
    return {
        "ae_handoff_count": 1,
        "ae_owner_match": True,
        "ae_metadata_only": True,
        "content_count": 1,
        "extraction_count": 1,
        "chunk_count": 2,
        "succeeded_run_count": 1,
        "succeeded_job_count": 1,
        "ready_index_count": 1,
        "vector_count": 2,
        "summary_count": 1,
        "summary_embedding_count": 1,
    }


def test_smoke_skips_without_protected_opt_in() -> None:
    result = smoke.run_smoke({})

    assert result == {
        "smoke_schema_version": smoke.SCHEMA_VERSION,
        "status": "SKIPPED",
        "skip_reason": f"{smoke.SMOKE_ENV} is not enabled.",
    }
    assert "=skip" in smoke.summary_line(result)


def test_evidence_accepts_durable_owner_scoped_restart_journey() -> None:
    evidence = smoke.build_evidence(
        migration_service_count=5,
        login={"status": "ACTIVE"},
        upload={"status": "QUEUED"},
        progress={
            "status": "INDEX_READY",
            "vector_index": {"retrieval_usable": True},
        },
        restored={"status": "INDEX_READY"},
        database=_database(),
        owner_denial={"status_code": 200, "run_count": 0},
        unauthenticated_status=401,
    )

    assert evidence["status"] == "PASS"
    assert all(evidence["checks"].values())
    assert evidence["provider_mode"] == "mock"
    assert smoke.SOURCE_SENTINEL not in json.dumps(evidence)


def test_evidence_fails_closed_for_incomplete_journey() -> None:
    database = _database()
    database["vector_count"] = 0
    evidence = smoke.build_evidence(
        migration_service_count=4,
        login={"status": "INACTIVE"},
        upload={"status": "FAILED"},
        progress={"status": "FAILED", "vector_index": {}},
        restored={"status": "QUEUED"},
        database=database,
        owner_denial={"status_code": 200, "run_count": 1},
        unauthenticated_status=200,
    )

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["five_test_databases_migrated"] is False
    assert evidence["checks"]["mock_embedding_vectors_ready"] is False
    assert evidence["checks"]["cross_owner_hidden"] is False
    assert "=fail" in smoke.summary_line(evidence)


def test_journey_identifiers_require_complete_upload_reference() -> None:
    assert smoke._journey_identifiers(
        {
            "upload_handoff_id": "handoff",
            "cx_document_ref": {
                "document_id": "document",
                "ingestion_job_id": "job",
            },
        }
    ) == {
        "upload_handoff_id": "handoff",
        "document_id": "document",
        "job_id": "job",
    }

    with pytest.raises(RuntimeError, match="omitted"):
        smoke._journey_identifiers({"upload_handoff_id": "handoff"})
    with pytest.raises(RuntimeError, match="identifiers"):
        smoke._journey_identifiers(
            {"upload_handoff_id": "handoff", "cx_document_ref": {}}
        )


def test_redaction_rejects_source_secret_token_and_database_url() -> None:
    kwargs = {
        "source": "private source",
        "context": {"user_secret": "user-secret"},
        "tokens": {"service": "service-token"},
    }
    smoke._assert_redacted(
        {"status": "PASS"},
        {"NEX_CX_DATABASE_URL": "postgresql://safe"},
        **kwargs,
    )

    for leaked in (
        "private source",
        smoke.SOURCE_SENTINEL,
        "user-secret",
        "service-token",
        "postgresql://safe",
    ):
        with pytest.raises(RuntimeError, match="leaked"):
            smoke._assert_redacted(
                {"leak": leaked},
                {"NEX_CX_DATABASE_URL": "postgresql://safe"},
                **kwargs,
            )


def test_summary_line_reports_pass_counts() -> None:
    line = smoke.summary_line(
        {
            "status": "PASS",
            "database_observations": {"chunk_count": 2, "vector_count": 2},
            "restart_generation_count": 2,
            "cleanup": {
                "ae_residue_count": 0,
                "cx_residue_count": 0,
                "oa_residue_count": 0,
                "storage_residue_count": 0,
            },
        }
    )

    assert line.endswith("chunks=2 vectors=2 restart=2 residue=0 next=1351")
