from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "smoke" / "run_cx_mock_vector_publish_freshness.py"
SPEC = importlib.util.spec_from_file_location(
    "run_cx_mock_vector_publish_freshness",
    SCRIPT,
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_mock_vector_publish_is_owner_scoped_fresh_and_private() -> None:
    evidence = MODULE.run_cx_mock_vector_publish_freshness()

    assert evidence["status"] == "PASS"
    assert all(evidence["checks"].values())
    assert evidence["provider_path"] == "cx_service_token_to_mo_mock_embedding"
    assert evidence["readiness"]["retrieval_usable"] is True
    assert evidence["private_payload_in_evidence"] is False


def test_mock_vector_publish_summary_reports_completion() -> None:
    evidence = MODULE.run_cx_mock_vector_publish_freshness()
    summary = MODULE.summary_line(evidence)

    assert summary.startswith("cx_mock_vector_publish=pass checks=12/12")
    assert "freshness=READY" in summary
    assert "next=1348" in summary


def test_mock_vector_publish_failure_summary_is_safe() -> None:
    assert (
        MODULE.summary_line({"status": "FAIL", "issues": ["freshness"]})
        == "cx_mock_vector_publish=fail issues=1"
    )


def test_memory_vector_evidence_store_rejects_owner_mismatch_and_deletes() -> None:
    bound = MODULE.MemoryBoundVectorStore(
        {
            "tenant_ref": {"id": "tenant-a"},
            "owner_subject_ref": {"id": "owner-a"},
        }
    )
    other = SimpleNamespace(ownership_key=("tenant-a", "owner-b"))
    key = SimpleNamespace(content_id="chunk-a")

    with pytest.raises(AssertionError, match="owner scope mismatch"):
        bound.put_vector(
            access_context=other,
            key=key,
            vector=[1.0],
            expected_sha256="0" * 64,
        )
    with pytest.raises(AssertionError, match="owner scope mismatch"):
        bound.payload_snapshot(access_context=other)

    bound.receipts["chunk-a"] = {"chunk_id": "chunk-a"}
    assert bound.delete_vector(access_context=other, key=key) is True
    assert bound.delete_vector(access_context=other, key=key) is False


def test_evidence_reports_failed_check_without_leaking_payload(monkeypatch) -> None:
    monkeypatch.setattr(MODULE, "PRIVATE_SOURCE", "mock-embedding-default")

    evidence = MODULE.run_cx_mock_vector_publish_freshness()

    assert evidence["status"] == "FAIL"
    assert evidence["issues"] == ["private_source_absent"]


def test_main_covers_summary_json_and_failure_exit(monkeypatch, capsys) -> None:
    passed = MODULE.run_cx_mock_vector_publish_freshness()
    monkeypatch.setattr(
        MODULE,
        "run_cx_mock_vector_publish_freshness",
        lambda: passed,
    )
    assert MODULE.main(["--summary"]) == 0
    assert "cx_mock_vector_publish=pass" in capsys.readouterr().out
    assert MODULE.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        MODULE,
        "run_cx_mock_vector_publish_freshness",
        lambda: {"status": "FAIL", "issues": ["freshness"]},
    )
    assert MODULE.main(["--summary"]) == 1
