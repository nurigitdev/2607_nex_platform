from __future__ import annotations

import run_platform_complete_process_manifest as smoke


def test_complete_process_manifest_evidence_passes() -> None:
    result = smoke.run_platform_complete_process_manifest()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["decision"]["local_mock_process_shell_claims_jobs"] is False


def test_summary_and_main(monkeypatch, capsys) -> None:
    passing = smoke.run_platform_complete_process_manifest()
    assert smoke.summary_line(passing) == (
        "platform_complete_process_manifest=pass endpoints=6 processes=13 "
        "kinds=5/1/5/2 layers=6 next=1318"
    )
    assert smoke.summary_line({"status": "FAIL", "issues": [1]}) == (
        "platform_complete_process_manifest=fail issues=1"
    )

    monkeypatch.setattr(
        smoke, "run_platform_complete_process_manifest", lambda: passing
    )
    assert smoke.main(["--summary"]) == 0
    assert "manifest=pass" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_platform_complete_process_manifest",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert smoke.main([]) == 1
