from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import run_ae_runtime_policy_postgres_smoke as smoke
from run_migrations import MigrationError


DATABASE_URL = (
    "postgresql+psycopg://nex_ae_user:private@127.0.0.1:5432/nex_ae_test"
)


def _execution() -> dict:
    checks = {
        "actual_database_identity": True,
        "required_tables_present": True,
        "canonical_bindings_seeded": True,
        "seed_idempotent": True,
        "policy_api_resolved": True,
        "prompt_binding_safe": True,
        "chat_completed": True,
        "policy_snapshot_persisted": True,
        "generation_package_persisted": True,
        "render_event_persisted": True,
        "restart_chat_read": True,
        "idempotent_retry": True,
        "operational_events_policy_metadata": True,
        "policy_privacy_preserved": True,
        "event_privacy_preserved": True,
        "cleanup_complete": True,
    }
    return {
        "status": "PASS",
        "execution_state": "EXECUTED",
        "actual_postgres": True,
        "database": "nex_ae_test",
        "role": "nex_ae_user",
        "checks": checks,
        "row_counts": {
            "bindings": 4,
            "render_events": 1,
            "chat": 1,
            "events": 2,
        },
        "cleanup_counts": {
            "events": 2,
            "chat": 1,
            "render_events": 1,
            "remaining": 0,
        },
        "provider_mode": "deterministic-mock",
        "generation_call_count": 1,
        "retrieval_call_count": 1,
        "remote_provider_required": False,
        "next_slice": "1031",
    }


def _migration(*, complete: bool = True):
    return SimpleNamespace(
        planned=("0021_prompt_analytics_foundation", "1014_ae_workspace_activity_persistence"),
        applied=(),
        skipped=(
            "0021_prompt_analytics_foundation",
            "1014_ae_workspace_activity_persistence",
        )
        if complete
        else (),
    )


def test_runner_requires_explicit_test_database_opt_in() -> None:
    skipped = smoke.run_ae_runtime_policy_postgres_smoke({})
    missing = smoke.run_ae_runtime_policy_postgres_smoke({smoke.SMOKE_ENV: "1"})
    wrong = smoke.run_ae_runtime_policy_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.DATABASE_ENV: DATABASE_URL.replace("nex_ae_test", "nex_ae_dev"),
        }
    )

    assert skipped["status"] == "SKIPPED"
    assert skipped["actual_postgres"] is False
    assert missing["failure_code"] == "database_url_missing"
    assert wrong["failure_code"] == "target_not_allowed"
    assert smoke._target_url_allowed(DATABASE_URL) is True
    assert smoke._target_url_allowed("not-a-url") is False
    headers = smoke._headers(
        "tenant-a",
        "user-a",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        request_id="request-a",
    )
    assert headers["X-Request-ID"] == "request-a"
    assert headers["traceparent"].startswith(
        "00-4bf92f3577b34da6a3ce929d0e0e4736-"
    )


def test_runner_executes_migrations_and_postgres_probe(monkeypatch) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *_args, **_kwargs: _migration(),
    )
    monkeypatch.setattr(smoke, "_execute_postgres_smoke", lambda _url: _execution())

    result = smoke.run_ae_runtime_policy_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.DATABASE_ENV: DATABASE_URL}
    )

    assert result["status"] == "PASS"
    assert result["checks"]["migration_current"] is True
    assert result["migration"] == {
        "planned_count": 2,
        "applied_count": 0,
        "skipped_count": 2,
        "latest_version": "1014_ae_workspace_activity_persistence",
    }
    assert "private" not in result["redacted_database_url"]


def test_runner_fails_for_incomplete_migration_ledger(monkeypatch) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *_args, **_kwargs: _migration(complete=False),
    )
    monkeypatch.setattr(smoke, "_execute_postgres_smoke", lambda _url: _execution())

    result = smoke.run_ae_runtime_policy_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.DATABASE_ENV: DATABASE_URL}
    )

    assert result["status"] == "FAIL"
    assert result["checks"]["migration_current"] is False
    assert result["failure_code"] == "ae_runtime_policy_postgres_smoke_failed"


def test_runner_redacts_execution_failures(monkeypatch) -> None:
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            MigrationError(f"failed {DATABASE_URL}")
        ),
    )

    result = smoke.run_ae_runtime_policy_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.DATABASE_ENV: DATABASE_URL}
    )

    assert result["failure_code"] == "execution_failed"
    assert "private" not in result["detail"]
    assert "***" in result["detail"]


def test_deterministic_clients_preserve_policy_lineage() -> None:
    generation = smoke.DeterministicGenerationClient()
    generated = generation.create_generation(
        {
            "client_request_id": "interaction-a",
            "alias": "general-llm-default",
            "provider_capability": "generation",
            "retrieval_package_ref": {
                "retrieval_package_id": "retrieval-a",
                "package_hash": "b" * 64,
            },
            "selected_evidence_ids": ["evidence-a"],
        },
        request_id="request-a",
        trace_id="a" * 32,
    )
    retrieval = smoke.DeterministicRetrievalClient()
    retrieved = retrieval.create_retrieval_context(
        {"request_id": "retrieval-request-a", "purpose": "search"},
        request_id="request-a",
        trace_id="a" * 32,
    )

    assert generated["request_metadata"]["selected_evidence_count"] == 1
    assert generation.call_count == 1
    assert generation.payload is not None
    assert retrieved["retrieval_package_id"] == "retrieval-retrieval-request-a"
    assert retrieval.call_count == 1


def test_postgres_smoke_is_registered_in_full_quality_gate() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "scripts/quality/run_quality_gate.sh"
    ).read_text(encoding="utf-8")

    assert "run_ae_runtime_policy_postgres_smoke.py --summary" in source


def test_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = {**_execution(), "migration": {"planned_count": 24}}
    assert smoke.summary_line(passing) == (
        "ae_runtime_policy_postgres=pass execution=executed "
        "database=nex_ae_test checks=16/16 migrations=24 "
        "rows=4/1/1/2 cleanup=0 next=1031"
    )
    assert "execution=not-run" in smoke.summary_line({"status": "SKIPPED"})

    monkeypatch.setattr(smoke, "run_ae_runtime_policy_postgres_smoke", lambda: passing)
    assert smoke.main(["--summary"]) == 0
    assert "execution=executed" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        smoke,
        "run_ae_runtime_policy_postgres_smoke",
        lambda: {"status": "FAIL"},
    )
    assert smoke.main([]) == 1
