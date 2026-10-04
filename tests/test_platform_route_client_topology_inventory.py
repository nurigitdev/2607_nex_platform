from __future__ import annotations

from pathlib import Path

import run_platform_route_client_topology_inventory as inventory


def test_inventory_passes_and_exposes_refactoring_gap() -> None:
    result = inventory.run_platform_route_client_topology_inventory()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["findings"]["http_edge_count"] == 11
    assert result["findings"]["logical_edge_count"] == 7
    assert result["findings"]["cross_service_package_import_count"] == 0
    assert result["findings"]["ag_cross_service_database_coupling_count"] == 4
    assert result["findings"]["base_url_configuration_count"] > 0
    assert result["findings"]["canonical_topology_manifest_present"] is False
    assert result["refactoring_candidates"][0]["priority"] == "P0"
    assert result["decision"]["cross_service_database_reads_allowed"] is False
    assert result["decision"]["mutation_performed"] is False
    assert result["decision"]["next_slice"] == "1304"


def test_inventory_fails_closed_for_empty_repository(tmp_path: Path) -> None:
    result = inventory.run_platform_route_client_topology_inventory(tmp_path)

    assert result["status"] == "FAIL"
    assert result["checks"] == {
        "all_expected_http_edges_present": False,
        "no_cross_service_python_package_imports": True,
        "ag_database_coupling_inventory_complete": False,
        "base_url_configuration_is_discoverable": False,
    }
    assert len(result["issues"]) == 11


def test_cross_service_import_scanner_detects_only_foreign_packages(
    tmp_path: Path,
) -> None:
    package = tmp_path / "services/nex-ae-api/nex_ae_api"
    package.mkdir(parents=True)
    (package / "client.py").write_text(
        "from nex_ae_api.local import helper\n"
        "from nex_cx.api import CxApi\n"
        "import nex_mo\n",
        encoding="utf-8",
    )

    assert inventory._cross_service_package_imports(tmp_path) == [
        {
            "owner": "nex-ae-api",
            "target_package": "nex_cx",
            "path": "services/nex-ae-api/nex_ae_api/client.py",
        },
        {
            "owner": "nex-ae-api",
            "target_package": "nex_mo",
            "path": "services/nex-ae-api/nex_ae_api/client.py",
        },
    ]


def test_base_url_scanner_deduplicates_file_environment_names(
    tmp_path: Path,
) -> None:
    package = tmp_path / "services/nex-cx/nex_cx"
    package.mkdir(parents=True)
    (package / "client.py").write_text(
        'A = "NEX_MO_BASE_URL"\nB = "NEX_MO_BASE_URL"\n',
        encoding="utf-8",
    )

    assert inventory._base_url_configuration_occurrences(tmp_path) == [
        {
            "service": "nex-cx",
            "environment": "NEX_MO_BASE_URL",
            "path": "services/nex-cx/nex_cx/client.py",
        }
    ]


def test_read_text_and_summary_branches(tmp_path: Path) -> None:
    present = tmp_path / "present.py"
    present.write_text("content", encoding="utf-8")
    assert inventory._read_text(present) == "content"
    assert inventory._read_text(tmp_path / "missing.py") == ""

    passing = {
        "status": "PASS",
        "findings": {
            "http_edge_count": 11,
            "logical_edge_count": 7,
            "cross_service_package_import_count": 0,
            "ag_cross_service_database_coupling_count": 4,
            "canonical_topology_manifest_present": False,
        },
        "decision": {"next_slice": "1304"},
    }
    assert inventory.summary_line(passing) == (
        "platform_route_client_topology=pass http=11 logical=7 "
        "cross_imports=0 ag_db_couplings=4 topology_manifest=False next=1304"
    )
    assert inventory.summary_line({"status": "FAIL", "issues": [1, 2]}) == (
        "platform_route_client_topology=fail issues=2"
    )


def test_main_prints_summary_json_and_failure(monkeypatch, capsys) -> None:
    passing = {
        "status": "PASS",
        "findings": {},
        "decision": {"next_slice": "1304"},
    }
    monkeypatch.setattr(
        inventory,
        "run_platform_route_client_topology_inventory",
        lambda: passing,
    )
    assert inventory.main(["--summary"]) == 0
    assert "topology=pass" in capsys.readouterr().out
    assert inventory.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        inventory,
        "run_platform_route_client_topology_inventory",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert inventory.main([]) == 1
