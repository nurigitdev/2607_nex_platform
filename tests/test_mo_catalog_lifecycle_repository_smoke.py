from __future__ import annotations

import run_mo_catalog_lifecycle_repository as runner


def test_repository_smoke_proves_migration_restart_and_cleanup() -> None:
    evidence = runner.run_mo_catalog_lifecycle_repository()

    assert evidence["status"] == "PASS"
    assert all(evidence["checks"].values())
    assert evidence["summary"] == {
        "migration_present": True,
        "catalog_entry_count": 3,
        "active_binding_count": 3,
        "deleted_entry_count": 3,
        "deleted_binding_count": 3,
    }


def test_repository_smoke_runner_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_catalog_lifecycle_repository()
    assert "repository=pass" in runner.summary_line(passing)
    monkeypatch.setattr(runner, "run_mo_catalog_lifecycle_repository", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "next=1175" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        runner,
        "run_mo_catalog_lifecycle_repository",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
