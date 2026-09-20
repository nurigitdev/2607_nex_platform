from __future__ import annotations

from pathlib import Path

import pytest

import run_s88_ag_resilience_performance_closure as closure


def _postgres_pass() -> dict[str, object]:
    return {
        "status": "PASS",
        "observation": {
            "database": "nex_ag_test",
            "backend": "postgresql",
            "indexes_present": {name: True for name in closure.NEW_INDEXES},
        },
        "load": {"request_count": 25, "concurrency": 4, "p95_ms": 50.0},
        "cleanup": {"remaining_rows": 0},
    }


def test_closure_passes_with_default_protected_postgres_skip() -> None:
    result = closure.run_s88_ag_resilience_performance_closure(environ={})

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["boundary_audit"]["status"] == "PASS"
    assert result["runtime_evidence"]["operations_status"] == "READY"
    assert result["contract_validation"]["status"] == "PASS"
    assert result["postgres_smoke"]["status"] == "SKIPPED"
    assert result["privacy_runbook"]["status"] == "PASS"
    assert result["source_tables"] == [
        "service_operational_events",
        "ag_ev_exports",
    ]
    assert result["new_tables"] == []
    assert result["new_indexes"] == list(closure.NEW_INDEXES)
    assert result["deferred_requirements"] == [
        "S89 retention archive and physical purge",
        "S90 AG MVP acceptance and CX transition",
    ]


def test_closure_requires_postgres_pass_when_opted_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(closure, "run_postgres", lambda _env: _postgres_pass())

    result = closure.run_s88_ag_resilience_performance_closure(
        environ={closure.POSTGRES_SMOKE_ENV: "1"}
    )

    assert result["status"] == "PASS"
    assert result["postgres_smoke_opted_in"] is True
    assert result["postgres_smoke"]["status"] == "PASS"


def test_closure_fails_when_opted_in_postgres_does_not_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        closure,
        "run_postgres",
        lambda _env: {"status": "FAIL", "failure_code": "database_failed"},
    )

    result = closure.run_s88_ag_resilience_performance_closure(
        environ={closure.POSTGRES_SMOKE_ENV: "1"}
    )

    assert result["status"] == "FAIL"
    assert result["checks"]["postgres_protection_respected"] is False
    assert result["checks"]["postgres_actual_pass_when_opted_in"] is False


def test_runtime_evidence_closes_all_in_memory_surfaces() -> None:
    result = closure._runtime_evidence()

    assert result == {
        "status": "PASS",
        "policy_status": "VALIDATED",
        "pagination_status": "STABLE",
        "admission_status": "BOUNDED",
        "source_status": "HEALTHY",
        "operations_status": "READY",
        "raw_values_exposed": False,
    }


def test_pool_helper_reports_ready_capacity() -> None:
    pool = closure._Pool(5)

    assert pool.checkedout() == 0
    assert pool.checkedin() == 5
    assert pool.overflow() == -5


def test_safe_evidence_reports_exception_type_without_private_detail() -> None:
    passed = closure._safe_evidence(lambda: {"status": "PASS"}, "unused")
    failed = closure._safe_evidence(
        lambda: (_ for _ in ()).throw(RuntimeError("private failure")),
        "runtime_failed",
    )

    assert passed == {"status": "PASS"}
    assert failed == {
        "status": "FAIL",
        "failure_code": "runtime_failed",
        "error_type": "RuntimeError",
    }
    assert "private failure" not in str(failed)


def test_contract_evidence_handles_validation_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    valid = closure._contract_evidence(closure.ROOT)
    monkeypatch.setattr(
        closure,
        "validate_contract_tree",
        lambda _root: (_ for _ in ()).throw(RuntimeError("private contract")),
    )
    failed = closure._contract_evidence(closure.ROOT)

    assert valid["status"] == "PASS"
    assert valid["failure_count"] == 0
    assert failed == {
        "status": "FAIL",
        "failure_code": "contract_validation_failed",
        "error_type": "RuntimeError",
    }


def test_file_token_and_postgres_helpers_cover_missing_root(
    tmp_path: Path,
) -> None:
    token_path = tmp_path / closure.TOKEN_CHECKS[0][1]
    token_path.parent.mkdir(parents=True)
    token_path.write_text(closure.TOKEN_CHECKS[0][2], encoding="utf-8")

    files = closure._required_file_results(tmp_path)
    tokens = closure._token_results(tmp_path)
    postgres = closure._postgres_doc_evidence(tmp_path)

    assert not all(item["present"] for item in files)
    assert tokens[0]["present"] is True
    assert tokens[1]["present"] is False
    assert not any(postgres.values())
    assert closure._read_text(tmp_path / "missing") == ""


def test_postgres_documentation_evidence_is_complete() -> None:
    result = closure._postgres_doc_evidence(closure.ROOT)

    assert all(result.values())


def test_summary_line_and_mapping_helpers() -> None:
    passed = closure.summary_line(
        {
            "status": "PASS",
            "slice_range": closure.SLICE_RANGE,
            "contract_validation": {"status": "PASS"},
            "postgres_smoke": {"status": "PASS"},
            "privacy_runbook": {"status": "PASS"},
        }
    )
    failed = closure.summary_line(
        {
            "status": "FAIL",
            "summary": {"missing_file_count": 1, "missing_token_count": 2},
        }
    )

    assert "closure=pass" in passed
    assert "contracts=PASS" in passed
    assert "postgres=PASS" in passed
    assert "closure=fail" in failed
    assert "missing_files=1" in failed
    assert closure._mapping(None) == {}


def test_main_prints_summary_json_and_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    passing = {
        "status": "PASS",
        "slice_range": closure.SLICE_RANGE,
        "contract_validation": {"status": "PASS"},
        "postgres_smoke": {"status": "SKIPPED"},
        "privacy_runbook": {"status": "PASS"},
    }
    monkeypatch.setattr(
        closure,
        "run_s88_ag_resilience_performance_closure",
        lambda: passing,
    )

    assert closure.main(["--summary"]) == 0
    assert "closure=pass" in capsys.readouterr().out
    assert closure.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        closure,
        "run_s88_ag_resilience_performance_closure",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert closure.main([]) == 1
