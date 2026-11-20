from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx
from nex_runtime.nsl_runtime_adapter import (
    InstalledNslExecution,
    NslExecutionBinding,
)

from nex_ae_api.delegated_work import SqlAlchemyWaitRegistrationRepository
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
from nex_ae_api.nsl_approval_resume import SqlAlchemyNslApprovalResumeSource
from nex_ae_api.nsl_approval_resume_integration import NslApprovalResumeIntegration
from nex_ae_api.service_auth import resolve_ae_outbound_service_token
from nex_ae_api.step_executors import (
    LocalSkillExecutorDependencies,
    P5ExecutorOutcome,
    P5StepExecutorError,
)

CONTROLLED_RESULT_CONTRACT = "contract://nex/eos/create-voucher-draft-result/v1"
_NSL_SCOPES = frozenset(
    {
        "nsl:skill:execute",
        "finance:voucher:validate",
        "finance:voucher:resolve",
        "finance:voucher:write",
        "finance:voucher:verify",
        "nsl:replay:read",
    }
)


class ControlledSkillRuntimeError(RuntimeError):
    pass


@dataclass(frozen=True)
class ControlledExecutionAuthority:
    context_projection: Mapping[str, Any]
    execution_binding: NslExecutionBinding
    canonical_write_payload: Mapping[str, Any]
    authority_hash: str
    project_id: str
    agent_id: str
    org_scope_refs: tuple[str, ...]
    business_result_seed: Mapping[str, Any] | None
    runtime_metadata: Mapping[str, Any] | None = None


