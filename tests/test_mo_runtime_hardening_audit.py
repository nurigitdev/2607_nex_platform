from __future__ import annotations

from pathlib import Path

from nex_mo.runtime_hardening_audit import (
    MODULE_RULES,
    ModuleRule,
    _inspect_module,
    build_mo_runtime_hardening_audit,
)
import run_mo_runtime_hardening_audit as runner


def test_repository_runtime_hardening_is_complete() -> None:
    result = build_mo_runtime_hardening_audit()

    assert result["status"] == "PASS"
    assert result["readiness"] == "DECOMPOSITION_HARDENED"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "module_count": 8,
        "module_rule_pass_count": 8,
        "completed_boundary_count": 5,
        "compatibility_export_count": 5,
        "issue_count": 0,
    }
    assert result["persistence_status"] == "HYBRID_DECIDED_NOT_IMPLEMENTED"


def test_audit_fails_closed_for_missing_oversized_and_forbidden_modules(
    tmp_path: Path,
) -> None:
    path = tmp_path / "module.py"
    path.write_text("import httpx\nsecond\n", encoding="utf-8")
    rules = (
        ModuleRule("bad", "module.py", 1, ("import httpx",)),
        ModuleRule("missing", "missing.py", 1),
    )

    result = build_mo_runtime_hardening_audit(tmp_path, rules=rules)

    assert result["status"] == "FAIL"
    assert result["readiness"] == "BLOCKED"
    assert result["checks"]["module_inventory_complete"] is False
    assert result["checks"]["module_rules_pass"] is False
    assert len(result["issues"]) == 2


def test_module_inspection_covers_passing_rule(tmp_path: Path) -> None:
    path = tmp_path / "module.py"
    path.write_text("one\ntwo\n", encoding="utf-8")
    result = _inspect_module(tmp_path, ModuleRule("module", "module.py", 2))

    assert result["present"] is True
    assert result["within_budget"] is True
    assert result["rule_passed"] is True
    assert len(MODULE_RULES) == 8


def test_runtime_hardening_audit_runner_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_runtime_hardening_audit()

    assert "hardening_audit=pass" in runner.summary_line(passing)
    monkeypatch.setattr(runner, "run_mo_runtime_hardening_audit", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "modules=8/8" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    failing = {"status": "FAIL", "summary": {}}
    monkeypatch.setattr(runner, "run_mo_runtime_hardening_audit", lambda: failing)
    assert runner.main(["--summary"]) == 1
    assert "hardening_audit=fail" in capsys.readouterr().out
