from __future__ import annotations

from pathlib import Path

import run_mo_mvp_acceptance_contracts as runner


def test_repository_contracts_are_strict_and_canonical() -> None:
    evidence = runner.run_mo_mvp_acceptance_contracts()

    assert evidence["status"] == "PASS"
    assert all(evidence["checks"].values())
    assert evidence["failed_checks"] == []
    assert evidence["issues"] == []
    assert evidence["summary"] == {
        "passed_check_count": 8,
        "check_count": 8,
        "positive_fixture_count": 1,
        "negative_fixture_count": 2,
    }
    assert evidence["next_slice"] == "1198"


def test_contract_evidence_fails_closed_when_files_are_missing(
    tmp_path: Path,
) -> None:
    evidence = runner.run_mo_mvp_acceptance_contracts(tmp_path)

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "mo.mvp_acceptance.contract_failed"
    assert evidence["issues"] == ["FileNotFoundError"]
    assert len(evidence["failed_checks"]) == 8
    assert evidence["next_slice"] == "blocked"


def test_json_reader_rejects_non_object(tmp_path: Path) -> None:
    path = tmp_path / "array.json"
    path.write_text("[]", encoding="utf-8")

    try:
        runner._json(path)
    except ValueError as exc:
        assert str(exc) == "JSON document must be an object"
    else:  # pragma: no cover
        raise AssertionError("non-object JSON must fail")


def test_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_mvp_acceptance_contracts()
    assert runner.summary_line(passing) == (
        "mo_mvp_acceptance_contracts=pass checks=8/8 fixtures=1/2 next=1198"
    )
    assert runner._mapping(None) == {}

    monkeypatch.setattr(
        runner,
        "run_mo_mvp_acceptance_contracts",
        lambda: passing,
    )
    assert runner.main(["--summary"]) == 0
    assert "checks=8/8" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_mo_mvp_acceptance_contracts",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
