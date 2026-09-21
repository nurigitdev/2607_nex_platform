#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "_shared", ROOT / "services" / "nex-cx"):
    sys.path.insert(0, str(path))

from nex_cx.access_context import CxAccessContext  # noqa: E402
from nex_cx.private_content import (  # noqa: E402
    CxPrivatePayloadReceipt,
    CxPrivateTextStore,
    CxVectorStore,
    build_private_payload_key,
    build_private_payload_receipt,
    normalize_private_vector,
    sha256_private_text,
    sha256_private_vector,
    validate_private_text,
)


SCHEMA_VERSION = "cx_private_content_capability_contract_evidence.v1"


class _CapabilityProbe:
    def put_text(self, **_: object) -> CxPrivatePayloadReceipt:
        raise NotImplementedError

    def get_text(self, **_: object) -> str | None:
        raise NotImplementedError

    def delete_text(self, **_: object) -> bool:
        raise NotImplementedError

    def put_vector(self, **_: object) -> CxPrivatePayloadReceipt:
        raise NotImplementedError

    def get_vector(self, **_: object) -> tuple[float, ...] | None:
        raise NotImplementedError

    def delete_vector(self, **_: object) -> bool:
        raise NotImplementedError


def run_cx_private_content_capability_contract() -> dict[str, Any]:
    context = CxAccessContext(
        caller_service_id="nex-ae-api",
        tenant_id="tenant-s92",
        subject_id="employee-9201",
        request_id="request-s92-0914",
        trace_id="91400000000000000000000000000001",
        scopes=("service:call",),
    )
    text = "Private summary content"
    text_key = build_private_payload_key(
        context,
        payload_kind="summary_text",
        content_id="summary-0914",
    )
    text_hash = sha256_private_text(text)
    validated_text = validate_private_text(
        key=text_key,
        text=text,
        expected_sha256=text_hash,
    )
    vector = (0.25, -0.5, 1.0)
    vector_key = build_private_payload_key(
        context,
        payload_kind="summary_embedding",
        content_id="summary-0914",
    )
    vector_hash = sha256_private_vector(vector)
    normalized_vector = normalize_private_vector(
        key=vector_key,
        vector=vector,
        expected_sha256=vector_hash,
    )
    receipt = build_private_payload_receipt(
        key=vector_key,
        storage_backend="contract-probe",
        storage_uri="cx-private://contract-probe/summary-0914",
        sha256=vector_hash,
        size_bytes=24,
        vector_dimension=len(vector),
    )
    receipt_wire = receipt.to_wire()
    probe = _CapabilityProbe()
    checks = {
        "text_contract_validated": validated_text == text,
        "vector_contract_validated": normalized_vector == vector,
        "owner_scope_bound_to_key": (
            text_key.tenant_id,
            text_key.subject_id,
        )
        == context.ownership_key,
        "text_store_protocol_structural": isinstance(probe, CxPrivateTextStore),
        "vector_store_protocol_structural": isinstance(probe, CxVectorStore),
        "receipt_metadata_only": text not in repr(receipt_wire)
        and repr(vector) not in repr(receipt_wire),
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "0914",
        "requirement": "S92",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "cx_private_content_capability_failed",
        "checks": checks,
        "receipt": receipt_wire,
        "summary": {
            "payload_kind_count": 4,
            "protocol_count": 2,
            "passed_check_count": sum(checks.values()),
            "check_count": len(checks),
            "postgres_required": False,
            "dgx_required": False,
        },
        "next_slice": "0915",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "cx_private_content_capability="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"checks={summary.get('passed_check_count', 0)}/"
        f"{summary.get('check_count', 0)} "
        f"protocols={summary.get('protocol_count', 0)} "
        f"dgx_required={summary.get('dgx_required')}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify CX private text/vector capability port contracts."
    )
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_cx_private_content_capability_contract()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
