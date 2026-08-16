#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
DB_SCRIPT_PATH = ROOT / "scripts" / "db"
AG_PATH = ROOT / "services" / "nex-ag"
SMOKE_PATH = ROOT / "scripts" / "smoke"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(DB_SCRIPT_PATH))
sys.path.insert(0, str(AG_PATH))
sys.path.insert(0, str(SMOKE_PATH))

from nex_ag.operations import (  # noqa: E402
    AgOperationsSourceRuntime,
    build_operations_source_registry,
    register_unified_operation_routes,
)
from nex_ag.processing_operations import (  # noqa: E402
    InMemoryCxProcessingRunOperationsStore,
)
from nex_ag.retrieval_operations import (  # noqa: E402
    AG_RETRIEVAL_THRESHOLD_DECISION_PROJECTION_SCHEMA_VERSION,
    SqlAlchemyRetrievalPackageOperationsStore,
    register_retrieval_package_operation_routes,
)
from nex_runtime import (  # noqa: E402
    InMemoryJobQueue,
    InMemoryOperationalEventStore,
    InMemoryServiceLogStore,
    SERVICE_SPECS,
    build_engine,
    build_service_app,
    build_session_factory,
    database_pool_settings,
    issue_mock_service_token,
    load_env_file,
    redact_database_url,
)
from nex_runtime.retrieval_policies import (  # noqa: E402
    CURRENT_POLICY_ID,
    WEIGHTED_RRF_POLICY_ID,
)
from run_ag_retrieval_package_postgres_smoke import (  # noqa: E402
    _delete_smoke_rows as _delete_retrieval_smoke_rows,
    _json_dumps,
    _json_sql_expression,
    _redaction_safe,
    _seed_retrieval_rows,
    _sha256_json,
    _smoke_refs as _retrieval_package_smoke_refs,
)
from run_migrations import (  # noqa: E402
    MigrationError,
    run_service_migrations,
    service_database_env,
    service_database_url,
)


SMOKE_ENV = "NEX_AG_RETRIEVAL_THRESHOLD_DECISION_POSTGRES_SMOKE"
SMOKE_PROFILE_ENV = "NEX_AG_RETRIEVAL_THRESHOLD_DECISION_POSTGRES_SMOKE_PROFILE"
DEFAULT_PROFILE = "test"
SERVICE_ID = "nex-cx"
SCHEMA_VERSION = "ag_retrieval_threshold_decision_postgres_smoke.v1"
DASHBOARD_SCHEMA_VERSION = "ag_operations_dashboard_snapshot_projection.v1"
ISSUE_CANDIDATE_SCHEMA_VERSION = "ag_operations_issue_candidate_projection.v1"
CURRENT_SAMPLE_COUNT = 20
WEIGHTED_SAMPLE_COUNT = 1
TOTAL_SAMPLE_COUNT = CURRENT_SAMPLE_COUNT + WEIGHTED_SAMPLE_COUNT


def run_ag_retrieval_threshold_decision_postgres_smoke(
    environ: dict[str, str] | None = None,
) -> dict[str, object]:
    env = environ if environ is not None else os.environ
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }

    profile = env.get(SMOKE_PROFILE_ENV, DEFAULT_PROFILE)
    if profile != "test":
        return _failure(
            "profile_not_allowed",
            f"{SMOKE_PROFILE_ENV} must be test for AG PostgreSQL smoke execution.",
            profile=profile,
        )

    try:
        database_env = service_database_env(SERVICE_ID, profile=profile)
        database_url = service_database_url(SERVICE_ID, profile=profile, environ=env)
        migration_result = run_service_migrations(
            SERVICE_ID,
            database_url=database_url,
            profile=profile,
        )
        execution = _execute_ag_retrieval_threshold_decision_postgres_smoke(
            database_url=database_url,
            database_env=database_env,
            environ=env,
        )
        raw_values = execution.pop("raw_values", [])
        if "failure_code" in execution:
            return _failure(
                str(execution["failure_code"]),
                str(execution["detail"]),
                profile=profile,
                database_env=database_env,
                checks=execution.get("checks"),
            )
        evidence = {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "PASS",
            "service_id": SERVICE_ID,
            "profile": profile,
            "database_env": database_env,
            "redacted_database_url": redact_database_url(database_url),
            "migrations": _migration_summary(migration_result),
            **execution,
        }
        if not _redaction_safe(evidence, raw_values):
            return _failure(
                "evidence_redaction_failed",
                "AG retrieval threshold decision PostgreSQL smoke evidence leaked private data.",
                profile=profile,
                database_env=database_env,
            )
        return evidence
    except (MigrationError, ValueError) as exc:
        return _failure("configuration_invalid", str(exc), profile=profile)
    except Exception as exc:
        return _failure("execution_failed", exc.__class__.__name__, profile=profile)


