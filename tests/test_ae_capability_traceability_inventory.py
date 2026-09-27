from __future__ import annotations

from pathlib import Path

from nex_ae_api.current_state_traceability import (
    API_LAYERS,
    CAPABILITY_SPECS,
    WEB_LAYERS,
    CapabilitySpec,
    EvidenceRef,
    _inspect_evidence,
    build_ae_capability_traceability_inventory,
)
import run_ae_capability_traceability_inventory as runner


def test_repository_inventory_is_complete_and_traceable() -> None:
    result = build_ae_capability_traceability_inventory()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["summary"] == {
        "requirement_count": 11,
        "traceable_count": 11,
        "evidence_count": 78,
    }
    assert [item["requirement_id"] for item in result["capabilities"]] == [
        *(f"AEAPI-FR-{number:03d}" for number in range(1, 7)),
        *(f"AEWEB-FR-{number:03d}" for number in range(1, 6)),
    ]
    assert result["decision"]["traceability_is_not_acceptance"] is True
    assert result["decision"]["new_table_required"] is False


def test_inventory_fails_closed_for_missing_and_incomplete_evidence(
    tmp_path: Path,
) -> None:
    implementation = tmp_path / "implementation.py"
    implementation.write_text("present but wrong token\n", encoding="utf-8")
    specs = (
        CapabilitySpec(
            "AEAPI-FR-001",
            "incomplete",
            API_LAYERS,
            (
                EvidenceRef("implementation", "implementation.py", "expected"),
                EvidenceRef("contract", "missing.schema.json"),
            ),
        ),
        CapabilitySpec(
            "AEAPI-FR-001",
            "duplicate",
            WEB_LAYERS,
            (EvidenceRef("test", "missing_test.py"),),
        ),
    )

    result = build_ae_capability_traceability_inventory(tmp_path, specs=specs)

    assert result["status"] == "FAIL"
    assert result["checks"] == {
        "requirement_set_complete": False,
        "requirement_ids_unique": False,
        "all_capabilities_traceable": False,
        "required_layers_represented": False,
    }
    assert len(result["issues"]) == 3


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
        tmp_path, EvidenceRef("implementation", "evidence.txt", "absent token")
    )["present"] is False
    assert _inspect_evidence(
        tmp_path, EvidenceRef("contract", "missing.txt")
    )["present"] is False


def test_runner_summary_json_and_failure_paths(monkeypatch, capsys) -> None:
    passing = runner.run_ae_capability_traceability_inventory()

    assert "inventory=pass" in runner.summary_line(passing)
    assert "requirements=11" in runner.summary_line(passing)
    monkeypatch.setattr(
        runner,
        "run_ae_capability_traceability_inventory",
        lambda: passing,
    )
    assert runner.main(["--summary"]) == 0
    assert "traceable=11" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    failing = {"status": "FAIL", "summary": {}, "issues": [{"gap": True}]}
    monkeypatch.setattr(
        runner,
        "run_ae_capability_traceability_inventory",
        lambda: failing,
    )
    assert runner.main(["--summary"]) == 1
    assert "inventory=fail" in capsys.readouterr().out
    assert "issues=1" in runner.summary_line(failing)


def test_capability_specs_keep_required_evidence_layers() -> None:
    assert len(CAPABILITY_SPECS) == 11
    assert all(
        set(spec.required_layers).issubset({ref.layer for ref in spec.evidence})
        for spec in CAPABILITY_SPECS
    )
