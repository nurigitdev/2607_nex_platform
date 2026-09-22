#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from jsonschema import Draft202012Validator, ValidationError


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "_shared", ROOT / "services" / "nex-cx"):
    sys.path.insert(0, str(path))

from nex_cx.document_intelligence_observability import (  # noqa: E402
    CX_DOCUMENT_INTELLIGENCE_FAILED_EVENT,
    CX_DOCUMENT_INTELLIGENCE_READY_EVENT,
    CX_DOCUMENT_INTELLIGENCE_SIMILARITY_EVENT,
    observe_document_intelligence_failure,
    observe_document_intelligence_ready,
    observe_document_intelligence_similarity,
)
from nex_runtime import (  # noqa: E402
    InMemoryOperationalEventStore,
    OperationalEventEmitter,
)
from run_cx_document_intelligence_similarity_boundary_audit import (  # noqa: E402
    run_cx_document_intelligence_similarity_boundary_audit,
)


SCHEMA_VERSION = "cx_document_intelligence_contract_observability_evidence.v1"
DOCUMENT_ID = "62cbb468-147e-5e66-9bd8-4551a5807cf6"
TRACE_ID = "95800000000000000000000000000002"
REQUEST_ID = "request-0958-evidence"


def run_cx_document_intelligence_contract_observability() -> dict[str, Any]:
    run_schema = _json(
        "contracts/schemas/service/nex_cx/"
        "document_intelligence_run.v1.schema.json"
    )
    similarity_schema = _json(
        "contracts/schemas/service/nex_cx/"
        "document_intelligence_similarity.v1.schema.json"
    )
    run_example = _json(
        "contracts/examples/retrieval/"
        "cx_document_intelligence_run.mock_success.json"
    )
    similarity_example = _json(
        "contracts/examples/retrieval/"
        "cx_document_intelligence_similarity.mock_success.json"
    )
    run_negative = _json(
        "contracts/tests/negative/retrieval/"
        "cx_document_intelligence_run.raw_summary_leak.json"
    )
    similarity_negative = _json(
        "contracts/tests/negative/retrieval/"
        "cx_document_intelligence_similarity.vector_leak.json"
    )
    run_validator = Draft202012Validator(run_schema)
    similarity_validator = Draft202012Validator(similarity_schema)
    schema_valid = _schemas_valid(run_schema, similarity_schema)
    examples_valid = _valid(run_validator, run_example) and _valid(
        similarity_validator,
        similarity_example,
    )
    negatives_rejected = _invalid(run_validator, run_negative) and _invalid(
        similarity_validator,
        similarity_negative,
    )

    event_store = InMemoryOperationalEventStore()
    emitter = OperationalEventEmitter(service_id="nex-cx", store=event_store)
    observe_document_intelligence_ready(
        emitter,
        document_id=DOCUMENT_ID,
        result=run_example,
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
    )
    observe_document_intelligence_similarity(
        emitter,
        document_id=DOCUMENT_ID,
        result=similarity_example,
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
    )
    observe_document_intelligence_failure(
        emitter,
        document_id=DOCUMENT_ID,
        operation="run",
        error_code="CX_PROVIDER_UNAVAILABLE",
        status_code=503,
        retryable=True,
        trace_id=TRACE_ID,
        request_id=REQUEST_ID,
    )
    ready_events = event_store.list_events(
        event_type=CX_DOCUMENT_INTELLIGENCE_READY_EVENT
    )
    similarity_events = event_store.list_events(
        event_type=CX_DOCUMENT_INTELLIGENCE_SIMILARITY_EVENT
    )
    failure_events = event_store.list_events(
        event_type=CX_DOCUMENT_INTELLIGENCE_FAILED_EVENT
    )
    serialized_events = json.dumps(event_store.list_events(), sort_keys=True)
    boundary = run_cx_document_intelligence_similarity_boundary_audit(ROOT)
    openapi = (ROOT / "contracts/openapi/nex-cx.openapi.yaml").read_text(
        encoding="utf-8"
    )
    checks = {
        "schemas_valid": schema_valid,
        "positive_examples_valid": examples_valid,
        "private_payload_negatives_rejected": negatives_rejected,
        "ready_event_emitted": len(ready_events) == 1,
        "similarity_event_emitted": len(similarity_events) == 1,
        "failure_event_emitted": len(failure_events) == 1,
        "events_correlated": all(
            event.get("trace_id") == TRACE_ID
            and event.get("request_id") == REQUEST_ID
            for event in event_store.list_events()
        ),
        "events_are_metadata_only": all(
            token not in serialized_events
            for token in (
                run_example["summary"]["summary_preview"],
                run_example["summary"]["summary_storage_uri"],
                "query_vector",
                "raw_summary",
            )
        ),
        "openapi_response_refs_bound": all(
            token in openapi
            for token in (
                "#/components/schemas/CxDocumentIntelligenceRun",
                "#/components/schemas/CxDocumentIntelligenceSimilarity",
            )
        ),
        "s96_observability_gap_resolved": (
            boundary["gap_states"][
                "document_intelligence_observability_missing"
            ]
            == "RESOLVED"
            and boundary["summary"]["open_gap_count"] == 0
        ),
    }
    failed_checks = [name for name, passed in checks.items() if not passed]
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "0958",
        "requirement": "S96",
        "status": "PASS" if not failed_checks else "FAIL",
        "checks": checks,
        "passed_checks": sum(checks.values()),
        "failed_checks": failed_checks,
        "event_types": [
            CX_DOCUMENT_INTELLIGENCE_READY_EVENT,
            CX_DOCUMENT_INTELLIGENCE_SIMILARITY_EVENT,
            CX_DOCUMENT_INTELLIGENCE_FAILED_EVENT,
        ],
        "postgres_required": False,
        "remote_provider_required": False,
    }


def _json(relative_path: str) -> dict[str, Any]:
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


def _schemas_valid(*schemas: dict[str, Any]) -> bool:
    try:
        for schema in schemas:
            Draft202012Validator.check_schema(schema)
    except Exception:
        return False
    return True


def _valid(
    validator: Draft202012Validator,
    payload: dict[str, Any],
) -> bool:
    return next(validator.iter_errors(payload), None) is None


def _invalid(
    validator: Draft202012Validator,
    payload: dict[str, Any],
) -> bool:
    try:
        validator.validate(payload)
    except ValidationError:
        return True
    return False


def summary_line(result: dict[str, Any]) -> str:
    checks = result.get("checks", {})
    return (
        "cx_document_intelligence_contract_observability="
        f"{str(result.get('status')).lower()} "
        f"checks={result.get('passed_checks', 0)}/{len(checks)} "
        "postgres_required=False remote_required=False"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_cx_document_intelligence_contract_observability()
    if args.summary:
        print(summary_line(result))
    else:
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
