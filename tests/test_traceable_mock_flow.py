from __future__ import annotations

import json

import pytest

import run_traceable_mock_flow as smoke


def test_run_traceable_mock_flow_links_trace_across_services() -> None:
    evidence = smoke.run_traceable_mock_flow()

    assert all(evidence["assertions"].values())
    assert evidence["cx_upload"]["document_id"] == evidence["cx_chunk_set"]["document_id"]
    assert evidence["cx_embedding_index"]["chunk_count"] == evidence["cx_chunk_set"]["chunk_count"]
    assert evidence["cx_lexical_index"]["chunk_count"] == evidence["cx_chunk_set"]["chunk_count"]
    assert evidence["cx_retrieval"]["status"] == "READY"
    assert evidence["cx_retrieval"]["evidence_items"]
    assert evidence["rag_workflow"]["workflow_schema_version"] == "rag_workflow_evidence.v1"
    assert evidence["rag_workflow"]["policy"]["active"]["policy_source"] == (
        "ag_registry_active"
    )
    assert evidence["rag_workflow"]["policy"]["weighted_probe"]["policy_id"] == (
        "weighted_rrf_vector_bm25_v1"
    )
    assert evidence["rag_workflow"]["retrieval"]["weighted_query_embedding"][
        "provided"
    ] is True
    assert "0.1, 0.2, 0.3" not in json.dumps(
        evidence["rag_workflow"],
        ensure_ascii=False,
    )
    assert evidence["ae"]["retrieval"]["cx_retrieval_package_id"] == (
        evidence["cx_retrieval"]["retrieval_package_id"]
    )
    assert evidence["ae"]["cx_generation_id"] == evidence["cx"]["cx_generation_id"]
    assert evidence["cx"]["mo_generation_id"] == evidence["mo"]["mo_generation_id"]
    assert evidence["mo_embedding"]["alias"] == "mock-embedding-default"
    assert evidence["ag"]["summary"]["total"] == 5


def test_assert_trace_evidence_reports_mismatch() -> None:
    evidence = smoke.run_traceable_mock_flow()
    evidence["ag"]["trace_id"] = "0" * 32

    with pytest.raises(AssertionError):
        smoke.assert_trace_evidence(evidence)


def test_assert_rag_workflow_evidence_reports_mismatch() -> None:
    evidence = smoke.run_traceable_mock_flow()
    evidence["rag_workflow"]["retrieval"]["weighted_status"] = "NO_ANSWER"

    with pytest.raises(AssertionError):
        smoke.assert_rag_workflow_evidence(evidence["rag_workflow"])


def test_main_prints_summary(capsys) -> None:
    assert smoke.main(["--summary"]) == 0

    output = capsys.readouterr().out
    assert "traceable_mock_flow=pass" in output
    assert "retrieval=" in output
    assert "rag_workflow=rag_workflow_evidence.v1" in output


def test_main_writes_evidence_file(tmp_path) -> None:
    output = tmp_path / "trace-smoke.json"

    assert smoke.main(["--output", str(output)]) == 0

    evidence = json.loads(output.read_text(encoding="utf-8"))
    assert evidence["trace_id"] == smoke.TRACE_ID
    assert evidence["assertions"]["retrieval_lineage"] is True
    assert evidence["rag_workflow"]["assertions"]["active_policy_from_registry"] is True
