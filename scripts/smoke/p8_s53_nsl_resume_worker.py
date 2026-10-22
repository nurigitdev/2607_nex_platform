#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nex_ae_api.nsl_approval_evidence import PlatformApprovalEvidenceVerifier
from nex_ae_api.nsl_approval_requests import SqlAlchemyProtectedApprovalRequestStore
from nex_ae_api.nsl_approval_resume import SqlAlchemyNslApprovalResumeSource
from nex_ae_api.nsl_approval_resume_integration import NslApprovalResumeIntegration
from nex_ae_api.nsl_v02_public_api import load_nsl_v02_public_api
from nex_ae_api.platform_approval_evidence import (
    SqlAlchemyPlatformApprovalEvidenceRepository,
)
from nex_ae_api.runtime_jobs import SqlAlchemyRuntimeJobQueue
from nex_runtime.nsl_package_admission import inspect_installed_nsl_package
from nex_wc.approvals import SqlAlchemyApprovalWorkItemRepository
from nsl.cli import _load_program
from nsl.cli_config import load_principal, load_tool_catalog, load_value_object
from nsl.cli_controlled import FileControlledStatePort, load_approval_request
from nsl.cli_profile import resolve_cli_configuration
from nsl.cli_runtime import build_execution_request
from nsl.core import BusinessOperationId
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool


@dataclass(frozen=True)
class _RecordedClock:
    recorded_at: datetime

    def now(self) -> datetime:
        return self.recorded_at


class _WcAuthoritySource:
    def __init__(self, repository: SqlAlchemyApprovalWorkItemRepository) -> None:
        self._repository = repository

    def resolve(
        self, *, tenant_id: str, approval_work_item_ref: str
    ) -> Mapping[str, Any]:
        return {
            "work_item": self._repository.get(
                tenant_id=tenant_id,
                approval_work_item_id=approval_work_item_ref,
            ),
            "decision": self._repository.get_decision(
                tenant_id=tenant_id,
                approval_work_item_id=approval_work_item_ref,
            ),
        }


class _OaAuthoritySource:
    def __init__(self, *, decision_ref: str, revision_hash: str) -> None:
        self._decision_ref = decision_ref
        self._revision_hash = revision_hash

    def effective_authorization(
        self, *, tenant_id: str, subject_id: str
    ) -> Mapping[str, Any]:
        return {
            "active": True,
            "tenant_id": tenant_id,
            "subject_id": subject_id,
            "scopes": ["approval:decide"],
            "roles": [],
            "revision_hash": self._revision_hash,
            "decision_ref": self._decision_ref,
        }


