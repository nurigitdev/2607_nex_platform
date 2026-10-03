import run_oa_group_role_authorization_domain as domain


def test_domain_evidence_passes() -> None:
    result = domain.run_oa_group_role_authorization_domain()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "check_count": 6,
        "passed_check_count": 6,
        "role_scope_count": 2,
        "entity_count": 4,
    }


def test_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = domain.run_oa_group_role_authorization_domain()
    assert "checks=6/6 entities=4" in domain.summary_line(passing)
    assert domain.main(["--summary"]) == 0
    assert "domain=pass" in capsys.readouterr().out

    monkeypatch.setattr(
        domain,
        "run_oa_group_role_authorization_domain",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert domain.main([]) == 1
