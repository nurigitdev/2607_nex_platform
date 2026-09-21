from __future__ import annotations

import json

import run_cx_retrieval_permission_contract as contract


def test_retrieval_permission_contract_passes() -> None:
    result = contract.run_cx_retrieval_permission_contract()

    assert result["status"] == "PASS"
    assert result["check_count"] == 8
    assert all(result["checks"].values())
    assert result["failed_checks"] == []
    assert result["postgres_required"] is False
    assert result["remote_provider_required"] is False
    assert result["next_slice"] == "0943"


def test_contract_helpers_and_main_paths(monkeypatch, capsys) -> None:
    passing = contract.run_cx_retrieval_permission_contract()
    assert contract.summary_line(passing) == (
        "cx_retrieval_permission_contract=pass checks=8/8 "
        "policy=cx.private_owner_active.v1 postgres_required=False "
        "remote_required=False"
    )
    assert "checks=0/0" in contract.summary_line({})

    monkeypatch.setattr(
        contract,
        "run_cx_retrieval_permission_contract",
        lambda: passing,
    )
    assert contract.main(["--summary"]) == 0
    assert "contract=pass" in capsys.readouterr().out
    assert contract.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        contract,
        "run_cx_retrieval_permission_contract",
        lambda: {"status": "FAIL"},
    )
    assert contract.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"


def test_mixed_scope_probe_fails_when_filter_does_not_reject(monkeypatch) -> None:
    monkeypatch.setattr(
        contract,
        "filter_retrieval_document_scope",
        lambda **_kwargs: {"visible_document_ids": []},
    )

    assert contract._mixed_scope_fails_closed(
        contract._context("tenant-a", "owner-a"),
        contract._content("tenant-a", "owner-a", "ACTIVE"),
        contract._content("tenant-a", "owner-b", "ACTIVE"),
    ) is False
