from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


class P8S77ReconciliationWorkerError(RuntimeError):
    pass


def run_worker(payload: dict[str, Any], readiness_path: Path) -> dict[str, Any]:
    from nex_ae_api.nsl_eos_reconciliation import HttpEosReconciliationAdapter
    from nex_ae_api.nsl_eos_write_execution import HttpEosWriteExecutionPort
    from nex_ae_api.nsl_v02_public_api import load_nsl_v02_public_api
    from nsl.core import STRING, DataClassification
    from p8_reliability_faults import EosCommitAckLossFaultPort

    readiness = json.loads(readiness_path.read_text(encoding="utf-8"))["readiness"]
    public_api = load_nsl_v02_public_api(readiness)
    commands = payload.get("commands")
    if not isinstance(commands, list) or len(commands) != 3:
        raise P8S77ReconciliationWorkerError(
            "P8-S77 requires exactly three reconciliation commands."
        )
    outcomes: list[dict[str, Any]] = []
    total_dispatches = 0
    for index, item in enumerate(commands):
        if not isinstance(item, dict) or not isinstance(item.get("command"), dict):
            raise P8S77ReconciliationWorkerError(
                "P8-S77 reconciliation command is invalid."
            )
        command = item["command"]
        request = _write_request(command)
        if index == 0:
            delegate = HttpEosWriteExecutionPort(
                public_api=public_api,
                base_url=payload["eos_base_url"],
                service_token=payload["service_token"],
                result_type=STRING,
                result_classification=DataClassification.CONFIDENTIAL,
            )
            fault_port = EosCommitAckLossFaultPort(delegate, public_api)
            unknown = asyncio.run(fault_port.execute(request))
            total_dispatches += fault_port.dispatch_attempts
        else:
            unknown = public_api.write_commit_unknown(
                identity=public_api.write_outcome_identity.from_request(request),
                reason_code="EOS_COMMIT_ACKNOWLEDGEMENT_LOST",
                message="The original WRITE outcome is uncertain.",
                evidence_refs=("fault-fixture:preexisting-unknown",),
            )
        adapter = HttpEosReconciliationAdapter(
            public_api=public_api,
            base_url=payload["eos_base_url"],
            service_token=payload["service_token"],
            result_type=STRING,
            result_classification=DataClassification.CONFIDENTIAL,
        )
        reconciled = asyncio.run(adapter.reconcile(request, unknown))
        outcome_identity = reconciled.identity
        evidence_refs = getattr(reconciled, "evidence_refs", None)
        if evidence_refs is None:
            evidence_refs = reconciled.result.evidence_refs
        outcomes.append(
            {
                "label": item.get("label"),
                "initial_commit_state": unknown.commit_state.value,
                "reconciled_commit_state": reconciled.commit_state.value,
                "business_operation_id": str(outcome_identity.business_operation_id),
                "idempotency_key": str(outcome_identity.idempotency_key),
                "payload_hash": str(outcome_identity.payload_hash),
                "reason_code": getattr(reconciled, "reason_code", None),
                "evidence_refs": list(evidence_refs),
                "attachment_batch_id": command["attachment_batch_id"],
                "attachment_manifest_hash": command["attachment_manifest_hash"],
                "attachment_ids": sorted(
                    attachment["attachment_id"]
                    for attachment in command["attachments"]
                ),
                "object_refs": sorted(
                    attachment["object_ref"] for attachment in command["attachments"]
                ),
            }
        )
    return {
        "schema_version": "p8_s77_reconciliation_worker.v1",
        "status": "PASS",
        "dispatch_attempts": total_dispatches,
        "outcomes": outcomes,
    }


def _write_request(command: dict[str, Any]) -> Any:
    from nsl.api import (
        BusinessPreconditionEvidence,
        BusinessPreconditionMechanism,
        WriteCallRequest,
        compute_payload_hash,
    )
    from nsl.core import (
        STRING,
        ApprovalRequestId,
        BusinessOperationId,
        IdempotencyKey,
        ValueEnvelope,
    )

    business_payload = {
        key: value
        for key, value in command.items()
        if key
        not in {
            "business_operation_id",
            "idempotency_key",
            "payload_hash",
            "nsl_approval_request_id",
            "nsl_approval_evidence_ref",
            "business_approval_proof_ref",
            "trace",
        }
    }
    business_payload["description_text"] = business_payload.pop("description")
    arguments = {
        key: ValueEnvelope.complete(value, STRING)
        for key, value in business_payload.items()
    }
    payload_hash = compute_payload_hash(arguments)
    if str(payload_hash) != command["payload_hash"]:
        raise P8S77ReconciliationWorkerError("NSL and EOS payload hashes differ.")
    now = datetime.now(UTC).replace(microsecond=0)
    business_operation_id = BusinessOperationId(command["business_operation_id"])
    precondition = BusinessPreconditionEvidence(
        evidence_id=f"precondition-p8-s77-{business_operation_id}",
        tenant_id=command["tenant_id"],
        business_operation_id=business_operation_id,
        write_node_id="write-voucher-draft",
        tool_id="FINANCE.CREATE_VOUCHER_DRAFT",
        contract_hash="sha256:" + "6" * 64,
        payload_hash=payload_hash,
        write_intent_hash="sha256:" + "8" * 64,
        mechanism=BusinessPreconditionMechanism.ETAG,
        evidence_ref="etag:opaque:p8-s77",
        observed_at=now,
        expires_at=now + timedelta(hours=1),
        provider_atomic_enforcement=True,
    )
    return WriteCallRequest(
        tenant_id=command["tenant_id"],
        execution_id=f"nsl-execution-p8-s77-{business_operation_id}",
        business_operation_id=business_operation_id,
        invocation_id=f"invocation-p8-s77-{business_operation_id}",
        node_id="write-voucher-draft",
        tool_ref="urn:nex:tool:finance-create-voucher-draft:v1",
        tool_id="FINANCE.CREATE_VOUCHER_DRAFT",
        contract_hash="sha256:" + "6" * 64,
        arguments=arguments,
        idempotency_key=IdempotencyKey(command["idempotency_key"]),
        payload_hash=payload_hash,
        approval_id="APPROVE_VOUCHER_DRAFT",
        approval_request_id=ApprovalRequestId(command["nsl_approval_request_id"]),
        write_intent_hash="sha256:" + "8" * 64,
        business_preconditions=precondition,
        trace_refs=tuple(f"{key}:{value}" for key, value in command["trace"].items()),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel", required=True, type=Path)
    parser.add_argument("--readiness", required=True, type=Path)
    parser.add_argument("--ae-source", required=True, type=Path)
    parser.add_argument("--shared-source", required=True, type=Path)
    args = parser.parse_args()
    sys.path[:0] = [str(args.wheel), str(args.ae_source), str(args.shared_source)]
    payload = json.load(sys.stdin)
    print(json.dumps(run_worker(payload, args.readiness), sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