class ControlledSkillRuntime:
    """Scenario-neutral approval and controlled-WRITE lifecycle."""

    @property
    def backend_profile(self) -> str:
        return "NSL_V02_IN_PROCESS"

    def execute(self, **_values: Any) -> dict[str, Any]:
        raise ControlledSkillRuntimeError(
            "Controlled NSL execution requires the installed initial/resume handlers."
        )

    def initial(
        self,
        context: Any,
        dependencies: LocalSkillExecutorDependencies,
    ) -> P5ExecutorOutcome:
        try:
            authority = _initial_stage(
                "ae.product_controlled_skill_authority_failed",
                "Product controlled Skill authority resolution failed.",
                lambda: self._resolve_authority(context),
            )
            now = _utc_now()
            binding = context.step["skill_binding"]
            artifact = _initial_stage(
                "ae.product_controlled_skill_artifact_failed",
                "Product controlled Skill artifact admission failed.",
                lambda: dependencies.artifact_gateway.resolve_verified(
                    tenant_id=context.job["tenant_id"],
                    skill_id=binding["skill_id"],
                    exact_version=binding["exact_skill_version"],
                    expected_semantic_hash=binding["skill_semantic_hash"],
                    runtime_contract_ref=binding["runtime_contract_ref"],
                    trust_policy_id=binding["trust_policy_id"],
                    environment="staging",
                    observed_at=now,
                ),
            )
            bound = _initial_stage(
                "ae.product_controlled_skill_binding_failed",
                "Product controlled Skill durable binding failed.",
                lambda: dependencies.binding_repository.bind_request(
                    tenant_id=context.job["tenant_id"],
                    executable_step_id=context.step["executable_step_id"],
                    verified_artifact_ref=artifact["artifact_ref"],
                    context_projection=authority.context_projection,
                    compiled_inputs={
                        "canonical_write_payload": dict(
                            authority.canonical_write_payload
                        )
                    },
                    input_provenance={"canonical_write_payload": "CONTEXT"},
                    now=now,
                ),
            )
            skill_binding = bound["binding"]
            execution = _initial_stage(
                "ae.product_controlled_skill_execution_failed",
                "Product controlled Skill execution construction failed.",
                lambda: self._execution(
                    context=context,
                    skill_binding=skill_binding,
                    authority=authority,
                ),
            )
            publication = _initial_stage(
                "ae.product_controlled_skill_publication_failed",
                "Product controlled Skill approval publication setup failed.",
                lambda: P8NSLApprovalPort(
                    binding_source=_ApprovalBindingSource(
                        context=context,
                        execution=execution,
                        approver_role=self._config.approver_role,
                    ),
                    request_store=self._request_store,
                    wait_repository=SqlAlchemyWaitRegistrationRepository(
                        self._sessions
                    ),
                    wc_client=build_default_wc_approval_work_item_client(),
                ),
            )
            state_port = _PlatformControlledStatePort(
                execution=execution,
                publication=publication,
            )
            request = _initial_stage(
                "ae.product_controlled_skill_checkpoint_failed",
                "Product controlled Skill approval checkpoint lookup failed.",
                execution.existing_approval_request,
            )
            if request is None:
                session = _initial_stage(
                    "ae.product_controlled_skill_approval_start_failed",
                    "Product controlled Skill approval start failed.",
                    lambda: asyncio.run(execution.start(state_port)),
                )
                request = session.approval_request
                if request is None or session.checkpoint is None:
                    raise P5StepExecutorError(
                        "ae.product_controlled_skill_approval_not_suspended",
                        "Product controlled Skill did not suspend for approval.",
                    )
            else:
                _initial_stage(
                    "ae.product_controlled_skill_approval_publish_failed",
                    "Product controlled Skill approval replay publication failed.",
                    lambda: asyncio.run(state_port.publish_platform(request)),
                )
            wait_id = _initial_stage(
                "ae.product_controlled_skill_wait_failed",
                "Product controlled Skill approval wait binding failed.",
                lambda: _approval_wait_id(
                    context=context,
                    approval_request_id=str(request.approval_request_id),
                    checkpoint_version=execution.checkpoint_version,
                ),
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
                "ae.product_controlled_skill_initial_failed",
                "Product controlled Skill could not enter approval wait.",
                _retryable(exc),
            ) from exc

    def resume(
        self,
        context: Any,
        dependencies: LocalSkillExecutorDependencies,
        continuation: Any,
    ) -> P5ExecutorOutcome:
        del dependencies, continuation
        try:
            claim = _claim_from_context(context)
            resume = SqlAlchemyNslApprovalResumeSource(self._sessions).resolve(claim)
            authority = self._resolve_authority(context)
            execution = self._package.execution(
                tenant_id=resume["tenant_id"],
                agent_execution_id=resume["agent_execution_id"],
                executable_step_id=resume["executable_step_id"],
                nsl_execution_id=resume["nsl_execution_id"],
                business_operation_id=resume["business_operation_id"],
                binding=authority.execution_binding,
            )
            invocation = asyncio.run(
                NslApprovalResumeIntegration(
                    authority_source=SqlAlchemyNslApprovalResumeSource(self._sessions),
                    request_source=self._request_store,
                    evidence_source=self._evidence,
                    public_api=self.public_api,
                ).resume(
                    claim,
                    skill=execution.skill,
                    request=execution.request,
                    checkpoint_port=execution.file_state_port,
                    verifier=PlatformApprovalEvidenceVerifier(
                        evidence_source=self._evidence,
                        wc_source=PersistedApprovalEventAuthoritySource(self._evidence),
                        oa_source=self._oa,
                    ),
                    clock=_RecordedClock(datetime.now(UTC)),
                )
            )
            validation = invocation.outcome.validation
            if not validation.approval_gate_passed:
                return P5ExecutorOutcome(
                    state="FAILED",
                    result_contract_ref=CONTROLLED_RESULT_CONTRACT,
                    result_payload={
                        "approval_status": validation.approval_status.value,
                        "reason_code": validation.reason_code,
                    },
                    error_ref="ae.product_approval_not_granted",
                    business_operation_id=invocation.business_operation_id,
                )
            controlled = self._execute_controlled_write(
                execution=execution,
                invocation=invocation,
                authority=authority,
            )
            return self._controlled_write_outcome(
                context=context,
                result=controlled,
                authority=authority,
                business_operation_id=invocation.business_operation_id,
            )
        except P5StepExecutorError:
            raise
        except Exception as exc:
            raise P5StepExecutorError(
                "ae.product_controlled_skill_resume_failed",
                "Product approval resume or controlled WRITE execution failed.",
                _retryable(exc),
            ) from exc

    def _execution(
        self,
        *,
        context: Any,
        skill_binding: Mapping[str, Any],
        authority: ControlledExecutionAuthority,
    ) -> InstalledNslExecution:
        return self._package.execution(
            tenant_id=context.job["tenant_id"],
            agent_execution_id=context.step["agent_execution_id"],
            executable_step_id=context.step["executable_step_id"],
            nsl_execution_id=skill_binding["nsl_execution_id"],
            business_operation_id=skill_binding["business_operation_id"],
            binding=authority.execution_binding,
        )

    def _resolve_authority(self, context: Any) -> ControlledExecutionAuthority:
        raise NotImplementedError

    def _execute_controlled_write(
        self,
        *,
        execution: InstalledNslExecution,
        invocation: Any,
        authority: ControlledExecutionAuthority,
    ) -> Any:
        raise NotImplementedError

    def _controlled_write_outcome(
        self,
        *,
        context: Any,
        result: Any,
        authority: ControlledExecutionAuthority,
        business_operation_id: str,
    ) -> P5ExecutorOutcome:
        del context, authority
        return _controlled_write_outcome(
            result, business_operation_id=business_operation_id
        )


