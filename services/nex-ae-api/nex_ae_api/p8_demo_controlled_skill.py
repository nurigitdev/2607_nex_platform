from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import quote

import httpx
from nex_runtime.demo_fixture import load_demo_business_fixture
from nex_runtime.demo_nsl_bundle import (
    DemoNslRuntimeBundle,
    load_demo_nsl_runtime_bundle,
    verify_demo_nsl_runtime_bundle,
)
from nex_runtime.demo_nsl_runtime_adapter import (
    DemoNslRuntimeAdapterError as P8DemoControlledSkillError,
)
from nex_runtime.demo_nsl_runtime_adapter import (
    InstalledDemoNslExecution as _InstalledSkillExecution,
)
from nex_runtime.demo_nsl_runtime_adapter import (
    InstalledDemoNslPackage as _InstalledDemoSkillPackage,
)
from nex_runtime.nsl_package_admission import inspect_installed_nsl_package
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from nex_ae_api.delegated_work import SqlAlchemyWaitRegistrationRepository
from nex_ae_api.golden_a_planning import build_golden_a_canonical_write_payload
from nex_ae_api.multi_step_engine import StepExecutionContext
from nex_ae_api.nsl_approval_evidence import (
    PersistedApprovalEventAuthoritySource,
    PlatformApprovalEvidenceVerifier,
)
from nex_ae_api.nsl_approval_publication import (
    NSL_APPROVAL_RESUME_CONTRACT_REF,
    P8NSLApprovalPort,
    build_default_wc_approval_work_item_client,
    deterministic_approval_work_item_id,
)
from nex_ae_api.nsl_approval_requests import SqlAlchemyProtectedApprovalRequestStore
from nex_ae_api.nsl_approval_resume import SqlAlchemyNslApprovalResumeSource
from nex_ae_api.nsl_approval_resume_integration import NslApprovalResumeIntegration
from nex_ae_api.nsl_controlled_write_integration import (
    NslControlledWriteIntegration,
    NslControlledWriteRequest,
)
from nex_ae_api.nsl_eos_post_write_verification import (
    HttpEosPostWriteVerificationAdapter,
)
from nex_ae_api.nsl_eos_write_execution import HttpEosWriteExecutionPort
from nex_ae_api.nsl_idempotency import SqlAlchemyNslIdempotencyEvidencePort
from nex_ae_api.nsl_runtime_policy import PlatformRuntimePolicyAdapter
from nex_ae_api.nsl_step_executions import (
    SqlAlchemyNSLStepExecutionRepository,
    build_context_projection,
)
from nex_ae_api.nsl_v02_public_api import load_nsl_v02_public_api
from nex_ae_api.nsl_write_evidence import SqlAlchemyNslWriteEvidencePort
from nex_ae_api.platform_approval_evidence import (
    SqlAlchemyPlatformApprovalEvidenceRepository,
)
from nex_ae_api.service_auth import resolve_ae_outbound_service_token
from nex_ae_api.skill_artifacts import (
    SkillArtifactGateway,
    SqlAlchemySkillArtifactRepository,
)
from nex_ae_api.step_executors import (
    LocalSkillExecutorDependencies,
    P5ExecutorOutcome,
    P5StepExecutorError,
)

P8_DEMO_RESULT_CONTRACT = "contract://nex/eos/create-voucher-draft-result/v1"


@dataclass(frozen=True)
class P8DemoControlledSkillConfig:
    manifest_path: Path
    wheel_path: Path
    platform_lock_path: Path
    skill_root: Path
    demo_fixture_path: Path
    base_fixture_path: Path
    state_root: Path
    oa_base_url: str
    eos_base_url: str
    ae_to_oa_service_token: str
    ae_to_eos_service_token: str


