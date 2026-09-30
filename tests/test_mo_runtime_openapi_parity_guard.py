from __future__ import annotations

from pathlib import Path

import run_mo_runtime_openapi_parity_guard as runner


def test_repository_mo_runtime_openapi_parity_is_hardened() -> None:
    result = runner.run_mo_runtime_openapi_parity_guard()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "runtime_operation_count": 27,
        "openapi_operation_count": 27,
        "operation_id_count": 27,
        "protected_operation_count": 23,
        "secured_operation_count": 23,
        "canonical_component_count": 19,
        "drift_count": 0,
    }
    assert result["missing_openapi_operations"] == []
    assert result["extra_openapi_operations"] == []
    assert result["duplicate_operation_ids"] == []
    assert result["unsecured_operations"] == []
    assert result["next_slice"] == "1139"


def test_parity_guard_fails_closed_for_drift_and_duplicate_ids(
    tmp_path: Path,
) -> None:
    document = {
        "paths": {
            "/": {
                "get": {
                    "operationId": "duplicate",
                    "responses": {"200": {}},
                }
            },
            "/private": {"get": {"operationId": "duplicate"}},
        }
    }
    result = runner.run_mo_runtime_openapi_parity_guard(
        tmp_path,
        document=document,
        runtime_operations={"GET /", "GET /missing"},
        audit={"status": "FAIL", "summary": {"drift_count": 2}},
    )

    assert result["status"] == "FAIL"
    assert result["duplicate_operation_ids"] == ["duplicate"]
    assert result["unsecured_operations"] == ["GET /private"]
    assert result["missing_openapi_operations"] == ["GET /missing"]
    assert result["extra_openapi_operations"] == ["GET /private"]
    assert result["next_slice"] == "blocked"


def test_parity_helpers_fail_closed_for_invalid_inputs(tmp_path: Path) -> None:
    target = tmp_path / "contracts" / "openapi"
    target.mkdir(parents=True)
    (target / "nex-mo.openapi.yaml").write_text("paths: [", encoding="utf-8")

    assert runner._read_openapi(tmp_path) == {}
    assert runner._operation_map({"paths": {"/": ["invalid"]}}) == {}
    assert runner._mapping(None) == {}
    assert runner._count({"value": 3}, "value") == 3
    assert runner._count({"value": -1}, "value") == 0
    assert runner._count({"value": "3"}, "value") == 0


def test_parity_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_runtime_openapi_parity_guard()
    assert runner.summary_line(passing) == (
        "mo_runtime_openapi_parity_guard=pass operations=27/27 "
        "secured=23/23 canonical=19 drift=0 next=1139"
    )

    monkeypatch.setattr(
        runner,
        "run_mo_runtime_openapi_parity_guard",
        lambda: passing,
    )
    assert runner.main(["--summary"]) == 0
    assert "operations=27/27" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_mo_runtime_openapi_parity_guard",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
