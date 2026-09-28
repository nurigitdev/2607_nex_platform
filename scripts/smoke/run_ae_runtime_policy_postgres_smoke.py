#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker


ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "nex-ae-api",
    ROOT / "services" / "_shared",
    ROOT / "scripts" / "db",
):
    sys.path.insert(0, str(path))

from nex_ae_api.chat import SqlAlchemyChatInteractionStore, register_chat_routes  # noqa: E402
from nex_ae_api.prompt_persistence import (  # noqa: E402
    PromptRepositoryError,
    SqlAlchemyAePromptRegistryStore,
)
from nex_ae_api.prompts import AE_PROMPT_SEEDS, seed_ae_prompt_registry  # noqa: E402
from nex_ae_api.runtime_policy_api import register_runtime_policy_routes  # noqa: E402
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    OperationalEventEmitter,
    SqlAlchemyOperationalEventStore,
    build_service_app,
    issue_mock_user_token,
    load_env_file,
    redact_database_url,
    sqlalchemy_database_url,
)
from run_migrations import MigrationError, run_service_migrations  # noqa: E402


SCHEMA_VERSION = "ae_runtime_policy_postgres_smoke.v1"
SMOKE_ENV = "NEX_AE_RUNTIME_POLICY_POSTGRES_SMOKE"
DATABASE_ENV = "NEX_AE_TEST_DATABASE_URL"
EXPECTED_DATABASE = "nex_ae_test"
EXPECTED_ROLE = "nex_ae_user"
REQUIRED_TABLES = frozenset(
    {
        "ae_prompt_templates",
        "ae_prompt_template_versions",
        "ae_prompt_bindings",
        "ae_prompt_render_events",
        "ae_chat_interactions",
        "service_operational_events",
    }
)


class DeterministicGenerationClient:
    def __init__(self) -> None:
        self.call_count = 0
        self.payload: dict[str, Any] | None = None

    def create_generation(self, payload, *, request_id, trace_id):
        self.call_count += 1
        self.payload = payload
        retrieval = payload["retrieval_package_ref"]
        return {
            "cx_generation_id": f"cx-generation-{payload['client_request_id']}",
            "status": "COMPLETED",
            "alias": payload["alias"],
            "provider_capability": payload["provider_capability"],
            "mo_generation_id": f"mo-generation-{payload['client_request_id']}",
            "request_metadata": {
                "grounding_required": True,
                "retrieval_package_id": retrieval["retrieval_package_id"],
                "retrieval_package_hash": retrieval["package_hash"],
                "selected_evidence_count": len(payload["selected_evidence_ids"]),
            },
            "response_metadata": {
                "finish_reason": "STOP",
                "output_preview": "Synthetic S103 policy answer.",
            },
            "usage": {"input_tokens": 4, "output_tokens": 5, "total_tokens": 9},
        }


class DeterministicRetrievalClient:
    def __init__(self) -> None:
        self.call_count = 0

    def create_retrieval_context(self, payload, *, request_id, trace_id):
        self.call_count += 1
        return {
            "retrieval_package_id": f"retrieval-{payload['request_id']}",
            "package_hash": "b" * 64,
            "status": "READY",
            "purpose": payload["purpose"],
            "evidence_items": [
                {
                    "evidence_id": "evidence-s103-postgres",
                    "citation_label": "[1]",
                    "text": "private synthetic PostgreSQL evidence",
                    "quality_flags": [],
                }
            ],
            "score_summary": {"best_score": 0.91, "confidence_bucket": "HIGH"},
            "warnings": [],
            "no_answer_reason": None,
        }


