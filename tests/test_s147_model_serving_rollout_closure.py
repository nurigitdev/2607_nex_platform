from __future__ import annotations

import json
from pathlib import Path

import run_s147_model_serving_rollout_closure as closure


def test_s147_closure_passes_with_exact_repository_evidence() -> None:
    result = closure.run_s147_model_serving_rollout_closure()

    assert result["status"] == "PASS"
    assert result["closure_readiness"] == "READY_FOR_S148"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "audit_count": 8,
        "passed_audit_count": 8,
        "check_count": 14,
        "passed_check_count": 14,
        "provider_count": 3,
        "runtime_ready_count": 3,
        "rollout_count": 3,
        "event_count": 6,
        "residue_count": 0,
    }
    assert result["decision"] == {
        "model_independent_rollout_ready": True,
        "protected_current_revision_observation_complete": True,
        "candidate_promotion_claimed": False,
        "production_deployment_approved": False,
        "next_requirement": "S148",
        "s148_model_serving_input_ready": True,
        "s149_rollout_rehearsal_input_ready": True,
    }


def test_s147_closure_fails_closed_for_missing_repository(tmp_path: Path) -> None:
    result = closure.run_s147_model_serving_rollout_closure(tmp_path)

    assert result["status"] == "FAIL"
    assert result["closure_readiness"] == "BLOCKED"
    assert result["audit_statuses"] == {}
    assert result["decision"]["next_requirement"] == "blocked"
    assert result["failed_checks"]
    assert closure._run_audits(tmp_path) == {}


def test_s147_closure_helpers_fail_closed(tmp_path: Path) -> None:
    malformed = tmp_path / "malformed.json"
    sequence = tmp_path / "sequence.json"
    text_file = tmp_path / "text.md"
    malformed.write_text("{", encoding="utf-8")
    sequence.write_text("[]", encoding="utf-8")
    text_file.write_text("hello", encoding="utf-8")

    assert closure._mapping([]) == {}
    assert closure._read_text(text_file) == "hello"
    assert closure._read_text(tmp_path / "missing.md") == ""
    assert closure._read_json(malformed) == {}
    assert closure._read_json(sequence) == {}
    assert closure._read_json(tmp_path / "missing.json") == {}
    assert closure._file_digest(text_file).startswith("sha256:")
    assert closure._file_digest(tmp_path / "missing.bin") == ""
    assert closure._index_contains(malformed, ("missing",)) is False
    digest = closure._evidence_digest({"status": "PASS", "evidence_digest": "old"})
    assert digest.startswith("sha256:")


def test_s147_closure_summary_and_main(monkeypatch, capsys) -> None:
    passing = closure.run_s147_model_serving_rollout_closure()
    assert closure.summary_line(passing) == (
        "s147_model_serving_rollout_closure=pass audits=8/8 checks=14/14 "
        "providers=3 runtime=3 rollouts=3 events=6 residue=0 next=S148"
    )
    monkeypatch.setattr(
        closure,
        "run_s147_model_serving_rollout_closure",
        lambda: passing,
    )
    assert closure.main(["--summary"]) == 0
    assert "audits=8/8" in capsys.readouterr().out
    assert closure.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    failing = {"status": "FAIL", "failed_checks": ["drift"]}
    assert closure.summary_line(failing) == (
        "s147_model_serving_rollout_closure=fail checks=1"
    )
    monkeypatch.setattr(
        closure,
        "run_s147_model_serving_rollout_closure",
        lambda: failing,
    )
    assert closure.main(["--summary"]) == 1
    assert "closure=fail" in capsys.readouterr().out
