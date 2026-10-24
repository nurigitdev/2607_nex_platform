#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "_shared",
    ROOT / "services" / "nex-ae-api",
    ROOT / "services" / "nex-eos",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

from nex_ae_api.golden_a_planning import build_golden_a_canonical_write_payload
from nex_ae_api.nsl_approval_evidence import project_nsl_approval_evidence
from nex_ae_api.nsl_controlled_write_integration import (
    NslControlledWriteIntegration,
    NslControlledWriteRequest,
)
from nex_ae_api.nsl_eos_post_write_verification import (
    HttpEosPostWriteVerificationAdapter,
)
from nex_ae_api.nsl_eos_reconciliation import HttpEosReconciliationAdapter
from nex_ae_api.nsl_eos_write_execution import HttpEosWriteExecutionPort
from nex_ae_api.nsl_idempotency import SqlAlchemyNslIdempotencyEvidencePort
from nex_ae_api.nsl_runtime_policy import PlatformRuntimePolicyAdapter
from nex_ae_api.nsl_v02_public_api import load_nsl_v02_public_api
from nex_ae_api.nsl_write_evidence import SqlAlchemyNslWriteEvidencePort
from nex_eos import HttpOaAuthorizationSource
from nex_runtime.nsl_package_admission import inspect_installed_nsl_package
from nex_runtime.semantic_hashes import (
    nsl_write_payload_hash_ref,
    semantic_sha256_hash_ref,
)
from p8_golden_a_fixture import load_golden_a_fixture
from p8_reliability_faults import EosCommitAckLossFaultPort

AE_DATABASE_ENV = "NEX_P8_S66_WORKER_AE_DATABASE_URL"
OA_BASE_URL_ENV = "NEX_P8_S66_WORKER_OA_BASE_URL"
EOS_BASE_URL_ENV = "NEX_P8_S66_WORKER_EOS_BASE_URL"
AE_TO_OA_TOKEN_ENV = "NEX_P8_S66_WORKER_AE_TO_OA_SERVICE_TOKEN"
AE_TO_EOS_TOKEN_ENV = "NEX_P8_S66_WORKER_AE_TO_EOS_SERVICE_TOKEN"


class P8S66WorkerError(RuntimeError):
    pass


class _GovernedWriteSource:
    def __init__(
        self,
        *,
        authorization_source: HttpOaAuthorizationSource,
        fixture: Mapping[str, Any],
        platform_evidence: Mapping[str, Any],
        evaluated_at: datetime,
    ) -> None:
        self._authorization_source = authorization_source
        self._fixture = fixture
        self._evidence = platform_evidence
        self._evaluated_at = evaluated_at
        self.calls = 0

    def resolve(self, request: Any) -> dict[str, Any]:
        self.calls += 1
        authorization = self._authorization_source.effective_authorization(
            tenant_id=request.tenant_id,
            subject_id=request.subject_id,
        )
        if "finance:voucher-draft:create" not in authorization.get("scopes", ()):
            raise P8S66WorkerError("OA denied Golden A governed WRITE authority")
        descriptor = {
            "tenant_id": request.tenant_id,
            "agent_execution_id": self._evidence["agent_execution_id"],
            "executable_step_id": self._evidence["executable_step_id"],
            "business_operation_id": str(request.business_operation_id),
            "actor_ref": request.subject_id,
            "agent_ref": self._fixture["admission"]["agent_id"],
            "org_scope_refs": [self._fixture["approval_target"]["org_unit_id"]],
            "project_ref": self._fixture["projects"]["child"]["project_id"],
            "resource_refs": [f"voucher_draft:{request.business_operation_id}"],
            "capability": "WRITE",
            "operation_class": "CREATE",
            "data_classification": "CONFIDENTIAL",
            "typed_parameters": {"voucher_type": "GENERAL"},
            "business_object_type": "VOUCHER_DRAFT",
        }
        descriptor["operation_fingerprint"] = semantic_sha256_hash_ref(descriptor)
        decision_hash = semantic_sha256_hash_ref(
            {
                "descriptor": descriptor,
                "authorization_revision_hash": authorization["revision_hash"],
            }
        )
        return {
            "tenant_id": request.tenant_id,
            "business_operation_id": str(request.business_operation_id),
            "oa_decision_ref": f"oa-authz:{authorization['revision_hash']}",
            "oa_allowed": True,
            "protected_operation": descriptor,
            "operation_trust_decision": {
                "decision": "ALLOW",
                "decision_mode": "RULE_EVALUATED",
                "assurance_level": "HIGH",
                "operation_fingerprint": descriptor["operation_fingerprint"],
                "rule_set_ref": "policy:golden-a-governed-write",
                "rule_set_version": "1",
                "facts_hash": semantic_sha256_hash_ref(authorization),
                "proof_ref": f"oa-revision:{authorization['revision_hash']}",
                "reason_code": None,
                "decision_hash": decision_hash,
                "evaluated_at": _time(self._evaluated_at),
                "expires_at": _time(self._evaluated_at + timedelta(minutes=10)),
            },
            "required_assurance_level": "HIGH",
        }


