from __future__ import annotations

from pathlib import Path

from nex_oa.current_state_traceability import (
    CAPABILITY_SPECS,
    REQUIRED_LAYERS,
    CapabilitySpec,
    EvidenceRef,
    _inspect_evidence,
    build_oa_capability_traceability_inventory,
)
import run_oa_capability_traceability_inventory as runner


def test_repository_inventory_is_complete_and_traceable() -> None:
    result = build_oa_capability_traceability_inventory()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["summary"] == {
        "requirement_count": 5,
        "traceable_count": 5,
        "implemented_count": 1,
        "partial_count": 4,
        "evidence_count": 25,
    }
    assert [item["requirement_id"] for item in result["capabilities"]] == [
        f"OA-FR-{number:03d}" for number in range(1, 6)
    ]
    assert result["decision"]["traceability_is_not_acceptance"] is True
    assert result["decision"]["partial_requirements_are_s122_inputs"] is True


def test_inventory_fails_closed_for_missing_duplicate_and_unexplained_partial(
    tmp_path: Path,
) -> None:
    present = tmp_path / "present.py"
    present.write_text("wrong token\n", encoding="utf-8")
    specs = (
        CapabilitySpec(
            "OA-FR-001",
            "incomplete",
            "PARTIAL",
            None,
            (
                EvidenceRef("implementation", "present.py", "expected"),
                EvidenceRef("test", "missing.py"),
            ),
        ),
        CapabilitySpec(
            "OA-FR-001",
            "duplicate",
            "IMPLEMENTED",
            None,
            (EvidenceRef("operations", "missing.md"),),
        ),
    )

    result = build_oa_capability_traceability_inventory(tmp_path, specs=specs)

    assert result["status"] == "FAIL"
    assert result["checks"] == {
        "requirement_set_complete": False,
        "requirement_ids_unique": False,
        "all_capabilities_traceable": False,
        "partial_capabilities_have_explicit_gaps": False,
    }
    assert {item["category"] for item in result["issues"]} == {
        "evidence_missing",
        "layer_missing",
    }


def test_evidence_inspection_covers_path_and_token_modes(tmp_path: Path) -> None:
    evidence_file = tmp_path / "evidence.txt"
    evidence_file.write_text("required token\n", encoding="utf-8")

    assert _inspect_evidence(
        tmp_path, EvidenceRef("test", "evidence.txt")
    )["present"] is True
    assert _inspect_evidence(
        tmp_path, EvidenceRef("implementation", "evidence.txt", "required token")
    )["present"] is True
    assert _inspect_evidence(
        tmp_path, EvidenceRef("implementation", "evidence.txt", "absent")
    )["present"] is False
    assert _inspect_evidence(
        tmp_path, EvidenceRef("test", "missing.txt")
    )["present"] is False


def test_specs_keep_required_layers_and_explicit_partial_gaps() -> None:
    assert len(CAPABILITY_SPECS) == 5
    assert all(
        set(REQUIRED_LAYERS).issubset({ref.layer for ref in spec.evidence})
        for spec in CAPABILITY_SPECS
    )
    assert all(
        spec.implementation_status != "PARTIAL" or spec.gap
        for spec in CAPABILITY_SPECS
    )


def test_runner_summary_json_and_failure_paths(monkeypatch, capsys) -> None:
    passing = runner.run_oa_capability_traceability_inventory()

    assert "inventory=pass" in runner.summary_line(passing)
    assert "requirements=5" in runner.summary_line(passing)
    assert "partial=4" in runner.summary_line(passing)
    monkeypatch.setattr(
        runner,
        "run_oa_capability_traceability_inventory",
        lambda: passing,
    )
    assert runner.main(["--summary"]) == 0
    assert "traceable=5" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    failing = {"status": "FAIL", "summary": {}, "issues": [{"gap": True}]}
    monkeypatch.setattr(
        runner,
        "run_oa_capability_traceability_inventory",
        lambda: failing,
    )
    assert runner.main(["--summary"]) == 1
    assert "inventory=fail" in capsys.readouterr().out
    assert "issues=1" in runner.summary_line(failing)
