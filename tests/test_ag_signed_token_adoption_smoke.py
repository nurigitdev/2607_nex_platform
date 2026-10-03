from __future__ import annotations

from pathlib import Path

import run_ag_signed_token_adoption as runner


def test_ag_signed_token_adoption_smoke_passes() -> None:
    evidence = runner.run_ag_signed_token_adoption()

    assert evidence["status"] == "PASS"
    assert all(evidence["checks"].values())
    assert evidence["legacy_validator_file_count"] == 0
    assert evidence["outbound_client_count"] == 6
    assert evidence["dual_admin_module_count"] == 4
    assert evidence["next_slice"] == "1279"


def test_audit_fails_for_empty_repository(tmp_path: Path) -> None:
    evidence = runner.run_ag_signed_token_adoption(tmp_path)

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["ag_main_wires_shared_admission"] is False


def test_summary_and_main(capsys, monkeypatch) -> None:
    evidence = runner.run_ag_signed_token_adoption()
    assert runner.summary_line(evidence) == (
        "ag_signed_token_adoption=pass outbound=6 admin=4 next=1279"
    )
    monkeypatch.setattr(runner, "run_ag_signed_token_adoption", lambda: evidence)
    assert runner.main(["--summary"]) == 0
    assert "ag_signed_token_adoption=pass" in capsys.readouterr().out
    failed = {
        "status": "FAIL",
        "outbound_client_count": 0,
        "dual_admin_module_count": 0,
        "next_slice": "blocked",
    }
    monkeypatch.setattr(runner, "run_ag_signed_token_adoption", lambda: failed)
    assert runner.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
