#!/usr/bin/env python3
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from typing import Any, Mapping

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))

from nex_mo.provider_telemetry_persistence import (  # noqa: E402
    ProviderTelemetryIdentity,
    ProviderTelemetryMutation,
)
from nex_mo.provider_telemetry_repository import (  # noqa: E402
    SqlAlchemyDurableProviderTelemetryRepository,
)


def run_mo_provider_telemetry_restart_concurrency() -> dict[str, Any]:
    with TemporaryDirectory(prefix="nex-mo-telemetry-") as directory:
        engine = create_engine(
            f"sqlite+pysqlite:///{Path(directory) / 'telemetry.db'}",
            connect_args={"check_same_thread": False, "timeout": 30},
        )
        _apply_sqlite_migration(engine)
        factory = sessionmaker(
            bind=engine,
            autoflush=False,
            expire_on_commit=False,
        )
        identity = ProviderTelemetryIdentity(
            capability="embedding",
            request_shape="openai_embeddings",
            deployment_id="concurrency-smoke",
            model_revision="concurrency-revision",
        )
        repository = SqlAlchemyDurableProviderTelemetryRepository(factory)

        def apply(index: int) -> None:
            repository.apply(
                ProviderTelemetryMutation(
                    identity=identity,
                    mutation_kind="success",
                    observed_at=f"2026-09-30T01:00:{index:02d}Z",
                    request_increment=1,
                    success_increment=1,
                    attempt_increment=1,
                    last_outcome="success",
                    last_latency_ms=index,
                    last_status_code=200,
                )
            )

        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(apply, reversed(range(40))))
        restarted = SqlAlchemyDurableProviderTelemetryRepository(factory)
        records = restarted.list_records(capability="embedding")
        record = records[0] if records else None
        deleted = restarted.clear()
        checks = {
            "migration_applied": _migration_recorded(factory),
            "restart_recovered_one_aggregate": len(records) == 1,
            "concurrent_requests_not_lost": record is not None
            and record.request_count == 40,
            "concurrent_attempts_not_lost": record is not None
            and record.attempt_count == 40,
            "latest_observation_wins": record is not None
            and record.last_observed_at == "2026-09-30T01:00:39Z",
            "cleanup_removed_evidence": deleted == 1
            and restarted.list_records() == [],
        }
        summary = {
            "worker_count": 8,
            "mutation_count": 40,
            "request_count": record.request_count if record else 0,
            "attempt_count": record.attempt_count if record else 0,
            "cleanup_count": deleted,
        }
        engine.dispose()
    passed = all(checks.values())
    return {
        "evidence_schema_version": (
            "mo_provider_telemetry_restart_concurrency_smoke.v1"
        ),
        "slice": "1157",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "summary": summary,
        "next_slice": "1158" if passed else None,
    }


def _apply_sqlite_migration(engine) -> None:
    migration = (
        ROOT / "database/nex-mo/migrations/1154_mo_provider_telemetry.sql"
    ).read_text(encoding="utf-8")
    connection = engine.raw_connection()
    try:
        connection.executescript(
            """
            CREATE TABLE schema_migrations (
                version TEXT PRIMARY KEY,
                description TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
            + migration
        )
    finally:
        connection.close()


def _migration_recorded(factory) -> bool:
    from sqlalchemy import text

    with factory() as session:
        return (
            session.execute(
                text(
                    "SELECT COUNT(*) FROM schema_migrations "
                    "WHERE version = '1154_mo_provider_telemetry'"
                )
            ).scalar_one()
            == 1
        )


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "mo_provider_telemetry_restart_concurrency="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"workers={summary.get('worker_count', 0)} "
        f"mutations={summary.get('mutation_count', 0)} "
        f"requests={summary.get('request_count', 0)} "
        f"attempts={summary.get('attempt_count', 0)} "
        f"cleanup={summary.get('cleanup_count', 0)} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_provider_telemetry_restart_concurrency()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
