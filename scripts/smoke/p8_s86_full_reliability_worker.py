from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


class P8S86FullReliabilityWorkerError(RuntimeError):
    pass


def run_worker(
    payload: dict[str, Any],
    readiness_path: Path,
    nsl_source: Path,
) -> dict[str, Any]:
    from nex_ae_api.nsl_eos_post_write_verification import (
        HttpEosPostWriteVerificationAdapter,
    )
    from nex_ae_api.nsl_eos_reconciliation import HttpEosReconciliationAdapter
    from nex_ae_api.nsl_eos_write_execution import HttpEosWriteExecutionPort
    from nex_ae_api.nsl_v02_public_api import load_nsl_v02_public_api
    from nsl.cli import _load_program
    from nsl.cli_config import load_tool_catalog
    from nsl.core import DataClassification, VerificationStatus
    from nsl.runtime_models import ExecutionContext, ExecutionRequest
    from nsl.security import ExecutionPrincipal, PrincipalVerification
    from p8_reliability_faults import EosCommitAckLossFaultPort

    command = payload.get("command")
    if not isinstance(command, dict):
        raise P8S86FullReliabilityWorkerError(
            "P8-S86 requires one canonical Voucher command."
        )
    readiness = json.loads(readiness_path.read_text(encoding="utf-8"))["readiness"]
    public_api = load_nsl_v02_public_api(readiness)
    example = nsl_source / "examples/golden_a_voucher_draft"
    catalog = load_tool_catalog(example / "tools.json")
    skill = _load_program(example / "golden_a_voucher_draft.ns", catalog)
    contract = catalog.resolve("FINANCE.CREATE_VOUCHER_DRAFT", "1.1.0")
    required_tool = next(
        item for item in skill.required_tools if item.tool_id == contract.tool_id
    )
    request = _write_request(
        command,
        contract_hash=contract.contract_hash,
        tool_ref=required_tool.tool_ref,
    )
    principal = ExecutionPrincipal(
        tenant_id=command["tenant_id"],
        subject_id=command["requester_ref"]["id"],
        actor_type="USER",
        roles=frozenset({"employee"}),
        scopes=frozenset({"finance:voucher-draft:create"}),
        auth_context_ref="oa:p8-s86-protected",
        verification=PrincipalVerification.VERIFIED,
    )
    context = ExecutionContext(
        skill,
        ExecutionRequest(
            execution_id=request.execution_id,
            inputs={},
            runtime_context={},
            principal=principal,
            business_operation_id=request.business_operation_id,
        ),
    )
    context.idempotency.keys_by_write_node[request.node_id] = request.idempotency_key
    context.idempotency.payload_hashes_by_write_node[request.node_id] = (
        request.payload_hash
    )

    write_delegate = HttpEosWriteExecutionPort(
        public_api=public_api,
        base_url=payload["eos_base_url"],
        service_token=payload["service_token"],
        result_type=contract.output_type,
        result_classification=DataClassification.CONFIDENTIAL,
    )
    ack_loss_port = EosCommitAckLossFaultPort(write_delegate, public_api)
    unknown = asyncio.run(ack_loss_port.execute(request))
    if unknown.commit_state.value != "UNKNOWN_COMMIT_STATE":
        raise P8S86FullReliabilityWorkerError(
            "P8-S86 ambiguous response did not produce UNKNOWN_COMMIT_STATE."
        )

    reconciliation_port = HttpEosReconciliationAdapter(
        public_api=public_api,
        base_url=payload["eos_base_url"],
        service_token=payload["service_token"],
        result_type=contract.output_type,
        result_classification=DataClassification.CONFIDENTIAL,
    )
    reconciled = asyncio.run(reconciliation_port.reconcile(request, unknown))
    if reconciled.commit_state.value != "COMMITTED":
        raise P8S86FullReliabilityWorkerError(
            "P8-S86 reconciliation did not recover the committed Voucher."
        )

    verification_port = HttpEosPostWriteVerificationAdapter(
        public_api=public_api,
        base_url=payload["eos_base_url"],
        service_token=payload["service_token"],
    )
    verification = asyncio.run(
        public_api.post_write_verifier().verify(
            reconciled.result,
            contract,
            context,
            verification_port,
        )
    )
    if verification.status is not VerificationStatus.VERIFIED:
        raise P8S86FullReliabilityWorkerError(
            "P8-S86 post-WRITE verification did not return VERIFIED."
        )
    if verification.commit_state.value != "COMMITTED":
        raise P8S86FullReliabilityWorkerError(
            "P8-S86 verification changed the reconciled commit state."
        )

    fault_evidence = ack_loss_port.evidence
    identity = reconciled.identity
    return {
        "schema_version": "p8_s86_full_reliability_worker.v1",
        "status": "PASS",
        "ambiguous_commit_state": unknown.commit_state.value,
        "reconciled_commit_state": reconciled.commit_state.value,
        "verification_status": verification.status.value,
        "verification_commit_state": verification.commit_state.value,
        "verification_reason_code": verification.reason_code,
        "write_dispatch_attempts": fault_evidence.dispatch_attempts,
        "response_status_discarded": fault_evidence.response_status_discarded,
        "reconciliation_status": fault_evidence.reconciliation_status,
        "business_operation_id": str(identity.business_operation_id),
        "idempotency_key": str(identity.idempotency_key),
        "payload_hash": str(identity.payload_hash),
        "verification_payload_hash": str(verification.identity.payload_hash),
        "voucher_ref": reconciled.result.business_reference,
        "attachment_batch_id": command["attachment_batch_id"],
        "attachment_manifest_hash": command["attachment_manifest_hash"],
        "attachment_ids": sorted(
            item["attachment_id"] for item in command["attachments"]
        ),
        "object_refs": sorted(item["object_ref"] for item in command["attachments"]),
    }


def _write_request(
    command: dict[str, Any],
    *,
    contract_hash: str,
    tool_ref: str,
) -> Any:
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
        raise P8S86FullReliabilityWorkerError("NSL and EOS payload hashes differ.")
    now = datetime.now(UTC).replace(microsecond=0)
    operation_id = BusinessOperationId(command["business_operation_id"])
    precondition = BusinessPreconditionEvidence(
        evidence_id=f"precondition-p8-s86-{operation_id}",
        tenant_id=command["tenant_id"],
        business_operation_id=operation_id,
        write_node_id="write-voucher-draft",
        tool_id="FINANCE.CREATE_VOUCHER_DRAFT",
        contract_hash=contract_hash,
        payload_hash=payload_hash,
        write_intent_hash="sha256:" + "8" * 64,
        mechanism=BusinessPreconditionMechanism.ETAG,
        evidence_ref="etag:opaque:p8-s86",
        observed_at=now,
        expires_at=now + timedelta(hours=1),
        provider_atomic_enforcement=True,
    )
    return WriteCallRequest(
        tenant_id=command["tenant_id"],
        execution_id=f"nsl-execution-p8-s86-{operation_id}",
        business_operation_id=operation_id,
        invocation_id=f"invocation-p8-s86-{operation_id}",
        node_id="write-voucher-draft",
        tool_ref=tool_ref,
        tool_id="FINANCE.CREATE_VOUCHER_DRAFT",
        contract_hash=contract_hash,
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
    parser.add_argument("--nsl-source", required=True, type=Path)
    args = parser.parse_args()
    sys.path[:0] = [str(args.wheel), str(args.ae_source), str(args.shared_source)]
    payload = json.load(sys.stdin)
    print(
        json.dumps(
            run_worker(payload, args.readiness, args.nsl_source),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
