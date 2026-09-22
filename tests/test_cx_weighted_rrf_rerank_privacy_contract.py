from __future__ import annotations

import json
import runpy
import sys

import run_cx_weighted_rrf_rerank_privacy_contract as smoke


def test_contract_runner_passes_without_private_payload_or_external_dependencies() -> None:
    result = smoke.run_cx_weighted_rrf_rerank_privacy_contract()

    assert result["status"] == "PASS"
    assert result["passed_checks"] == len(result["checks"]) == 10
    assert result["failed_checks"] == []
    assert result["policy_id"] == "weighted_rrf_vector_bm25_v1"
    assert result["rerank_state"] == "APPLIED"
    assert result["postgres_required"] is False
    assert result["remote_provider_required"] is False
    serialized = json.dumps(result)
    assert "PRIVATE_S95" not in serialized
    assert "private retrieval query" not in serialized


def test_summary_line_reports_contract_counts() -> None:
    result = smoke.run_cx_weighted_rrf_rerank_privacy_contract()

    assert smoke.summary_line(result) == (
        "cx_weighted_rrf_rerank_privacy_contract=pass checks=10/10 "
        "postgres_required=False remote_required=False"
    )


def test_main_prints_json_and_summary(capsys) -> None:
    assert smoke.main([]) == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["status"] == "PASS"

    assert smoke.main(["--summary"]) == 0
    assert "checks=10/10" in capsys.readouterr().out


def test_main_returns_failure_for_failed_contract(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        smoke,
        "run_cx_weighted_rrf_rerank_privacy_contract",
        lambda: {
            "status": "FAIL",
            "checks": {"failed": False},
            "passed_checks": 0,
        },
    )

    assert smoke.main(["--summary"]) == 1
    assert "fail" in capsys.readouterr().out


def test_module_entrypoint(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_cx_weighted_rrf_rerank_privacy_contract.py", "--summary"],
    )

    try:
        runpy.run_module(
            "run_cx_weighted_rrf_rerank_privacy_contract",
            run_name="__main__",
        )
    except SystemExit as exc:
        assert exc.code == 0

    assert "cx_weighted_rrf_rerank_privacy_contract=pass" in capsys.readouterr().out
