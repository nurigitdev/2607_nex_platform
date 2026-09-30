#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))

from nex_mo.provider_telemetry_persistence import (  # noqa: E402
    ProviderTelemetryIdentity,
    ProviderTelemetryMutation,
)
from nex_mo.provider_telemetry_repository import (  # noqa: E402
    SqlAlchemyDurableProviderTelemetryRepository,
)


def run_mo_provider_telemetry_repository() -> dict[str, Any]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE mo_provider_telemetry (
                    telemetry_key CHAR(64) PRIMARY KEY,
                    capability TEXT NOT NULL,
                    request_shape TEXT NOT NULL,
                    deployment_id TEXT NOT NULL,
                    model_revision TEXT NOT NULL,
                    request_count INTEGER NOT NULL,
                    success_count INTEGER NOT NULL,
                    failure_count INTEGER NOT NULL,
                    retryable_failure_count INTEGER NOT NULL,
                    degraded_count INTEGER NOT NULL,
                    attempt_count INTEGER NOT NULL,
                    retry_count INTEGER NOT NULL,
                    last_outcome TEXT,
                    last_observed_at TEXT,
                    last_latency_ms INTEGER,
                    last_status_code INTEGER,
                    last_error_code TEXT,
                    last_failure_kind TEXT,
                    last_upstream_status_code INTEGER,
                    last_retry_at TEXT,
                    last_retry_delay_ms INTEGER,
                    last_retry_failure_kind TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    identity = ProviderTelemetryIdentity(
        capability="reranking",
        request_shape="rerank",
        deployment_id="smoke-deployment",
        model_revision="smoke-revision",
    )
    first = SqlAlchemyDurableProviderTelemetryRepository(factory)
    first.apply(
        ProviderTelemetryMutation(
            identity=identity,
            mutation_kind="retry",
            observed_at="2026-09-30T01:00:00Z",
            attempt_increment=1,
            retry_increment=1,
            last_retry_delay_ms=100,
            last_retry_failure_kind="throttled",
        )
    )
    first.apply(
        ProviderTelemetryMutation(
            identity=identity,
            mutation_kind="success",
            observed_at="2026-09-30T01:00:01Z",
            request_increment=1,
            success_increment=1,
            attempt_increment=1,
            last_outcome="success",
            last_latency_ms=9,
            last_status_code=200,
        )
    )
    restarted = SqlAlchemyDurableProviderTelemetryRepository(factory)
    records = restarted.list_records(capability="reranking")
    record = records[0] if records else None
    deleted = restarted.clear()
    checks = {
        "record_recovered_after_store_restart": record is not None,
        "request_count_preserved": record is not None and record.request_count == 1,
        "attempt_count_preserved": record is not None and record.attempt_count == 2,
        "retry_count_preserved": record is not None and record.retry_count == 1,
        "cleanup_removed_evidence": deleted == 1 and restarted.list_records() == [],
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "mo_provider_telemetry_repository_smoke.v1",
        "slice": "1154",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "summary": {
            "migration_present": (
                ROOT
                / "database/nex-mo/migrations/1154_mo_provider_telemetry.sql"
            ).is_file(),
            "row_count": len(records),
            "request_count": record.request_count if record else 0,
            "attempt_count": record.attempt_count if record else 0,
            "retry_count": record.retry_count if record else 0,
            "cleanup_count": deleted,
        },
        "next_slice": "1155" if passed else None,
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "mo_provider_telemetry_repository="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"migration={str(bool(summary.get('migration_present'))).lower()} "
        f"rows={summary.get('row_count', 0)} "
        f"requests={summary.get('request_count', 0)} "
        f"attempts={summary.get('attempt_count', 0)} "
        f"retries={summary.get('retry_count', 0)} "
        f"cleanup={summary.get('cleanup_count', 0)} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_provider_telemetry_repository()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
