#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import bindparam, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import ArgumentError

ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "_shared",
    ROOT / "services" / "nex-mo",
    ROOT / "scripts" / "db",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

from nex_mo.catalog_lifecycle_repository import (
    SqlAlchemyCatalogLifecycleRepository,
)
from nex_mo.catalog_lifecycle_service import (
    CatalogLifecycleService,
    RegisterCatalogEntry,
)
from nex_mo.model_rollout import ModelRevisionIdentity
from nex_mo.model_rollout_api import register_model_rollout_routes
from nex_mo.model_rollout_repository import (
    SqlAlchemyModelRolloutRepository,
)
from nex_mo.model_rollout_service import ModelRolloutService
from nex_mo.model_rollout_state import (
    begin_validation,
    register_rollout,
)
from nex_mo.provider_catalog import build_model_profile_catalog
from nex_mo.provider_auth import MO_OPERATIONS_READ_SCOPE
from nex_runtime import (
    build_engine,
    build_session_factory,
    issue_mock_service_token,
    redact_database_url,
)
from run_migrations import run_service_migrations
from run_mo_operations_live_acceptance import (
    GENERATION_REASONING_MODE,
    run_mo_operations_live_acceptance,
)

SCHEMA_VERSION = "s147_model_rollout_live_acceptance.v1"
ACTIVATION_ENV = "NEX_MO_MODEL_ROLLOUT_LIVE_ACCEPTANCE"
PROFILE_ENV = "NEX_MO_MODEL_ROLLOUT_LIVE_ACCEPTANCE_PROFILE"
DATABASE_ENV = "NEX_MO_TEST_DATABASE_URL"
DEFAULT_PROFILE = "test"
EXPECTED_DATABASE = "nex_mo_test"
EXPECTED_ROLE = "nex_mo_user"
MIGRATION_VERSION = "1470_mo_model_rollout_persistence"
CAPABILITIES = ("embedding", "reranking", "generation")
PROTECTED_ENV_KEYS = (
    DATABASE_ENV,
    "NEX_MO_REMOTE_EMBEDDING_URL",
    "NEX_MO_REMOTE_EMBEDDING_API_KEY",
    "NEX_MO_REMOTE_RERANKER_URL",
    "NEX_MO_REMOTE_RERANKER_API_KEY",
    "NEX_MO_VLLM_BASE_URL",
    "NEX_MO_VLLM_MODELS_URL",
    "NEX_MO_VLLM_CHAT_COMPLETIONS_URL",
    "NEX_MO_VLLM_API_KEY",
    "NEX_MO_DGX_SSH_TARGET",
)

LiveRunner = Callable[[Mapping[str, str]], Mapping[str, Any]]
PersistenceExercise = Callable[[str, Mapping[str, str]], Mapping[str, Any]]


