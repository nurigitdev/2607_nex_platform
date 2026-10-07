from __future__ import annotations

from pathlib import Path

import run_platform_production_security_boundary as boundary


def test_repository_boundary_freezes_s143_scope() -> None:
    result = boundary.run_platform_production_security_boundary()

    assert result["status"] == "PASS", result
    assert result["boundary_readiness"] == "BOUNDARY_FROZEN"
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["summary"] == {
        "required_path_count": len(boundary.REQUIRED_PATHS),
        "required_environment_count": 25,
        "secret_environment_count": 16,
        "public_connection_count": 9,
        "tls_endpoint_count": 9,
        "gap_count": 9,
        "missing_path_count": 0,
    }
    assert result["decision"] == {
        "provider_neutral_contract_required": True,
        "external_secret_provider_required_for_closure": True,
        "managed_tls_endpoint_required_for_closure": True,
        "production_connection_required": False,
        "production_deployment_approved": False,
        "new_table_required": False,
        "next_slice": "1424",
    }


def test_secret_and_connection_inventory_is_exact_and_nonoverlapping() -> None:
    result = boundary.run_platform_production_security_boundary()

    assert result["secret_environment_names"] == list(boundary.SECRET_ENV_NAMES)
    assert result["public_connection_environment_names"] == list(
        boundary.PUBLIC_CONNECTION_ENV_NAMES
    )
    assert result["tls_endpoint_environment_names"] == list(
        boundary.TLS_ENDPOINT_ENV_NAMES
    )
    assert len(result["gaps"]) == 9
    assert all(item["state"] == "OPEN" for item in result["gaps"])
    assert set(boundary.SECRET_ENV_NAMES).isdisjoint(
        boundary.PUBLIC_CONNECTION_ENV_NAMES
    )


def test_empty_repository_fails_closed(tmp_path: Path) -> None:
    result = boundary.run_platform_production_security_boundary(tmp_path)

    assert result["status"] == "FAIL"
    assert result["boundary_readiness"] == "AUDIT_FAILED"
    assert result["summary"]["missing_path_count"] == len(boundary.REQUIRED_PATHS)
    assert result["decision"]["next_slice"] == "blocked"
    assert result["issues"]


def test_text_summary_and_main_branches(tmp_path: Path, monkeypatch, capsys) -> None:
    source = tmp_path / "source"
    source.write_text("present", encoding="utf-8")
    assert boundary._read_text(source) == "present"
    assert boundary._read_text(tmp_path / "missing") == ""

    passing = boundary.run_platform_production_security_boundary()
    assert boundary.summary_line(passing) == (
        "platform_production_security_boundary=pass required=25 secrets=16 "
        "connections=9 tls=9 gaps=9 next=1424"
    )
    failing = {"status": "FAIL", "issues": ["one"]}
    assert boundary.summary_line(failing) == (
        "platform_production_security_boundary=fail issues=1"
    )

    monkeypatch.setattr(
        boundary, "run_platform_production_security_boundary", lambda: passing
    )
    assert boundary.main(["--summary"]) == 0
    assert "boundary=pass" in capsys.readouterr().out
    assert boundary.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        boundary, "run_platform_production_security_boundary", lambda: failing
    )
    assert boundary.main([]) == 1

