from __future__ import annotations

import run_oa_openbao_transit_key_lifecycle as runner


def test_key_lifecycle_evidence_passes_without_live_contact() -> None:
    result = runner.run_oa_openbao_transit_key_lifecycle()

    assert result["status"] == "PASS"
    assert result["summary"] == {
        "check_count": 12,
        "request_count": 5,
        "key_version": 1,
        "jwks_key_count": 1,
    }
    assert all(result["checks"].values())
    assert result["decision"]["runtime_has_provisioning_permission"] is False
    assert result["decision"]["live_openbao_contacted"] is False


def test_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = runner.run_oa_openbao_transit_key_lifecycle()
    assert runner.summary_line(passing) == (
        "oa_transit_key_lifecycle=pass checks=12/12 requests=5 "
        "version=1 jwks=1 next=1437"
    )
    assert runner.summary_line({"status": "FAIL", "issues": ["x"]}) == (
        "oa_transit_key_lifecycle=fail issues=1"
    )

    monkeypatch.setattr(runner, "run_oa_openbao_transit_key_lifecycle", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "oa_transit_key_lifecycle=pass" in capsys.readouterr().out

    failing = {**passing, "status": "FAIL"}
    monkeypatch.setattr(runner, "run_oa_openbao_transit_key_lifecycle", lambda: failing)
    assert runner.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