def run_s147_model_rollout_live_acceptance(
    environ: Mapping[str, str] | None = None,
    *,
    live_runner: LiveRunner | None = None,
    persistence_exercise: PersistenceExercise | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(ACTIVATION_ENV) != "1":
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "slice": "1471",
            "requirement": "S147",
            "status": "SKIPPED",
            "skip_reason": f"{ACTIVATION_ENV} is not enabled.",
        }
    profile = env.get(PROFILE_ENV, DEFAULT_PROFILE)
    if profile != DEFAULT_PROFILE:
        return _failure("profile_not_allowed")
    database_url = str(env.get(DATABASE_ENV) or "").strip()
    nested_env = {
        **env,
        "NEX_MO_OPERATIONS_LIVE_ACCEPTANCE": "1",
        "NEX_MO_OPERATIONS_LIVE_ACCEPTANCE_PROFILE": "test",
    }
    try:
        live = dict(
            (live_runner or _run_live_operations)(nested_env)
        )
        if live.get("status") != "PASS":
            failure = _failure(
                "live_provider_acceptance_failed",
                {"nested_failure_code": live.get("failure_code")},
            )
            assert_evidence_redacted(failure, env)
            return failure
        persistence = dict(
            (persistence_exercise or _exercise_rollout_persistence)(
                database_url,
                nested_env,
            )
        )
        cleanup = _mapping(persistence.get("cleanup"))
        live_summary = _mapping(live.get("summary"))
        checks = {
            "actual_test_database_identity": persistence.get("database_identity")
            == {"database_name": EXPECTED_DATABASE, "database_user": EXPECTED_ROLE},
            "rollout_migration_current": persistence.get("migration_current") is True,
            "all_live_provider_requests_succeeded": live_summary.get(
                "provider_success_count"
            )
            == 3,
            "all_live_models_matched": live_summary.get("model_match_count") == 3,
            "all_live_runtime_models_healthy": live_summary.get(
                "runtime_ready_capability_count"
            )
            == 3,
            "all_capability_rehearsals_persisted": persistence.get("rollout_count")
            == 3,
            "atomic_transition_events_persisted": persistence.get("event_count")
            == 6,
            "restart_readback_complete": persistence.get("restart_read_count") == 3,
            "protected_api_readback_complete": persistence.get("api_status") == 200
            and persistence.get("api_item_count") == 3,
            "rollouts_stop_before_unproven_canary": persistence.get(
                "validating_count"
            )
            == 3
            and persistence.get("promotion_mutation_count") == 0,
            "live_aliases_unchanged": persistence.get("aliases_unchanged") is True,
            "targeted_cleanup_complete": cleanup.get("residue") == 0,
        }
        passed = all(checks.values())
        evidence = {
            "evidence_schema_version": SCHEMA_VERSION,
            "slice": "1471",
            "requirement": "S147",
            "status": "PASS" if passed else "FAIL",
            "failure_code": None if passed else "model_rollout_live_acceptance_failed",
            "profile": profile,
            "redacted_database_url": redact_database_url(database_url),
            "database_identity": persistence.get("database_identity"),
            "checks": checks,
            "summary": {
                "passed_check_count": sum(checks.values()),
                "check_count": len(checks),
                "live_provider_count": _count(live_summary.get("provider_success_count")),
                "live_model_match_count": _count(live_summary.get("model_match_count")),
                "runtime_ready_count": _count(
                    live_summary.get("runtime_ready_capability_count")
                ),
                "rollout_count": _count(persistence.get("rollout_count")),
                "event_count": _count(persistence.get("event_count")),
                "restart_read_count": _count(
                    persistence.get("restart_read_count")
                ),
                "api_status": _count(persistence.get("api_status")),
                "api_item_count": _count(persistence.get("api_item_count")),
                "generation_reasoning_mode": GENERATION_REASONING_MODE,
            },
            "candidate_admission": {
                "status": "CALIBRATION_REQUIRED",
                "promotion_eligible": False,
                "reason": "protected smoke has no candidate artifact provenance or ACTIVE calibration",
                "live_mutation_performed": False,
            },
            "cleanup": cleanup,
            "redaction": {
                "status": "PASS",
                "excluded": [
                    "provider_endpoints",
                    "provider_api_keys",
                    "database_password",
                    "authorization_token",
                    "ssh_target",
                    "raw_provider_payloads",
                    "process_commands",
                ],
            },
            "next_slice": "1472" if passed else "blocked",
        }
        assert_evidence_redacted(evidence, env)
        return evidence
    except Exception as exc:  # noqa: BLE001 - protected runner must fail closed
        error_code = getattr(exc, "error_code", None)
        diagnostics = {"exception_type": exc.__class__.__name__}
        if isinstance(error_code, str) and error_code:
            diagnostics["error_code"] = error_code
        failure = _failure(
            "model_rollout_live_acceptance_execution_failed",
            diagnostics,
        )
        assert_evidence_redacted(failure, env)
        return failure


def _run_live_operations(env: Mapping[str, str]) -> Mapping[str, Any]:
    return run_mo_operations_live_acceptance(env)


