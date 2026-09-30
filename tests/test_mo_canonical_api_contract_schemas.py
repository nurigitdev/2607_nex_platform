from __future__ import annotations

from pathlib import Path

import run_mo_canonical_api_contract_schemas as runner


def test_repository_mo_runtime_surfaces_match_canonical_schemas() -> None:
    result = runner.run_mo_canonical_api_contract_schemas()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "surface_count": 6,
        "request_schema_count": 3,
        "response_schema_count": 6,
        "validated_surface_count": 6,
    }
    assert {item["name"] for item in result["surfaces"]} == {
        "provider_routes",
        "model_profiles",
        "provider_telemetry",
        "embedding",
        "rerank",
        "generation",
    }
    assert result["next_slice"] == "1134"


def test_schema_evidence_fails_closed_when_contract_tree_is_missing(
    tmp_path: Path,
) -> None:
    result = runner.run_mo_canonical_api_contract_schemas(tmp_path)

    assert result["status"] == "FAIL"
    assert result["failure_code"] == "mo_canonical_api_contract_schemas_failed"
    assert result["failure_detail"] == "FileNotFoundError"
    assert result["next_slice"] == "blocked"


def test_schema_validation_helper_rejects_invalid_payload(tmp_path: Path) -> None:
    schema = tmp_path / "schema.json"
    schema.write_text(
        '{"type":"object","required":["ok"],'
        '"properties":{"ok":{"const":true}}}',
        encoding="utf-8",
    )

    assert runner._validates(schema, {"ok": True}) is True
    assert runner._validates(schema, {"ok": False}) is False


def test_privacy_helper_checks_keys_without_rejecting_safe_env_names() -> None:
    assert runner._contains_forbidden_key(
        {"authorization_env": "NEX_MO_REMOTE_API_KEY"}
    ) is False
    assert runner._contains_forbidden_key(
        {"nested": [{"provider_endpoint": "private"}]}
    ) is True
    assert runner._contains_forbidden_key(["api_key", "provider_endpoint"]) is False


def test_schema_runner_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_canonical_api_contract_schemas()
    assert runner.summary_line(passing) == (
        "mo_canonical_api_contract_schemas=pass surfaces=6/6 "
        "requests=3 responses=6 next=1134"
    )

    monkeypatch.setattr(
        runner,
        "run_mo_canonical_api_contract_schemas",
        lambda: passing,
    )
    assert runner.main(["--summary"]) == 0
    assert "surfaces=6/6" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_mo_canonical_api_contract_schemas",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
