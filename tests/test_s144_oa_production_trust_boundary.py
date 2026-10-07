from __future__ import annotations

from pathlib import Path

import run_s144_oa_production_trust_boundary as boundary


def test_repository_boundary_freezes_s144_scope() -> None:
    result = boundary.run_oa_production_trust_boundary()

    assert result["status"] == "PASS", result
    assert result["boundary_readiness"] == "BOUNDARY_FROZEN"
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["summary"] == {
        "required_path_count": len(boundary.REQUIRED_PATHS),
        "check_count": 12,
        "gap_count": 8,
        "slice_count": 10,
        "missing_path_count": 0,
    }
    assert result["decision"] == {
        "single_host_compose_feasible": True,
        "key_custody_adapter": "openbao_transit",
        "staging_oidc_issuer": "openbao_oidc_provider",
        "provider_neutral_runtime_contract_required": True,
        "corporate_idp_contact_required_for_staging": False,
        "actual_external_acceptance_required_for_closure": True,
        "host_software_install_required": False,
        "production_connection_required": False,
        "production_deployment_approved": False,
        "new_table_required": False,
        "next_slice": "1434",
    }


def test_gap_inventory_is_exact_and_open() -> None:
    result = boundary.run_oa_production_trust_boundary()

    assert [item["gap_id"] for item in result["gaps"]] == [
        item.gap_id for item in boundary.PRODUCTION_TRUST_GAPS
    ]
    assert all(item["state"] == "OPEN" for item in result["gaps"])
    assert result["gaps"][6]["target_slices"] == ["1440", "1441"]


def test_empty_repository_fails_closed(tmp_path: Path) -> None:
    result = boundary.run_oa_production_trust_boundary(tmp_path)

    assert result["status"] == "FAIL"
    assert result["boundary_readiness"] == "AUDIT_FAILED"
    assert result["summary"]["missing_path_count"] == len(boundary.REQUIRED_PATHS)
    assert result["decision"]["next_slice"] == "blocked"
    assert result["issues"]


def test_helpers_summary_and_main_branches(tmp_path: Path, monkeypatch, capsys) -> None:
    source = tmp_path / "source"
    source.write_text('{"value": 1}', encoding="utf-8")
    assert boundary._read_text(source) == '{"value": 1}'
    assert boundary._read_text(tmp_path / "missing") == ""
    assert boundary._read_json(source) == {"value": 1}
    invalid = tmp_path / "invalid"
    invalid.write_text("[]", encoding="utf-8")
    assert boundary._read_json(invalid) == {}
    assert boundary._read_json(tmp_path / "absent") == {}

    passing = boundary.run_oa_production_trust_boundary()
    assert boundary.summary_line(passing) == (
        "oa_production_trust_boundary=pass checks=12/12 gaps=8 slices=10 "
        "single_host=true next=1434"
    )
    failing = {"status": "FAIL", "issues": ["one"]}
    assert boundary.summary_line(failing) == (
        "oa_production_trust_boundary=fail issues=1"
    )

    monkeypatch.setattr(boundary, "run_oa_production_trust_boundary", lambda: passing)
    assert boundary.main(["--summary"]) == 0
    assert "boundary=pass" in capsys.readouterr().out
    assert boundary.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(boundary, "run_oa_production_trust_boundary", lambda: failing)
    assert boundary.main([]) == 1