def run_ae_runtime_policy_postgres_smoke(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "slice": "1030",
            "requirement": "S103",
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
            "actual_postgres": False,
        }
    database_url = env.get(DATABASE_ENV, "")
    if not database_url:
        return _failure("database_url_missing", f"{DATABASE_ENV} is required.")
    if not _target_url_allowed(database_url):
        return _failure(
            "target_not_allowed",
            f"database target must be {EXPECTED_ROLE}@.../{EXPECTED_DATABASE}",
        )

    try:
        migration = run_service_migrations(
            "nex-ae-api",
            database_url=database_url,
            profile="test",
        )
        evidence = _execute_postgres_smoke(database_url)
        migration_current = bool(migration.planned) and len(migration.planned) == (
            len(migration.applied) + len(migration.skipped)
        )
        evidence.update(
            {
                "smoke_schema_version": SCHEMA_VERSION,
                "slice": "1030",
                "requirement": "S103",
                "profile": "test",
                "database_env": DATABASE_ENV,
                "redacted_database_url": redact_database_url(database_url),
                "migration": {
                    "planned_count": len(migration.planned),
                    "applied_count": len(migration.applied),
                    "skipped_count": len(migration.skipped),
                    "latest_version": migration.planned[-1]
                    if migration.planned
                    else None,
                },
            }
        )
        evidence["checks"] = {
            "migration_current": migration_current,
            **evidence["checks"],
        }
        evidence["status"] = (
            "PASS" if all(evidence["checks"].values()) else "FAIL"
        )
        if evidence["status"] == "FAIL":
            evidence["failure_code"] = "ae_runtime_policy_postgres_smoke_failed"
        return evidence
    except (
        MigrationError,
        PromptRepositoryError,
        SQLAlchemyError,
        OSError,
        ValueError,
        RuntimeError,
    ) as exc:
        return _failure(
            "execution_failed",
            _redact_detail(str(exc), database_url=database_url),
        )


