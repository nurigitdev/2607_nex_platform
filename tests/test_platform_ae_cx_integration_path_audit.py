from __future__ import annotations

from pathlib import Path

import run_platform_ae_cx_integration_path_audit as audit


def test_repository_ae_cx_path_audit_passes_and_exposes_owner_gap() -> None:
    result = audit.run_platform_ae_cx_integration_path_audit()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert len(result["clients"]) == 8
    assert all(
        client[key]
        for client in result["clients"]
        for key in ("present", "service_token", "owner_headers", "request_id", "traceparent")
    )
    assert len(result["cx_routes"]) == 5
    assert result["cross_database_references"] == []
    assert result["findings"]["local_owner_fallback_present"] is True
    assert result["findings"]["cross_database_reference_count"] == 0
    assert result["decision"]["owner_fallback_is_accepted_protected_state"] is False
    assert result["decision"]["next_slice"] == "1307"


def test_audit_fails_closed_for_empty_repository(tmp_path: Path) -> None:
    result = audit.run_platform_ae_cx_integration_path_audit(tmp_path)

    assert result["status"] == "FAIL"
    assert result["checks"] == {
        "all_ae_cx_clients_present": False,
        "all_ae_cx_clients_propagate_trust_owner_and_trace": False,
        "cx_core_routes_present": False,
        "upload_owner_is_overridden_from_browser_context": False,
        "async_generation_uses_idempotency_key": False,
        "ae_does_not_read_cx_database": True,
    }
    assert len(result["issues"]) == 5


def test_database_reference_scanner_reports_matching_python_files(
    tmp_path: Path,
) -> None:
    package = tmp_path / "services/nex-ae-api/nex_ae_api"
    package.mkdir(parents=True)
    (package / "bad.py").write_text('DB = "NEX_CX_DATABASE_URL"\n', encoding="utf-8")
    (package / "clean.py").write_text("VALUE = 1\n", encoding="utf-8")

    assert audit._matching_python_files(
        package,
        "NEX_CX_DATABASE_URL",
        root=tmp_path,
    ) == ["services/nex-ae-api/nex_ae_api/bad.py"]
    assert audit._matching_python_files(
        tmp_path / "missing",
        "NEX_CX_DATABASE_URL",
        root=tmp_path,
    ) == []


def test_read_text_and_summary_branches(tmp_path: Path) -> None:
    path = tmp_path / "source.py"
    path.write_text("source", encoding="utf-8")
    assert audit._read_text(path) == "source"
    assert audit._read_text(tmp_path / "missing.py") == ""

    passing = {
        "status": "PASS",
        "findings": {
            "ae_cx_client_count": 8,
            "cx_core_route_count": 5,
            "local_owner_fallback_present": True,
            "cross_database_reference_count": 0,
        },
        "decision": {"next_slice": "1307"},
    }
    assert audit.summary_line(passing) == (
        "platform_ae_cx_integration_path=pass clients=8 routes=5 "
        "owner_fallback=True cross_db=0 next=1307"
    )
    assert audit.summary_line({"status": "FAIL", "issues": [1]}) == (
        "platform_ae_cx_integration_path=fail issues=1"
    )


def test_main_prints_summary_json_and_failure(monkeypatch, capsys) -> None:
    passing = {
        "status": "PASS",
        "findings": {},
        "decision": {"next_slice": "1307"},
    }
    monkeypatch.setattr(
        audit,
        "run_platform_ae_cx_integration_path_audit",
        lambda: passing,
    )
    assert audit.main(["--summary"]) == 0
    assert "integration_path=pass" in capsys.readouterr().out
    assert audit.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        audit,
        "run_platform_ae_cx_integration_path_audit",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert audit.main([]) == 1
