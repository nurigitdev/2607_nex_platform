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
SMOKE_ENABLED = os.getenv("NEX_P8_S59_ACTUAL_WHEEL_OUTCOME_SMOKE") == "1"

pytestmark = pytest.mark.skipif(
    not SMOKE_ENABLED or not WHEEL.is_file() or not READINESS.is_file(),
    reason="Protected P8-S59 admitted-wheel outcome smoke is disabled",
)


def test_actual_admitted_wheel_maps_all_three_commit_outcomes() -> None:
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
        text=True,
        capture_output=True,
        check=True,
    )

    assert json.loads(completed.stdout) == {
        "committed": {
            "business_reference": (
                "eos.voucher_draft:84000000-0000-4000-8000-000000000059"
            ),
            "classification": "CONFIDENTIAL",
            "commit_state": "COMMITTED",
            "type": "WriteCommitted",
            "type_name": "VoucherDraft",
            "value": {"voucher_no": "84000000-0000-4000-8000-000000000059"},
        },
        "not_committed": {
            "commit_state": "NOT_COMMITTED",
            "reason_code": "EOS_AUTHORIZATION_DENIED",
            "type": "WriteNotCommitted",
        },
        "unknown": {
            "commit_state": "UNKNOWN_COMMIT_STATE",
            "reason_code": "EOS_TRANSACTION_UNAVAILABLE",
            "type": "WriteCommitUnknown",
        },
    }