def _execute_postgres_smoke(database_url: str) -> dict[str, Any]:
    engine = create_engine(
        sqlalchemy_database_url(database_url),
        future=True,
        pool_pre_ping=True,
    )
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    token = uuid4().hex
    interaction_id = str(uuid4())
    tenant_id = f"tenant-s103-{token[:12]}"
    owner_user_id = f"user-s103-{token[:12]}"
    trace_id = uuid4().hex
    request_id = f"request-s103-{token}"
    private_message = f"Summarize this private S103 document {token}."
    prompt_store = SqlAlchemyAePromptRegistryStore(factory)
    chat_store = SqlAlchemyChatInteractionStore(factory)
    event_store = SqlAlchemyOperationalEventStore(factory)
    generation = DeterministicGenerationClient()
    retrieval = DeterministicRetrievalClient()
    render_event_id: str | None = None
    row_counts: dict[str, int] = {}
    cleanup_counts: dict[str, int] = {}
    database = ""
    role = ""

    try:
        first_seed = seed_ae_prompt_registry(prompt_store)
        second_seed = seed_ae_prompt_registry(prompt_store)
        app = build_service_app(SERVICE_SPECS["nex-ae-api"])
        register_runtime_policy_routes(app, store=prompt_store)
        register_chat_routes(
            app,
            store=chat_store,
            cx_client=generation,
            retrieval_client=retrieval,
            prompt_store=prompt_store,
            event_emitter=OperationalEventEmitter(
                service_id="nex-ae-api",
                store=event_store,
            ),
        )
        client = TestClient(app)
        headers = _headers(
            tenant_id,
            owner_user_id,
            trace_id=trace_id,
            request_id=request_id,
        )
        policy_response = client.post(
            "/api/v1/runtime-policies/resolve",
            json={"user_message": private_message},
            headers=headers,
        )
        chat_payload = {
            "interaction_id": interaction_id,
            "user_message": private_message,
        }
        chat_response = client.post(
            "/api/v1/chat/interactions",
            json=chat_payload,
            headers=headers,
        )
        repeated = client.post(
            "/api/v1/chat/interactions",
            json=chat_payload,
            headers=headers,
        )
        chat_body = chat_response.json()
        policy_summary = (chat_body.get("generation") or {}).get("policy") or {}
        package = policy_summary.get("generation_policy_package") or {}
        render_event_id = (policy_summary.get("prompt_render_event_ref") or {}).get(
            "prompt_render_event_id"
        )

        restarted_prompts = SqlAlchemyAePromptRegistryStore(factory)
        restarted_chats = SqlAlchemyChatInteractionStore(factory)
        loaded_event = (
            restarted_prompts.get_render_event(render_event_id)
            if render_event_id
            else None
        )
        loaded_chat = restarted_chats.get_for_owner(
            interaction_id,
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
        )
        events = event_store.list_events(
            service_id="nex-ae-api",
            trace_id=trace_id,
            limit=10,
        )

        with engine.connect() as connection:
            database, role = connection.execute(
                text("SELECT current_database(), current_user")
            ).one()
            table_names = {
                row[0]
                for row in connection.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public' AND table_name = ANY(:names)"
                    ),
                    {"names": sorted(REQUIRED_TABLES)},
                )
            }
            row_counts = {
                "bindings": int(
                    connection.execute(
                        text(
                            "SELECT count(*) FROM ae_prompt_bindings "
                            "WHERE binding_key = ANY(:keys)"
                        ),
                        {"keys": [seed.binding_key for seed in AE_PROMPT_SEEDS]},
                    ).scalar_one()
                ),
                "render_events": int(
                    connection.execute(
                        text(
                            "SELECT count(*) FROM ae_prompt_render_events "
                            "WHERE prompt_render_event_id = :event_id"
                        ),
                        {"event_id": render_event_id},
                    ).scalar_one()
                ),
                "chat": int(
                    connection.execute(
                        text(
                            "SELECT count(*) FROM ae_chat_interactions "
                            "WHERE chat_interaction_id = :interaction_id"
                        ),
                        {"interaction_id": interaction_id},
                    ).scalar_one()
                ),
                "events": len(events),
            }

        serialized_policy = json.dumps(policy_summary, sort_keys=True)
        serialized_api_policy = json.dumps(policy_response.json(), sort_keys=True)
        serialized_events = json.dumps(events, sort_keys=True)
        expected_keys = sorted(seed.binding_key for seed in AE_PROMPT_SEEDS)
        checks = {
            "actual_database_identity": database == EXPECTED_DATABASE
            and role == EXPECTED_ROLE,
            "required_tables_present": table_names == REQUIRED_TABLES,
            "canonical_bindings_seeded": row_counts["bindings"] == 4
            and [item["binding_key"] for item in prompt_store.list_bindings()]
            == expected_keys,
            "seed_idempotent": [item["prompt_binding_id"] for item in first_seed]
            == [item["prompt_binding_id"] for item in second_seed],
            "policy_api_resolved": policy_response.status_code == 200
            and policy_response.json().get("runtime_policy_schema_version")
            == "ae_runtime_policy.v1",
            "prompt_binding_safe": policy_response.json()
            .get("prompt_binding", {})
            .get("content_included")
            is False
            and private_message not in serialized_api_policy,
            "chat_completed": chat_response.status_code == 200
            and chat_body.get("status") == "COMPLETED",
            "policy_snapshot_persisted": policy_summary
            .get("runtime_policy_snapshot", {})
            .get("policy_snapshot_hash")
            == package.get("policy_snapshot_hash"),
            "generation_package_persisted": len(
                package.get("client_package_hash", "")
            )
            == 64
            and generation.payload is not None
            and generation.payload.get("client_package_hash")
            == package.get("client_package_hash"),
            "render_event_persisted": row_counts["render_events"] == 1
            and loaded_event is not None
            and loaded_event.get("user_prompt_hash")
            == chat_body.get("user_message_hash"),
            "restart_chat_read": loaded_chat is not None
            and loaded_chat.get("generation", {}).get("policy") == policy_summary,
            "idempotent_retry": repeated.status_code == 200
            and repeated.json() == chat_body
            and generation.call_count == 1
            and retrieval.call_count == 1,
            "operational_events_policy_metadata": len(events) == 2
            and all(event["details"]["policy_available"] for event in events)
            and all(
                event["details"]["execution_mode"] == "DOCUMENT_SUMMARY"
                for event in events
            ),
            "policy_privacy_preserved": private_message not in serialized_policy
            and "private synthetic PostgreSQL evidence" not in serialized_policy
            and "api_key" not in serialized_policy,
            "event_privacy_preserved": private_message not in serialized_events
            and owner_user_id not in serialized_events,
        }
    finally:
        try:
            with engine.begin() as connection:
                cleanup_counts["events"] = int(
                    connection.execute(
                        text(
                            "DELETE FROM service_operational_events "
                            "WHERE trace_id = :trace_id"
                        ),
                        {"trace_id": trace_id},
                    ).rowcount
                    or 0
                )
                cleanup_counts["chat"] = int(
                    connection.execute(
                        text(
                            "DELETE FROM ae_chat_interactions "
                            "WHERE chat_interaction_id = :interaction_id"
                        ),
                        {"interaction_id": interaction_id},
                    ).rowcount
                    or 0
                )
                cleanup_counts["render_events"] = int(
                    connection.execute(
                        text(
                            "DELETE FROM ae_prompt_render_events "
                            "WHERE prompt_render_event_id = :event_id"
                        ),
                        {"event_id": render_event_id},
                    ).rowcount
                    or 0
                )
            with engine.connect() as connection:
                cleanup_counts["remaining"] = sum(
                    int(value)
                    for value in connection.execute(
                        text(
                            "SELECT "
                            "(SELECT count(*) FROM ae_chat_interactions "
                            " WHERE chat_interaction_id = :interaction_id), "
                            "(SELECT count(*) FROM ae_prompt_render_events "
                            " WHERE prompt_render_event_id = :event_id), "
                            "(SELECT count(*) FROM service_operational_events "
                            " WHERE trace_id = :trace_id)"
                        ),
                        {
                            "interaction_id": interaction_id,
                            "event_id": render_event_id,
                            "trace_id": trace_id,
                        },
                    ).one()
                )
        finally:
            engine.dispose()

    checks["cleanup_complete"] = cleanup_counts.get("remaining") == 0
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "execution_state": "EXECUTED",
        "actual_postgres": True,
        "database": database,
        "role": role,
        "checks": checks,
        "row_counts": row_counts,
        "cleanup_counts": cleanup_counts,
        "provider_mode": "deterministic-mock",
        "generation_call_count": generation.call_count,
        "retrieval_call_count": retrieval.call_count,
        "remote_provider_required": False,
        "next_slice": "1031",
    }


