from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from pathlib import Path

import pytest

import run_mo_mvp_acceptance_postgres_live_smoke as smoke


NOW = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)


def _env() -> dict[str, str]:
    return {
        smoke.ACTIVATION_ENV: "1",
        "NEX_MO_OPERATIONS_LIVE_ACCEPTANCE_PROFILE": "test",
        "NEX_MO_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_mo_user:private-db-secret@127.0.0.1/"
            "nex_mo_test"
        ),
        "NEX_MO_REMOTE_EMBEDDING_API_KEY": "private-provider-key",
        "NEX_MO_REMOTE_RERANKER_API_KEY": "private-provider-key",
        "NEX_MO_VLLM_API_KEY": "private-provider-key",
    }


def _source() -> dict[str, object]:
    return {
        "status": "PASS",
        "failure_code": None,
        "checks": {"one": True, "two": True},
        "database_identity": {
            "database_name": "nex_mo_test",
            "database_user": "nex_mo_user",
        },
        "summary": {
            "provider_success_count": 3,
            "model_match_count": 3,
            "ready_capability_count": 3,
            "runtime_ready_capability_count": 3,
        },
        "cleanup": {"residue": 0},
    }


def _run(source: dict[str, object] | None = None, *, root: Path = smoke.ROOT):
    return smoke.run_mo_mvp_acceptance_postgres_live_smoke(
        _env(),
        operations_runner=lambda _env: source or _source(),
        clock=lambda: NOW,
        root=root,
    )


def test_smoke_is_explicitly_protected() -> None:
    evidence = smoke.run_mo_mvp_acceptance_postgres_live_smoke({})

    assert evidence["status"] == "SKIPPED"
    assert smoke.ACTIVATION_ENV in evidence["skip_reason"]


def test_smoke_accepts_normalized_postgres_live_and_handoff_evidence() -> None:
    evidence = _run()
    serialized = json.dumps(evidence)

    assert evidence["status"] == "PASS"
    assert all(evidence["checks"].values())
    assert evidence["summary"] == {
        "passed_check_count": 8,
        "check_count": 8,
        "provider_success_count": 3,
        "model_match_count": 3,
        "ready_capability_count": 3,
        "runtime_ready_capability_count": 3,
        "cleanup_residue": 0,
    }
    assert set(evidence["acceptance_gate_evidence"]) == {
        "postgres_smoke",
        "live_provider_acceptance",
        "oa_transition_handoff",
    }
    assert all(
        item["status"] == "PASS"
        for item in evidence["acceptance_gate_evidence"].values()
    )
    assert evidence["next_slice"] == "1200"
    assert "private-provider-key" not in serialized
    assert "private-db-secret" not in serialized


def test_smoke_fails_closed_for_each_evidence_family() -> None:
    database = _source()
    database["database_identity"] = {
        "database_name": "nex_mo_dev",
        "database_user": "nex_mo_user",
    }
    live = _source()
    live["summary"] = {
        **live["summary"],
        "runtime_ready_capability_count": 2,
    }
    source_checks = _source()
    source_checks["checks"] = {"one": True, "two": False}

    database_result = _run(database)
    live_result = _run(live)
    source_result = _run(source_checks)

    assert database_result["acceptance_gate_evidence"]["postgres_smoke"][
        "status"
    ] == "FAIL"
    assert live_result["acceptance_gate_evidence"]["live_provider_acceptance"][
        "status"
    ] == "FAIL"
    assert source_result["checks"]["source_acceptance_passed"] is False
    assert source_result["status"] == "FAIL"


def test_smoke_redacts_source_failures_and_exceptions(tmp_path: Path) -> None:
    failed = smoke.run_mo_mvp_acceptance_postgres_live_smoke(
        _env(),
        operations_runner=lambda _env: {
            "status": "FAIL",
            "failure_code": "provider_failed",
        },
        clock=lambda: NOW,
    )
    crashed = smoke.run_mo_mvp_acceptance_postgres_live_smoke(
        _env(),
        operations_runner=lambda _env: (_ for _ in ()).throw(
            RuntimeError("private-provider-key")
        ),
        clock=lambda: NOW,
    )
    missing_asset = _run(root=tmp_path)

    assert failed["source_failure_code"] == "provider_failed"
    assert crashed["source_failure_code"] == "RuntimeError"
    assert missing_asset["source_failure_code"] == "MoMvpOaTransitionHandoffError"
    assert "private-provider-key" not in json.dumps(crashed)


def test_smoke_rejects_naive_clock() -> None:
    evidence = smoke.run_mo_mvp_acceptance_postgres_live_smoke(
        _env(),
        operations_runner=lambda _env: _source(),
        clock=lambda: datetime(2026, 10, 1, 10, 0),
    )

    assert evidence["failure_code"] == "clock_timezone_required"


def test_helpers_summary_and_main_paths(monkeypatch, capsys) -> None:
    skipped = smoke.run_mo_mvp_acceptance_postgres_live_smoke({})
    passing = _run()
    assert smoke.summary_line(skipped).startswith(
        "mo_mvp_acceptance_postgres_live_smoke=skipped"
    )
    assert smoke.summary_line(passing) == (
        "mo_mvp_acceptance_postgres_live_smoke=pass checks=8/8 "
        "providers=3/3 models=3/3 runtime=3/3 cleanup=0 next=1200"
    )
    assert smoke._mapping(None) == {}
    assert smoke._nonnegative_int(1) == 1
    assert smoke._nonnegative_int(-1) == 0
    assert smoke._nonnegative_int(True) is True

    monkeypatch.setattr(
        smoke,
        "run_mo_mvp_acceptance_postgres_live_smoke",
        lambda: passing,
    )
    assert smoke.main(["--summary"]) == 0
    assert "checks=8/8" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_mo_mvp_acceptance_postgres_live_smoke",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert smoke.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out


@pytest.mark.skipif(
    os.getenv(smoke.ACTIVATION_ENV) != "1",
    reason=f"set {smoke.ACTIVATION_ENV}=1 for protected PostgreSQL/DGX smoke",
)
def test_protected_smoke_uses_actual_nex_mo_test_and_dgx() -> None:
    evidence = smoke.run_mo_mvp_acceptance_postgres_live_smoke()

    assert evidence["status"] == "PASS"
    assert all(evidence["checks"].values())
    assert evidence["database_identity"] == smoke.EXPECTED_DATABASE_IDENTITY