def run_resume(args: argparse.Namespace) -> dict[str, Any]:
    lock = json.loads(args.lock.read_text(encoding="utf-8"))
    readiness = inspect_installed_nsl_package(
        lock,
        platform_lock_path=args.platform_lock,
    )
    public_api = load_nsl_v02_public_api(readiness)
    configuration = resolve_cli_configuration(profile_path=args.profile)
    catalog = load_tool_catalog(configuration.tool_contracts)
    skill = _load_program(configuration.program, catalog)
    principal = load_principal(configuration.principal)
    inputs = (
        None
        if configuration.input is None
        else load_value_object(configuration.input, "input")
    )
    runtime_context = (
        None
        if configuration.context is None
        else load_value_object(configuration.context, "context")
    )
    approval_request = load_approval_request(args.approval_request)
    request = build_execution_request(
        principal,
        approval_request.execution_id,
        inputs=inputs,
        runtime_context=runtime_context,
        business_operation_id=BusinessOperationId(
            approval_request.business_operation_id
        ),
    )
    observed_at = _instant(args.observed_at)

    ae_engine = create_engine(args.ae_database_url, poolclass=NullPool)
    wc_engine = create_engine(args.wc_database_url, poolclass=NullPool)
    ae_factory = sessionmaker(bind=ae_engine, expire_on_commit=False)
    wc_factory = sessionmaker(bind=wc_engine, expire_on_commit=False)
    try:
        jobs = SqlAlchemyRuntimeJobQueue(ae_factory)
        claim = jobs.claim(
            tenant_id=args.tenant_id,
            worker_id=args.worker_id,
            lease_seconds=60,
            now=_time(observed_at),
        )
        if claim is None:
            raise RuntimeError("P8-S53 resume RuntimeJob is not claimable")
        evidence_repository = SqlAlchemyPlatformApprovalEvidenceRepository(ae_factory)
        evidence = evidence_repository.get(
            tenant_id=args.tenant_id,
            approval_request_id=str(approval_request.approval_request_id),
        )
        if evidence is None:
            raise RuntimeError("P8-S53 Platform ApprovalEvidence is missing")
        wc_repository = SqlAlchemyApprovalWorkItemRepository(wc_factory)
        decision = wc_repository.get_decision(
            tenant_id=args.tenant_id,
            approval_work_item_id=evidence["approval_work_item_ref"],
        )
        if decision is None:
            raise RuntimeError("P8-S53 WC ApprovalDecision is missing")
        verifier = PlatformApprovalEvidenceVerifier(
            evidence_source=evidence_repository,
            wc_source=_WcAuthoritySource(wc_repository),
            oa_source=_OaAuthoritySource(
                decision_ref=decision["oa_decision_ref"],
                revision_hash=decision["authorization_revision_hash"],
            ),
        )
        invocation = asyncio.run(
            NslApprovalResumeIntegration(
                authority_source=SqlAlchemyNslApprovalResumeSource(ae_factory),
                request_source=SqlAlchemyProtectedApprovalRequestStore(ae_factory),
                evidence_source=evidence_repository,
                public_api=public_api,
            ).resume(
                claim,
                skill=skill,
                request=request,
                checkpoint_port=FileControlledStatePort(
                    args.checkpoint, args.approval_request
                ),
                verifier=verifier,
                clock=_RecordedClock(observed_at),
            )
        )
        outcome = invocation.outcome
        completed = jobs.complete(
            tenant_id=args.tenant_id,
            runtime_job_id=invocation.runtime_job_id,
            worker_id=args.worker_id,
            lease_token=claim.job["lease_token"],
            now=_time(observed_at),
        )
        return {
            "schema_version": "p8_s53_nsl_resume_worker.v1",
            "status": "PASS",
            "release_admission_hash": public_api.release_admission_hash,
            "runtime_job_id": invocation.runtime_job_id,
            "runtime_job_state": completed["state"],
            "claim_id": invocation.claim_id,
            "nsl_execution_id": invocation.nsl_execution_id,
            "business_operation_id": invocation.business_operation_id,
            "checkpoint_version": invocation.checkpoint_version,
            "approval_request_id": invocation.approval_request_id,
            "approval_validation": outcome.validation.validation.value,
            "approval_status": outcome.validation.approval_status.value,
            "reason_code": outcome.validation.reason_code,
            "approval_gate_passed": outcome.validation.approval_gate_passed,
            "claim_consumed": outcome.claim_consumed,
            "checkpoint_consumed": args.checkpoint.with_name(
                f"{args.checkpoint.name}.consumed"
            ).is_file(),
            "write_execution": "not_started",
            "eos_mutation_count": 0,
        }
    finally:
        ae_engine.dispose()
        wc_engine.dispose()


def _instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("observed_at must include a timezone")
    return parsed.astimezone(UTC)


def _time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ae-database-url", required=True)
    parser.add_argument("--wc-database-url", required=True)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--worker-id", required=True)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--approval-request", required=True, type=Path)
    parser.add_argument("--observed-at", required=True)
    parser.add_argument("--lock", required=True, type=Path)
    parser.add_argument("--platform-lock", required=True, type=Path)
    result = run_resume(parser.parse_args())
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
