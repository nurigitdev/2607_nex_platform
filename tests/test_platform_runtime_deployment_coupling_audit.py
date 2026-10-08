from __future__ import annotations

from pathlib import Path

import run_platform_runtime_deployment_coupling_audit as audit


def test_repository_coupling_audit_freezes_current_boundary() -> None:
    result = audit.run_platform_runtime_deployment_coupling_audit()

    assert result["status"] == "PASS", result
    assert result["issues"] == []
    assert all(result["checks"].values())
    assert result["summary"] == {
        "http_client_anchor_count": 11,
        "logical_api_edge_count": 7,
        "cross_service_import_count": 0,
        "non_mo_provider_reference_count": 0,
        "legacy_database_adapter_count": 4,
        "loopback_occurrence_count": 46,
        "loopback_file_count": 26,
        "source_process_count": 13,
        "coupling_record_count": 6,
    }
    assert result["decision"] == {
        "shared_runtime_imports_allowed": True,
        "service_domain_imports_allowed": False,
        "cross_service_database_reads_allowed": False,
        "direct_provider_access_outside_mo_allowed": False,
        "production_connection_required": False,
        "next_slice": "1407",
    }


def test_empty_repository_fails_closed(tmp_path: Path) -> None:
    result = audit.run_platform_runtime_deployment_coupling_audit(tmp_path)

    assert result["status"] == "FAIL"
    assert result["loopback_evidence"] == {
        "file_count": 0,
        "occurrence_count": 0,
        "files": [],
    }
    assert result["decision"]["next_slice"] == "blocked"
    assert "prior_topology_inventory_passed" in result["issues"]
    assert "all_coupling_records_documented" in result["issues"]


def test_loopback_scanner_counts_and_sorts_files(tmp_path: Path) -> None:
    shared = tmp_path / "services/_shared"
    shared.mkdir(parents=True)
    (shared / "z.py").write_text(
        'A = "http://127.0.0.1:1"\nB = "http://127.0.0.1:2"\n',
        encoding="utf-8",
    )
    oa = tmp_path / "services/nex-oa"
    oa.mkdir(parents=True)
    (oa / "a.py").write_text('A = "http://127.0.0.1:3"\n', encoding="utf-8")

    assert audit._loopback_occurrences(tmp_path) == {
        "file_count": 2,
        "occurrence_count": 3,
        "files": [
            {"path": "services/_shared/z.py", "occurrence_count": 2},
            {"path": "services/nex-oa/a.py", "occurrence_count": 1},
        ],
    }


def test_projection_guard_and_text_helpers(tmp_path: Path, monkeypatch) -> None:
    assert audit._protected_legacy_projection_rejected() is True
    monkeypatch.setattr(audit, "resolve_ag_projection_policy", lambda *a, **k: None)
    assert audit._protected_legacy_projection_rejected() is False

    assert audit._read_text(tmp_path / "missing") == ""
    source = tmp_path / "source"
    source.write_text("value", encoding="utf-8")
    assert audit._read_text(source) == "value"


def test_summary_and_main_branches(monkeypatch, capsys) -> None:
    passing = audit.run_platform_runtime_deployment_coupling_audit()
    assert audit.summary_line(passing) == (
        "platform_runtime_deployment_coupling_audit=pass http=11 imports=0 "
        "provider_refs=0 legacy_db=4 loopback=46/26 processes=13 next=1407"
    )
    failing = {"status": "FAIL", "issues": ["one"]}
    assert audit.summary_line(failing) == (
        "platform_runtime_deployment_coupling_audit=fail issues=1"
    )

    monkeypatch.setattr(
        audit, "run_platform_runtime_deployment_coupling_audit", lambda: passing
    )
    assert audit.main(["--summary"]) == 0
    assert "audit=pass" in capsys.readouterr().out
    assert audit.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        audit,
        "run_platform_runtime_deployment_coupling_audit",
        lambda: failing,
    )
    assert audit.main([]) == 1
