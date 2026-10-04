from __future__ import annotations

from pathlib import Path

import run_platform_runtime_profile_residue_audit as audit


def test_repository_runtime_profile_audit_passes_with_explicit_gaps() -> None:
    result = audit.run_platform_runtime_profile_residue_audit()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["declared_profiles"] == list(audit.EXPECTED_PROFILES)
    assert result["runner_services"] == list(audit.BACKEND_SERVICES)
    assert result["direct_provider_references_outside_mo"] == []
    assert result["findings"] == {
        "mock_first_defaults": 4,
        "runtime_profile_count": 5,
        "backend_runner_service_count": 5,
        "backend_runner_includes_ae_web": False,
        "backend_runner_waits_for_readiness": False,
        "service_shell_validates_runtime_profile": False,
        "direct_provider_reference_count_outside_mo": 0,
        "canonical_runtime_profile_manifest_present": False,
    }
    assert result["decision"]["live_provider_mode_remains_opt_in"] is True
    assert result["decision"]["current_runner_is_release_topology"] is False
    assert result["decision"]["next_slice"] == "1305"


def test_audit_fails_closed_when_repository_evidence_is_absent(
    tmp_path: Path,
) -> None:
    result = audit.run_platform_runtime_profile_residue_audit(tmp_path)

    assert result["status"] == "FAIL"
    assert len(result["issues"]) == 8
    assert result["checks"]["remote_provider_endpoints_are_mo_owned"] is True


def test_direct_provider_reference_scanner_detects_non_mo_ownership(
    tmp_path: Path,
) -> None:
    cx_root = tmp_path / "services/nex-cx/nex_cx"
    cx_root.mkdir(parents=True)
    (cx_root / "bad_client.py").write_text(
        'endpoint = "NEX_MO_REMOTE_EMBEDDING_URL"\n'
        'generation = "NEX_MO_VLLM_BASE_URL"\n',
        encoding="utf-8",
    )

    assert audit._direct_provider_references(tmp_path) == [
        {
            "service": "nex-cx",
            "environment": "NEX_MO_REMOTE_EMBEDDING_URL",
            "path": "services/nex-cx/nex_cx/bad_client.py",
        },
        {
            "service": "nex-cx",
            "environment": "NEX_MO_VLLM_BASE_URL",
            "path": "services/nex-cx/nex_cx/bad_client.py",
        },
    ]


def test_read_text_and_summary_branches(tmp_path: Path) -> None:
    path = tmp_path / "value.txt"
    path.write_text("value", encoding="utf-8")
    assert audit._read_text(path) == "value"
    assert audit._read_text(tmp_path / "missing.txt") == ""

    passing = {
        "status": "PASS",
        "findings": {
            "runtime_profile_count": 5,
            "backend_runner_service_count": 5,
            "backend_runner_includes_ae_web": False,
            "backend_runner_waits_for_readiness": False,
            "direct_provider_reference_count_outside_mo": 0,
        },
        "decision": {"next_slice": "1305"},
    }
    assert audit.summary_line(passing) == (
        "platform_runtime_profile_residue=pass profiles=5 backends=5 "
        "web=False readiness=False direct_provider_refs=0 next=1305"
    )
    assert audit.summary_line({"status": "FAIL", "issues": ["one"]}) == (
        "platform_runtime_profile_residue=fail issues=1"
    )


def test_main_prints_summary_json_and_failure(monkeypatch, capsys) -> None:
    passing = {
        "status": "PASS",
        "findings": {},
        "decision": {"next_slice": "1305"},
    }
    monkeypatch.setattr(
        audit,
        "run_platform_runtime_profile_residue_audit",
        lambda: passing,
    )
    assert audit.main(["--summary"]) == 0
    assert "residue=pass" in capsys.readouterr().out
    assert audit.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        audit,
        "run_platform_runtime_profile_residue_audit",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert audit.main([]) == 1
