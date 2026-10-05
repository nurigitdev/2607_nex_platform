from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/smoke/run_ae_grounded_artifact_recovery_access.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "run_ae_grounded_artifact_recovery_access",
        SCRIPT,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_recovery_access_evidence_is_complete() -> None:
    result = _load_module().run_ae_grounded_artifact_recovery_access(ROOT)

    assert result["status"] == "PASS"
    assert result["summary"] == {
        "passed": 8,
        "total": 8,
        "issues": 0,
        "next_slice": "1369",
    }


def test_recovery_access_evidence_reports_drift(tmp_path: Path) -> None:
    module = _load_module()
    for relative in {path for path, _token in module.TOKENS.values()}:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("missing\n", encoding="utf-8")
    test_file = tmp_path / "tests/test_ae_grounded_artifact_recovery_access.py"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text("missing\n", encoding="utf-8")

    result = module.run_ae_grounded_artifact_recovery_access(tmp_path)

    assert result["status"] == "FAIL"
    assert result["summary"]["issues"] == 8


def test_recovery_access_cli_paths(capsys, monkeypatch) -> None:
    module = _load_module()
    assert module.main(["--summary"]) == 0
    assert "pass checks=8/8 issues=0 next=1369" in capsys.readouterr().out
    assert module.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    failed = module.run_ae_grounded_artifact_recovery_access(ROOT)
    failed.update(status="FAIL", issues=["forced"])
    failed["summary"].update(passed=7, issues=1, next_slice="blocked")
    monkeypatch.setattr(
        module,
        "run_ae_grounded_artifact_recovery_access",
        lambda: failed,
    )
    assert module.main(["--summary"]) == 1
    assert "fail checks=7/8 issues=1 next=blocked" in capsys.readouterr().out
