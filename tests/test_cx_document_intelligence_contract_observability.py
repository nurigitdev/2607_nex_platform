from __future__ import annotations

import json

import run_cx_document_intelligence_contract_observability as evidence


def test_document_intelligence_contract_observability_evidence_passes() -> None:
    result = evidence.run_cx_document_intelligence_contract_observability()

    assert result["status"] == "PASS"
    assert result["passed_checks"] == len(result["checks"]) == 10
    assert result["failed_checks"] == []
    assert result["postgres_required"] is False
    assert result["remote_provider_required"] is False
    assert result["event_types"] == [
        "cx.document_intelligence.ready",
        "cx.document_intelligence.similarity_observed",
        "cx.document_intelligence.failed",
    ]


def test_document_intelligence_contract_observability_summary_and_cli(
    monkeypatch,
    capsys,
) -> None:
    passing = evidence.run_cx_document_intelligence_contract_observability()
    assert evidence.summary_line(passing) == (
        "cx_document_intelligence_contract_observability=pass checks=10/10 "
        "postgres_required=False remote_required=False"
    )
    assert "checks=0/0" in evidence.summary_line({})

    monkeypatch.setattr(
        evidence,
        "run_cx_document_intelligence_contract_observability",
        lambda: passing,
    )
    assert evidence.main(["--summary"]) == 0
    assert "contract_observability=pass" in capsys.readouterr().out
    assert evidence.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        evidence,
        "run_cx_document_intelligence_contract_observability",
        lambda: {"status": "FAIL"},
    )
    assert evidence.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"


def test_schema_helpers_cover_invalid_schema_and_valid_negative() -> None:
    assert evidence._schemas_valid({"type": "object"}) is True
    assert evidence._schemas_valid({"type": "not-a-json-schema-type"}) is False

    validator = evidence.Draft202012Validator({"type": "object"})
    assert evidence._valid(validator, {}) is True
    assert evidence._invalid(validator, {}) is False