def run_worker(args: argparse.Namespace) -> dict[str, Any]:
    from nsl.cli import _load_program
    from nsl.cli_config import load_tool_catalog
    from nsl.core import (
        STRING,
        ApprovalRequestId,
        ApprovalStatus,
        BusinessOperationId,
        DataClassification,
        ValueEnvelope,
        VerificationStatus,
    )
    from nsl.runtime_models import ExecutionContext, ExecutionRequest, ValidationSummary
    from nsl.security import ExecutionPrincipal, PrincipalVerification
    from nsl.validation import (
        BusinessPreconditionEvidence,
        BusinessPreconditionMechanism,
        PreWriteEvidence,
        WriteContractEvidence,
    )
    from nsl.write_intent import (
        WriteIntent,
        compute_payload_hash,
        compute_write_intent_hash,
    )

    runtime = _runtime_environment()
    evidence = _load_evidence(args.approval_evidence)
    fixture = load_golden_a_fixture()
    tenant_id = fixture["tenant"]["tenant_id"]
    requester_id = fixture["scenario"]["requester_subject_id"]
    platform_evidence = evidence["platform_approval_evidence"]
    write_identity = evidence["write_identity"]
    expected_hash = evidence["expected_payload_hash"]
    payload = build_golden_a_canonical_write_payload(fixture)
    if nsl_write_payload_hash_ref(payload) != expected_hash:
        raise P8S66WorkerError("approved Golden A payload hash changed")

    lock = json.loads(args.lock.read_text(encoding="utf-8"))
    readiness = inspect_installed_nsl_package(
        lock,
        platform_lock_path=args.platform_lock,
    )
    public_api = load_nsl_v02_public_api(readiness)
    example = args.source / "examples/golden_a_voucher_draft"
    catalog = load_tool_catalog(example / "tools.json")
    skill = _load_program(example / "golden_a_voucher_draft.ns", catalog)
    contract = catalog.resolve(
        fixture["admission"]["tool_id"],
        fixture["admission"]["exact_skill_version"],
    )
    required_tool = next(
        item for item in skill.required_tools if item.tool_id == contract.tool_id
    )
    principal_record = next(
        item for item in fixture["principals"] if item["subject_id"] == requester_id
    )
    principal = ExecutionPrincipal(
        tenant_id=tenant_id,
        subject_id=requester_id,
        actor_type="USER",
        roles=frozenset(principal_record["roles"]),
        scopes=frozenset(principal_record["scopes"]),
        auth_context_ref=f"oa-golden-a:{requester_id}",
        verification=PrincipalVerification.VERIFIED,
    )
    context = ExecutionContext(
        skill,
        ExecutionRequest(
            execution_id=platform_evidence["nsl_execution_id"],
            inputs={},
            runtime_context={},
            principal=principal,
            business_operation_id=BusinessOperationId(
                platform_evidence["business_operation_id"]
            ),
        ),
    )
    arguments = {
        name: ValueEnvelope.complete(value, STRING) for name, value in payload.items()
    }
    payload_hash = compute_payload_hash(arguments)
    intent_hash = compute_write_intent_hash(
        skill_semantic_hash=skill.semantic_hash,
        write_node_id=write_identity["write_node_id"],
        tool_id=contract.tool_id,
        payload_hash=payload_hash,
    )
    intent = WriteIntent(
        tenant_id=tenant_id,
        business_operation_id=context.identity.business_operation_id,
        node_id=write_identity["write_node_id"],
        tool_ref=required_tool.tool_ref,
        tool_id=contract.tool_id,
        approval_id=write_identity["approval_id"],
        skill_semantic_hash=skill.semantic_hash,
        canonical_arguments=arguments,
        payload_hash=payload_hash,
        write_intent_hash=intent_hash,
    )
    approval_evidence = project_nsl_approval_evidence(
        platform_evidence,
        approval_evidence_type=public_api.approval_evidence,
    )
    now = datetime.now(UTC).replace(microsecond=0)
    contract_evidence = WriteContractEvidence(
        tool_id=contract.tool_id,
        contract_hash=contract.contract_hash,
        capability=contract.capability,
        risk_level=contract.risk_level,
        preconditions_supported=True,
    )
    precondition = BusinessPreconditionEvidence(
        evidence_id=f"golden-a-fixture:{fixture['fixture_hash']}",
        tenant_id=tenant_id,
        business_operation_id=context.identity.business_operation_id,
        write_node_id=intent.node_id,
        tool_id=intent.tool_id,
        contract_hash=contract.contract_hash,
        payload_hash=payload_hash,
        write_intent_hash=intent_hash,
        mechanism=BusinessPreconditionMechanism.ETAG,
        evidence_ref=f"fixture:{fixture['fixture_hash']}",
        observed_at=now - timedelta(seconds=1),
        expires_at=now + timedelta(minutes=10),
        provider_atomic_enforcement=True,
    )
    execution_evidence = PreWriteEvidence(
        validation=ValidationSummary.from_checks(tuple(context.checks)),
        approval_status=ApprovalStatus.APPROVED,
        approval_evidence_valid=True,
        runtime_preflight_passed=True,
        current_policy_allowed=False,
        tool_preconditions_passed=False,
        business_preconditions_passed=False,
        intent_binding_valid=True,
        idempotency_ready=True,
        durability_ready=True,
        trust_valid=True,
        replay_live_write_allowed=True,
    )
    provider_evidence = public_api.provider_idempotency_evidence(
        tool_id=contract.tool_id,
        contract_hash=contract.contract_hash,
        retention_policy="PROVIDER_DEFINED",
        provider_guarantee_ref="eos:idempotency:golden-a",
        verified_at=now - timedelta(seconds=1),
        guaranteed_until=now + timedelta(days=30),
        durable_duplicate_guarantee=True,
    )
    request = NslControlledWriteRequest(
        intent=intent,
        context=context,
        contract=contract,
        contract_evidence=contract_evidence,
        execution_evidence=execution_evidence,
        business_preconditions=precondition,
        approval_evidence=approval_evidence,
        approval_request_id=ApprovalRequestId(platform_evidence["approval_request_id"]),
        provider_idempotency_evidence=provider_evidence,
        invocation_id=f"p8-s66-{uuid4().hex}",
        trace_refs=(
            f"trace_id:{uuid4().hex}",
            f"correlation_id:{platform_evidence['agent_execution_id']}",
            f"causation_id:{platform_evidence['approval_request_id']}",
        ),
        evaluated_at=now,
        required_until=now + timedelta(days=7),
        requested_at=now,
    )
    governed_source = _GovernedWriteSource(
        authorization_source=HttpOaAuthorizationSource(
            base_url=runtime[OA_BASE_URL_ENV],
            service_token=runtime[AE_TO_OA_TOKEN_ENV],
        ),
        fixture=fixture,
        platform_evidence=platform_evidence,
        evaluated_at=now,
    )
    engine = create_engine(runtime[AE_DATABASE_ENV], poolclass=NullPool)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        verification_port = HttpEosPostWriteVerificationAdapter(
            public_api=public_api,
            base_url=runtime[EOS_BASE_URL_ENV],
            service_token=runtime[AE_TO_EOS_TOKEN_ENV],
        )
        normal_write_port = HttpEosWriteExecutionPort(
            public_api=public_api,
            base_url=runtime[EOS_BASE_URL_ENV],
            service_token=runtime[AE_TO_EOS_TOKEN_ENV],
            result_type=contract.output_type,
            result_classification=DataClassification.CONFIDENTIAL,
        )

        def integration(write_port: object) -> NslControlledWriteIntegration:
            return NslControlledWriteIntegration(
                public_api=public_api,
                policy_port=PlatformRuntimePolicyAdapter(
                    authorization_source=governed_source,
                    public_api=public_api,
                ),
                idempotency_port=SqlAlchemyNslIdempotencyEvidencePort(
                    factory, public_api=public_api, clock=lambda: now
                ),
                write_evidence_port=SqlAlchemyNslWriteEvidencePort(
                    factory, public_api=public_api, clock=lambda: now
                ),
                write_port=write_port,
                verification_port=verification_port,
            )

        variants: dict[str, Any] | None = None
        if args.exactly_once_variants:
            ack_loss_port = EosCommitAckLossFaultPort(normal_write_port, public_api)
            ack_loss = asyncio.run(integration(ack_loss_port).execute(request))
            if not isinstance(ack_loss.outcome, public_api.write_commit_unknown):
                raise P8S66WorkerError(
                    "ACK-loss variant did not produce UNKNOWN_COMMIT_STATE"
                )
            reconciled = asyncio.run(
                HttpEosReconciliationAdapter(
                    public_api=public_api,
                    base_url=runtime[EOS_BASE_URL_ENV],
                    service_token=runtime[AE_TO_EOS_TOKEN_ENV],
                    result_type=contract.output_type,
                    result_classification=DataClassification.CONFIDENTIAL,
                ).reconcile(ack_loss.write_request, ack_loss.outcome)
            )
            if not isinstance(reconciled, public_api.write_committed):
                raise P8S66WorkerError(
                    "ACK-loss reconciliation did not confirm COMMITTED"
                )
            worker_retry = asyncio.run(
                integration(normal_write_port).execute(
                    replace(request, invocation_id=f"p8-s67-worker-{uuid4().hex}")
                )
            )
            publication_retry = asyncio.run(
                integration(normal_write_port).execute(
                    replace(request, invocation_id=f"p8-s67-publication-{uuid4().hex}")
                )
            )
            for label, candidate in (
                ("AE worker retry", worker_retry),
                ("result publication retry", publication_retry),
            ):
                if not isinstance(candidate.outcome, public_api.write_committed):
                    raise P8S66WorkerError(f"{label} did not preserve COMMITTED")
                if candidate.verification.status is not VerificationStatus.VERIFIED:
                    raise P8S66WorkerError(f"{label} did not preserve VERIFIED")
                if candidate.reservation.disposition.value != "REUSED":
                    raise P8S66WorkerError(
                        f"{label} did not reuse idempotency evidence"
                    )
            result = publication_retry
            variants = {
                "ack_loss_after_commit": {
                    "response_status_discarded": ack_loss_port.response_status,
                    "observed_commit_state": ack_loss.outcome.commit_state.value,
                    "reconciled_commit_state": reconciled.commit_state.value,
                },
                "ae_worker_retry": {
                    "reservation": worker_retry.reservation.disposition.value,
                    "commit_state": worker_retry.outcome.commit_state.value,
                    "verification_status": worker_retry.verification.status.value,
                },
                "result_publication_retry": {
                    "reservation": publication_retry.reservation.disposition.value,
                    "commit_state": publication_retry.outcome.commit_state.value,
                    "verification_status": publication_retry.verification.status.value,
                },
            }
        else:
            result = asyncio.run(integration(normal_write_port).execute(request))
    finally:
        engine.dispose()

    if not isinstance(result.outcome, public_api.write_committed):
        raise P8S66WorkerError("Golden A EOS outcome was not COMMITTED")
    if result.verification.status is not VerificationStatus.VERIFIED:
        verification_request = public_api.post_write_verifier._request(
            result.outcome.result,
            contract.write_semantics.verification,
        )
        try:
            asyncio.run(verification_port.read(verification_request))
        except Exception as exc:  # noqa: BLE001 - protected diagnostic boundary.
            diagnostic = (
                f"{type(exc).__name__}:"
                f"{getattr(exc, 'error_code', 'unknown')}:{exc}"
            )
        else:
            diagnostic = "adapter returned without an exception"
        raise P8S66WorkerError(
            "Golden A EOS read-back was not VERIFIED: "
            f"status={result.verification.status.value}, "
            f"reason={result.verification.reason_code}, detail={diagnostic}"
        )
    output = {
        "schema_version": "p8_s66_eos_commit_worker.v1",
        "status": "PASS",
        "release_admission_hash": public_api.release_admission_hash,
        "skill": {
            "skill_id": skill.skill_id,
            "skill_version": skill.skill_version,
            "semantic_hash": skill.semantic_hash,
        },
        "payload_hash": str(payload_hash),
        "write_request_payload_hash": str(result.write_request.payload_hash),
        "outcome_payload_hash": str(result.outcome.identity.payload_hash),
        "verification_payload_hash": str(result.verification.identity.payload_hash),
        "business_operation_id": str(result.write_request.business_operation_id),
        "approval_request_id": str(result.write_request.approval_request_id),
        "commit_state": result.outcome.commit_state.value,
        "voucher_ref": result.outcome.result.business_reference,
        "verification_status": result.verification.status.value,
        "verification_evidence_ref": result.verification.evidence_ref,
        "fresh_oa_runtime_policy_calls": governed_source.calls,
        "expected_write_evidence_count": 3 if variants is not None else 1,
    }
    if variants is not None:
        output["retry_variants"] = variants
    return output


