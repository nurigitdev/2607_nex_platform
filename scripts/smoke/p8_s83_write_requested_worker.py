#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

CRASH_EXIT_CODE = 83


class P8S83WorkerError(RuntimeError):
    pass


def run_phase(args: argparse.Namespace, payload: dict[str, Any]) -> dict[str, Any]:
    from nex_ae_api.nsl_eos_reconciliation import HttpEosReconciliationAdapter
    from nex_ae_api.nsl_eos_write_execution import HttpEosWriteExecutionPort
    from nex_ae_api.nsl_v02_public_api import load_nsl_v02_public_api
    from nex_ae_api.nsl_write_evidence import SqlAlchemyNslWriteEvidencePort
    from nsl.core import STRING, DataClassification
    from p8_reliability_faults import (
        WorkerCrashAfterWriteRequestedFaultError,
        WorkerCrashAfterWriteRequestedFaultPort,
        WorkerRestartAfterWriteRequestedRecovery,
    )
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import NullPool

    command = payload.get("command")
    if not isinstance(command, dict):
        raise P8S83WorkerError("P8-S83 command must be an object.")
    requested_at = _utc(payload.get("requested_at"))
    readiness = json.loads(args.readiness.read_text(encoding="utf-8"))["readiness"]
    public_api = load_nsl_v02_public_api(readiness)
    request = _write_request(command, requested_at)
    record = public_api.write_attempt_record.from_request(request, requested_at)
    engine = create_engine(args.ae_database_url, poolclass=NullPool)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    evidence_port = SqlAlchemyNslWriteEvidencePort(
        factory,
        public_api=public_api,
        clock=lambda: requested_at + timedelta(seconds=1),
    )

    def load_evidence(candidate: object) -> object:
        return evidence_port.get(
            tenant_id=str(candidate.tenant_id),
            nsl_execution_id=str(candidate.execution_id),
            invocation_id=str(candidate.invocation_id),
        )

    try:
        if args.phase == "crash":
            receipt = asyncio.run(evidence_port.record_requested(record))
            delegate = HttpEosWriteExecutionPort(
                public_api=public_api,
                base_url=args.eos_base_url,
                service_token=args.service_token,
                result_type=STRING,
                result_classification=DataClassification.CONFIDENTIAL,
            )
            fault = WorkerCrashAfterWriteRequestedFaultPort(
                delegate,
                load_evidence,
                public_api,
            )
            try:
                asyncio.run(fault.execute(request))
            except WorkerCrashAfterWriteRequestedFaultError:
                fault_evidence = asdict(fault.evidence)
            else:
                raise P8S83WorkerError("P8-S83 crash fault did not stop the worker.")
            return {
                "schema_version": "p8_s83_write_requested_worker.v1",
                "phase": "crash",
                "status": "CRASHED",
                "process_exit_code": CRASH_EXIT_CODE,
                "receipt": {
                    "record_hash": str(receipt.record_hash),
                    "durable_ref": str(receipt.durable_ref),
                    "durable": receipt.durable,
                },
                "fault": fault_evidence,
            }

        recovery = WorkerRestartAfterWriteRequestedRecovery(
            HttpEosReconciliationAdapter(
                public_api=public_api,
                base_url=args.eos_base_url,
                service_token=args.service_token,
                result_type=STRING,
                result_classification=DataClassification.CONFIDENTIAL,
            ),
            load_evidence,
            public_api,
        )
        outcome = asyncio.run(recovery.recover(request))
        result = getattr(outcome, "result", None)
        return {
            "schema_version": "p8_s83_write_requested_worker.v1",
            "phase": "recover",
            "status": "PASS",
            "commit_state": outcome.commit_state.value,
            "business_reference": getattr(result, "business_reference", None),
            "recovery": asdict(recovery.evidence),
        }
    finally:
        engine.dispose()


def _write_request(command: dict[str, Any], requested_at: datetime) -> Any:
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
    try:
        business_payload["description_text"] = business_payload.pop("description")
        trace = command["trace"]
    except (KeyError, TypeError) as exc:
        raise P8S83WorkerError("P8-S83 command fields are incomplete.") from exc
    arguments = {
        key: ValueEnvelope.complete(value, STRING)
        for key, value in business_payload.items()
    }
    payload_hash = compute_payload_hash(arguments)
    if str(payload_hash) != command.get("payload_hash"):
        raise P8S83WorkerError("NSL and EOS payload hashes differ.")
    operation_id = BusinessOperationId(command["business_operation_id"])
    precondition_id = f"precondition-p8-s83-{operation_id}"
    precondition = BusinessPreconditionEvidence(
        evidence_id=precondition_id,
        tenant_id=command["tenant_id"],
        business_operation_id=operation_id,
        write_node_id="write-voucher-draft",
        tool_id="FINANCE.CREATE_VOUCHER_DRAFT",
        contract_hash="sha256:" + "6" * 64,
        payload_hash=payload_hash,
        write_intent_hash="sha256:" + "8" * 64,
        mechanism=BusinessPreconditionMechanism.ETAG,
        evidence_ref="etag:opaque:p8-s83",
        observed_at=requested_at,
        expires_at=requested_at + timedelta(hours=1),
        provider_atomic_enforcement=True,
    )
    return WriteCallRequest(
        tenant_id=command["tenant_id"],
        execution_id=f"nsl-execution-p8-s83-{operation_id}",
        business_operation_id=operation_id,
        invocation_id=f"invocation-p8-s83-{operation_id}",
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
        trace_refs=tuple(f"{key}:{value}" for key, value in trace.items()),
    )


def _utc(value: object) -> datetime:
    if not isinstance(value, str):
        raise P8S83WorkerError("P8-S83 requested_at must be a UTC timestamp.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise P8S83WorkerError("P8-S83 requested_at must be a UTC timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise P8S83WorkerError("P8-S83 requested_at must use UTC.")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("crash", "recover"), required=True)
    parser.add_argument("--wheel", required=True, type=Path)
    parser.add_argument("--readiness", required=True, type=Path)
    parser.add_argument("--ae-source", required=True, type=Path)
    parser.add_argument("--shared-source", required=True, type=Path)
    parser.add_argument("--smoke-source", required=True, type=Path)
    parser.add_argument("--ae-database-url", required=True)
    parser.add_argument("--eos-base-url", required=True)
    parser.add_argument("--service-token", required=True)
    args = parser.parse_args()
    sys.path[:0] = [
        str(args.wheel),
        str(args.ae_source),
        str(args.shared_source),
        str(args.smoke_source),
    ]
    payload = json.load(sys.stdin)
    result = run_phase(args, payload)
    print(json.dumps(result, sort_keys=True), flush=True)
    return CRASH_EXIT_CODE if args.phase == "crash" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