_PROBE = r"""
import json
import sys
from datetime import UTC, datetime, timedelta

sys.path[:0] = [sys.argv[1], sys.argv[3], sys.argv[4]]

from nex_ae_api.nsl_eos_write_execution import (
    EosWriteExecutionResponse,
    map_eos_write_execution_response,
)
from nex_ae_api.nsl_v02_public_api import load_nsl_v02_public_api
from nsl.api import (
    BusinessPreconditionEvidence,
    BusinessPreconditionMechanism,
    WriteCallRequest,
    compute_payload_hash,
)
from nsl.core import (
    ApprovalRequestId,
    BusinessOperationId,
    DataClassification,
    IdempotencyKey,
    STRING,
    ValueEnvelope,
    record_type,
)

readiness = json.loads(open(sys.argv[2], encoding="utf-8").read())["readiness"]
public_api = load_nsl_v02_public_api(readiness)
operation_id = "86000000-0000-4000-8000-000000000059"
voucher_id = "84000000-0000-4000-8000-000000000059"
outbox_id = "87000000-0000-4000-8000-000000000059"
payload = {
    "schema_version": "eos_create_voucher_draft_command.v1",
    "tenant_id": "tenant-p8-s59",
    "requester_ref": {"type": "oa.user", "id": "employee-p8-s59"},
    "project_ref": {
        "type": "eos.project",
        "id": "82000000-0000-4000-8000-000000000059",
    },
    "voucher_type": "GENERAL",
    "transaction_date": "2026-10-22",
    "currency": "KRW",
    "description": "P8-S59 actual outcome mapping",
    "lines": [
        {
            "line_no": 1,
            "account_ref": {
                "type": "eos.account",
                "id": "83000000-0000-4000-8000-000000000059",
            },
            "signed_amount": "1000.00",
            "economic_category": "TRAVEL",
            "description": "Debit",
            "evidence_refs": ["approval-evidence-p8-s59"],
        },
        {
            "line_no": 2,
            "account_ref": {
                "type": "eos.account",
                "id": "83000000-0000-4000-8000-000000000060",
            },
            "signed_amount": "-1000.00",
            "economic_category": "CASH",
            "description": "Credit",
            "evidence_refs": ["approval-evidence-p8-s59"],
        },
    ],
    "nsl_approval_request_id": "approval-request-p8-s59",
    "nsl_approval_evidence_ref": "approval-evidence-p8-s59",
    "business_approval_proof_ref": None,
    "attachments": [],
}
arguments = {
    key: ValueEnvelope.complete(value, STRING)
    for key, value in payload.items()
}
payload_hash = compute_payload_hash(arguments)
now = datetime(2026, 10, 22, 12, tzinfo=UTC)
precondition = BusinessPreconditionEvidence(
    evidence_id="precondition-p8-s59",
    tenant_id=payload["tenant_id"],
    business_operation_id=BusinessOperationId(operation_id),
    write_node_id="write-voucher-draft",
    tool_id="FINANCE.CREATE_VOUCHER_DRAFT",
    contract_hash="sha256:" + "6" * 64,
    payload_hash=payload_hash,
    write_intent_hash="sha256:" + "8" * 64,
    mechanism=BusinessPreconditionMechanism.ETAG,
    evidence_ref="etag:opaque:p8-s59",
    observed_at=now,
    expires_at=now + timedelta(hours=1),
    provider_atomic_enforcement=True,
)
request = WriteCallRequest(
    tenant_id=payload["tenant_id"],
    execution_id="nsl-execution-p8-s59",
    business_operation_id=BusinessOperationId(operation_id),
    invocation_id="invocation-p8-s59",
    node_id="write-voucher-draft",
    tool_ref="urn:nex:tool:finance-create-voucher-draft:v1",
    tool_id="FINANCE.CREATE_VOUCHER_DRAFT",
    contract_hash="sha256:" + "6" * 64,
    arguments=arguments,
    idempotency_key=IdempotencyKey("idem:sha256:" + "7" * 64),
    payload_hash=payload_hash,
    approval_id="APPROVE_VOUCHER_DRAFT",
    approval_request_id=ApprovalRequestId(payload["nsl_approval_request_id"]),
    write_intent_hash="sha256:" + "8" * 64,
    business_preconditions=precondition,
    trace_refs=(
        "trace_id:trace-p8-s59",
        "correlation_id:correlation-p8-s59",
        "causation_id:causation-p8-s59",
    ),
)
result_type = record_type("VoucherDraft", voucher_no=STRING)
committed_payload = {
    "schema_version": "eos_create_voucher_draft_result.v1",
    "tenant_id": payload["tenant_id"],
    "business_operation_id": operation_id,
    "idempotency_key": request.idempotency_key,
    "payload_hash": payload_hash,
    "commit_state": "COMMITTED",
    "idempotency_disposition": "CREATED",
    "voucher_ref": {"type": "eos.voucher_draft", "id": voucher_id},
    "business_transaction_ref": {
        "type": "eos.business_operation",
        "id": operation_id,
    },
    "committed_at": "2026-10-22T12:00:00Z",
    "outbox_event_ref": {"type": "eos.outbox_event", "id": outbox_id},
    "reason_code": None,
    "reconciliation_ref": None,
}

def mapped(status, body):
    return map_eos_write_execution_response(
        EosWriteExecutionResponse(status, body),
        request,
        public_api=public_api,
        result_type=result_type,
        result_classification=DataClassification.CONFIDENTIAL,
    )

committed = mapped(201, committed_payload)
not_committed = mapped(
    403,
    {"status": 403, "error_code": "EOS_AUTHORIZATION_DENIED"},
)
unknown = mapped(
    503,
    {"status": 503, "error_code": "EOS_TRANSACTION_UNAVAILABLE"},
)
print(json.dumps({
    "committed": {
        "type": type(committed).__name__,
        "commit_state": committed.commit_state.value,
        "value": committed.result.value.value,
        "type_name": committed.result.value.type_info.name,
        "classification": committed.result.value.classification.value,
        "business_reference": committed.result.business_reference,
    },
    "not_committed": {
        "type": type(not_committed).__name__,
        "commit_state": not_committed.commit_state.value,
        "reason_code": not_committed.reason_code,
    },
    "unknown": {
        "type": type(unknown).__name__,
        "commit_state": unknown.commit_state.value,
        "reason_code": unknown.reason_code,
    },
}, sort_keys=True))
"""