def _execute_ag_retrieval_threshold_decision_postgres_smoke(
    *,
    database_url: str,
    database_env: str,
    environ: dict[str, str] | None = None,
) -> dict[str, object]:
    env = environ if environ is not None else os.environ
    pool_settings = database_pool_settings(SERVICE_ID, workload="api", environ=env)
    engine = build_engine(database_url, pool_settings=pool_settings)
    refs = _smoke_refs()
    seeded_refs: list[dict[str, str]] = []
    try:
        seeded_refs = _seed_threshold_sample_rows(engine, refs=refs)
        db_counts = _select_seeded_sample_counts(engine, refs=refs)
        store = SqlAlchemyRetrievalPackageOperationsStore(
            build_session_factory(engine),
            database_env=database_env,
            redacted_database_url=redact_database_url(database_url),
        )
        client = _build_ag_client(store=store)
        projections = _read_projections(client, refs=refs)
        raw_values = _raw_values(seed_refs=seeded_refs)
        checks = _checks(
            projections=projections,
            db_counts=db_counts,
            database_env=database_env,
            raw_values=raw_values,
        )
        if not all(checks.values()):
            return _execution_failure(
                "checks_failed",
                "AG retrieval threshold decision PostgreSQL smoke checks failed.",
                checks=checks,
                raw_values=raw_values,
            )
        threshold_response = projections["threshold_decisions"]
        dashboard_response = projections["dashboard"]
        issue_response = projections["issue_candidates"]
        return {
            "trace_id": refs["trace_id"],
            "request_id_prefix": refs["request_id_prefix"],
            "projection_versions": {
                name: projection.get("projection_schema_version")
                for name, projection in projections.items()
            },
            "http_statuses": {
                name: projection["_http_status"]
                for name, projection in projections.items()
            },
            "counts": {
                "seeded_package_rows": db_counts["package_count"],
                "seeded_policy_count": db_counts["policy_count"],
                "threshold_decisions": threshold_response["summary"][
                    "total_decisions"
                ],
                "observed_sample_count": threshold_response["summary"][
                    "observed_sample_count"
                ],
                "ready_for_review": threshold_response["summary"][
                    "ready_for_review"
                ],
                "insufficient_samples": threshold_response["summary"][
                    "insufficient_samples"
                ],
                "dashboard_observed_sample_count": dashboard_response[
                    "retrieval_threshold_decisions"
                ]["summary"]["observed_sample_count"],
                "issue_candidates": issue_response["summary"]["total"],
            },
            "checks": checks,
            "raw_values": raw_values,
        }
    finally:
        for sample_refs in seeded_refs:
            _delete_retrieval_smoke_rows(engine, refs=sample_refs)


def _build_ag_client(
    *,
    store: SqlAlchemyRetrievalPackageOperationsStore,
) -> TestClient:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    stores = {SERVICE_ID: store}
    registry = build_operations_source_registry(
        job_queues={SERVICE_ID: InMemoryJobQueue()},
        event_stores={SERVICE_ID: InMemoryOperationalEventStore()},
        service_log_stores={SERVICE_ID: InMemoryServiceLogStore()},
    )
    runtime = AgOperationsSourceRuntime(
        mode="postgres",
        profile="test",
        selected_service_ids=(SERVICE_ID,),
        registry=registry,
    )
    register_retrieval_package_operation_routes(app, stores=stores, runtime=runtime)
    register_unified_operation_routes(
        app,
        registry=registry,
        runtime=runtime,
        retrieval_package_stores=stores,
        cx_processing_run_stores={
            SERVICE_ID: InMemoryCxProcessingRunOperationsStore()
        },
    )
    return TestClient(app)


