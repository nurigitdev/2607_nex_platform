from __future__ import annotations

from pathlib import Path

import pytest

import run_s86_ag_recovery_notification_live_delivery_closure as closure


def _postgres_pass() -> dict[str, object]:
    return {
        "status": "PASS",
        "execution": {"provider_mode": "live_http", "http_status_code": 202},
        "loopback": {"request_count": 1},
        "cleanup": {"remaining_rows": 0},
    }


def test_closure_passes_with_default_protected_postgres_skip() -> None:
    result = closure.run_s86_ag_recovery_notification_live_delivery_closure(
        environ={}
    )

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["loopback_smoke"]["status"] == "PASS"
    assert result["postgres_smoke"]["status"] == "SKIPPED"
    assert result["privacy_runbook"]["status"] == "PASS"
    assert result["new_tables"] == []
    assert result["real_external_endpoint_activated"] is False


def test_closure_requires_postgres_pass_when_opted_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(closure, "run_postgres", lambda _env: _postgres_pass())

    result = closure.run_s86_ag_recovery_notification_live_delivery_closure(
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

    result = closure.run_s86_ag_recovery_notification_live_delivery_closure(
        environ={closure.POSTGRES_SMOKE_ENV: "1"}
    )

    assert result["status"] == "FAIL"
    assert result["checks"]["postgres_protection_respected"] is False
    assert result["checks"]["postgres_actual_pass_when_opted_in"] is False


def test_safe_evidence_reports_exceptions_without_detail() -> None:
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


def test_file_token_and_postgres_doc_helpers_cover_missing_root(
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
            "loopback_smoke": {"status": "PASS"},
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
        "loopback_smoke": {"status": "PASS"},
        "postgres_smoke": {"status": "SKIPPED"},
        "privacy_runbook": {"status": "PASS"},
    }
    monkeypatch.setattr(
        closure,
        "run_s86_ag_recovery_notification_live_delivery_closure",
        lambda: passing,
    )

    assert closure.main(["--summary"]) == 0
    assert "closure=pass" in capsys.readouterr().out
    assert closure.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        closure,
        "run_s86_ag_recovery_notification_live_delivery_closure",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert closure.main([]) == 1
