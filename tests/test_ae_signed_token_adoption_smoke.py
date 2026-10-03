from __future__ import annotations

from pathlib import Path

import run_ae_signed_token_adoption as runner


def test_ae_signed_token_adoption_smoke_passes() -> None:
    evidence = runner.run_ae_signed_token_adoption()

    assert evidence["status"] == "PASS"
    assert all(evidence["checks"].values())
    assert evidence["direct_mock_file_count"] == 0
    assert evidence["direct_validator_file_count"] == 0
    assert evidence["next_slice"] == "1276"


def test_audit_fails_for_empty_repository(tmp_path: Path) -> None:
    evidence = runner.run_ae_signed_token_adoption(tmp_path)

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["ae_main_wires_shared_admission"] is False


def test_summary_and_main(capsys, monkeypatch) -> None:
    evidence = runner.run_ae_signed_token_adoption()
    assert runner.summary_line(evidence) == (
        "ae_signed_token_adoption=pass mock_files=0 validators=0 next=1276"
    )
    monkeypatch.setattr(runner, "run_ae_signed_token_adoption", lambda: evidence)
    assert runner.main(["--summary"]) == 0
    assert "ae_signed_token_adoption=pass" in capsys.readouterr().out
    failed = {
        "status": "FAIL",
        "direct_mock_file_count": 1,
        "direct_validator_file_count": 1,
        "next_slice": "blocked",
    }
    monkeypatch.setattr(runner, "run_ae_signed_token_adoption", lambda: failed)
    assert runner.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
