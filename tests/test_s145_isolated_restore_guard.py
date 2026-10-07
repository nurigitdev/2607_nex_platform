from __future__ import annotations

import run_s145_isolated_restore_guard as audit


def test_deterministic_isolated_restore_guard_passes() -> None:
    result = audit.run_isolated_restore_guard()
    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["metrics"] == {"database_targets": 5, "restore_probes": 4}
    assert result["next_slice"] == "1447"


def test_summary_and_main_branches(monkeypatch, capsys) -> None:
    passing = audit.run_isolated_restore_guard()
    assert audit.summary_line(passing) == "postgres_isolated_restore_guard=pass checks=7/7 targets=5 probes=4 next=1447"
    failed = {"status": "FAIL", "checks": {"one": False}, "metrics": {}, "next_slice": "blocked"}
    assert audit.summary_line(failed) == "postgres_isolated_restore_guard=fail checks=0/1 targets=0 probes=0 next=blocked"
    monkeypatch.setattr(audit, "run_isolated_restore_guard", lambda: passing)
    assert audit.main(["--summary"]) == 0
    assert "guard=pass" in capsys.readouterr().out
    assert audit.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(audit, "run_isolated_restore_guard", lambda: failed)
    assert audit.main([]) == 1

