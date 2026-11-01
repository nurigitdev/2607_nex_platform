from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/smoke"))

import run_platform_authenticated_ingestion_postgres_smoke as smoke


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


def test_wait_for_index_ready_retries_malformed_http_then_succeeds(
    monkeypatch,
) -> None:
    class Response:
        def __init__(self, status_code: int, payload=None, *, malformed=False):
            self.status_code = status_code
            self._payload = payload
            self._malformed = malformed

        def json(self):
            if self._malformed:
                raise ValueError("malformed")
            return self._payload

    responses = iter(
        (
            Response(503, malformed=True),
            Response(200, {"status": "RUNNING"}),
            Response(200, {"status": "INDEX_READY"}),
        )
    )
    client = SimpleNamespace(get=lambda *_args, **_kwargs: next(responses))
    worker = SimpleNamespace(poll=lambda: None)
    clock = iter((0.0, 0.1, 0.2, 0.3))
    monkeypatch.setattr(smoke, "monotonic", lambda: next(clock))
    monkeypatch.setattr(smoke, "sleep", lambda _seconds: None)

    result = smoke._wait_for_index_ready(
        client, "http://ae", "handoff", worker, run_prefix="run", timeout_seconds=1
    )
    assert result == {"status": "INDEX_READY"}


@pytest.mark.parametrize("terminal", ("FAILED", "CANCELLED"))
def test_wait_for_index_ready_rejects_terminal_failure(monkeypatch, terminal) -> None:
    response = SimpleNamespace(
        status_code=200,
        json=lambda: {
            "status": terminal,
            "failure": {"failed_step": "CHUNK", "error_code": "invalid"},
        },
    )
    client = SimpleNamespace(get=lambda *_args, **_kwargs: response)
    worker = SimpleNamespace(poll=lambda: None)
    clock = iter((0.0, 0.1))
    monkeypatch.setattr(smoke, "monotonic", lambda: next(clock))

    with pytest.raises(RuntimeError, match=f"terminal status={terminal}"):
        smoke._wait_for_index_ready(
            client,
            "http://ae",
            "handoff",
            worker,
            run_prefix="run",
            timeout_seconds=1,
        )


def test_wait_for_index_ready_rejects_worker_exit(monkeypatch) -> None:
    clock = iter((0.0, 0.1))
    monkeypatch.setattr(smoke, "monotonic", lambda: next(clock))
    with pytest.raises(RuntimeError, match="worker exited"):
        smoke._wait_for_index_ready(
            SimpleNamespace(),
            "http://ae",
            "handoff",
            SimpleNamespace(poll=lambda: 3),
            run_prefix="run",
            timeout_seconds=1,
        )


def test_cleanup_evidence_and_exit_code_are_deterministic() -> None:
    passed = smoke._finalize_cleanup_evidence(
        {"checks": {"journey": True}, "failure_code": "old"},
        cleanup={"ae_residue_count": 0, "cx_residue_count": 0},
        oa_residue_count=0,
        storage_residue_count=0,
    )
    assert passed["status"] == "PASS"
    assert "failure_code" not in passed
    assert smoke._exit_code(passed) == 0

    failed = smoke._finalize_cleanup_evidence(
        {"checks": {"journey": True}},
        cleanup={"ae_residue_count": 1},
        oa_residue_count=0,
        storage_residue_count=0,
    )
    assert failed["status"] == "FAIL"
    assert failed["failure_code"] == "authenticated_ingestion_check_failed"
    assert smoke._exit_code(failed) == 1
    assert smoke._exit_code({"status": "SKIPPED"}) == 0
