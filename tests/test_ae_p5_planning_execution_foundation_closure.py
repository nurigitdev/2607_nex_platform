from __future__ import annotations

import json
from pathlib import Path

import run_p5_planning_execution_foundation_closure as closure


def _restart(_env) -> dict:
    return {
        "status": "PASS",
        "actual_postgres": True,
        "database": "nex_ae_test",
        "role": "nex_ae_user",
        "checks": {
            "runtime_job_deduplicated": True,
            "immutable_result_replay": True,
            "restart_does_not_reexecute": True,
            "write_identity_null": True,
        },
        "row_counts": {"step_result": 2},
        "cleanup_counts": {"remaining": 0},
    }


def _journey(_env) -> dict:
    return {
        "status": "PASS",
        "actual_postgres": True,
        "database": "nex_ae_test",
        "role": "nex_ae_user",
        "migration": {
            "planned_count": 38,
            "latest_version": "2106_ae_step_result",
        },
        "checks": {
            "s_e_uuid_lineage": True,
            "atomic_idempotent_restart": True,
            "chat_invoked_once": True,
            "terminal_results_persisted": True,
            "required_step_results_verified": True,
            "agent_result_immutable_replay": True,
            "workspace_delivery_pending": True,
            "execution_waits_for_ack": True,
            "zero_nsl_write_identity": True,
        },
        "row_counts": {
            "step_result": 2,
            "agent_result": 1,
            "result_delivery": 1,
        },
        "cleanup_counts": {"remaining": 0},
    }


def test_repository_closure_static_and_injected_postgres_evidence_pass() -> None:
    result = closure.run_p5_planning_execution_foundation_closure(
        {closure.SMOKE_ENV: "1"},
        restart_runner=_restart,
        journey_runner=_journey,
    )

    assert result["status"] == "PASS", result
    assert all(result["checks"].values())
    assert result["failed_checks"] == []
    assert result["excluded_scope_hits"] == {
        "nsl_wc": [],
        "direct_provider_imports": [],
    }
    assert result["restart"]["cleanup_remaining"] == 0
    assert result["journey"]["row_counts"]["agent_result"] == 1
    assert result["requirement"] == "P5 Agent Planning and Execution Foundation"
    assert "P6 NSL v0.2 READ integration" in result["deferred"]


def test_closure_is_protected_and_fails_closed_for_evidence() -> None:
    skipped = closure.run_p5_planning_execution_foundation_closure({})
    assert skipped["status"] == "SKIPPED"
    assert closure.SMOKE_ENV in skipped["skip_reason"]

    def failed_restart(_env):
        result = _restart(_env)
        result["checks"]["runtime_job_deduplicated"] = False
        return result

    def failed_journey(_env):
        result = _journey(_env)
        result["checks"]["execution_waits_for_ack"] = False
        result["cleanup_counts"]["remaining"] = 1
        return result

    failed = closure.run_p5_planning_execution_foundation_closure(
        {closure.SMOKE_ENV: "1"},
        restart_runner=failed_restart,
        journey_runner=failed_journey,
    )

    assert failed["status"] == "FAIL"
    assert "actual_restart_postgresql_smoke_passed" in failed["failed_checks"]
    assert "restart_and_dedup_guards_passed" in failed["failed_checks"]
    assert "actual_complete_journey_postgresql_smoke_passed" in failed["failed_checks"]
    assert "publication_ack_barrier_preserved" in failed["failed_checks"]
    assert "complete_journey_zero_residue" in failed["failed_checks"]


def test_static_evidence_detects_missing_and_forbidden_scope(tmp_path: Path) -> None:
    for path in closure.P5_MIGRATIONS + closure.P5_RUNTIME_SOURCES:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("", encoding="utf-8")
    source = tmp_path / closure.P5_RUNTIME_SOURCES[0]
    source.write_text("import httpx\nfrom nex_nsl import Client\n", encoding="utf-8")

    evidence = closure._static_evidence(tmp_path)

    assert evidence["checks"]["p5_migration_chain_present"] is True
    assert evidence["checks"]["p5_runtime_modules_present"] is True
    assert evidence["checks"]["p5_canonical_docs_present"] is False
    assert evidence["checks"]["p5_as_built_records_complete"] is False
    assert evidence["checks"]["nsl_wc_runtime_coupling_absent"] is False
    assert evidence["checks"]["direct_provider_client_absent"] is False
    assert evidence["checks"]["step_result_write_identity_fail_closed"] is False


def test_required_checks_projection_summary_and_cli(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    assert closure._required_checks_passed({"one": True}, ("one",)) is True
    assert closure._required_checks_passed({}, ("missing",)) is False
    assert closure._cleanup_remaining({}) is None

    passing = closure.run_p5_planning_execution_foundation_closure(
        {closure.SMOKE_ENV: "1"},
        restart_runner=_restart,
        journey_runner=_journey,
    )
    assert "closure=pass" in closure.summary_line(passing)
    assert "results=2/1" in closure.summary_line(passing)
    assert closure.summary_line({"status": "SKIPPED"}).startswith(
        "p5_planning_execution_closure=skipped"
    )

    monkeypatch.setattr(
        closure,
        "run_p5_planning_execution_foundation_closure",
        lambda: passing,
    )
    output = tmp_path / "p5-s9.json"
    assert closure.main(["--summary", "--output", str(output)]) == 0
    assert "closure=pass" in capsys.readouterr().out
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "PASS"

    monkeypatch.setattr(
        closure,
        "run_p5_planning_execution_foundation_closure",
        lambda: {"status": "FAIL", "checks": {}},
    )
    assert closure.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
