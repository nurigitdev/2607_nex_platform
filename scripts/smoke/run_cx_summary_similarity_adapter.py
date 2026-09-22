#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "_shared", ROOT / "services" / "nex-cx"):
    sys.path.insert(0, str(path))

from nex_cx.access_context import CxAccessContext  # noqa: E402
from nex_cx.summary_similarity import (  # noqa: E402
    PostgresSummarySimilarityStore,
)


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows


class _Session:
    def __init__(self, rows, capture):
        self.rows = rows
        self.capture = capture

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, statement, parameters):
        self.capture.update(sql=" ".join(str(statement).split()), parameters=parameters)
        return _Result(self.rows)


class _SessionFactory:
    def __init__(self, rows):
        self.rows = rows
        self.capture = {}

    def __call__(self):
        return _Session(self.rows, self.capture)


def run_cx_summary_similarity_adapter() -> dict[str, object]:
    context = CxAccessContext(
        caller_service_id="nex-cx",
        tenant_id="tenant-0956",
        subject_id="owner-0956",
        request_id="request-0956",
        trace_id="09560000000000000000000000000001",
        scopes=("service:call",),
    )
    row = {
        "summary_embedding_id": str(uuid4()),
        "document_summary_id": str(uuid4()),
        "content_object_id": str(uuid4()),
        "summary_text_sha256": "a" * 64,
        "embedding_sha256": "b" * 64,
        "vector_dimension": 3,
        "original_filename": "similar-document.pdf",
        "content_type": "application/pdf",
        "summary_char_count": 540,
        "distance": 0.125,
        "similarity_score": 0.875,
    }
    factory = _SessionFactory([row])
    result = PostgresSummarySimilarityStore(factory).search(  # type: ignore[arg-type]
        access_context=context,
        query_vector=(1.0, 0.0, 0.0),
        profile_fingerprint="c" * 64,
        limit=5,
        minimum_score=0.5,
    )
    sql = factory.capture["sql"]
    parameters = factory.capture["parameters"]
    checks = {
        "owner_tenant_filter": "content.tenant_ref_id = :tenant_id" in sql,
        "owner_subject_filter": "content.owner_subject_ref_id = :owner_subject_id" in sql,
        "active_filter": "content.lifecycle_status = 'ACTIVE'" in sql,
        "ready_filter": "summary_embedding.status = 'READY'" in sql,
        "latest_summary_filter": "SELECT latest.document_summary_id" in sql,
        "profile_filter": "summary_vector.profile_fingerprint = :profile_fingerprint" in sql,
        "owner_parameters": parameters["tenant_id"] == context.tenant_id
        and parameters["owner_subject_id"] == context.subject_id,
        "candidate_ranked": result["candidates"][0]["candidate_rank"] == 1,
        "score_bounded": result["candidates"][0]["similarity_score"] == 0.875,
        "raw_vector_absent": all(
            "embedding" not in candidate for candidate in result["candidates"]
        ),
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "check_count": len(checks),
        "failed_checks": [name for name, passed in checks.items() if not passed],
        "candidate_count": result["candidate_count"],
        "postgres_required": False,
        "remote_required": False,
    }


def _format_summary(result: dict[str, object]) -> str:
    return (
        f"cx_summary_similarity_adapter={str(result['status']).lower()} "
        f"checks={result['check_count'] - len(result['failed_checks'])}/"
        f"{result['check_count']} candidates={result['candidate_count']} "
        "postgres_required=False remote_required=False"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()
    result = run_cx_summary_similarity_adapter()
    print(_format_summary(result) if args.summary else json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