def _exercise_rollout_persistence(
    database_url: str,
    environment: Mapping[str, str],
) -> dict[str, Any]:  # pragma: no cover - protected PostgreSQL/DGX evidence
    migration = run_service_migrations(
        "nex-mo",
        database_url=database_url,
        profile="test",
    )
    suffix = uuid4().hex
    rollout_ids: list[str] = []
    catalog_ids: list[str] = []
    initial_binding_ids: list[str] = []
    engine: Engine | None = None
    cleanup = {
        "deleted_event_rows": 0,
        "deleted_rollout_rows": 0,
        "deleted_catalog_rows": 0,
        "residue": -1,
    }
    cleanup_done = False
    try:
        engine = build_engine(database_url)
        session_factory = build_session_factory(engine)
        catalog = CatalogLifecycleService(
            SqlAlchemyCatalogLifecycleRepository(session_factory)
        )
        catalog.ensure_bootstrap()
        selected_profiles = {
            profile.provider_capability: profile
            for profile in build_model_profile_catalog(dict(environment))
            if profile.selected
        }
        rollout_service = ModelRolloutService(
            SqlAlchemyModelRolloutRepository(session_factory)
        )
        for capability in CAPABILITIES:
            binding = next(
                item
                for item in catalog.list_alias_bindings(
                    capability=capability,
                    state="ACTIVE",
                )
            )
            lkg = catalog.get_catalog_entry(binding.catalog_id)
            initial_binding_ids.append(binding.binding_id)
            profile = selected_profiles[capability]
            entry = catalog.register_catalog_entry(
                RegisterCatalogEntry(
                    provider_capability=capability,
                    model_name=profile.model_name,
                    model_revision=f"s147-rehearsal-{suffix[:12]}",
                    deployment_id=f"s147-{capability}-{suffix[:12]}",
                    runtime_profile="s147-protected-rehearsal",
                    precision=profile.precision,
                    provider_type="protected-rehearsal",
                    supports_response_formats=_response_formats(capability),
                    max_input_tokens=8192,
                    max_output_tokens=1024 if capability == "generation" else 0,
                    embedding_dimensions=8 if capability == "embedding" else None,
                )
            )
            catalog_ids.append(entry.catalog_id)
            identity = ModelRevisionIdentity(
                provider_capability=capability,
                alias=binding.alias,
                catalog_id=entry.catalog_id,
                model_revision=entry.model_revision,
                deployment_id=entry.deployment_id,
                artifact_digest=_digest(
                    {
                        "scope": "s147-protected-rehearsal",
                        "catalog_id": entry.catalog_id,
                        "model_revision": entry.model_revision,
                    }
                ),
                runtime_engine=profile.runtime_engine,
                precision=profile.precision,
                request_shape_hash=_digest(
                    {
                        "capability": capability,
                        "formats": entry.supports_response_formats,
                    }
                ),
            )
            rollout_id = f"rollout:s147:{capability}:{suffix[:12]}"
            rollout_ids.append(rollout_id)
            created_at = _utc_now()
            record = register_rollout(
                identity,
                rollout_id=rollout_id,
                last_known_good_binding_id=binding.binding_id,
                last_known_good_identity_fingerprint=_digest(
                    {
                        "catalog_id": lkg.catalog_id,
                        "model_revision": lkg.model_revision,
                        "deployment_id": lkg.deployment_id,
                    }
                ),
                created_at=created_at,
            )
            rollout_service.register(record)
            durable_record = rollout_service.get(rollout_id)
            validating = begin_validation(
                durable_record,
                changed_at=_utc_after(durable_record.updated_at),
            )
            rollout_service.persist_transition(
                validating,
                expected_state_revision=durable_record.state_revision,
                event_type="rollout.validation_started",
            )

        engine.dispose()
        engine = build_engine(database_url)
        restarted_factory = build_session_factory(engine)
        restarted = ModelRolloutService(
            SqlAlchemyModelRolloutRepository(restarted_factory)
        )
        readback = [restarted.get(rollout_id) for rollout_id in rollout_ids]
        events = [
            event
            for rollout_id in rollout_ids
            for event in restarted.list_events(rollout_id)
        ]
        app = FastAPI()
        register_model_rollout_routes(app, service=restarted)
        token = issue_mock_service_token(
            service_id="nex-ag",
            audience="nex-mo",
            scopes=("service:call", MO_OPERATIONS_READ_SCOPE),
        )
        response = TestClient(app).get(
            "/api/v1/model-rollouts?state=VALIDATING&limit=10",
            headers={"Authorization": f"Bearer {token.access_token}"},
        )
        payload = response.json() if response.status_code == 200 else {}
        items = payload.get("data", []) if isinstance(payload, Mapping) else []

        restarted_catalog = CatalogLifecycleService(
            SqlAlchemyCatalogLifecycleRepository(restarted_factory)
        )
        current_binding_ids = [
            next(
                item
                for item in restarted_catalog.list_alias_bindings(
                    capability=capability,
                    state="ACTIVE",
                )
            ).binding_id
            for capability in CAPABILITIES
        ]
        with engine.connect() as connection:
            database_name, database_user = connection.execute(
                text("SELECT current_database(), current_user")
            ).one()
            migration_current = (
                connection.execute(
                    text(
                        "SELECT count(*) FROM schema_migrations WHERE version = :version"
                    ),
                    {"version": MIGRATION_VERSION},
                ).scalar_one()
                == 1
            )
        cleanup = _cleanup(engine, rollout_ids, catalog_ids)
        cleanup_done = True
        return {
            "database_identity": {
                "database_name": database_name,
                "database_user": database_user,
            },
            "migration": {
                "planned_count": len(migration.planned),
                "applied_count": len(migration.applied),
                "skipped_count": len(migration.skipped),
            },
            "migration_current": migration_current,
            "rollout_count": len(readback),
            "event_count": len(events),
            "validating_count": sum(item.state == "VALIDATING" for item in readback),
            "restart_read_count": len(readback),
            "api_status": response.status_code,
            "api_item_count": len(items),
            "promotion_mutation_count": sum(
                item.state in {"CANARY", "ACTIVE", "ROLLED_BACK"} for item in readback
            ),
            "aliases_unchanged": current_binding_ids == initial_binding_ids,
            "cleanup": cleanup,
        }
    finally:
        if engine is not None and not cleanup_done:
            _cleanup(engine, rollout_ids, catalog_ids)
        if engine is not None:
            engine.dispose()