def _read_projections(
    client: TestClient,
    *,
    refs: dict[str, str],
) -> dict[str, dict[str, Any]]:
    return {
        "threshold_decisions": _get_json(
            client,
            "/admin/v1/operations/retrieval-threshold-decisions",
            params={"service_id": SERVICE_ID, "limit": "50"},
            trace_id=refs["trace_id"],
            request_id=refs["request_id_prefix"],
        ),
        "dashboard": _get_json(
            client,
            "/admin/v1/operations/dashboard",
            params={"service_id": SERVICE_ID, "recent_limit": "1"},
            trace_id=refs["trace_id"],
            request_id=refs["request_id_prefix"],
        ),
        "issue_candidates": _get_json(
            client,
            "/admin/v1/operations/issue-candidates",
            params={"service_id": SERVICE_ID, "recent_limit": "1"},
            trace_id=refs["trace_id"],
            request_id=refs["request_id_prefix"],
        ),
    }


def _get_json(
    client: TestClient,
    path: str,
    *,
    params: dict[str, str],
    trace_id: str,
    request_id: str,
) -> dict[str, Any]:
    response = client.get(
        path,
        params=params,
        headers=_ag_headers(trace_id=trace_id, request_id=request_id),
    )
    body = response.json()
    body["_http_status"] = response.status_code
    return body


def _ag_headers(*, trace_id: str, request_id: str) -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-oa", audience="nex-ag")
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": request_id,
        "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
    }


def _seed_threshold_sample_rows(
    engine: object,
    *,
    refs: dict[str, str],
) -> list[dict[str, str]]:
    seeded_refs: list[dict[str, str]] = []
    for index, sample in enumerate(_threshold_sample_specs()):
        sample_refs = _retrieval_package_smoke_refs()
        sample_refs["trace_id"] = refs["trace_id"]
        sample_refs["request_id"] = f"{refs['request_id_prefix']}-{index:02d}"
        _seed_retrieval_rows(engine, refs=sample_refs)
        _update_threshold_sample_row(
            engine,
            refs=sample_refs,
            sample=sample,
            created_at=f"2026-08-09T00:{index:02d}:00Z",
        )
        seeded_refs.append(sample_refs)
    return seeded_refs


def _update_threshold_sample_row(
    engine: object,
    *,
    refs: dict[str, str],
    sample: dict[str, object],
    created_at: str,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                f"""
                UPDATE cx_retrieval_packages
                SET
                    status = :status,
                    retrieval_policy_id = :retrieval_policy_id,
                    retrieval_policy_version = :retrieval_policy_version,
                    retrieval_policy_hash = :retrieval_policy_hash,
                    ranker_mix = :ranker_mix,
                    score_summary = {_json_sql_expression(connection, "score_summary")},
                    evidence_count = :evidence_count,
                    no_answer_reason = :no_answer_reason,
                    created_at = :created_at,
                    updated_at = :created_at
                WHERE retrieval_package_id = :retrieval_package_id
                """
            ),
            {
                "retrieval_package_id": refs["retrieval_package_id"],
                "status": sample["status"],
                "retrieval_policy_id": sample["retrieval_policy_id"],
                "retrieval_policy_version": "0001",
                "retrieval_policy_hash": _sha256_json(
                    {
                        "policy_id": sample["retrieval_policy_id"],
                        "slice": "0307",
                    }
                ),
                "ranker_mix": sample["ranker_mix"],
                "score_summary": _json_dumps(
                    {
                        "best_score": sample["best_score"],
                        "score_spread": 0.0,
                        "confidence_bucket": sample["confidence_bucket"],
                        "quality_policy_id": sample["retrieval_policy_id"],
                        "low_confidence_threshold": sample[
                            "low_confidence_threshold"
                        ],
                    }
                ),
                "evidence_count": sample["evidence_count"],
                "no_answer_reason": sample["no_answer_reason"],
                "created_at": created_at,
            },
        )


def _select_seeded_sample_counts(
    engine: object,
    *,
    refs: dict[str, str],
) -> dict[str, int]:
    with engine.begin() as connection:
        row = connection.execute(
            text(
                """
                SELECT
                    count(*) AS package_count,
                    count(DISTINCT retrieval_policy_id) AS policy_count,
                    sum(
                        CASE
                            WHEN retrieval_policy_id = :current_policy_id
                            THEN 1 ELSE 0
                        END
                    ) AS current_policy_count,
                    sum(
                        CASE
                            WHEN retrieval_policy_id = :weighted_policy_id
                            THEN 1 ELSE 0
                        END
                    ) AS weighted_policy_count
                FROM cx_retrieval_packages
                WHERE request_id LIKE :request_id_pattern
                """
            ),
            {
                "current_policy_id": CURRENT_POLICY_ID,
                "weighted_policy_id": WEIGHTED_RRF_POLICY_ID,
                "request_id_pattern": f"{refs['request_id_prefix']}-%",
            },
        ).mappings().one()
    return {
        "package_count": int(row["package_count"] or 0),
        "policy_count": int(row["policy_count"] or 0),
        "current_policy_count": int(row["current_policy_count"] or 0),
        "weighted_policy_count": int(row["weighted_policy_count"] or 0),
    }


