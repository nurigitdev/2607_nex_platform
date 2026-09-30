from __future__ import annotations

from pathlib import Path

import run_mo_log_retention_openapi_contract as runner


def test_repository_mo_log_retention_openapi_matches_runtime() -> None:
    result = runner.run_mo_log_retention_openapi_contract()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "operation_count": 3,
        "documented_operation_count": 3,
        "component_count": 4,
        "remaining_drift_count": 1,
    }
    assert all(result["components"].values())
    assert result["next_slice"] == "1138"


def test_retention_contract_fails_closed_for_missing_operations(
    tmp_path: Path,
) -> None:
    result = runner.run_mo_log_retention_openapi_contract(
        tmp_path,
        document={},
        runtime_operations=set(),
        audit={"summary": {}, "missing_openapi_operations": []},
    )

    assert result["status"] == "FAIL"
    assert result["summary"]["documented_operation_count"] == 0
    assert result["checks"]["only_root_operation_remains"] is False
    assert result["next_slice"] == "blocked"


def test_retention_helpers_cover_invalid_inputs(tmp_path: Path) -> None:
    target = tmp_path / "contracts" / "openapi"
    target.mkdir(parents=True)
    (target / "nex-mo.openapi.yaml").write_text("paths: [", encoding="utf-8")

    assert runner._read_openapi(tmp_path) == {}
    assert runner._mapping(None) == {}
    assert runner._count({"value": 3}, "value") == 3
    assert runner._count({"value": -1}, "value") == 0
    assert runner._count({"value": "3"}, "value") == 0


def test_retention_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_log_retention_openapi_contract()
    assert runner.summary_line(passing) == (
        "mo_log_retention_openapi_contract=pass operations=3/3 "
        "components=4 remaining=1 next=1138"
    )

    monkeypatch.setattr(
        runner,
        "run_mo_log_retention_openapi_contract",
        lambda: passing,
    )
    assert runner.main(["--summary"]) == 0
    assert "operations=3/3" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_mo_log_retention_openapi_contract",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
