#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "nex-ae-api", ROOT / "services" / "_shared"):
    sys.path.insert(0, str(path))

from nex_ae_api.upload_handoff_persistence import SqlAlchemyUploadHandoffStore


SCHEMA_VERSION = "ae_upload_handoff_persistence_evidence.v1"
MIGRATION = "database/nex-ae-api/migrations/1344_ae_upload_handoff_persistence.sql"


def run_ae_upload_handoff_persistence(root: Path = ROOT) -> dict[str, Any]:
    migration = _read_text(root / MIGRATION)
    factory = _session_factory()
    first = SqlAlchemyUploadHandoffStore(factory)
    second = SqlAlchemyUploadHandoffStore(factory)
    record = _record()
    saved = first.save(record)
    loaded = second.get(
        record["upload_handoff_id"],
        tenant_id=record["tenant_id"],
        owner_user_id=record["owner_user_id"],
    )
    hidden = second.get(
        record["upload_handoff_id"],
        tenant_id=record["tenant_id"],
        owner_user_id="other-user",
    )
    checks = {
        "migration_present": bool(migration),
        "table_name_bounded": "CREATE TABLE IF NOT EXISTS ae_upload_handoffs" in migration,
        "owner_index_present": "idx_ae_upload_owner_time" in migration,
        "workspace_owner_index_present": "idx_ae_upload_ws_owner" in migration,
        "document_owner_index_present": "idx_ae_upload_cx_doc" in migration,
        "restart_readback_matches": saved == loaded == record,
        "cross_owner_readback_hidden": hidden is None,
        "source_bytes_absent": "content_base64" not in json.dumps(saved),
        "private_text_absent": "private-s135" not in json.dumps(saved),
    }
    issues = sorted(name for name, passed in checks.items() if not passed)
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1344",
        "requirement": "S135",
        "status": "PASS" if not issues else "FAIL",
        "checks": checks,
        "issues": issues,
        "table": "ae_upload_handoffs",
        "index_count": 3,
        "database_used": "sqlite_regression",
        "actual_postgres_deferred_to": "1350",
        "next_slice": "1345",
    }


def _session_factory():
    engine = create_engine(
        "sqlite+pysqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE ae_upload_handoffs (
                upload_handoff_id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL, owner_user_id TEXT NOT NULL,
                source_sha256 TEXT NOT NULL, cx_document_id TEXT NOT NULL,
                cx_upload_id TEXT NOT NULL, ingestion_job_id TEXT NOT NULL,
                status TEXT NOT NULL, record_payload TEXT NOT NULL,
                trace_id TEXT NOT NULL, request_id TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )
        """))
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _record() -> dict[str, Any]:
    digest = "d12261539d27dcab69f873a5e1a30587919b8ce4802782151f1bc2ba5390b610"
    return {
        "upload_handoff_schema_version": "ae_upload_handoff.v1",
        "upload_handoff_id": "handoff-1344",
        "workspace_id": "workspace-1344",
        "tenant_id": "tenant-1344",
        "owner_user_id": "user-1344",
        "status": "QUEUED",
        "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
        "request_id": "request-1344",
        "source": {
            "filename": "report.md",
            "content_type": "text/markdown",
            "size_bytes": 12,
            "source_sha256": digest,
            "source_text_hash": None,
        },
        "cx_document_ref": {
            "document_id": "document-1344",
            "upload_id": "upload-1344",
            "ingestion_job_id": "job-1344",
            "extraction_status": "PENDING",
            "markdown_available": False,
            "dedupe_status": "CREATED",
            "existing_document_id": None,
        },
        "links": {},
        "metadata": {"raw_source_stored_in_ae": False},
        "created_at": "2026-10-05T00:00:00Z",
        "updated_at": "2026-10-05T00:00:00Z",
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") != "PASS":
        return f"ae_upload_handoff_persistence=fail issues={len(evidence.get('issues') or [])}"
    checks = evidence.get("checks") or {}
    return (
        "ae_upload_handoff_persistence=pass "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"indexes={evidence.get('index_count')} next={evidence.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_ae_upload_handoff_persistence()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