def _runtime_environment() -> dict[str, str]:
    values = {
        name: os.getenv(name, "")
        for name in (
            AE_DATABASE_ENV,
            OA_BASE_URL_ENV,
            EOS_BASE_URL_ENV,
            AE_TO_OA_TOKEN_ENV,
            AE_TO_EOS_TOKEN_ENV,
        )
    }
    missing = sorted(name for name, value in values.items() if not value.strip())
    if missing:
        raise P8S66WorkerError(
            f"P8-S66 worker environment is incomplete: {', '.join(missing)}"
        )
    return values


def _load_evidence(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise P8S66WorkerError("P8-S66 approval evidence is invalid")
    required = {
        "platform_approval_evidence",
        "write_identity",
        "expected_payload_hash",
    }
    if set(value) != required or not all(
        isinstance(value[name], Mapping)
        for name in ("platform_approval_evidence", "write_identity")
    ):
        raise P8S66WorkerError("P8-S66 approval evidence fields are invalid")
    return dict(value)


def _time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--lock", required=True, type=Path)
    parser.add_argument("--platform-lock", required=True, type=Path)
    parser.add_argument("--approval-evidence", required=True, type=Path)
    parser.add_argument("--exactly-once-variants", action="store_true")
    print(json.dumps(run_worker(parser.parse_args()), sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
