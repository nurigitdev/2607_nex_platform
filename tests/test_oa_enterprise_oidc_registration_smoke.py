from __future__ import annotations

import run_oa_enterprise_oidc_registration as runner


def test_registration_evidence_passes_without_live_contact() -> None:
    result = runner.run_oa_enterprise_oidc_registration()

    assert result["status"] == "PASS"
    assert result["summary"] == {
        "check_count": 14,
        "scope_count": 1,
        "trusted_claim_count": 8,
        "endpoint_count": 3,
    }
    assert all(result["checks"].values())
    assert result["decision"]["client_secret_in_database"] is False
    assert result["decision"]["live_idp_contacted"] is False


def test_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = runner.run_oa_enterprise_oidc_registration()
    assert runner.summary_line(passing) == (
        "oa_enterprise_oidc_registration=pass checks=14/14 scopes=1 "
        "claims=8 endpoints=3 next=1439"
    )
    assert runner.summary_line({"status": "FAIL", "issues": ["x"]}) == (
        "oa_enterprise_oidc_registration=fail issues=1"
    )

    monkeypatch.setattr(
        runner,
        "run_oa_enterprise_oidc_registration",
        lambda: passing,
    )
    assert runner.main(["--summary"]) == 0
    assert "oa_enterprise_oidc_registration=pass" in capsys.readouterr().out

    failing = {**passing, "status": "FAIL"}
    monkeypatch.setattr(
        runner,
        "run_oa_enterprise_oidc_registration",
        lambda: failing,
    )
    assert runner.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
