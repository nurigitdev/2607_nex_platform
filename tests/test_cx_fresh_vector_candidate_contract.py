from __future__ import annotations

import json

import run_cx_fresh_vector_candidate_contract as contract


def test_fresh_vector_candidate_contract_passes() -> None:
    result = contract.run_cx_fresh_vector_candidate_contract()

    assert result["status"] == "PASS"
    assert result["passed_checks"] == 8
    assert result["failed_checks"] == []
    assert all(result["checks"].values())
    assert result["postgres_required"] is False
    assert result["remote_provider_required"] is False
    assert result["result_summary"] == {
        "requested_index_count": 3,
        "admitted_index_count": 1,
        "excluded_index_count": 2,
        "candidate_count": 1,
        "exclusion_counts": {"INDEX_NOT_FOUND": 1, "INDEX_NOT_READY": 1},
    }


def test_fixture_supports_building_and_ready_states() -> None:
    building = contract._fixture(
        "building-test",
        owner="owner-a",
        status="BUILDING",
        score=0.5,
    )
    ready = contract._fixture(
        "ready-test",
        owner="owner-a",
        status="READY",
        score=0.6,
    )

    assert building["manifest"]["status"] == "BUILDING"
    assert ready["manifest"]["status"] == "READY"
    assert contract._all_strings(1) == []


def test_summary_and_cli_outputs(monkeypatch, capsys) -> None:
    passing = contract.run_cx_fresh_vector_candidate_contract()
    assert contract.summary_line(passing) == (
        "cx_fresh_vector_candidate_contract=pass checks=8/8 "
        "policy=cx.private_owner_active.v1 postgres_required=False "
        "remote_required=False"
    )
    assert "checks=0/0" in contract.summary_line({})

    monkeypatch.setattr(
        contract,
        "run_cx_fresh_vector_candidate_contract",
        lambda: passing,
    )
    assert contract.main(["--summary"]) == 0
    assert "contract=pass" in capsys.readouterr().out
    assert contract.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        contract,
        "run_cx_fresh_vector_candidate_contract",
        lambda: {"status": "FAIL"},
    )
    assert contract.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