def _headers(
    tenant_id: str,
    user_id: str,
    *,
    trace_id: str,
    request_id: str,
) -> dict[str, str]:
    issued = issue_mock_user_token(tenant_id=tenant_id, user_id=user_id)
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": request_id,
        "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
    }


def _target_url_allowed(database_url: str) -> bool:
    parsed = urlsplit(database_url)
    return (
        unquote(parsed.username or "") == EXPECTED_ROLE
        and unquote(parsed.path.lstrip("/")) == EXPECTED_DATABASE
    )


def _redact_detail(detail: str, *, database_url: str) -> str:
    redacted = detail.replace(database_url, redact_database_url(database_url))
    password = urlsplit(database_url).password
    return redacted.replace(unquote(password), "***") if password else redacted


def _failure(code: str, detail: str) -> dict[str, Any]:
    return {
        "smoke_schema_version": SCHEMA_VERSION,
        "slice": "1030",
        "requirement": "S103",
        "status": "FAIL",
        "failure_code": code,
        "detail": detail,
        "actual_postgres": False,
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    checks = evidence.get("checks") or {}
    migration = evidence.get("migration") or {}
    rows = evidence.get("row_counts") or {}
    return (
        "ae_runtime_policy_postgres="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"execution={str(evidence.get('execution_state') or 'not-run').lower()} "
        f"database={evidence.get('database', 'not-run')} "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"migrations={migration.get('planned_count', 0)} "
        f"rows={rows.get('bindings', 0)}/{rows.get('render_events', 0)}/"
        f"{rows.get('chat', 0)}/{rows.get('events', 0)} "
        f"cleanup={str((evidence.get('cleanup_counts') or {}).get('remaining', 'not-run'))} "
        f"next={evidence.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_ae_runtime_policy_postgres_smoke()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
