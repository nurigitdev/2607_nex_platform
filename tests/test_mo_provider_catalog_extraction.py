from __future__ import annotations

from pathlib import Path

from nex_mo.provider_catalog import (
    build_model_profile_catalog,
    list_model_profiles,
)
from nex_mo.providers import build_model_profile_catalog as compatibility_catalog
import run_mo_provider_catalog_extraction as runner


def test_catalog_compatibility_and_selected_capabilities() -> None:
    direct = build_model_profile_catalog({})

    assert direct == compatibility_catalog({})
    assert {item.provider_capability for item in direct if item.selected} == {
        "embedding",
        "reranking",
        "generation",
    }
    assert len(list_model_profiles("generation", direct)) == 3
    assert list_model_profiles("missing", direct) == []


def test_catalog_owns_environment_resolution() -> None:
    profiles = build_model_profile_catalog(
        {
            "NEX_MO_PROVIDER_MODE": "live",
            "NEX_MO_MODEL_ROOT": "/private/models",
            "NEX_MO_GENERATION_PROFILE": "qwen3_6_27b_nvfp4",
            "NEX_MO_GENERATION_QWEN36_27B_MODEL_PATH": "/private/generation",
        }
    )
    generation = next(item for item in profiles if item.selected and item.provider_capability == "generation")

    assert generation.model_name == "Qwen3.6-27B-NVFP4"
    assert generation.model_path == "/private/generation"
    assert generation.status == "CONFIGURED"
    assert all("model_path" not in item.to_wire() for item in profiles)


def test_catalog_extraction_evidence_fails_closed_for_missing_source(
    tmp_path: Path,
) -> None:
    result = runner.run_mo_provider_catalog_extraction(tmp_path)

    assert result["status"] == "FAIL"
    assert result["checks"]["catalog_module_present"] is False
    assert result["checks"]["compatibility_import_present"] is False
    assert result["checks"]["environment_parsing_is_catalog_owned"] is False
    assert result["summary"]["failed_check_count"] == 3


def test_catalog_extraction_runner_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_provider_catalog_extraction()

    assert passing["status"] == "PASS"
    assert all(passing["checks"].values())
    monkeypatch.setattr(runner, "run_mo_provider_catalog_extraction", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "selected=3" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    failing = {"status": "FAIL", "summary": {}}
    monkeypatch.setattr(runner, "run_mo_provider_catalog_extraction", lambda: failing)
    assert runner.main(["--summary"]) == 1
    assert "catalog_extraction=fail" in capsys.readouterr().out
