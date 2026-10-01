from __future__ import annotations

from pathlib import Path

import run_mo_mvp_oa_transition_handoff as runner


def test_repository_handoff_evidence_passes() -> None:
    evidence = runner.run_mo_mvp_oa_transition_handoff()

    assert evidence["status"] == "PASS"
    assert all(evidence["checks"].values())
    assert evidence["failed_checks"] == []
    assert evidence["summary"] == {
        "asset_count": 11,
        "privacy_flag_count": 5,
        "model_alias_count": 3,
        "manifest_status": "SEALED",
        "attestation_status": "BOUND",
    }
    assert evidence["acceptance_gate_evidence"]["oa_transition_handoff"] == {
        "status": "PASS",
        "observed_at": "2026-10-01T09:00:00Z",
        "target_service": "nex-oa",
        "manifest_status": "SEALED",
    }
    assert evidence["next_slice"] == "1199"


def test_handoff_evidence_fails_closed_without_assets(tmp_path: Path) -> None:
    evidence = runner.run_mo_mvp_oa_transition_handoff(tmp_path)

    assert evidence["status"] == "FAIL"
    assert evidence["failure_detail"] == "MoMvpOaTransitionHandoffError"
    assert evidence["failed_checks"] == ["handoff_evidence_unavailable"]
    assert evidence["next_slice"] == "blocked"


def test_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_mvp_oa_transition_handoff()
    assert runner.summary_line(passing) == (
        "mo_mvp_oa_transition_handoff=pass assets=11 privacy=5 "
        "manifest=SEALED attestation=BOUND next=1199"
    )
    assert runner._mapping(None) == {}

    monkeypatch.setattr(
        runner,
        "run_mo_mvp_oa_transition_handoff",
        lambda: passing,
    )
    assert runner.main(["--summary"]) == 0
    assert "assets=11" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_mo_mvp_oa_transition_handoff",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
