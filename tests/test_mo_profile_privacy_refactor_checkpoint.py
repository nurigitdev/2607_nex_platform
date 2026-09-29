from __future__ import annotations

import json
from pathlib import Path

from nex_mo.profile_privacy_audit import (
    FORBIDDEN_PUBLIC_FIELDS,
    _read_json,
    _read_text,
    build_mo_profile_privacy_refactor_checkpoint,
)
import run_mo_profile_privacy_refactor_checkpoint as runner


def test_repository_profile_privacy_boundary_is_repaired() -> None:
    result = build_mo_profile_privacy_refactor_checkpoint()

    assert result["status"] == "PASS"
    assert result["refactor_readiness"] == "PRIVACY_BOUNDARY_REPAIRED"
    assert all(result["checks"].values())
    assert result["failed_checks"] == []
    assert result["summary"] == {
        "internal_profile_count": 5,
        "public_profile_count": 5,
        "forbidden_public_field_count": 0,
        "remaining_catalog_drift_count": 4,
    }
    assert not (FORBIDDEN_PUBLIC_FIELDS & set(result["public_profile_fields"]))
    assert result["decision"]["internal_model_paths_retained_for_runtime"] is True
    assert result["decision"]["public_model_paths_allowed"] is False


def test_checkpoint_fails_closed_when_contract_files_are_missing(tmp_path: Path) -> None:
    provider_path = tmp_path / "services/nex-mo/nex_mo/providers.py"
    provider_path.parent.mkdir(parents=True)
    provider_path.write_text("safe projection\n", encoding="utf-8")

    result = build_mo_profile_privacy_refactor_checkpoint(tmp_path)

    assert result["status"] == "FAIL"
    assert result["refactor_readiness"] == "BLOCKED"
    assert result["checks"]["schema_is_closed_and_private_fields_absent"] is False
    assert result["checks"]["model_path_negative_fixture_registered"] is False
    assert result["checks"]["route_privacy_contract_present"] is False
    assert result["failed_checks"] == sorted(result["failed_checks"])


def test_read_helpers_cover_valid_invalid_and_missing(tmp_path: Path) -> None:
    valid = tmp_path / "valid.json"
    invalid = tmp_path / "invalid.json"
    text = tmp_path / "text.txt"
    valid.write_text('{"value": 1}', encoding="utf-8")
    invalid.write_text("{", encoding="utf-8")
    text.write_text("content", encoding="utf-8")

    assert _read_json(valid) == {"value": 1}
    assert _read_json(invalid) == {}
    assert _read_json(tmp_path / "missing.json") == {}
    assert _read_text(text) == "content"
    assert _read_text(tmp_path / "missing.txt") == ""


def test_public_profile_schema_rejects_model_path_fixture() -> None:
    result = build_mo_profile_privacy_refactor_checkpoint()
    serialized = json.dumps(result, sort_keys=True)

    assert "/private/mo-model-root" not in serialized
    assert "model_path" not in result["public_profile_fields"]
    assert "live_health_env" not in result["public_profile_fields"]


def test_runner_summary_json_and_failure_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_profile_privacy_refactor_checkpoint()

    assert "checkpoint=pass" in runner.summary_line(passing)
    assert "forbidden_fields=0" in runner.summary_line(passing)
    monkeypatch.setattr(
        runner,
        "run_mo_profile_privacy_refactor_checkpoint",
        lambda: passing,
    )
    assert runner.main(["--summary"]) == 0
    assert "remaining_drift=4" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    failing = {"status": "FAIL", "summary": {}}
    monkeypatch.setattr(
        runner,
        "run_mo_profile_privacy_refactor_checkpoint",
        lambda: failing,
    )
    assert runner.main(["--summary"]) == 1
    assert "checkpoint=fail" in capsys.readouterr().out