def _checks(
    *,
    projections: dict[str, dict[str, Any]],
    db_counts: dict[str, int],
    database_env: str,
    raw_values: list[str],
) -> dict[str, bool]:
    threshold_response = projections["threshold_decisions"]
    dashboard_response = projections["dashboard"]
    issue_response = projections["issue_candidates"]
    decisions = _decisions_by_policy(threshold_response)
    dashboard_decisions = _decisions_by_policy(
        dashboard_response.get("retrieval_threshold_decisions", {})
    )
    current_decision = decisions.get(CURRENT_POLICY_ID, {})
    weighted_decision = decisions.get(WEIGHTED_RRF_POLICY_ID, {})
    dashboard_source = (
        dashboard_response.get("retrieval_threshold_decisions", {})
        .get("source_statuses", {})
        .get(SERVICE_ID, {})
    )
    issue_rules = {
        candidate.get("rule_id")
        for candidate in issue_response.get("issue_candidates", [])
        if isinstance(candidate, dict)
    }
    serialized_responses = json.dumps(projections, ensure_ascii=False)
    return {
        "postgres_seed_select_confirms_samples": db_counts == {
            "package_count": TOTAL_SAMPLE_COUNT,
            "policy_count": 2,
            "current_policy_count": CURRENT_SAMPLE_COUNT,
            "weighted_policy_count": WEIGHTED_SAMPLE_COUNT,
        },
        "threshold_projection_reads_postgres": (
            threshold_response["_http_status"] == 200
            and threshold_response.get("projection_schema_version")
            == AG_RETRIEVAL_THRESHOLD_DECISION_PROJECTION_SCHEMA_VERSION
            and threshold_response.get("projection_status") == "READY"
            and threshold_response.get("source_statuses", {})
            .get(SERVICE_ID, {})
            .get("source_kind")
            == "postgres-read"
            and threshold_response.get("source_statuses", {})
            .get(SERVICE_ID, {})
            .get("database_env")
            == database_env
        ),
        "threshold_decision_counts_match_seed": (
            threshold_response.get("summary", {}).get("total_decisions") == 2
            and threshold_response.get("summary", {}).get("observed_sample_count")
            == TOTAL_SAMPLE_COUNT
            and threshold_response.get("summary", {}).get(
                "threshold_override_count"
            )
            == WEIGHTED_SAMPLE_COUNT
            and threshold_response.get("summary", {}).get("ready_for_review") == 1
            and threshold_response.get("summary", {}).get(
                "insufficient_samples"
            )
            == 1
        ),
        "current_policy_ready_for_review": (
            current_decision.get("sample_readiness") == "READY_FOR_REVIEW"
            and current_decision.get("recommended_operator_action")
            == "prepare_threshold_policy_review"
            and current_decision.get("observed_sample_count")
            == CURRENT_SAMPLE_COUNT
            and current_decision.get("observed_default_pass_count")
            == CURRENT_SAMPLE_COUNT
        ),
        "weighted_policy_remains_insufficient": (
            weighted_decision.get("sample_readiness") == "INSUFFICIENT_SAMPLES"
            and weighted_decision.get("recommended_operator_action")
            == "collect_live_score_samples"
            and weighted_decision.get("observed_sample_count")
            == WEIGHTED_SAMPLE_COUNT
            and weighted_decision.get("observed_threshold_override_count")
            == WEIGHTED_SAMPLE_COUNT
        ),
        "dashboard_reuses_postgres_threshold_section": (
            dashboard_response["_http_status"] == 200
            and dashboard_response.get("projection_schema_version")
            == DASHBOARD_SCHEMA_VERSION
            and dashboard_response.get("retrieval_threshold_decisions", {})
            .get("summary", {})
            .get("observed_sample_count")
            == TOTAL_SAMPLE_COUNT
            and dashboard_source.get("status") == "READY"
            and dashboard_source.get("source_kind") == "postgres-read"
            and set(dashboard_decisions) == {CURRENT_POLICY_ID, WEIGHTED_RRF_POLICY_ID}
        ),
        "issue_candidates_include_threshold_rules": (
            issue_response["_http_status"] == 200
            and issue_response.get("projection_schema_version")
            == ISSUE_CANDIDATE_SCHEMA_VERSION
            and issue_rules
            == {
                "retrieval_threshold_live_samples_insufficient.v1",
                "retrieval_threshold_policy_review_ready.v1",
            }
        ),
        "raw_values_absent_from_ag_evidence": not any(
            value and value in serialized_responses for value in raw_values
        ),
    }


