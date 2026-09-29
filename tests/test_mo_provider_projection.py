from __future__ import annotations

from dataclasses import replace

from nex_mo.provider_projection import project_model_profile, project_provider_route
from nex_mo.providers import DEFAULT_PROVIDER_ROUTES, build_model_profile_catalog
import run_mo_provider_projection_extraction as runner


def test_route_projection_preserves_public_shape_and_optional_dimension() -> None:
    embedding = DEFAULT_PROVIDER_ROUTES[0]
    generation = DEFAULT_PROVIDER_ROUTES[2]

    assert project_provider_route(embedding)["embedding_dimensions"] == 8
    assert "embedding_dimensions" not in project_provider_route(generation)
    assert project_provider_route(replace(generation, status="DEGRADED"))["status"] == (
        "DEGRADED"
    )


def test_model_projection_omits_private_runtime_fields() -> None:
    profile = build_model_profile_catalog({})[0]
    projected = project_model_profile(profile)

    assert projected["model_name"] == "Qwen3-Embedding-4B"
    assert projected["precision"] == "BF16"
    assert "model_path" not in projected
    assert "live_health_env" not in projected


def test_projection_extraction_evidence_and_runner(monkeypatch, capsys) -> None:
    passing = runner.run_mo_provider_projection_extraction()

    assert passing["status"] == "PASS"
    assert all(passing["checks"].values())
    assert passing["issues"] == []
    assert "projection_extraction=pass" in runner.summary_line(passing)
    monkeypatch.setattr(runner, "run_mo_provider_projection_extraction", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "private_fields=0" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    failing = {"status": "FAIL", "summary": {}}
    monkeypatch.setattr(runner, "run_mo_provider_projection_extraction", lambda: failing)
    assert runner.main(["--summary"]) == 1
    assert "projection_extraction=fail" in capsys.readouterr().out