class HttpOaAuthoritySource:
    def __init__(self, *, base_url: str, service_token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.service_token = service_token

    def effective_authorization(
        self, *, tenant_id: str, subject_id: str
    ) -> Mapping[str, Any]:
        token = resolve_ae_outbound_service_token(
            self.service_token, audience="nex-oa"
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
            raise ControlledSkillRuntimeError(
                "OA authorization response is invalid."
            )
        return {**authorization, "active": True}


def principal_document(
    *, tenant_id: str, principal_id: str, authorization: Mapping[str, Any]
) -> dict[str, Any]:
    roles = _string_tuple(authorization.get("roles"))
    scopes = set(_string_tuple(authorization.get("scopes")))
    scopes.update(_NSL_SCOPES)
    return {
        "tenant_id": tenant_id,
        "subject_id": principal_id,
        "actor_type": "USER",
        "roles": sorted(roles),
        "scopes": sorted(scopes),
        "auth_context_ref": f"oa-auth-context:{authorization['revision_hash']}",
        "verification": "VERIFIED",
    }


class _PlatformControlledStatePort:
    def __init__(self, *, execution: InstalledNslExecution, publication: Any) -> None:
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
        context: Any,
        execution: InstalledNslExecution,
        approver_role: str,
    ) -> None:
        self.context = context
        self.execution = execution
        self.approver_role = approver_role

    def resolve(self, _request: Mapping[str, Any]) -> Mapping[str, Any]:
        return {
            "tenant_id": self.execution.tenant_id,
            "agent_execution_id": self.context.step["agent_execution_id"],
            "executable_step_id": self.context.step["executable_step_id"],
            "nsl_execution_id": self.execution.nsl_execution_id,
            "business_operation_id": self.execution.business_operation_id,
            "checkpoint_version": self.execution.checkpoint_version,
            "target_approver_ref": None,
            "target_role_ref": self.approver_role,
            "target_org_scope_ref": None,
            "target_project_scope_ref": None,
        }


@dataclass(frozen=True)
class _RecordedClock:
    recorded_at: datetime

    def now(self) -> datetime:
        return self.recorded_at


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
        result_contract_ref=CONTROLLED_RESULT_CONTRACT,
        result_payload={
            "commit_state": state,
            "verification_status": verification,
            "business_operation_id": business_operation_id,
        },
        external_refs=(f"EOS:BUSINESS_OPERATION:{business_operation_id}",),
        evidence_refs=(
            f"AE:WRITE_REQUESTED:{result.write_request.idempotency_key}",
        ),
        error_ref=error_ref,
        business_operation_id=business_operation_id,
    )


def _claim_from_context(context: Any) -> Any:
    from nex_ae_api.runtime_jobs import RuntimeJobClaim

    return RuntimeJobClaim(job=context.job, attempt=context.attempt)


def _approval_wait_id(
    *, context: Any, approval_request_id: str, checkpoint_version: int
) -> str:
    from nex_ae_api.delegated_work import deterministic_nsl_approval_wait_id

    return deterministic_nsl_approval_wait_id(
        tenant_id=context.job["tenant_id"],
        agent_execution_id=context.step["agent_execution_id"],
        executable_step_id=context.step["executable_step_id"],
        approval_request_id=approval_request_id,
        checkpoint_version=checkpoint_version,
    )


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ControlledSkillRuntimeError("Authorization string set is invalid.")
    return tuple(sorted(set(value)))


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _retryable(exc: Exception) -> bool:
    return isinstance(exc, (httpx.HTTPError, OSError)) or bool(
        getattr(exc, "retryable", False)
    )


def _initial_stage(
    error_code: str, detail: str, operation: Callable[[], Any]
) -> Any:
    try:
        return operation()
    except P5StepExecutorError:
        raise
    except Exception as exc:
        raise P5StepExecutorError(error_code, detail, _retryable(exc)) from exc