def _decisions_by_policy(section: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(section, dict):
        return {}
    decisions = section.get("threshold_decisions")
    if not isinstance(decisions, list):
        return {}
    return {
        str(decision["policy_id"]): decision
        for decision in decisions
        if isinstance(decision, dict) and decision.get("policy_id")
    }


def _threshold_sample_specs() -> list[dict[str, object]]:
    current_samples = [
        {
            "retrieval_policy_id": CURRENT_POLICY_ID,
            "ranker_mix": "bm25_with_embedding_presence",
            "status": "READY",
            "confidence_bucket": "READY",
            "best_score": round(0.83 + (index * 0.001), 6),
            "low_confidence_threshold": 0.2,
            "evidence_count": 1,
            "no_answer_reason": None,
        }
        for index in range(CURRENT_SAMPLE_COUNT)
    ]
    return [
        *current_samples,
        {
            "retrieval_policy_id": WEIGHTED_RRF_POLICY_ID,
            "ranker_mix": "weighted_rrf_vector_bm25_v1",
            "status": "READY",
            "confidence_bucket": "READY",
            "best_score": 0.159322,
            "low_confidence_threshold": 0.0,
            "evidence_count": 1,
            "no_answer_reason": None,
        },
    ]


def _raw_values(*, seed_refs: list[dict[str, str]]) -> list[str]:
    values: list[str] = []
    for refs in seed_refs:
        values.extend([refs["query_text"], refs["evidence_text"], refs["principal_id"]])
    return values


def _execution_failure(
    failure_code: str,
    detail: str,
    *,
    checks: dict[str, bool],
    raw_values: list[str],
) -> dict[str, object]:
    return {
        "failure_code": failure_code,
        "detail": detail,
        "checks": checks,
        "raw_values": raw_values,
    }


def _smoke_refs() -> dict[str, str]:
    run_id = uuid4()
    return {
        "trace_id": uuid4().hex,
        "request_id_prefix": f"ag-retrieval-threshold-postgres-smoke-{run_id}",
    }


def _migration_summary(result: object) -> dict[str, list[str]]:
    return {
        "planned": list(getattr(result, "planned", ())),
        "applied": list(getattr(result, "applied", ())),
        "skipped": list(getattr(result, "skipped", ())),
    }


def _failure(
    failure_code: str,
    detail: str,
    *,
    profile: str,
    database_env: str | None = None,
    checks: object | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "service_id": SERVICE_ID,
        "profile": profile,
        "failure_code": failure_code,
        "detail": detail,
    }
    if database_env is not None:
        payload["database_env"] = database_env
    if checks is not None:
        payload["checks"] = checks
    return payload


def summary_line(evidence: dict[str, object]) -> str:
    if evidence["status"] == "SKIPPED":
        return (
            "ag_retrieval_threshold_decision_postgres_smoke=skipped "
            f"reason={SMOKE_ENV}"
        )
    if evidence["status"] == "PASS":
        counts = evidence["counts"]
        return (
            "ag_retrieval_threshold_decision_postgres_smoke=pass "
            f"service={evidence['service_id']} db_env={evidence['database_env']} "
            f"decisions={counts['threshold_decisions']} "
            f"samples={counts['observed_sample_count']} "
            f"ready={counts['ready_for_review']} "
            f"insufficient={counts['insufficient_samples']} "
            f"issues={counts['issue_candidates']}"
        )
    return (
        "ag_retrieval_threshold_decision_postgres_smoke=fail "
        f"service={evidence.get('service_id')} reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run optional AG retrieval threshold decision PostgreSQL smoke."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    load_env_file(ROOT / ".env.local")
    evidence = run_ag_retrieval_threshold_decision_postgres_smoke()
    output = (
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False)
    )
    print(output)
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
