from __future__ import annotations

import ast
import json
from pathlib import Path

import run_oa_token_surface_inventory as inventory


def test_repository_token_surface_inventory_passes() -> None:
    result = inventory.build_oa_token_surface_inventory()

    assert result["status"] == "PASS"
    assert result["issues"] == []
    assert all(result["checks"].values())
    assert result["scope"] == "production_source_only_excluding_tests"
    assert result["caller_coverage_gaps"] == {
        symbol: [] for symbol in inventory.TRACKED_SYMBOLS
    }
    assert result["transition_decision"] == {
        "mock_symbols_removed_in_s125": False,
        "production_silent_mock_fallback_allowed": False,
        "explicit_test_profile_compatibility_preserved": True,
        "signed_profile_implementation_requirement": "S126",
        "migration_order": (
            "shared_verifier_and_oa_issuer",
            "nex-ae-api",
            "nex-cx",
            "nex-mo",
            "nex-ag",
        ),
        "new_table_required": False,
        "database_evidence_required": False,
    }


def test_inventory_records_definition_calls_fallbacks_and_service_roles() -> None:
    result = inventory.build_oa_token_surface_inventory()
    symbols = result["symbols"]

    assert all(
        symbols[symbol]["definition_count"] == 1
        for symbol in inventory.TRACKED_SYMBOLS
    )
    service_issue = symbols["issue_mock_service_token"]
    assert service_issue["call_count"] >= service_issue["fallback_count"] >= 4
    assert set(service_issue["fallback_services"]) == {
        "shared",
        "nex-ae-api",
        "nex-cx",
        "nex-ag",
    }
    assert result["service_profiles"]["nex-oa"]["migration_role"] == (
        "issuer_session_owner_and_service_validator"
    )
    assert result["service_profiles"]["nex-mo"]["migration_role"] == (
        "token_consumer"
    )
    assert result["service_profiles"]["shared"]["migration_role"] == (
        "outbound_mock_fallback_and_token_consumer"
    )


def test_empty_repository_fails_closed_with_definition_and_caller_gaps(
    tmp_path: Path,
) -> None:
    result = inventory.build_oa_token_surface_inventory(tmp_path)

    assert result["status"] == "FAIL"
    assert result["failure_code"] == "oa_token_surface_inventory_failed"
    categories = {item["category"] for item in result["issues"]}
    assert categories == {
        "symbol_definition_drift",
        "caller_coverage_gap",
        "repository_evidence_missing",
        "inventory_check_failed",
    }


def test_scanner_reports_syntax_errors_and_classifies_direct_and_fallback_calls(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "services" / "nex-cx" / "nex_cx"
    source_dir.mkdir(parents=True)
    (source_dir / "valid.py").write_text(
        "def issue_mock_service_token():\n"
        "    pass\n"
        "configured = None\n"
        "direct = issue_mock_service_token()\n"
        "fallback = configured or issue_mock_service_token()\n",
        encoding="utf-8",
    )
    (source_dir / "invalid.py").write_text("def broken(:\n", encoding="utf-8")

    definitions, calls, issues = inventory._scan_python_sources(tmp_path)

    assert len(definitions["issue_mock_service_token"]) == 1
    assert [item.kind for item in calls["issue_mock_service_token"]] == [
        "direct",
        "fallback",
    ]
    assert issues == [
        {
            "category": "python_parse_error",
            "path": "services/nex-cx/nex_cx/invalid.py",
            "line": 1,
        }
    ]


def test_ast_helpers_cover_supported_and_unknown_shapes(tmp_path: Path) -> None:
    name_call = ast.parse("token()", mode="eval").body
    attribute_call = ast.parse("client.token()", mode="eval").body
    lambda_call = ast.parse("(lambda: None)()", mode="eval").body

    assert isinstance(name_call, ast.Call)
    assert isinstance(attribute_call, ast.Call)
    assert isinstance(lambda_call, ast.Call)
    assert inventory._call_name(name_call.func) == "token"
    assert inventory._call_name(attribute_call.func) == "token"
    assert inventory._call_name(lambda_call.func) is None
    assert inventory._service_name(
        tmp_path / "outside.py",
        tmp_path,
    ) == "outside_services"
    assert inventory._service_name(tmp_path / "services", tmp_path) == "unknown"
    assert inventory._read_text(tmp_path / "missing") == ""


def test_service_profile_can_report_unclassified() -> None:
    calls = {symbol: [] for symbol in inventory.TRACKED_SYMBOLS}

    assert inventory._service_profile("future-service", calls) == {
        "migration_role": "unclassified",
        "service_token_fallback_count": 0,
        "call_counts": {symbol: 0 for symbol in inventory.TRACKED_SYMBOLS},
    }


def test_summary_and_main_report_pass_and_failure(monkeypatch, capsys) -> None:
    passing = inventory.build_oa_token_surface_inventory()
    assert inventory.summary_line(passing).startswith(
        "oa_token_surface_inventory=pass service_calls="
    )
    assert inventory.summary_line(
        {"status": "FAIL", "issues": [{"category": "drift"}]}
    ) == "oa_token_surface_inventory=fail issues=1"

    monkeypatch.setattr(
        inventory,
        "build_oa_token_surface_inventory",
        lambda: passing,
    )
    assert inventory.main(["--summary"]) == 0
    assert "inventory=pass" in capsys.readouterr().out
    assert inventory.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        inventory,
        "build_oa_token_surface_inventory",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert inventory.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