def _cleanup(
    engine: Engine,
    rollout_ids: list[str],
    catalog_ids: list[str],
) -> dict[str, int]:  # pragma: no cover - protected PostgreSQL/DGX evidence
    event_delete = text(
        "DELETE FROM mo_rollout_events WHERE rollout_id IN :rollout_ids"
    ).bindparams(bindparam("rollout_ids", expanding=True))
    rollout_delete = text(
        "DELETE FROM mo_model_rollouts WHERE rollout_id IN :rollout_ids"
    ).bindparams(bindparam("rollout_ids", expanding=True))
    catalog_delete = text(
        "DELETE FROM mo_model_catalog WHERE catalog_id IN :catalog_ids"
    ).bindparams(bindparam("catalog_ids", expanding=True))
    with engine.begin() as connection:
        deleted_events = (
            connection.execute(event_delete, {"rollout_ids": rollout_ids})
            if rollout_ids
            else None
        )
        deleted_rollouts = (
            connection.execute(rollout_delete, {"rollout_ids": rollout_ids})
            if rollout_ids
            else None
        )
        deleted_catalogs = (
            connection.execute(catalog_delete, {"catalog_ids": catalog_ids})
            if catalog_ids
            else None
        )
        residue = 0
        if rollout_ids:
            residue += int(
                connection.execute(
                    text(
                        "SELECT count(*) FROM mo_model_rollouts "
                        "WHERE rollout_id IN :rollout_ids"
                    ).bindparams(bindparam("rollout_ids", expanding=True)),
                    {"rollout_ids": rollout_ids},
                ).scalar_one()
            )
        if catalog_ids:
            residue += int(
                connection.execute(
                    text(
                        "SELECT count(*) FROM mo_model_catalog "
                        "WHERE catalog_id IN :catalog_ids"
                    ).bindparams(bindparam("catalog_ids", expanding=True)),
                    {"catalog_ids": catalog_ids},
                ).scalar_one()
            )
    return {
        "deleted_event_rows": int(deleted_events.rowcount or 0)
        if deleted_events is not None
        else 0,
        "deleted_rollout_rows": int(deleted_rollouts.rowcount or 0)
        if deleted_rollouts is not None
        else 0,
        "deleted_catalog_rows": int(deleted_catalogs.rowcount or 0)
        if deleted_catalogs is not None
        else 0,
        "residue": residue,
    }


def _response_formats(capability: str) -> tuple[str, ...]:
    return {
        "embedding": ("vector",),
        "reranking": ("score",),
        "generation": ("text", "json_object"),
    }[capability]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _utc_after(value: str) -> str:
    instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return instant.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _digest(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _count(value: Any) -> int:
    return value if isinstance(value, int) and value >= 0 else 0


def _failure(
    failure_code: str,
    diagnostics: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1471",
        "requirement": "S147",
        "status": "FAIL",
        "failure_code": failure_code,
        "issues": [failure_code],
        "next_slice": "blocked",
    }
    if diagnostics:
        evidence["diagnostics"] = dict(diagnostics)
    return evidence


def assert_evidence_redacted(
    evidence: Mapping[str, Any],
    environ: Mapping[str, str],
) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
    protected = [str(environ.get(key) or "") for key in PROTECTED_ENV_KEYS]
    database_url = str(environ.get(DATABASE_ENV) or "")
    try:
        protected.append(str(make_url(database_url).password or ""))
    except (ArgumentError, TypeError, ValueError):
        protected.append("")
    if any(value and len(value) >= 6 and value in serialized for value in protected):
        raise ValueError("S147 live acceptance evidence contains protected value")


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") == "SKIPPED":
        return f"s147_model_rollout_live_acceptance=skipped reason={ACTIVATION_ENV}"
    summary = _mapping(evidence.get("summary"))
    cleanup = _mapping(evidence.get("cleanup"))
    return (
        "s147_model_rollout_live_acceptance="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"checks={summary.get('passed_check_count', 0)}/"
        f"{summary.get('check_count', 0)} "
        f"providers={summary.get('live_provider_count', 0)}/3 "
        f"runtime={summary.get('runtime_ready_count', 0)}/3 "
        f"rollouts={summary.get('rollout_count', 0)}/3 "
        f"events={summary.get('event_count', 0)}/6 "
        f"cleanup={cleanup.get('residue', 'not-run')} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_s147_model_rollout_live_acceptance()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
