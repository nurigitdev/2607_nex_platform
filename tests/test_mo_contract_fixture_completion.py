from __future__ import annotations

import run_mo_contract_fixture_completion as runner


def test_repository_mo_contract_fixtures_are_complete() -> None:
    result = runner.run_mo_contract_fixture_completion()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "schema_count": 28,
        "positive_fixture_count": 28,
        "negative_fixture_count": 28,
        "remaining_drift_count": 0,
    }
    assert result["next_slice"] == "1135"


def test_fixture_completion_fails_closed_for_incomplete_audit() -> None:
    result = runner.run_mo_contract_fixture_completion(
        audit={
            "status": "FAIL",
            "summary": {
                "schema_count": 17,
                "positive_fixture_covered_count": 16,
                "negative_fixture_covered_count": 15,
                "drift_count": 27,
            },
            "missing_positive_fixture_schemas": ["positive"],
            "missing_negative_fixture_schemas": ["negative"],
        }
    )

    assert result["status"] == "FAIL"
    assert result["next_slice"] == "blocked"
    assert not all(result["checks"].values())


def test_fixture_completion_helpers_fail_closed() -> None:
    assert runner._mapping({"ok": True}) == {"ok": True}
    assert runner._mapping(None) == {}
    assert runner._count({"value": 2}, "value") == 2
    assert runner._count({"value": -1}, "value") == 0
    assert runner._count({"value": "2"}, "value") == 0


def test_fixture_completion_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_contract_fixture_completion()
    assert runner.summary_line(passing) == (
        "mo_contract_fixture_completion=pass positive=28/28 "
        "negative=28/28 drift=0 next=1135"
    )

    monkeypatch.setattr(
        runner,
        "run_mo_contract_fixture_completion",
        lambda: passing,
    )
    assert runner.main(["--summary"]) == 0
    assert "negative=28/28" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_mo_contract_fixture_completion",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
