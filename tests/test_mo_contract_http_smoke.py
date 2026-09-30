from __future__ import annotations

import os
from pathlib import Path

import run_mo_contract_http_smoke as runner


def test_repository_mo_contract_http_smoke_is_deterministic() -> None:
    result = runner.run_mo_contract_http_smoke()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "protected_operation_count": 15,
        "unauthorized_rejection_count": 15,
        "provider_success_count": 7,
        "provider_contract_count": 7,
        "error_case_count": 6,
        "matched_error_count": 6,
        "external_request_count": 0,
    }
    assert result["next_slice"] == "1140"


def test_contract_http_smoke_fails_closed_for_incomplete_observations() -> None:
    result = runner.run_mo_contract_http_smoke(
        observations={
            "profile": "live",
            "persistence_mode": "postgres",
            "external_request_count": 1,
            "root_status": 500,
            "root_schema_valid": False,
            "service_claim_status": 401,
            "unauthorized_statuses": [200],
            "provider_results": [{"status": 500, "schema_valid": False}],
            "error_results": [{"status": 500, "expected_status": 400}],
            "payload_content_recorded": True,
        }
    )

    assert result["status"] == "FAIL"
    assert not any(result["checks"].values())
    assert result["next_slice"] == "blocked"


def test_contract_http_helpers_fail_closed_and_restore_environment(
    tmp_path: Path,
) -> None:
    os.environ.pop("NEX_SLICE_1139_TEST", None)
    with runner._temporary_environment({"NEX_SLICE_1139_TEST": "active"}):
        assert os.environ["NEX_SLICE_1139_TEST"] == "active"
    assert "NEX_SLICE_1139_TEST" not in os.environ

    assert runner._schema_valid(tmp_path, "missing", {}) is False
    assert runner._root_schema(tmp_path) == {}
    assert runner._validator_accepts({}, {}) is False
    assert runner._mapping(None) == {}
    assert runner._mapping_list([{"ok": True}]) == [{"ok": True}]
    assert runner._mapping_list(["invalid"]) == []
    assert runner._int_list([200, 401]) == [200, 401]
    assert runner._int_list(["401"]) == []
    assert runner._nonnegative_int(1) == 1
    assert runner._nonnegative_int(-1) == 0


def test_contract_http_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_contract_http_smoke()
    assert runner.summary_line(passing) == (
        "mo_contract_http_smoke=pass auth=15/15 providers=7/7 "
        "errors=6/6 external=0 next=1140"
    )

    monkeypatch.setattr(runner, "run_mo_contract_http_smoke", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "providers=7/7" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_mo_contract_http_smoke",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
