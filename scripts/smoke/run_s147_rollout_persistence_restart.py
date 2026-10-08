#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))

from nex_mo.model_rollout import ModelRevisionIdentity
from nex_mo.model_rollout_api import register_model_rollout_routes
from nex_mo.model_rollout_repository import SqlAlchemyModelRolloutRepository
from nex_mo.model_rollout_service import ModelRolloutService
from nex_mo.model_rollout_state import begin_validation, register_rollout
from nex_mo.provider_auth import MO_OPERATIONS_READ_SCOPE
from nex_runtime import issue_mock_service_token

DIGESTS = ["sha256:" + char * 64 for char in "abcd"]

SQLITE_SCHEMA = """
CREATE TABLE mo_model_rollouts (
    rollout_id TEXT PRIMARY KEY,
    capability TEXT NOT NULL,
    alias TEXT NOT NULL,
    catalog_id TEXT NOT NULL,
    model_revision TEXT NOT NULL,
    deployment_id TEXT NOT NULL,
    artifact_digest TEXT NOT NULL,
    runtime_engine TEXT NOT NULL,
    precision TEXT NOT NULL,
    request_shape_hash TEXT NOT NULL,
    identity_fingerprint TEXT NOT NULL,
    rollout_state TEXT NOT NULL,
    state_revision INTEGER NOT NULL,
    lkg_binding_id TEXT NOT NULL,
    lkg_identity_fingerprint TEXT NOT NULL,
    readiness_digest TEXT,
    calibration_profile_id TEXT,
    calibration_profile_hash TEXT,
    reservation_id TEXT,
    canary_policy_hash TEXT,
    canary_status TEXT,
    activated_binding_id TEXT,
    failure_code TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE mo_rollout_events (
    event_id TEXT PRIMARY KEY,
    rollout_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    from_state TEXT,
    to_state TEXT NOT NULL,
    state_revision INTEGER NOT NULL,
    evidence_digest TEXT,
    failure_code TEXT,
    occurred_at TEXT NOT NULL,
    UNIQUE (rollout_id, state_revision)
);
"""


