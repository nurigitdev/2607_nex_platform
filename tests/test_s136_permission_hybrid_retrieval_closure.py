from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError
import pytest

import run_s136_permission_hybrid_retrieval_closure as closure


def test_repository_closure_passes_and_hands_off_to_s137() -> None:
    result = closure.run_s136_permission_hybrid_retrieval_closure()

    assert result["status"] == "PASS", result
    assert all(result["checks"].values())
    assert result["failed_checks"] == []
    assert result["closure_readiness"] == "READY_FOR_S137"
    assert result["evidence_statuses"] == {
        "boundary": "PASS",
        "permission": "PASS",
        "current_chunk_postgres": "SKIPPED",
        "provider_identity": "PASS",
        "weighted_rrf": "PASS",
        "confidence": "PASS",
        "operations": "PASS",
        "raw_score_calibration": "SKIPPED",
        "protected_live": "SKIPPED",
    }
    assert result["summary"] == {
        "evidence_count": 9,
        "passed_evidence_count": 6,
        "protected_skip_count": 3,
        "check_count": 13,
        "passed_check_count": 13,
        "contract_artifact_count": 6,
        "decision_state_count": 3,
        "candidate_channel_count": 2,
    }
    assert result["decision"]["completion_signal_met"] is True
    assert result["decision"][
        "actual_protected_database_and_provider_evidence_recorded"
    ] is True
    assert result["decision"]["closure_database_or_provider_mutation_performed"] is False
    assert result["decision"]["generation_provider_required"] is False
    assert result["decision"]["next_requirement"] == "S137"


def test_closure_fails_closed_for_empty_repository(tmp_path: Path) -> None:
    result = closure.run_s136_permission_hybrid_retrieval_closure(tmp_path)

    assert result["status"] == "FAIL"
    assert result["closure_readiness"] == "BLOCKED"
    assert result["failed_checks"]
    assert result["summary"]["evidence_count"] == 0
    assert result["decision"]["next_requirement"] == "blocked"


def test_retrieval_handoff_examples_and_state_guards() -> None:
    schema = _json(closure.RETRIEVAL_SCHEMA)
    validator = Draft202012Validator(schema)
    ready = _json(closure.READY_EXAMPLE)
    no_answer = _json(closure.NO_ANSWER_EXAMPLE)

    validator.validate(ready)
    validator.validate(no_answer)

    missing_profile_hash = deepcopy(ready)
    missing_profile_hash["score_summary"].pop("calibration_profile_hash")
    with pytest.raises(ValidationError):
        validator.validate(missing_profile_hash)

    no_answer_with_evidence = deepcopy(no_answer)
    no_answer_with_evidence["evidence_items"] = ready["evidence_items"]
    with pytest.raises(ValidationError):
        validator.validate(no_answer_with_evidence)


def test_helpers_cover_mapping_text_and_noncanonical_root(tmp_path: Path) -> None:
    assert closure._mapping({"ok": True}) == {"ok": True}
    assert closure._mapping(None) == {}
    assert closure._run_evidence(tmp_path) == {}

    source = tmp_path / "source.md"
    source.write_text("line one\n  line two", encoding="utf-8")
    assert closure._read_text(source) == "line one\n  line two"
    assert closure._normalized_text(source) == "line one line two"
    assert closure._read_text(tmp_path / "missing.md") == ""


def test_summary_and_main_branches(monkeypatch, capsys) -> None:
    passing = {
        "status": "PASS",
        "summary": {
            "passed_evidence_count": 6,
            "protected_skip_count": 3,
            "evidence_count": 9,
            "passed_check_count": 13,
            "check_count": 13,
            "decision_state_count": 3,
        },
        "decision": {"next_requirement": "S137"},
    }
    assert closure.summary_line(passing) == (
        "s136_permission_hybrid_retrieval_closure=pass evidence=6+3/9 "
        "checks=13/13 states=3 next=S137"
    )
    assert closure.summary_line(
        {"status": "FAIL", "failed_checks": ["a"]}
    ) == "s136_permission_hybrid_retrieval_closure=fail checks=1"

    monkeypatch.setattr(
        closure,
        "run_s136_permission_hybrid_retrieval_closure",
        lambda: passing,
    )
    assert closure.main(["--summary"]) == 0
    assert "next=S137" in capsys.readouterr().out
    assert closure.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        closure,
        "run_s136_permission_hybrid_retrieval_closure",
        lambda: {"status": "FAIL", "failed_checks": []},
    )
    assert closure.main([]) == 1


def _json(path: str) -> dict[str, object]:
    return json.loads((closure.ROOT / path).read_text(encoding="utf-8"))
