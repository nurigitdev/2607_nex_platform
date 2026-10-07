from __future__ import annotations

from pathlib import Path

import run_s142_platform_deployment_packaging_closure as closure


def test_repository_closure_passes_and_hands_off_to_s143() -> None:
    result = closure.run_s142_platform_deployment_packaging_closure()

    assert result["status"] == "PASS", result
    assert result["closure_readiness"] == "READY_FOR_S143"
    assert result["failed_checks"] == []
    assert all(result["checks"].values())
    assert result["summary"] == {
        "audit_count": 8,
        "passed_audit_count": 8,
        "check_count": 15,
        "passed_check_count": 15,
        "artifact_count": 6,
        "process_binding_count": 13,
        "profile_count": 5,
        "packaged_process_step_count": 65,
        "image_digest_count": 0,
    }
    assert result["decision"] == {
        "package_context_accepted": True,
        "oci_image_execution_prerequisite_open": True,
        "release_set_published": False,
        "production_deployment_approved": False,
        "production_resources_contacted": False,
        "full_gate_registered": True,
        "next_requirement": "S143",
        "next_requirement_scope": (
            "production_configuration_secret_and_tls_lifecycle"
        ),
    }


def test_closure_fails_closed_for_empty_repository(tmp_path: Path) -> None:
    result = closure.run_s142_platform_deployment_packaging_closure(tmp_path)

    assert result["status"] == "FAIL"
    assert result["closure_readiness"] == "BLOCKED"
    assert result["summary"]["audit_count"] == 0
    assert result["decision"]["package_context_accepted"] is False
    assert result["decision"]["full_gate_registered"] is False
    assert result["decision"]["next_requirement"] == "blocked"
    assert result["failed_checks"]


def test_helpers_cover_mapping_text_summary_decision_and_noncanonical_root(
    tmp_path: Path,
) -> None:
    evidence = {
        "one": {
            "summary": {"count": 1},
            "decision": {"ready": True},
        }
    }
    assert closure._mapping({"ok": True}) == {"ok": True}
    assert closure._mapping(None) == {}
    assert closure._summary(evidence, "one") == {"count": 1}
    assert closure._summary(evidence, "missing") == {}
    assert closure._decision(evidence, "one") == {"ready": True}
    assert closure._decision(evidence, "missing") == {}
    assert closure._run_evidence(tmp_path) == {}

    source = tmp_path / "source.md"
    source.write_text("content", encoding="utf-8")
    assert closure._read_text(source) == "content"
    assert closure._read_text(tmp_path / "missing.md") == ""


def test_summary_and_main_branches(monkeypatch, capsys) -> None:
    passing = {
        "status": "PASS",
        "summary": {
            "passed_audit_count": 8,
            "audit_count": 8,
            "artifact_count": 6,
            "process_binding_count": 13,
            "profile_count": 5,
            "packaged_process_step_count": 65,
            "image_digest_count": 0,
        },
        "decision": {"next_requirement": "S143"},
    }
    assert closure.summary_line(passing) == (
        "s142_platform_deployment_packaging_closure=pass audits=8/8 "
        "artifacts=6 bindings=13 profiles=5 process_steps=65 images=0 "
        "next=S143"
    )
    failing = {"status": "FAIL", "failed_checks": ["one"]}
    assert closure.summary_line(failing) == (
        "s142_platform_deployment_packaging_closure=fail checks=1"
    )

    monkeypatch.setattr(
        closure,
        "run_s142_platform_deployment_packaging_closure",
        lambda: passing,
    )
    assert closure.main(["--summary"]) == 0
    assert "next=S143" in capsys.readouterr().out
    assert closure.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        closure,
        "run_s142_platform_deployment_packaging_closure",
        lambda: failing,
    )
    assert closure.main([]) == 1
