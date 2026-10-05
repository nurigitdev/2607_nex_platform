from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    ROOT
    / "scripts/smoke/run_platform_grounded_generation_artifact_e2e.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "run_platform_grounded_generation_artifact_e2e",
        SCRIPT,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_grounded_generation_artifact_e2e_is_complete() -> None:
    result = _load_module().run_platform_grounded_generation_artifact_e2e(ROOT)

    assert result["status"] == "PASS"
    assert result["failed_checks"] == []
    assert result["summary"] == {
        "check_count": 12,
        "passed_check_count": 12,
        "component_count": 5,
        "passed_component_count": 5,
        "scenario_count": 4,
        "passed_scenario_count": 4,
    }
    assert result["scenarios"] == {
        "SUCCESS": True,
        "REPAIR": True,
        "DENIAL": True,
        "RECOVERY": True,
    }
    assert result["decision"]["next_slice"] == "1370"


def test_grounded_generation_artifact_e2e_fails_closed_on_missing_tree(
    tmp_path: Path,
) -> None:
    result = _load_module().run_platform_grounded_generation_artifact_e2e(
        tmp_path
    )

    assert result["status"] == "FAIL"
    assert result["failure_code"].endswith("e2e_failed")
    assert result["failed_checks"]
    assert result["decision"]["next_slice"] == "blocked"


def test_grounded_generation_artifact_e2e_helpers_cover_invalid_values(
    tmp_path: Path,
) -> None:
    module = _load_module()
    invalid_json = tmp_path / "invalid.json"
    invalid_json.write_text("{", encoding="utf-8")
    list_json = tmp_path / "list.json"
    list_json.write_text("[]", encoding="utf-8")

    assert module._read_json(invalid_json) == {}
    assert module._read_json(list_json) == {}
    assert module._mapping(None) == {}
    assert module._contains_forbidden_key({"nested": [{"raw_content": "x"}]})
    assert not module._contains_forbidden_key({"nested": ["safe"]})


def test_grounded_generation_artifact_e2e_cli_outputs(
    capsys,
    monkeypatch,
) -> None:
    module = _load_module()

    assert module.main(["--summary"]) == 0
    assert (
        "platform_grounded_generation_artifact_e2e=pass checks=12/12 "
        "components=5/5 scenarios=4/4 next=1370"
        in capsys.readouterr().out
    )
    assert module.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    failed = module.run_platform_grounded_generation_artifact_e2e(ROOT)
    failed["status"] = "FAIL"
    failed["decision"]["next_slice"] = "blocked"
    monkeypatch.setattr(
        module,
        "run_platform_grounded_generation_artifact_e2e",
        lambda: failed,
    )
    assert module.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
