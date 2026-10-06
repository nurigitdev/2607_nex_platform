from __future__ import annotations

import json

import run_oa_mvp_contract_privacy_runbook as runner


def test_contract_privacy_runbook_evidence_passes() -> None:
    evidence = runner.run_oa_mvp_contract_privacy_runbook()

    assert evidence["status"] == "PASS", evidence
    assert all(evidence["checks"].values())
    assert evidence["contract_counts"] == {
        "schemas": 166,
        "examples": 225,
        "negative_examples": 193,
        "openapi": 7,
    }
    assert evidence["summary"] == {
        "check_count": 11,
        "passed_check_count": 11,
        "route_count": 6,
        "strict_schema_count": 8,
        "document_count": 9,
        "privacy_violation_count": 0,
    }
    assert evidence["next_slice"] == "1300"


def test_schema_and_sensitive_route_helpers_fail_closed() -> None:
    assert runner._strict_schema({}) is False
    assert runner._strict_schema(
        {"type": "object", "additionalProperties": False, "required": []}
    ) is False
    assert runner._sensitive_route_matches(
        {}, route="/missing", scope="token:introspect"
    ) is False
    assert runner._auth_event_types({}) == set()


def test_document_loaders_fail_closed(tmp_path) -> None:
    missing = tmp_path / "missing"
    assert runner._yaml(missing) == {}
    assert runner._json(missing) == {}
    assert runner._text(missing) == ""

    yaml_path = tmp_path / "bad.yaml"
    yaml_path.write_text("value: [", encoding="utf-8")
    assert runner._yaml(yaml_path) == {}
    yaml_path.write_text("- item", encoding="utf-8")
    assert runner._yaml(yaml_path) == {}

    json_path = tmp_path / "bad.json"
    json_path.write_text("{", encoding="utf-8")
    assert runner._json(json_path) == {}
    json_path.write_text("[]", encoding="utf-8")
    assert runner._json(json_path) == {}


def test_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = runner.run_oa_mvp_contract_privacy_runbook()
    assert runner.summary_line(passing) == (
        "oa_mvp_contract_privacy_runbook=pass checks=11/11 schemas=166 "
        "routes=6 documents=9 privacy=0 next=1300"
    )

    monkeypatch.setattr(
        runner,
        "run_oa_mvp_contract_privacy_runbook",
        lambda: passing,
    )
    assert runner.main(["--summary"]) == 0
    assert "next=1300" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        runner,
        "run_oa_mvp_contract_privacy_runbook",
        lambda: {"status": "FAIL", "next_slice": "blocked"},
    )
    assert runner.main([]) == 1
