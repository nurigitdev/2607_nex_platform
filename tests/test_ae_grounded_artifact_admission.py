from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/smoke/run_ae_grounded_artifact_admission.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "run_ae_grounded_artifact_admission",
        SCRIPT,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_grounded_artifact_admission_evidence_is_complete() -> None:
    result = _load_module().run_ae_grounded_artifact_admission(ROOT)

    assert result["summary"] == {
        "passed": 8,
        "total": 8,
        "issues": 0,
        "next_slice": "1368",
    }
    assert result["issues"] == []


def test_grounded_artifact_admission_evidence_reports_drift(tmp_path: Path) -> None:
    (tmp_path / "services/nex-ae-api/nex_ae_api").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    for relative in {
        path for path, _token in _load_module().TOKENS.values()
    }:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("missing\n", encoding="utf-8")
    (tmp_path / "tests/test_ae_async_artifact_response_lineage.py").write_text(
        "missing\n",
        encoding="utf-8",
    )

    result = _load_module().run_ae_grounded_artifact_admission(tmp_path)

    assert result["summary"]["issues"] == 8
    assert result["summary"]["next_slice"] == "blocked"


def test_grounded_artifact_admission_cli_outputs(capsys, monkeypatch) -> None:
    module = _load_module()
    assert module.main(["--summary"]) == 0

    assert (
        "ae_grounded_artifact_admission=pass checks=8/8 issues=0 next=1368"
        in capsys.readouterr().out
    )
    assert module.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    failed = module.run_ae_grounded_artifact_admission(ROOT)
    failed["status"] = "FAIL"
    failed["issues"] = ["forced"]
    failed["summary"] = {
        "passed": 7,
        "total": 8,
        "issues": 1,
        "next_slice": "blocked",
    }
    monkeypatch.setattr(module, "run_ae_grounded_artifact_admission", lambda: failed)
    assert module.main(["--summary"]) == 1
    assert "fail checks=7/8 issues=1 next=blocked" in capsys.readouterr().out
