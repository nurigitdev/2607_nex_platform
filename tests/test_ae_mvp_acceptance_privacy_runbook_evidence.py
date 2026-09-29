from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

import run_ae_mvp_acceptance_privacy_runbook_evidence as evidence


def test_runbook_evidence_passes_with_complete_repository() -> None:
    result = evidence.run_ae_mvp_acceptance_privacy_runbook_evidence()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert len(result["runbook_inventory"]) == 7
    assert len(result["failure_matrix"]) == 11
    assert all(
        item["status"] == "BLOCKED"
        for item in result["failure_matrix"].values()
    )
    assert result["acceptance_gate_evidence"]["privacy_failure_runbooks"] == {
        "status": "PASS",
        "observed_at": "2026-09-29T08:00:00Z",
        "runbook_count": 7,
    }


def test_missing_documents_and_quality_hook_fail_closed(tmp_path: Path) -> None:
    (tmp_path / "scripts/quality").mkdir(parents=True)
    (tmp_path / "scripts/quality/run_quality_gate.sh").write_text(
        "#!/bin/sh\n", encoding="utf-8"
    )

    result = evidence.run_ae_mvp_acceptance_privacy_runbook_evidence(tmp_path)

    assert result["status"] == "FAIL"
    assert result["checks"]["required_docs_present"] is False
    assert result["checks"]["quality_gate_hook_present"] is False


def test_passing_evidence_is_accepted_and_each_failure_blocks() -> None:
    policy = evidence.build_ae_mvp_acceptance_policy({})
    baseline = evidence._passing_evidence()
    report = evidence.evaluate_ae_mvp_acceptance(
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
    "mutation",
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
def test_runbook_completeness_rejects_incomplete_items(mutation) -> None:
    assert evidence._runbook_complete(mutation) is False


def test_privacy_key_scanner_reports_nested_paths() -> None:
    value = {
        "safe": [
            {"password": "not-returned"},
            {"nested": {"raw_payload": "not-returned"}},
        ]
    }
    assert evidence._forbidden_key_paths(value) == [
        "$.safe[0].password",
        "$.safe[1].nested.raw_payload",
    ]
    assert evidence._forbidden_key_paths({"safe": True}) == []


def test_helpers_summary_and_main(monkeypatch, tmp_path, capsys) -> None:
    assert evidence._read_text(tmp_path / "missing") == ""
    binary = tmp_path / "binary"
    binary.write_bytes(b"\xff")
    assert evidence._read_text(binary) == ""
    assert evidence._mapping([]) == {}

    passing = evidence.run_ae_mvp_acceptance_privacy_runbook_evidence()
    assert evidence.summary_line(passing) == (
        "ae_mvp_acceptance_runbook=pass checks=7/7 "
        "runbooks=7 failure_cases=11"
    )
    monkeypatch.setattr(
        evidence,
        "run_ae_mvp_acceptance_privacy_runbook_evidence",
        lambda: {"status": "PASS", "checks": {}},
    )
    assert evidence.main(["--summary"]) == 0
    assert "ae_mvp_acceptance_runbook=pass" in capsys.readouterr().out
    monkeypatch.setattr(
        evidence,
        "run_ae_mvp_acceptance_privacy_runbook_evidence",
        lambda: {"status": "FAIL", "checks": {}},
    )
    assert evidence.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
