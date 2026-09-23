from __future__ import annotations

import json
from pathlib import Path

import run_cx_grounded_generation_runtime_boundary_audit as audit


def test_repository_grounded_generation_runtime_boundary_passes() -> None:
    result = audit.run_cx_grounded_generation_runtime_boundary_audit()

    assert result["status"] == "PASS"
    assert result["boundary_readiness"] == "BOUNDARY_CURRENT"
    assert result["summary"] == {
        "foundation_count": 5,
        "gap_count": 8,
        "open_gap_count": 3,
        "resolved_gap_count": 5,
        "planned_slice_count": 10,
        "issue_count": 0,
    }
    assert all(result["checks"].values())
    assert all(result["gap_checks"].values())
    assert result["gap_states"]["provider_prompt_evidence_binding_missing"] == (
        "RESOLVED"
    )
    assert result["gap_states"]["provider_output_structure_validation_weak"] == (
        "RESOLVED"
    )
    assert result["gap_states"]["durable_private_generated_output_missing"] == (
        "RESOLVED"
    )
    assert result["gap_states"]["sql_generation_runtime_store_missing"] == (
        "RESOLVED"
    )
    assert result["gap_states"]["idempotent_execution_admission_missing"] == (
        "RESOLVED"
    )
    assert list(result["gap_states"].values()).count("OPEN") == 3
    assert result["next_slice"] == "0967"


def test_grounded_generation_runtime_boundary_freezes_runtime_decisions() -> None:
    decision = audit._boundary_decision()

    assert decision["generation_model"] == "Qwen3.5-4B"
    assert decision["generation_provider_port"] == 9111
    assert decision["retrieval_input_policy"] == (
        "owner_admitted_ready_package_only"
    )
    assert decision["execution_policy"] == (
        "bounded_synchronous_idempotent_write_through"
    )
    assert decision["private_output_policy"] == (
        "durable_private_payload_reference"
    )
    assert decision["remote_provider_required_now"] is False
    assert decision["remote_provider_required_slice"] == "0969"
    assert "asynchronous_generation_worker" in decision["deferred_scope"]


def test_grounded_generation_runtime_boundary_fails_closed_for_missing_repo(
    tmp_path: Path,
) -> None:
    result = audit.run_cx_grounded_generation_runtime_boundary_audit(tmp_path)

    assert result["status"] == "FAIL"
    assert result["boundary_readiness"] == "AUDIT_FAILED"
    assert result["summary"]["issue_count"] > 0
    assert result["summary"]["open_gap_count"] == 8
    assert result["checks"]["required_paths_present"] is False
    assert result["checks"]["required_tokens_present"] is False


def test_grounded_generation_runtime_boundary_helpers(tmp_path: Path) -> None:
    assert audit._group_present([], "missing") is False
    assert audit._read_text(tmp_path / "missing") == ""
    assert audit._read_tree(tmp_path / "missing", "*.sql") == ""

    file_path = tmp_path / "present"
    file_path.write_text("value", encoding="utf-8")
    assert audit._read_text(file_path) == "value"

    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "b.sql").write_text("second", encoding="utf-8")
    (tree / "a.sql").write_text("first", encoding="utf-8")
    assert audit._read_tree(tree, "*.sql") == "first\nsecond"


def test_grounded_generation_runtime_boundary_summary_and_main(
    monkeypatch,
    capsys,
) -> None:
    passing = audit.run_cx_grounded_generation_runtime_boundary_audit()
    assert audit.summary_line(passing) == (
        "cx_grounded_generation_runtime_boundary=pass foundations=5 gaps=8 "
        "open=3 scope=owner_private_grounded_generation_runtime "
        "remote_required_now=False issues=0"
    )
    assert "scope=unknown" in audit.summary_line({"status": "FAIL"})

    monkeypatch.setattr(
        audit,
        "run_cx_grounded_generation_runtime_boundary_audit",
        lambda: passing,
    )
    assert audit.main(["--summary"]) == 0
    assert "boundary=pass" in capsys.readouterr().out
    assert audit.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        audit,
        "run_cx_grounded_generation_runtime_boundary_audit",
        lambda: {"status": "FAIL"},
    )
    assert audit.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
