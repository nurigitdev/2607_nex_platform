from __future__ import annotations

from pathlib import Path

from nex_cx.current_state_traceability import (
    CAPABILITY_SPECS,
    CapabilitySpec,
    EvidenceRef,
    _inspect_evidence,
    build_cx_capability_traceability_inventory,
)
import run_cx_capability_traceability_inventory as runner


def test_repository_inventory_is_complete_and_traceable() -> None:
    result = build_cx_capability_traceability_inventory()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["summary"]["requirement_count"] == 8
    assert result["summary"]["traceable_count"] == 8
    assert result["summary"]["evidence_count"] >= 60
    assert [item["requirement_id"] for item in result["capabilities"]] == [
        f"CX-FR-{number:03d}" for number in range(1, 9)
    ]
    assert all(
        item["traceability_status"] == "TRACEABLE"
        for item in result["capabilities"]
    )
    assert result["decision"]["traceability_is_not_acceptance"] is True
    assert result["decision"]["new_table_required"] is False


def test_inventory_fails_closed_for_missing_and_incomplete_evidence(
    tmp_path: Path,
) -> None:
    implementation = tmp_path / "implementation.py"
    implementation.write_text("present but wrong token\n", encoding="utf-8")
    specs = (
        CapabilitySpec(
            "CX-FR-001",
            "incomplete",
            (
                EvidenceRef(
                    "implementation", "implementation.py", "expected token"
                ),
                EvidenceRef("contract", "missing.schema.json"),
            ),
        ),
        CapabilitySpec(
            "CX-FR-001",
            "duplicate",
            (EvidenceRef("test", "missing_test.py"),),
        ),
    )

    result = build_cx_capability_traceability_inventory(
        tmp_path,
        specs=specs,
    )

    assert result["status"] == "FAIL"
    assert result["failure_code"] == (
        "cx_capability_traceability_inventory_failed"
    )
    assert result["checks"] == {
        "requirement_set_complete": False,
        "requirement_ids_unique": False,
        "all_capabilities_traceable": False,
        "all_layers_represented": False,
    }
    assert len(result["issues"]) == 3
    assert {item["layer"] for item in result["issues"]} == {
        "implementation",
        "contract",
        "test",
    }


def test_evidence_inspection_covers_path_and_token_modes(tmp_path: Path) -> None:
    evidence_file = tmp_path / "evidence.txt"
    evidence_file.write_text("required token\n", encoding="utf-8")

    path_only = _inspect_evidence(
        tmp_path,
        EvidenceRef("test", "evidence.txt"),
    )
    token_match = _inspect_evidence(
        tmp_path,
        EvidenceRef("implementation", "evidence.txt", "required token"),
    )
    token_miss = _inspect_evidence(
        tmp_path,
        EvidenceRef("implementation", "evidence.txt", "absent token"),
    )
    path_miss = _inspect_evidence(
        tmp_path,
        EvidenceRef("contract", "missing.txt"),
    )

    assert path_only["present"] is True
    assert path_only["token_checked"] is False
    assert token_match["present"] is True
    assert token_match["token_checked"] is True
    assert token_miss["present"] is False
    assert path_miss["present"] is False


def test_runner_summary_json_and_failure_paths(monkeypatch, capsys) -> None:
    passing = runner.run_cx_capability_traceability_inventory()

    assert "inventory=pass" in runner.summary_line(passing)
    assert "requirements=8" in runner.summary_line(passing)
    monkeypatch.setattr(
        runner,
        "run_cx_capability_traceability_inventory",
        lambda: passing,
    )
    assert runner.main(["--summary"]) == 0
    assert "traceable=8" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    failing = {"status": "FAIL", "summary": {}, "issues": [{"gap": True}]}
    monkeypatch.setattr(
        runner,
        "run_cx_capability_traceability_inventory",
        lambda: failing,
    )
    assert runner.main(["--summary"]) == 1
    assert "inventory=fail" in capsys.readouterr().out
    assert "issues=1" in runner.summary_line(failing)


def test_capability_specs_keep_all_required_evidence_layers() -> None:
    required = {"implementation", "contract", "migration", "test", "route"}

    assert len(CAPABILITY_SPECS) == 8
    assert all(
        required.issubset({ref.layer for ref in spec.evidence})
        for spec in CAPABILITY_SPECS
    )
