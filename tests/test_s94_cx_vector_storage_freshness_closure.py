from __future__ import annotations

import json
from pathlib import Path

import run_s94_cx_vector_storage_freshness_closure as closure


def test_repository_s94_closure_passes() -> None:
    result = closure.run_s94_cx_vector_storage_freshness_closure()

    assert result["status"] == "PASS"
    assert result["closure_readiness"] == "READY_FOR_S95"
    assert result["feature_readiness"] == (
        "CX_VECTOR_STORAGE_AND_INDEX_FRESHNESS_FOUNDATION_READY"
    )
    assert all(result["checks"].values())
    assert result["summary"] == {
        "evidence_count": 3,
        "passed_evidence_count": 3,
        "freshness_state_count": 5,
        "stale_reason_count": 11,
        "postgres_check_count": 53,
        "live_check_count": 11,
        "runtime_route_count": 33,
        "missing_file_count": 0,
        "missing_token_count": 0,
    }
    assert set(result["evidence_statuses"].values()) == {"PASS"}
    assert all(result["postgres_evidence"].values())
    assert all(result["live_evidence"].values())
    assert result["next_requirement"] == "S95"


def test_s94_closure_freezes_foundation_decisions_without_overclaiming() -> None:
    decision = closure._closure_decision()

    assert decision["feature_scope"] == "storage_and_freshness_foundation"
    assert decision["metadata_system_of_record"] == "cx_vector_indexes"
    assert decision["payload_backend"] == "cx_vectors_postgresql_pgvector"
    assert decision["embedding_dimension"] == 2560
    assert decision["ann_index"] == "halfvec_2560_hnsw_cosine"
    assert len(decision["freshness_states"]) == 5
    assert decision["publish_protocol"] == (
        "validate_publish_ready_cas_with_compensation"
    )
    assert decision["cross_owner_visibility"] == "not-found"
    assert decision["live_embedding_evidence_completed"] is True
    assert "durable_ingestion_worker_vector_build_wiring" in decision[
        "deferred_scope"
    ]


def test_s94_closure_fails_closed_when_repository_evidence_is_missing(
    tmp_path: Path,
) -> None:
    result = closure.run_s94_cx_vector_storage_freshness_closure(tmp_path)

    assert result["status"] == "FAIL"
    assert result["closure_readiness"] == "BLOCKED"
    assert result["summary"]["missing_file_count"] == len(closure.REQUIRED_FILES)
    assert result["summary"]["missing_token_count"] == len(closure.TOKEN_CHECKS)
    assert result["failed_checks"]


def test_s94_closure_fails_when_deterministic_evidence_does_not_pass(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        closure,
        "run_freshness_contract",
        lambda: {"status": "FAIL", "checks": {}},
    )

    result = closure.run_s94_cx_vector_storage_freshness_closure()

    assert result["status"] == "FAIL"
    assert result["checks"]["deterministic_evidence_passed"] is False
    assert result["checks"]["freshness_contract_closed"] is False
    assert result["summary"]["freshness_state_count"] == 0


def test_s94_closure_fails_when_contract_drift_returns(monkeypatch) -> None:
    monkeypatch.setattr(
        closure,
        "run_contract_drift",
        lambda *_a, **_k: {
            "status": "PASS",
            "contract_readiness": "GAPS_CONFIRMED",
            "openapi_version": "0.93.0",
            "summary": {
                "runtime_operation_count": 34,
                "missing_openapi_operation_count": 1,
            },
        },
    )

    result = closure.run_s94_cx_vector_storage_freshness_closure()

    assert result["status"] == "FAIL"
    assert result["checks"]["fresh_retrieval_and_readiness_api_closed"] is False


def test_s94_closure_helpers_fail_closed(tmp_path: Path) -> None:
    failed = closure._safe_evidence(
        lambda: (_ for _ in ()).throw(RuntimeError("private detail"))
    )
    assert failed == {
        "status": "FAIL",
        "failure_code": "evidence_builder_failed",
        "detail": "RuntimeError",
    }
    assert closure._mapping({"ok": True}) == {"ok": True}
    assert closure._mapping(None) == {}
    assert closure._read_text(tmp_path / "missing") == ""
    present = tmp_path / "present"
    present.write_text("ok", encoding="utf-8")
    assert closure._read_text(present) == "ok"


def test_s94_closure_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = closure.run_s94_cx_vector_storage_freshness_closure()
    assert closure.summary_line(passing) == (
        "s94_cx_vector_storage_freshness_closure=pass evidence=3/3 "
        "postgres_checks=53 live_checks=11 next=S95"
    )
    assert "next=blocked" in closure.summary_line({"status": "FAIL"})

    monkeypatch.setattr(
        closure,
        "run_s94_cx_vector_storage_freshness_closure",
        lambda: passing,
    )
    assert closure.main(["--summary"]) == 0
    assert "closure=pass" in capsys.readouterr().out
    assert closure.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        closure,
        "run_s94_cx_vector_storage_freshness_closure",
        lambda: {"status": "FAIL"},
    )
    assert closure.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
