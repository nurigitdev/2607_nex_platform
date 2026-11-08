from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WHEEL = (
    ROOT
    / "reports/deployment/p8-nsl-v0.2-wheel"
    / "nex_skill_language-0.2.0-py3-none-any.whl"
)
READINESS = ROOT / "reports/deployment/p8-s04-nsl-v0.2-readiness.json"
SMOKE_ENABLED = os.getenv("NEX_P8_S57_ACTUAL_WHEEL_ADAPTER_SMOKE") == "1"

pytestmark = pytest.mark.skipif(
    not SMOKE_ENABLED or not WHEEL.is_file() or not READINESS.is_file(),
    reason="Protected P8-S57 admitted-wheel adapter smoke is disabled",
)


def test_actual_admitted_write_call_request_projects_unchanged_identities() -> None:
    business_payload = json.loads(
        (
            ROOT
            / "contracts/examples/service/eos_create_voucher_draft_command.golden_a.json"
        ).read_text(encoding="utf-8")
    )
    for field in (
        "business_operation_id",
        "idempotency_key",
        "payload_hash",
        "nsl_approval_request_id",
        "nsl_approval_evidence_ref",
        "business_approval_proof_ref",
        "trace",
    ):
        business_payload.pop(field)
    business_payload["description_text"] = business_payload.pop("description")

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            _PROBE,
            str(WHEEL),
            str(READINESS),
            str(ROOT / "services/nex-ae-api"),
            str(ROOT / "services/_shared"),
        ],
        input=json.dumps(business_payload, ensure_ascii=False),
        text=True,
        capture_output=True,
        check=True,
    )
    evidence = json.loads(completed.stdout)

    assert evidence == {
        "business_operation_id": "86000000-0000-4000-8000-000000000001",
        "idempotency_key": "idem:sha256:" + "7" * 64,
        "payload_hash": (
            "sha256:1705802a128eb6206a7e8f9547bb4074d3699c27a6e87ad69b3b6a0def4c02ba"
        ),
        "request_type": "WriteCallRequest",
        "write_call_request_admitted": True,
    }


_PROBE = r"""
import json
import sys
from datetime import UTC, datetime, timedelta

sys.path[:0] = [sys.argv[1], sys.argv[3], sys.argv[4]]

from nex_ae_api.nsl_eos_write_execution import build_eos_create_voucher_command
from nex_ae_api.nsl_v02_public_api import load_nsl_v02_public_api
from nsl.api import (
    BusinessPreconditionEvidence,
    BusinessPreconditionMechanism,
    WriteCallRequest,
    compute_payload_hash,
)
from nsl.core import ApprovalRequestId, BusinessOperationId, IdempotencyKey, STRING, ValueEnvelope

readiness = json.loads(open(sys.argv[2], encoding="utf-8").read())["readiness"]
public_api = load_nsl_v02_public_api(readiness)
payload = json.load(sys.stdin)
arguments = {key: ValueEnvelope.complete(value, STRING) for key, value in payload.items()}
payload_hash = compute_payload_hash(arguments)
now = datetime(2026, 10, 22, 12, tzinfo=UTC)
precondition = BusinessPreconditionEvidence(
    evidence_id="precondition-p8-s57",
    tenant_id=payload["tenant_id"],
    business_operation_id=BusinessOperationId("86000000-0000-4000-8000-000000000001"),
    write_node_id="write-voucher-draft",
    tool_id="FINANCE.CREATE_VOUCHER_DRAFT",
    contract_hash="sha256:" + "6" * 64,
    payload_hash=payload_hash,
    write_intent_hash="sha256:" + "8" * 64,
    mechanism=BusinessPreconditionMechanism.ETAG,
    evidence_ref="etag:opaque:p8-s57",
    observed_at=now,
    expires_at=now + timedelta(hours=1),
    provider_atomic_enforcement=True,
)
request = WriteCallRequest(
    tenant_id=payload["tenant_id"],
    execution_id="nsl-execution-p8-s57",
    business_operation_id=BusinessOperationId("86000000-0000-4000-8000-000000000001"),
    invocation_id="invocation-p8-s57",
    node_id="write-voucher-draft",
    tool_ref="urn:nex:tool:finance-create-voucher-draft:v1",
    tool_id="FINANCE.CREATE_VOUCHER_DRAFT",
    contract_hash="sha256:" + "6" * 64,
    arguments=arguments,
    idempotency_key=IdempotencyKey("idem:sha256:" + "7" * 64),
    payload_hash=payload_hash,
    approval_id="APPROVE_VOUCHER_DRAFT",
    approval_request_id=ApprovalRequestId("approval-request-1001"),
    write_intent_hash="sha256:" + "8" * 64,
    business_preconditions=precondition,
    trace_refs=(
        "trace_id:trace-p8-s57",
        "correlation_id:correlation-p8-s57",
        "causation_id:causation-p8-s57",
    ),
)
command = build_eos_create_voucher_command(request, public_api=public_api)
print(json.dumps({
    "business_operation_id": command["business_operation_id"],
    "idempotency_key": command["idempotency_key"],
    "payload_hash": command["payload_hash"],
    "request_type": type(request).__name__,
    "write_call_request_admitted": public_api.write_call_request is WriteCallRequest,
}, sort_keys=True))
"""