class P8DemoControlledSkillRuntime:
    """Installed composition for the admitted Golden A controlled WRITE Skill."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        config: P8DemoControlledSkillConfig,
    ) -> None:
        self._sessions = session_factory
        self._config = config
        self._bundle = load_demo_nsl_runtime_bundle(config.manifest_path)
        self.bundle_readiness = verify_demo_nsl_runtime_bundle(
            self._bundle,
            wheel_path=config.wheel_path,
            skill_root=config.skill_root,
            demo_fixture_path=config.demo_fixture_path,
            base_fixture_path=config.base_fixture_path,
        )
        admission_lock = _json_object(
            _resolve_admission_lock(config.manifest_path, self._bundle)
        )
        readiness = inspect_installed_nsl_package(
            admission_lock,
            platform_lock_path=config.platform_lock_path,
        )
        self.package_readiness = readiness
        self.public_api = load_nsl_v02_public_api(readiness)
        _, self.fixture = load_demo_business_fixture(
            config.demo_fixture_path,
            base_fixture_path=config.base_fixture_path,
        )
        self._package = _InstalledDemoSkillPackage(
            self._bundle,
            config.skill_root,
            self.fixture,
            config.state_root,
        )
        self._evidence = SqlAlchemyPlatformApprovalEvidenceRepository(session_factory)
        self._request_store = SqlAlchemyProtectedApprovalRequestStore(session_factory)

    @property
    def backend_profile(self) -> str:
        return "NSL_V02_IN_PROCESS"

    def execute(self, **_values: Any) -> dict[str, Any]:
        """Fail closed when bypassing the continuation-aware Skill handlers."""

        raise P8DemoControlledSkillError(
            "Controlled NSL execution requires the installed initial/resume handlers."
        )

    @property
    def dependencies(self) -> LocalSkillExecutorDependencies:
        artifacts = SqlAlchemySkillArtifactRepository(self._sessions)
        gateway = SkillArtifactGateway(
            resolver=_BundleResolver(self._bundle),
            admission_source=_BundleAdmissionSource(self._bundle),
            repository=artifacts,
        )
        return LocalSkillExecutorDependencies(
            artifact_gateway=gateway,
            binding_repository=SqlAlchemyNSLStepExecutionRepository(self._sessions),
            request_builder=lambda **_kwargs: {},
            backend=self,
            result_mapper=lambda value: value,
        )

    def initial(
        self,
        context: StepExecutionContext,
        dependencies: LocalSkillExecutorDependencies,
    ) -> P5ExecutorOutcome:
        try:
            now = _utc_now()
            binding = context.step["skill_binding"]
            artifact = dependencies.artifact_gateway.resolve_verified(
                tenant_id=context.job["tenant_id"],
                skill_id=binding["skill_id"],
                exact_version=binding["exact_skill_version"],
                expected_semantic_hash=binding["skill_semantic_hash"],
                runtime_contract_ref=binding["runtime_contract_ref"],
                trust_policy_id=binding["trust_policy_id"],
                environment="staging",
                observed_at=now,
            )
            projection = _context_projection(
                self._sessions,
                tenant_id=context.job["tenant_id"],
                execution_id=context.step["agent_execution_id"],
                fixture=self.fixture,
            )
            bound = dependencies.binding_repository.bind_request(
                tenant_id=context.job["tenant_id"],
                executable_step_id=context.step["executable_step_id"],
                verified_artifact_ref=artifact["artifact_ref"],
                context_projection=projection,
                compiled_inputs={
                    "canonical_write_payload": build_golden_a_canonical_write_payload(
                        self.fixture
                    )
                },
                input_provenance={"canonical_write_payload": "DEFAULT"},
                now=now,
            )
            skill_binding = bound["binding"]
            execution = self._package.execution(
                tenant_id=context.job["tenant_id"],
                agent_execution_id=context.step["agent_execution_id"],
                executable_step_id=context.step["executable_step_id"],
                nsl_execution_id=skill_binding["nsl_execution_id"],
                business_operation_id=skill_binding["business_operation_id"],
            )
            state_port = _PlatformControlledStatePort(
                execution=execution,
                publication=P8NSLApprovalPort(
                    binding_source=_ApprovalBindingSource(
                        context=context,
                        execution=execution,
                        fixture=self.fixture,
                    ),
                    request_store=self._request_store,
                    wait_repository=SqlAlchemyWaitRegistrationRepository(
                        self._sessions
                    ),
                    wc_client=build_default_wc_approval_work_item_client(),
                ),
            )
            request = execution.existing_approval_request()
            if request is None:
                session = asyncio.run(execution.start(state_port))
                request = session.approval_request
                checkpoint = session.checkpoint
                if request is None or checkpoint is None:
                    raise P8DemoControlledSkillError(
                        "The admitted NSL Skill did not suspend for approval."
                    )
            else:
                asyncio.run(state_port.publish_platform(request))
            wait_id = _approval_wait_id(
                context=context,
                approval_request_id=str(request.approval_request_id),
                checkpoint_version=execution.checkpoint_version,
            )
            return P5ExecutorOutcome(
                state="WAITING",
                result_contract_ref=NSL_APPROVAL_RESUME_CONTRACT_REF,
                result_payload={},
                external_refs=(
                    "WC:APPROVAL_WORK_ITEM:"
                    + deterministic_approval_work_item_id(
                        tenant_id=context.job["tenant_id"],
                        approval_request_id=str(request.approval_request_id),
                    ),
                ),
                evidence_refs=(
                    f"AE:NSL_APPROVAL_REQUEST:{request.approval_request_id}",
                ),
                business_operation_id=skill_binding["business_operation_id"],
                wait_id=wait_id,
                wait_external_ref=str(request.approval_request_id),
            )
        except P5StepExecutorError:
            raise
        except Exception as exc:
            raise P5StepExecutorError(
                "ae.p8_demo_controlled_skill_initial_failed",
                "Installed controlled Skill execution could not enter approval wait.",
                _retryable(exc),
            ) from exc

    def resume(
        self,
        context: StepExecutionContext,
        dependencies: LocalSkillExecutorDependencies,
        continuation: Any,
    ) -> P5ExecutorOutcome:
        del dependencies, continuation
        try:
            authority = SqlAlchemyNslApprovalResumeSource(self._sessions).resolve(
                _claim_from_context(context)
            )
            execution = self._package.execution(
                tenant_id=authority["tenant_id"],
                agent_execution_id=authority["agent_execution_id"],
                executable_step_id=authority["executable_step_id"],
                nsl_execution_id=authority["nsl_execution_id"],
                business_operation_id=authority["business_operation_id"],
            )
            oa_source = _HttpOaAuthoritySource(
                base_url=self._config.oa_base_url,
                service_token=self._config.ae_to_oa_service_token,
            )
            invocation = asyncio.run(
                NslApprovalResumeIntegration(
                    authority_source=SqlAlchemyNslApprovalResumeSource(self._sessions),
                    request_source=self._request_store,
                    evidence_source=self._evidence,
                    public_api=self.public_api,
                ).resume(
                    _claim_from_context(context),
                    skill=execution.skill,
                    request=execution.request,
                    checkpoint_port=execution.file_state_port,
                    verifier=PlatformApprovalEvidenceVerifier(
                        evidence_source=self._evidence,
                        wc_source=PersistedApprovalEventAuthoritySource(self._evidence),
                        oa_source=oa_source,
                    ),
                    clock=_RecordedClock(datetime.now(UTC)),
                )
            )
            validation = invocation.outcome.validation
            if not validation.approval_gate_passed:
                return P5ExecutorOutcome(
                    state="FAILED",
                    result_contract_ref=P8_DEMO_RESULT_CONTRACT,
                    result_payload={
                        "approval_status": validation.approval_status.value,
                        "reason_code": validation.reason_code,
                    },
                    error_ref="ae.p8_demo_approval_not_granted",
                    business_operation_id=invocation.business_operation_id,
                )
            controlled = self._execute_controlled_write(
                execution=execution,
                invocation=invocation,
                oa_source=oa_source,
            )
            return _controlled_write_outcome(
                controlled,
                business_operation_id=invocation.business_operation_id,
            )
        except P5StepExecutorError:
            raise
        except Exception as exc:
            raise P5StepExecutorError(
                "ae.p8_demo_controlled_skill_resume_failed",
                "Installed approval resume or controlled WRITE execution failed.",
                _retryable(exc),
            ) from exc

    def _execute_controlled_write(
        self,
        *,
        execution: _InstalledSkillExecution,
        invocation: Any,
        oa_source: _HttpOaAuthoritySource,
    ) -> Any:
        request = execution.controlled_write_request(
            invocation=invocation,
            public_api=self.public_api,
            request_factory=NslControlledWriteRequest,
            canonical_write_payload=build_golden_a_canonical_write_payload(
                self.fixture
            ),
            fixture_hash=str(self.fixture["fixture_hash"]),
        )
        integration = NslControlledWriteIntegration(
            public_api=self.public_api,
            policy_port=PlatformRuntimePolicyAdapter(
                authorization_source=_GovernedWriteSource(
                    authorization_source=oa_source,
                    fixture=self.fixture,
                    platform_evidence=self._evidence.get(
                        tenant_id=execution.tenant_id,
                        approval_request_id=invocation.approval_request_id,
                    ),
                    evaluated_at=request.evaluated_at,
                ),
                public_api=self.public_api,
            ),
            idempotency_port=SqlAlchemyNslIdempotencyEvidencePort(
                self._sessions,
                public_api=self.public_api,
                clock=lambda: request.evaluated_at,
            ),
            write_evidence_port=SqlAlchemyNslWriteEvidencePort(
                self._sessions,
                public_api=self.public_api,
                clock=lambda: request.evaluated_at,
            ),
            write_port=HttpEosWriteExecutionPort(
                public_api=self.public_api,
                base_url=self._config.eos_base_url,
                service_token=self._config.ae_to_eos_service_token,
                result_type=execution.contract.output_type,
                result_classification=execution.data_classification,
            ),
            verification_port=HttpEosPostWriteVerificationAdapter(
                public_api=self.public_api,
                base_url=self._config.eos_base_url,
                service_token=self._config.ae_to_eos_service_token,
            ),
        )
        return asyncio.run(integration.execute(request))


class _PlatformControlledStatePort:
    def __init__(
        self, *, execution: _InstalledSkillExecution, publication: Any
    ) -> None:
        self.execution = execution
        self.file = execution.file_state_port
        self.publication = publication

    async def save(self, checkpoint: Any) -> None:
        await self.file.save(checkpoint)

    async def publish(self, request: Any) -> None:
        await self.file.publish(request)
        await self.publication.publish(request)

    async def publish_platform(self, request: Any) -> None:
        await self.publication.publish(request)


class _ApprovalBindingSource:
    def __init__(
        self,
        *,
        context: StepExecutionContext,
        execution: _InstalledSkillExecution,
        fixture: Mapping[str, Any],
    ) -> None:
        self.context = context
        self.execution = execution
        self.fixture = fixture

    def resolve(self, _request: Mapping[str, Any]) -> Mapping[str, Any]:
        return {
            "tenant_id": self.execution.tenant_id,
            "agent_execution_id": self.context.step["agent_execution_id"],
            "executable_step_id": self.context.step["executable_step_id"],
            "nsl_execution_id": self.execution.nsl_execution_id,
            "business_operation_id": self.execution.business_operation_id,
            "checkpoint_version": self.execution.checkpoint_version,
            "target_approver_ref": self.fixture["approval_target"][
                "approver_subject_id"
            ],
            "target_role_ref": None,
            "target_org_scope_ref": self.fixture["approval_target"]["org_unit_id"],
            "target_project_scope_ref": self.fixture["projects"]["child"]["project_id"],
        }


class _BundleResolver:
    def __init__(self, bundle: DemoNslRuntimeBundle) -> None:
        self.bundle = bundle

    def resolve(self, *, skill_id: str, skill_version: str) -> object:
        if (
            skill_id != self.bundle.skill_id
            or skill_version != self.bundle.skill_version
        ):
            raise P8DemoControlledSkillError(
                "Skill selector is outside the Demo bundle."
            )
        return SimpleNamespace(
            skill=SimpleNamespace(
                skill_id=skill_id,
                skill_version=skill_version,
                semantic_hash=self.bundle.skill_semantic_hash,
            ),
            package_hash=_bundle_hash(self.bundle),
            signer_key_id="release:p8-demo-nsl-bundle-v1",
        )


class _BundleAdmissionSource:
    def __init__(self, bundle: DemoNslRuntimeBundle) -> None:
        self.bundle = bundle

    def current_admission(self, **values: Any) -> Mapping[str, Any] | None:
        admitted_at = self.bundle.admitted_at
        trust = {
            "evidence_ref": f"release-bundle:{self.bundle.bundle_id}",
            "package_id": values["package_id"],
            "package_hash": values["package_hash"],
            "publisher_id": "nex-platform-release",
            "signing_key_id": values["signing_key_id"],
            "verified_at": admitted_at,
            "trust_policy_id": values["trust_policy_id"],
            "trust_status": "VALID",
            "governance_status": "ACTIVE",
            "governance_decision_ref": f"release-admission:{self.bundle.bundle_id}",
        }
        decision = {
            "decision_id": f"release-admission:{self.bundle.bundle_id}",
            "decision": "ADMITTED",
            "package_id": values["package_id"],
            "package_hash": values["package_hash"],
            "publisher_id": trust["publisher_id"],
            "signing_key_id": values["signing_key_id"],
            "governance_status": "ACTIVE",
            "trust_policy_id": values["trust_policy_id"],
            "package_trust_evidence_ref": trust["evidence_ref"],
            "reason_codes": [],
            "decided_at": admitted_at,
        }
        return {"trust_evidence": trust, "admission_decision": decision}


class _HttpOaAuthoritySource:
    def __init__(self, *, base_url: str, service_token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.service_token = service_token

    def effective_authorization(
        self, *, tenant_id: str, subject_id: str
    ) -> Mapping[str, Any]:
        token = resolve_ae_outbound_service_token(
            self.service_token,
            audience="nex-oa",
        )
        response = httpx.get(
            f"{self.base_url}/internal/v1/auth/tenants/"
            f"{quote(tenant_id, safe='')}/subjects/{quote(subject_id, safe='')}"
            "/authorization",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Cache-Control": "no-store, max-age=0",
                "X-Service-ID": "nex-ae-api",
            },
            timeout=15.0,
        )
        response.raise_for_status()
        body = response.json()
        authorization = body.get("authorization") if isinstance(body, Mapping) else None
        if not isinstance(authorization, Mapping):
            raise P8DemoControlledSkillError("OA authorization response is invalid.")
        return {**authorization, "active": True}


class _GovernedWriteSource:
    def __init__(
        self,
        *,
        authorization_source: _HttpOaAuthoritySource,
        fixture: Mapping[str, Any],
        platform_evidence: Mapping[str, Any] | None,
        evaluated_at: datetime,
    ) -> None:
        if platform_evidence is None:
            raise P8DemoControlledSkillError("Platform approval evidence is missing.")
        self.authorization_source = authorization_source
        self.fixture = fixture
        self.evidence = platform_evidence
        self.evaluated_at = evaluated_at

    def resolve(self, request: Any) -> dict[str, Any]:
        authorization = self.authorization_source.effective_authorization(
            tenant_id=request.tenant_id,
            subject_id=request.subject_id,
        )
        if "finance:voucher-draft:create" not in authorization.get("scopes", ()):
            raise P8DemoControlledSkillError("OA denied Demo governed WRITE authority.")
        descriptor = {
            "tenant_id": request.tenant_id,
            "agent_execution_id": self.evidence["agent_execution_id"],
            "executable_step_id": self.evidence["executable_step_id"],
            "business_operation_id": str(request.business_operation_id),
            "actor_ref": request.subject_id,
            "agent_ref": self.fixture["admission"]["agent_id"],
            "org_scope_refs": [self.fixture["approval_target"]["org_unit_id"]],
            "project_ref": self.fixture["projects"]["child"]["project_id"],
            "resource_refs": [f"voucher_draft:{request.business_operation_id}"],
            "capability": "WRITE",
            "operation_class": "CREATE",
            "data_classification": "CONFIDENTIAL",
            "typed_parameters": {"voucher_type": "GENERAL"},
            "business_object_type": "VOUCHER_DRAFT",
        }
        descriptor["operation_fingerprint"] = semantic_sha256_hash_ref(descriptor)
        revision = str(authorization["revision_hash"])
        decision_hash = semantic_sha256_hash_ref(
            {"descriptor": descriptor, "authorization_revision_hash": revision}
        )
        return {
            "tenant_id": request.tenant_id,
            "business_operation_id": str(request.business_operation_id),
            "oa_decision_ref": f"oa-authz:{revision}",
            "oa_allowed": True,
            "protected_operation": descriptor,
            "operation_trust_decision": {
                "decision": "ALLOW",
                "decision_mode": "RULE_EVALUATED",
                "assurance_level": "HIGH",
                "operation_fingerprint": descriptor["operation_fingerprint"],
                "rule_set_ref": "policy:p8-demo-governed-write",
                "rule_set_version": "1",
                "facts_hash": semantic_sha256_hash_ref(authorization),
                "proof_ref": f"oa-revision:{revision}",
                "reason_code": None,
                "decision_hash": decision_hash,
                "evaluated_at": _time(self.evaluated_at),
                "expires_at": _time(self.evaluated_at + timedelta(minutes=10)),
            },
            "required_assurance_level": "HIGH",
        }


@dataclass(frozen=True)
class _RecordedClock:
    recorded_at: datetime

    def now(self) -> datetime:
        return self.recorded_at


def _context_projection(
    sessions: sessionmaker[Session],
    *,
    tenant_id: str,
    execution_id: str,
    fixture: Mapping[str, Any],
) -> dict[str, Any]:
    with sessions() as session:
        row = (
            session.execute(
                text(
                    "SELECT context_id, context_generation, context_hash, context_json "
                    "FROM ae_agent_context WHERE tenant_id = :tenant_id "
                    "AND agent_execution_id = :execution_id "
                    "ORDER BY context_generation DESC LIMIT 1"
                ),
                {"tenant_id": tenant_id, "execution_id": execution_id},
            )
            .mappings()
            .one()
        )
    context_ref = f"AE:AGENT_CONTEXT:{row['context_id']}:{row['context_generation']}"
    context_json = row["context_json"]
    if isinstance(context_json, str):
        try:
            context_json = json.loads(context_json)
        except json.JSONDecodeError as exc:
            raise P8DemoControlledSkillError(
                "Persisted AgentContext document is malformed."
            ) from exc
    if not isinstance(context_json, Mapping):
        raise P8DemoControlledSkillError(
            "Persisted AgentContext document must be an object."
        )
    try:
        principal_id = context_json["identity"]["principal_id"]
    except (KeyError, TypeError) as exc:
        raise P8DemoControlledSkillError(
            "Persisted AgentContext identity is unavailable."
        ) from exc
    principal = next(
        item for item in fixture["principals"] if item["subject_id"] == principal_id
    )
    return build_context_projection(
        agent_context_ref=context_ref,
        agent_context_hash=row["context_hash"],
        runtime_context_entries=(),
        explicit_resource_refs=(),
        verified_principal={
            "tenant_id": tenant_id,
            "subject_id": principal_id,
            "actor_type": "USER",
            "roles": list(principal["roles"]),
            "scopes": list(principal["scopes"]),
            "auth_context_ref": f"OA:AUTH_CONTEXT:{principal_id}",
            "verification": "VERIFIED",
            "on_behalf_of": None,
        },
        authority={
            "effective_role_bindings": list(principal["roles"]),
            "org_scope": [fixture["approval_target"]["org_unit_id"]],
            "project_scope": [fixture["projects"]["child"]["project_id"]],
        },
        data_policy={
            "policy_ref": "OA:DATA_POLICY:P8-DEMO",
            "max_trace_classification": "CONFIDENTIAL",
            "snapshot_retention_days": 30,
            "audit_retention_days": 90,
        },
    )


def _controlled_write_outcome(
    result: Any, *, business_operation_id: str
) -> P5ExecutorOutcome:
    outcome = result.outcome
    state = str(outcome.commit_state.value)
    verification = (
        None if result.verification is None else result.verification.status.value
    )
    if state == "COMMITTED" and verification == "VERIFIED":
        terminal = "SUCCEEDED"
        error_ref = None
    elif state == "NOT_COMMITTED":
        terminal = "FAILED"
        error_ref = "eos.write_not_committed"
    else:
        terminal = "BLOCKED"
        error_ref = "eos.write_outcome_requires_reconciliation"
    return P5ExecutorOutcome(
        state=terminal,
        result_contract_ref=P8_DEMO_RESULT_CONTRACT,
        result_payload={
            "commit_state": state,
            "verification_status": verification,
            "business_operation_id": business_operation_id,
        },
        external_refs=(f"EOS:BUSINESS_OPERATION:{business_operation_id}",),
        evidence_refs=(f"AE:WRITE_REQUESTED:{result.write_request.idempotency_key}",),
        error_ref=error_ref,
        business_operation_id=business_operation_id,
    )


def _claim_from_context(context: StepExecutionContext) -> Any:
    from nex_ae_api.runtime_jobs import RuntimeJobClaim

    return RuntimeJobClaim(job=context.job, attempt=context.attempt)


def _approval_wait_id(
    *, context: StepExecutionContext, approval_request_id: str, checkpoint_version: int
) -> str:
    from nex_ae_api.delegated_work import deterministic_nsl_approval_wait_id

    return deterministic_nsl_approval_wait_id(
        tenant_id=context.job["tenant_id"],
        agent_execution_id=context.step["agent_execution_id"],
        executable_step_id=context.step["executable_step_id"],
        approval_request_id=approval_request_id,
        checkpoint_version=checkpoint_version,
    )


def _bundle_hash(bundle: DemoNslRuntimeBundle) -> str:
    return semantic_sha256_hash_ref(
        {
            "bundle_id": bundle.bundle_id,
            "wheel_sha256": bundle.wheel_sha256,
            "skill_id": bundle.skill_id,
            "skill_version": bundle.skill_version,
            "skill_semantic_hash": bundle.skill_semantic_hash,
            "skill_files": dict(bundle.skill_files),
        }
    )


def _resolve_admission_lock(manifest_path: Path, bundle: DemoNslRuntimeBundle) -> Path:
    installed = manifest_path.parent / Path(bundle.admission_lock).name
    if installed.is_file():
        return installed
    raise P8DemoControlledSkillError("NSL wheel admission lock is unavailable.")


def _json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise P8DemoControlledSkillError(
            f"JSON document is unavailable: {path.name}"
        ) from exc
    if not isinstance(value, Mapping):
        raise P8DemoControlledSkillError(
            f"JSON document must be an object: {path.name}"
        )
    return dict(value)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _retryable(exc: Exception) -> bool:
    return bool(getattr(exc, "retryable", False)) or isinstance(
        exc, (httpx.NetworkError, httpx.TimeoutException)
    )
