from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from nex_mo.main import app
from nex_mo.operations_contract import (
    _mapping,
    _read_json,
    _read_text,
    _read_yaml,
    build_operations_contract_audit,
)
from nex_runtime import issue_mock_service_token
import run_mo_operations_contract as runner


ROOT = Path(__file__).resolve().parents[1]


def _headers() -> dict[str, str]:
    token = issue_mock_service_token(service_id="nex-ag", audience="nex-mo")
    return {"Authorization": f"Bearer {token.access_token}"}


def test_repository_operations_contract_is_hardened() -> None:
    evidence = build_operations_contract_audit()

    assert evidence["status"] == "PASS"
    assert all(evidence["checks"].values())
    assert evidence["summary"] == {
        "check_count": 9,
        "passed_check_count": 9,
        "forbidden_field_count": 7,
        "positive_error_count": 0,
        "negative_error_count": 1,
    }
    assert evidence["next_slice"] == "1188"


def test_main_operations_route_returns_schema_valid_private_projection() -> None:
    response = TestClient(app).get(
        "/api/v1/operations-snapshot",
        headers=_headers(),
    )
    schema = _read_json(
        ROOT / "contracts/schemas/service/nex_mo/operations_snapshot.v1.schema.json"
    )

    assert response.status_code == 200
    payload = response.json()
    assert not list(Draft202012Validator(schema).iter_errors(payload))
    serialized = json.dumps(payload, sort_keys=True).lower()
    for private in (
        "api_key",
        "authorization",
        "database_url",
        "password",
        "ssh_target",
    ):
        assert private not in serialized


def test_contract_audit_fails_closed_for_missing_tree(tmp_path: Path) -> None:
    evidence = build_operations_contract_audit(tmp_path)

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "mo_operations_contract_failed"
    assert evidence["checks"]["canonical_schema_present"] is False
    assert evidence["checks"]["negative_privacy_fixture_rejected"] is False
    assert evidence["next_slice"] == "blocked"


def test_contract_read_helpers_fail_closed(tmp_path: Path) -> None:
    invalid_json = tmp_path / "invalid.json"
    invalid_yaml = tmp_path / "invalid.yaml"
    text_file = tmp_path / "note.txt"
    invalid_json.write_text("{", encoding="utf-8")
    invalid_yaml.write_text("paths: [", encoding="utf-8")
    text_file.write_text("present", encoding="utf-8")

    assert _read_json(invalid_json) == {}
    assert _read_json(tmp_path / "missing.json") == {}
    assert _read_yaml(invalid_yaml) == {}
    assert _read_yaml(tmp_path / "missing.yaml") == {}
    assert _read_text(text_file) == "present"
    assert _read_text(tmp_path / "missing.txt") == ""
    assert _mapping({"ok": True}) == {"ok": True}
    assert _mapping(None) == {}


def test_operations_contract_runner_summary_json_and_failure_paths(
    monkeypatch,
    capsys,
) -> None:
    evidence = runner.run_mo_operations_contract()

    assert runner.summary_line(evidence) == (
        "mo_operations_contract=pass checks=9/9 forbidden=7 next=1188"
    )
    monkeypatch.setattr(runner, "run_mo_operations_contract", lambda: evidence)
    assert runner.main(["--summary"]) == 0
    assert "next=1188" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_mo_operations_contract",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
