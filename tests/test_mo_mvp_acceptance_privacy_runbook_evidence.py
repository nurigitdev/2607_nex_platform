from __future__ import annotations

from pathlib import Path

import pytest

import run_mo_mvp_acceptance_privacy_runbook_evidence as evidence


def test_runbook_evidence_passes_with_complete_repository() -> None:
    result = evidence.run_mo_mvp_acceptance_privacy_runbook_evidence()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert len(result["runbook_inventory"]) == 7
    assert len(result["failure_matrix"]) == 12
    assert all(
        item["status"] == "BLOCKED"
        and item["blocked_gate_count"] == 1
        for item in result["failure_matrix"].values()
    )
    assert result["acceptance_gate_evidence"]["privacy_failure_runbooks"] == {
        "status": "PASS",
        "observed_at": "2026-10-01T11:00:00Z",
        "runbook_count": 7,
    }
    assert result["next_slice"] == "1201"


def test_missing_documents_hook_and_handoff_fail_closed(tmp_path: Path) -> None:
    (tmp_path / "scripts/quality").mkdir(parents=True)
    (tmp_path / "scripts/quality/run_quality_gate.sh").write_text(
        "#!/bin/sh\n",
        encoding="utf-8",
    )

    result = evidence.run_mo_mvp_acceptance_privacy_runbook_evidence(tmp_path)

    assert result["status"] == "FAIL"
    assert result["checks"]["required_docs_present"] is False
    assert result["checks"]["quality_gate_hook_present"] is False
    assert result["checks"]["oa_handoff_verified"] is False
    assert result["handoff_projection"]["status"] == "INVALID"
    assert result["next_slice"] == "blocked"


def test_passing_evidence_is_accepted_and_each_failure_blocks() -> None:
    policy = evidence.build_mo_mvp_acceptance_policy({})
    baseline = evidence.build_passing_evidence()
    for item in baseline.values():
        item["observed_at"] = evidence._timestamp(evidence.OBSERVED_AT)
    report = evidence.evaluate_mo_mvp_acceptance(
        baseline,
        policy=policy,
        now=evidence.OBSERVED_AT,
    )
    failures = evidence._failure_matrix(baseline, policy=policy)

    assert report["status"] == "ACCEPTED"
    assert report["summary"]["passed_gate_count"] == 9
    assert {item["blocked_gate_count"] for item in failures.values()} == {1}


def test_path_mutation_supports_nested_update_and_gate_removal() -> None:
    target = {"gate": {"nested": {"value": "old"}}}
    evidence._set_path(target, "gate.nested.value", "new")
    assert target["gate"]["nested"]["value"] == "new"
    evidence._set_path(target, "gate", None)
    assert "gate" not in target


@pytest.mark.parametrize(
    "item",
    [
        None,
        {},
        {"detect": "yes"},
        {
            "detect": "yes",
            "contain": "yes",
            "recover": "yes",
            "verify": "yes",
            "owner": "",
        },
    ],
)
def test_runbook_completeness_rejects_incomplete_items(item) -> None:
    assert evidence._runbook_complete(item) is False


def test_privacy_key_scanner_reports_nested_paths() -> None:
    value = {
        "safe": [
            {"password": "not-returned"},
            {"nested": {"provider_payload": "not-returned"}},
        ]
    }
    assert evidence._forbidden_key_paths(value) == [
        "$.safe[0].password",
        "$.safe[1].nested.provider_payload",
    ]
    assert evidence._forbidden_key_paths({"safe": True}) == []


def test_helpers_summary_and_main(monkeypatch, tmp_path, capsys) -> None:
    assert evidence._read_text(tmp_path / "missing") == ""
    binary = tmp_path / "binary"
    binary.write_bytes(b"\xff")
    assert evidence._read_text(binary) == ""
    assert evidence._mapping([]) == {}

    passing = evidence.run_mo_mvp_acceptance_privacy_runbook_evidence()
    assert evidence.summary_line(passing) == (
        "mo_mvp_acceptance_runbook=pass checks=7/7 "
        "runbooks=7 failure_cases=12 next=1201"
    )
    monkeypatch.setattr(
        evidence,
        "run_mo_mvp_acceptance_privacy_runbook_evidence",
        lambda: {"status": "PASS", "checks": {}},
    )
    assert evidence.main(["--summary"]) == 0
    assert "mo_mvp_acceptance_runbook=pass" in capsys.readouterr().out
    monkeypatch.setattr(
        evidence,
        "run_mo_mvp_acceptance_privacy_runbook_evidence",
        lambda: {"status": "FAIL", "checks": {}},
    )
    assert evidence.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