def run_rollout_persistence_restart() -> dict[str, Any]:
    with TemporaryDirectory(prefix="nex-s147-") as directory:
        path = Path(directory) / "rollout.db"
        first_engine = create_engine(f"sqlite+pysqlite:///{path}")
        with first_engine.begin() as connection:
            for statement in SQLITE_SCHEMA.split(";"):
                if statement.strip():
                    connection.execute(text(statement))
        first = _service(first_engine, ("register", "validate"))
        registered = _record()
        first.register(registered)
        validating = begin_validation(
            registered,
            changed_at="2026-10-08T00:01:00Z",
        )
        first.persist_transition(
            validating,
            expected_state_revision=1,
            event_type="rollout.validation_started",
            evidence_digest=DIGESTS[3],
        )
        first_engine.dispose()

        restarted_engine = create_engine(f"sqlite+pysqlite:///{path}")
        restarted = _service(restarted_engine, ("unused",))
        recovered = restarted.get(registered.rollout_id)
        events = restarted.list_events(registered.rollout_id)
        app = FastAPI()
        register_model_rollout_routes(app, service=restarted)
        client = TestClient(app)
        unauthorized = client.get("/api/v1/model-rollouts")
        token = issue_mock_service_token(
            service_id="nex-ag",
            audience="nex-mo",
            scopes=("service:call", MO_OPERATIONS_READ_SCOPE),
        )
        headers = {"Authorization": f"Bearer {token.access_token}"}
        collection = client.get("/api/v1/model-rollouts", headers=headers)
        history = client.get(
            f"/api/v1/model-rollouts/{registered.rollout_id}/events",
            headers=headers,
        )
        migration = (
            ROOT
            / "database"
            / "nex-mo"
            / "migrations"
            / "1470_mo_model_rollout_persistence.sql"
        ).read_text(encoding="utf-8")
        with restarted_engine.begin() as connection:
            deleted_events = connection.execute(
                text("DELETE FROM mo_rollout_events WHERE rollout_id = :rollout_id"),
                {"rollout_id": registered.rollout_id},
            ).rowcount
            deleted_rollouts = connection.execute(
                text("DELETE FROM mo_model_rollouts WHERE rollout_id = :rollout_id"),
                {"rollout_id": registered.rollout_id},
            ).rowcount
            residue = connection.execute(
                text("SELECT COUNT(*) FROM mo_model_rollouts")
            ).scalar_one()
        restarted_engine.dispose()

    serialized = json.dumps(collection.json(), sort_keys=True)
    checks = {
        "migration_defines_concise_tables": "mo_model_rollouts" in migration
        and "mo_rollout_events" in migration,
        "migration_has_operations_index": "ix_mo_rollout_operations" in migration,
        "migration_has_identity_index": "ix_mo_rollout_identity" in migration,
        "migration_has_event_history_index": "ix_mo_rollout_event_history" in migration,
        "restart_recovered_latest_state": recovered.state == "VALIDATING"
        and recovered.state_revision == 2,
        "restart_recovered_exact_identity": recovered.identity.fingerprint
        == registered.identity.fingerprint,
        "append_only_events_recovered": [item.state_revision for item in events]
        == [1, 2],
        "unauthorized_request_denied": unauthorized.status_code == 401,
        "authorized_collection_available": collection.status_code == 200
        and len(collection.json()["data"]) == 1,
        "authorized_history_available": history.status_code == 200
        and len(history.json()["data"]) == 2,
        "operations_projection_payload_free": "model_name" not in serialized
        and "endpoint" not in serialized,
        "cleanup_deleted_exact_rows": deleted_events == 2 and deleted_rollouts == 1,
        "cleanup_zero_residue": residue == 0,
    }
    passed = all(checks.values())
    return {
        "schema_version": "s147_rollout_persistence_restart.v1",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "summary": {
            "recovered_revision": recovered.state_revision,
            "event_count": len(events),
            "api_request_count": 3,
            "cleanup_residue": int(residue),
            "check_count": len(checks),
        },
        "next_slice": "1471" if passed else "blocked",
    }


def _service(engine, identifiers) -> ModelRolloutService:
    values = iter(identifiers)
    factory: sessionmaker[Session] = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    return ModelRolloutService(
        SqlAlchemyModelRolloutRepository(factory),
        id_factory=lambda: next(values),
    )


def _record():
    identity = ModelRevisionIdentity(
        provider_capability="generation",
        alias="generation-default",
        catalog_id="catalog:generation:2",
        model_revision="revision:generation:2",
        deployment_id="deployment:generation:2",
        artifact_digest=DIGESTS[0],
        runtime_engine="openai-compatible",
        precision="bfloat16",
        request_shape_hash=DIGESTS[1],
    )
    stable = ModelRevisionIdentity(
        provider_capability="generation",
        alias="generation-default",
        catalog_id="catalog:generation:1",
        model_revision="revision:generation:1",
        deployment_id="deployment:generation:1",
        artifact_digest=DIGESTS[2],
        runtime_engine="openai-compatible",
        precision="bfloat16",
        request_shape_hash=DIGESTS[1],
    )
    return register_rollout(
        identity,
        rollout_id="rollout:generation:2",
        last_known_good_binding_id="binding:generation:1",
        last_known_good_identity_fingerprint=stable.fingerprint,
        created_at="2026-10-08T00:00:00Z",
    )


def summary_line(result: Mapping[str, Any]) -> str:
    summary = dict(result.get("summary") or {})
    return (
        f"rollout_persistence_restart={str(result.get('status') or 'FAIL').lower()} "
        f"revision={summary.get('recovered_revision', 0)} "
        f"events={summary.get('event_count', 0)} "
        f"api={summary.get('api_request_count', 0)} "
        f"cleanup={summary.get('cleanup_residue', -1)} "
        f"checks={summary.get('check_count', 0)}/13 "
        f"next={result.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_rollout_persistence_restart()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
