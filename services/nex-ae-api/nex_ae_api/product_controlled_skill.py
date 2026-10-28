from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import quote

import httpx
from nex_runtime.nsl_package_admission import inspect_installed_nsl_package
from nex_runtime.nsl_runtime_adapter import (
    InstalledNslExecution,
    InstalledNslPackage,
    NslExecutionBinding,
    NslRuntimeAdapterError,
    decode_nsl_document,
)
from nex_runtime.nsl_runtime_bundle import (
    NslRuntimeBundle,
    load_nsl_runtime_bundle,
    verify_nsl_runtime_bundle,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from nex_ae_api.delegated_work import SqlAlchemyWaitRegistrationRepository
from nex_ae_api.golden_a_planning import GOLDEN_A_WRITE_SCHEMA_VERSION
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
from nex_ae_api.product_capabilities import (
    ProductCapabilityRegistration,
    load_product_capability_registry,
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
from nex_ae_api.voucher_attachment_manifest import (
    bind_manifest_to_governed_payload,
    build_attachment_manifest,
    work_intent_manifest_binding,
)
from nex_ae_api.voucher_attachments import SqlAlchemyVoucherAttachmentRepository

PRODUCT_RESULT_CONTRACT = "contract://nex/eos/create-voucher-draft-result/v1"
PRODUCT_CAPABILITY_ID = "FINANCE.CREATE_VOUCHER_DRAFT"
PRODUCT_APPROVER_ROLE = "finance_approver"
_OA_REQUIRED_SCOPE = "finance:voucher-draft:create"
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


class ProductControlledSkillError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProductControlledSkillConfig:
    manifest_path: Path
    wheel_path: Path
    platform_lock_path: Path
    skill_root: Path
    state_root: Path
    oa_base_url: str
    eos_base_url: str
    ae_to_oa_service_token: str
    ae_to_eos_service_token: str
    approver_role: str = PRODUCT_APPROVER_ROLE


@dataclass(frozen=True)
class ProductExecutionAuthority:
    context_projection: Mapping[str, Any]
    execution_binding: NslExecutionBinding
    canonical_write_payload: Mapping[str, Any]
    authority_hash: str
    project_id: str
    agent_id: str
    org_scope_refs: tuple[str, ...]


class ProductControlledSkillRuntime:
    """Product LOCAL_SKILL runtime backed by registry and service authorities."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        config: ProductControlledSkillConfig,
        *,
        environ: Mapping[str, str],
    ) -> None:
        self._sessions = session_factory
        self._config = config
        self._bundle = load_nsl_runtime_bundle(config.manifest_path)
        self.bundle_readiness = verify_nsl_runtime_bundle(
            self._bundle,
            wheel_path=config.wheel_path,
            skill_root=config.skill_root,
        )
        admission_lock = _json_object(
            _resolve_admission_lock(config.manifest_path, self._bundle)
        )
        self.package_readiness = inspect_installed_nsl_package(
            admission_lock,
            platform_lock_path=config.platform_lock_path,
        )
        self.public_api = load_nsl_v02_public_api(self.package_readiness)
        registry = load_product_capability_registry(environ)
        registration = registry.resolve(PRODUCT_CAPABILITY_ID, required=True)
        assert registration is not None
        self._registration = registration
        self._registry_hash = registry.registry_hash
        self._require_registration_matches_bundle()
        self._package = InstalledNslPackage(
            self._bundle,
            config.skill_root,
            config.state_root,
        )
        self._evidence = SqlAlchemyPlatformApprovalEvidenceRepository(session_factory)
        self._request_store = SqlAlchemyProtectedApprovalRequestStore(session_factory)
        self._oa = _HttpOaAuthoritySource(
            base_url=config.oa_base_url,
            service_token=config.ae_to_oa_service_token,
        )
        self._eos = _HttpEosBusinessAuthoritySource(
            base_url=config.eos_base_url,
            service_token=config.ae_to_eos_service_token,
        )

    @property
    def backend_profile(self) -> str:
        return "NSL_V02_IN_PROCESS"

    def execute(self, **_values: Any) -> dict[str, Any]:
        raise ProductControlledSkillError(
            "Controlled NSL execution requires the installed initial/resume handlers."
        )

    @property
    def dependencies(self) -> LocalSkillExecutorDependencies:
        gateway = SkillArtifactGateway(
            resolver=_BundleResolver(self._bundle),
            admission_source=_BundleAdmissionSource(self._bundle),
            repository=SqlAlchemySkillArtifactRepository(self._sessions),
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
            authority = self._resolve_authority(context)
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
            bound = dependencies.binding_repository.bind_request(
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
            )
            skill_binding = bound["binding"]
            execution = self._execution(
                context=context,
                skill_binding=skill_binding,
                authority=authority,
            )
            publication = P8NSLApprovalPort(
                binding_source=_ApprovalBindingSource(
                    context=context,
                    execution=execution,
                    approver_role=self._config.approver_role,
                ),
                request_store=self._request_store,
                wait_repository=SqlAlchemyWaitRegistrationRepository(self._sessions),
                wc_client=build_default_wc_approval_work_item_client(),
            )
            state_port = _PlatformControlledStatePort(
                execution=execution,
                publication=publication,
            )
            request = execution.existing_approval_request()
            if request is None:
                session = asyncio.run(execution.start(state_port))
                request = session.approval_request
                if request is None or session.checkpoint is None:
                    raise ProductControlledSkillError(
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
                "ae.product_controlled_skill_initial_failed",
                "Product controlled Skill could not enter approval wait.",
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
            resume = SqlAlchemyNslApprovalResumeSource(self._sessions).resolve(
                _claim_from_context(context)
            )
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
                    _claim_from_context(context),
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
                    result_contract_ref=PRODUCT_RESULT_CONTRACT,
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
            return _controlled_write_outcome(
                controlled,
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
        context: StepExecutionContext,
        skill_binding: Mapping[str, Any],
        authority: ProductExecutionAuthority,
    ) -> InstalledNslExecution:
        return self._package.execution(
            tenant_id=context.job["tenant_id"],
            agent_execution_id=context.step["agent_execution_id"],
            executable_step_id=context.step["executable_step_id"],
            nsl_execution_id=skill_binding["nsl_execution_id"],
            business_operation_id=skill_binding["business_operation_id"],
            binding=authority.execution_binding,
        )

    def _execute_controlled_write(
        self,
        *,
        execution: InstalledNslExecution,
        invocation: Any,
        authority: ProductExecutionAuthority,
    ) -> Any:
        request = execution.controlled_write_request(
            invocation=invocation,
            public_api=self.public_api,
            request_factory=NslControlledWriteRequest,
            canonical_write_payload=authority.canonical_write_payload,
            authority_hash=authority.authority_hash,
        )
        integration = NslControlledWriteIntegration(
            public_api=self.public_api,
            policy_port=PlatformRuntimePolicyAdapter(
                authorization_source=_GovernedWriteSource(
                    authorization_source=self._oa,
                    platform_evidence=self._evidence.get(
                        tenant_id=execution.tenant_id,
                        approval_request_id=invocation.approval_request_id,
                    ),
                    evaluated_at=request.evaluated_at,
                    agent_id=authority.agent_id,
                    org_scope_refs=authority.org_scope_refs,
                    project_id=authority.project_id,
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

    def _resolve_authority(
        self, context: StepExecutionContext
    ) -> ProductExecutionAuthority:
        persisted = _persisted_execution_context(
            self._sessions,
            tenant_id=context.job["tenant_id"],
            execution_id=context.step["agent_execution_id"],
        )
        principal_id = persisted["principal_id"]
        authorization = self._oa.effective_authorization(
            tenant_id=context.job["tenant_id"], subject_id=principal_id
        )
        if _OA_REQUIRED_SCOPE not in authorization.get("scopes", ()):
            raise ProductControlledSkillError(
                "OA denied product governed WRITE authority."
            )
        request = _product_business_request(persisted["work_intent"])
        eos = self._eos.resolve(
            tenant_id=context.job["tenant_id"],
            subject_id=principal_id,
            project_code=request["project_code"],
            account_codes=request["account_codes"],
            effective_at=request["transaction_date"],
        )
        product = _product_business_binding(
            tenant_id=context.job["tenant_id"],
            work_intent=persisted["work_intent"],
            registration=self._registration,
            principal_id=principal_id,
            eos=eos,
            attachment_manifest=_persisted_attachment_manifest(
                self._sessions,
                tenant_id=context.job["tenant_id"],
                work_intent=persisted["work_intent"],
            ),
        )
        authority_hash = semantic_sha256_hash_ref(
            {
                "registry_hash": self._registry_hash,
                "work_intent_hash": persisted["work_intent"]["intent_hash"],
                "oa_revision_hash": authorization["revision_hash"],
                "eos": eos,
            }
        )
        principal = _principal_document(
            tenant_id=context.job["tenant_id"],
            principal_id=principal_id,
            authorization=authorization,
        )
        handlers = _product_handlers(product)
        binding = NslExecutionBinding(
            input_document=product["nsl_input"],
            principal_document=principal,
            handlers=handlers,
            write_tool_id=PRODUCT_CAPABILITY_ID,
            write_tool_version=str(
                self._registration.skill_artifact["exact_skill_version"]
            ),
            precondition_evidence_ref=f"product-authority:{authority_hash}",
        )
        org_scope_refs = _string_tuple(authorization.get("org_scope_refs", ()))
        projection = build_context_projection(
            agent_context_ref=persisted["context_ref"],
            agent_context_hash=persisted["context_hash"],
            runtime_context_entries=(),
            explicit_resource_refs=(
                f"EOS:PROJECT:{product['project']['project_id']}",
            ),
            verified_principal={
                **principal,
                "roles": list(principal["roles"]),
                "scopes": list(principal["scopes"]),
                "on_behalf_of": None,
            },
            authority={
                "effective_role_bindings": list(principal["roles"]),
                "org_scope": list(org_scope_refs),
                "project_scope": [product["project"]["project_id"]],
            },
            data_policy={
                "policy_ref": "OA:DATA_POLICY:PRODUCT_CONTROLLED_WRITE",
                "max_trace_classification": "CONFIDENTIAL",
                "snapshot_retention_days": 30,
                "audit_retention_days": 90,
            },
        )
        return ProductExecutionAuthority(
            context_projection=projection,
            execution_binding=binding,
            canonical_write_payload=product["canonical_payload"],
            authority_hash=authority_hash,
            project_id=product["project"]["project_id"],
            agent_id=persisted["agent_id"],
            org_scope_refs=org_scope_refs,
        )

    def _require_registration_matches_bundle(self) -> None:
        artifact = self._registration.skill_artifact
        if (
            artifact["bundle_id"] != self._bundle.bundle_id
            or artifact["skill_id"] != self._bundle.skill_id
            or artifact["exact_skill_version"] != self._bundle.skill_version
            or artifact["skill_semantic_hash"] != self._bundle.skill_semantic_hash
        ):
            raise ProductControlledSkillError(
                "Product Capability Registry differs from the admitted NSL bundle."
            )


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
        context: StepExecutionContext,
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


class _BundleResolver:
    def __init__(self, bundle: NslRuntimeBundle) -> None:
        self.bundle = bundle

    def resolve(self, *, skill_id: str, skill_version: str) -> object:
        if skill_id != self.bundle.skill_id or skill_version != self.bundle.skill_version:
            raise ProductControlledSkillError(
                "Skill selector is outside the product bundle."
            )
        return SimpleNamespace(
            skill=SimpleNamespace(
                skill_id=skill_id,
                skill_version=skill_version,
                semantic_hash=self.bundle.skill_semantic_hash,
            ),
            package_hash=_bundle_hash(self.bundle),
            signer_key_id="release:nex-product-nsl-bundle-v1",
        )


class _BundleAdmissionSource:
    def __init__(self, bundle: NslRuntimeBundle) -> None:
        self.bundle = bundle

    def current_admission(self, **values: Any) -> Mapping[str, Any] | None:
        trust = {
            "evidence_ref": f"release-bundle:{self.bundle.bundle_id}",
            "package_id": values["package_id"],
            "package_hash": values["package_hash"],
            "publisher_id": "nex-platform-release",
            "signing_key_id": values["signing_key_id"],
            "verified_at": self.bundle.admitted_at,
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
            "decided_at": self.bundle.admitted_at,
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
            raise ProductControlledSkillError("OA authorization response is invalid.")
        return {**authorization, "active": True}


class _HttpEosBusinessAuthoritySource:
    def __init__(self, *, base_url: str, service_token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.service_token = service_token

    def resolve(
        self,
        *,
        tenant_id: str,
        subject_id: str,
        project_code: str,
        account_codes: tuple[str, str],
        effective_at: str,
    ) -> dict[str, Any]:
        project_page = self._get(
            "/internal/v1/projects?limit=100&offset=0",
            tenant_id=tenant_id,
            subject_id=subject_id,
        )
        projects = project_page.get("items")
        matches = (
            [
                dict(item)
                for item in projects
                if isinstance(item, Mapping)
                and item.get("project_code") == project_code
            ]
            if isinstance(projects, list)
            else []
        )
        if len(matches) != 1:
            raise ProductControlledSkillError(
                "EOS does not expose one accessible Project for the WorkIntent."
            )
        accounts = [
            self._get(
                "/internal/v1/accounts?account_code="
                f"{quote(account_code, safe='')}&effective_at={effective_at}",
                tenant_id=tenant_id,
                subject_id=subject_id,
            )
            for account_code in account_codes
        ]
        return {"project": matches[0], "accounts": accounts}

    def _get(
        self, path: str, *, tenant_id: str, subject_id: str
    ) -> dict[str, Any]:
        token = resolve_ae_outbound_service_token(
            self.service_token, audience="nex-eos"
        )
        response = httpx.get(
            self.base_url + path,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "X-NeX-Tenant-Id": tenant_id,
                "X-NeX-Subject-Id": subject_id,
                "X-Service-ID": "nex-ae-api",
            },
            timeout=15.0,
        )
        response.raise_for_status()
        value = response.json()
        if not isinstance(value, Mapping):
            raise ProductControlledSkillError("EOS authority response is invalid.")
        return dict(value)


class _GovernedWriteSource:
    def __init__(
        self,
        *,
        authorization_source: _HttpOaAuthoritySource,
        platform_evidence: Mapping[str, Any] | None,
        evaluated_at: datetime,
        agent_id: str,
        org_scope_refs: tuple[str, ...],
        project_id: str,
    ) -> None:
        if platform_evidence is None:
            raise ProductControlledSkillError("Platform approval evidence is missing.")
        self.authorization_source = authorization_source
        self.evidence = platform_evidence
        self.evaluated_at = evaluated_at
        self.agent_id = agent_id
        self.org_scope_refs = org_scope_refs
        self.project_id = project_id

    def resolve(self, request: Any) -> dict[str, Any]:
        authorization = self.authorization_source.effective_authorization(
            tenant_id=request.tenant_id,
            subject_id=request.subject_id,
        )
        if _OA_REQUIRED_SCOPE not in authorization.get("scopes", ()):
            raise ProductControlledSkillError("OA denied governed WRITE authority.")
        descriptor = {
            "tenant_id": request.tenant_id,
            "agent_execution_id": self.evidence["agent_execution_id"],
            "executable_step_id": self.evidence["executable_step_id"],
            "business_operation_id": str(request.business_operation_id),
            "actor_ref": request.subject_id,
            "agent_ref": self.agent_id,
            "org_scope_refs": list(self.org_scope_refs),
            "project_ref": self.project_id,
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
                "rule_set_ref": "policy:nex-product-governed-write",
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


def _persisted_execution_context(
    sessions: sessionmaker[Session], *, tenant_id: str, execution_id: str
) -> dict[str, Any]:
    with sessions() as session:
        row = (
            session.execute(
                text(
                    "SELECT c.context_id, c.context_generation, c.context_hash, "
                    "c.context_json, c.principal_id, c.agent_id, i.intent_json "
                    "FROM ae_agent_context c JOIN ae_work_intent i "
                    "ON i.tenant_id = c.tenant_id AND i.work_intent_id = c.work_intent_id "
                    "WHERE c.tenant_id = :tenant_id "
                    "AND c.agent_execution_id = :execution_id "
                    "ORDER BY c.context_generation DESC LIMIT 1"
                ),
                {"tenant_id": tenant_id, "execution_id": execution_id},
            )
            .mappings()
            .one()
        )
    context = _json_mapping(row["context_json"], "AgentContext")
    intent = _json_mapping(row["intent_json"], "WorkIntent")
    identity = context.get("identity")
    if (
        not isinstance(identity, Mapping)
        or not _same_persisted_identifier(
            identity.get("principal_id"), row["principal_id"]
        )
        or not _same_persisted_identifier(
            identity.get("agent_id"), row["agent_id"]
        )
        or not _same_persisted_identifier(
            intent.get("execution_id"), execution_id
        )
    ):
        raise ProductControlledSkillError(
            "Persisted AgentContext and WorkIntent lineage is invalid."
        )
    return {
        "context_ref": (
            f"AE:AGENT_CONTEXT:{row['context_id']}:{row['context_generation']}"
        ),
        "context_hash": row["context_hash"],
        "principal_id": str(row["principal_id"]),
        "agent_id": str(row["agent_id"]),
        "work_intent": intent,
    }


def _same_persisted_identifier(document_value: Any, stored_value: Any) -> bool:
    return (
        isinstance(document_value, str)
        and bool(document_value.strip())
        and stored_value is not None
        and document_value.strip() == str(stored_value)
    )


def _product_business_request(work_intent: Mapping[str, Any]) -> dict[str, Any]:
    selectors = work_intent.get("entity_selectors")
    if not isinstance(selectors, list):
        raise ProductControlledSkillError("Product project selector is unavailable.")
    project_codes = {
        item.get("raw_text") or item.get("value")
        for item in selectors
        if isinstance(item, Mapping)
        and item.get("entity_type", "PROJECT") == "PROJECT"
        and isinstance(item.get("raw_text") or item.get("value"), str)
    }
    if len(project_codes) != 1:
        raise ProductControlledSkillError(
            "Persisted WorkIntent does not identify one Project code."
        )
    parameters = _work_intent_parameters(work_intent)
    return {
        "project_code": next(iter(project_codes)),
        "account_codes": (
            str(parameters["economic_category"]).upper(),
            str(parameters["settlement_method"]).upper(),
        ),
        "transaction_date": _iso_date(parameters["transaction_date"]),
    }


def _product_business_binding(
    *,
    tenant_id: str,
    work_intent: Mapping[str, Any],
    registration: ProductCapabilityRegistration,
    principal_id: str,
    eos: Mapping[str, Any],
    attachment_manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    request = _product_business_request(work_intent)
    parameters = _work_intent_parameters(work_intent)
    project, debit, credit = _validated_eos_authority(eos, request=request)
    amount = _positive_amount(parameters["amount"])
    transaction_date = request["transaction_date"]
    currency = str(parameters["currency"]).upper()
    voucher_type = str(parameters["voucher_type"]).upper()
    economic_category = str(parameters["economic_category"]).upper()
    settlement_method = str(parameters["settlement_method"]).upper()
    description = "IA governed voucher draft"
    evidence_ref = f"capability:{PRODUCT_CAPABILITY_ID}"
    payload = {
        "schema_version": GOLDEN_A_WRITE_SCHEMA_VERSION,
        "tenant_id": tenant_id,
        "requester_ref": {"type": "oa.user", "id": principal_id},
        "project_ref": {"type": "eos.project", "id": project["project_id"]},
        "voucher_type": voucher_type,
        "transaction_date": transaction_date,
        "currency": currency,
        "description_text": description,
        "lines": [
            {
                "line_no": 1,
                "account_ref": {"type": "eos.account", "id": debit["account_id"]},
                "signed_amount": f"{amount:.2f}",
                "economic_category": economic_category,
                "description": "Governed expense",
                "evidence_refs": [evidence_ref],
            },
            {
                "line_no": 2,
                "account_ref": {"type": "eos.account", "id": credit["account_id"]},
                "signed_amount": f"{-amount:.2f}",
                "economic_category": settlement_method,
                "description": "Governed settlement",
                "evidence_refs": [evidence_ref],
            },
        ],
        "attachments": [],
    }
    if attachment_manifest is not None:
        payload = bind_manifest_to_governed_payload(payload, attachment_manifest)
    nsl_input = {
        "tenant_id": tenant_id,
        "requester_id": principal_id,
        "account_code": debit["account_code"],
        "counter_account_code": credit["account_code"],
        "project_code": project["project_code"],
        "accounting_period": transaction_date[:7],
        "amount": {
            "$type": "Money",
            "amount": f"{amount:.2f}",
            "currency": currency,
        },
        "transaction_date": transaction_date,
        "voucher_type": voucher_type,
        "economic_category": economic_category,
        "settlement_method": settlement_method,
        "description_text": description,
    }
    return {
        "project": project,
        "accounts": (dict(debit), dict(credit)),
        "canonical_payload": payload,
        "nsl_input": nsl_input,
        "capability": dict(registration.capability),
    }


def _persisted_attachment_manifest(
    sessions: sessionmaker[Session],
    *,
    tenant_id: str,
    work_intent: Mapping[str, Any],
) -> dict[str, Any] | None:
    binding = work_intent_manifest_binding(work_intent)
    if binding is None:
        return None
    batch = SqlAlchemyVoucherAttachmentRepository(sessions).get_batch(
        tenant_id=tenant_id,
        attachment_batch_id=binding["attachment_batch_id"],
    )
    if batch is None or batch.get("state") != "LOCKED":
        raise ProductControlledSkillError(
            "Persisted Voucher attachment manifest is not approval-locked."
        )
    manifest = build_attachment_manifest(batch)
    if manifest["attachment_manifest_hash"] != binding["attachment_manifest_hash"]:
        raise ProductControlledSkillError(
            "Persisted Voucher attachment manifest differs from WorkIntent."
        )
    return manifest


def _work_intent_parameters(work_intent: Mapping[str, Any]) -> dict[str, Any]:
    values = work_intent.get("parameter_candidates")
    if not isinstance(values, list):
        raise ProductControlledSkillError(
            "Persisted WorkIntent parameters are unavailable."
        )
    parameters = {
        item.get("name"): item.get("value")
        for item in values
        if isinstance(item, Mapping) and isinstance(item.get("name"), str)
    }
    required = {
        "amount",
        "currency",
        "transaction_date",
        "voucher_type",
        "economic_category",
        "settlement_method",
    }
    if not required.issubset(parameters):
        raise ProductControlledSkillError(
            "Persisted WorkIntent parameters are incomplete."
        )
    return parameters


def _positive_amount(value: object) -> Decimal:
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise ProductControlledSkillError(
            "Persisted WorkIntent amount is invalid."
        ) from exc
    if amount <= 0:
        raise ProductControlledSkillError(
            "Persisted WorkIntent amount must be positive."
        )
    return amount


def _iso_date(value: object) -> str:
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError as exc:
        raise ProductControlledSkillError(
            "Persisted WorkIntent transaction_date is invalid."
        ) from exc


def _product_handlers(product: Mapping[str, Any]) -> dict[str, Any]:
    inputs = decode_nsl_document(product["nsl_input"])
    accounts = product["accounts"]
    payload = dict(product["canonical_payload"])
    return {
        "ACCOUNT.GET_ACCOUNT": _exact_handler(
            {"account_code": inputs["account_code"]},
            {"account_code": accounts[0]["account_code"], "status": "ACTIVE"},
        ),
        "PROJECT.GET_PROJECT": _exact_handler(
            {"project_code": inputs["project_code"]},
            {"project_code": product["project"]["project_code"], "status": "ACTIVE"},
        ),
        "FINANCE.GET_ACCOUNTING_PERIOD": _exact_handler(
            {"accounting_period": inputs["accounting_period"]},
            {"accounting_period": inputs["accounting_period"], "open": True},
        ),
        "FINANCE.RESOLVE_VOUCHER_DRAFT_COMMAND": _exact_handler(
            dict(inputs), payload
        ),
    }


def _exact_handler(expected: Mapping[str, Any], result: Any):
    def handler(arguments: Mapping[str, Any]) -> Any:
        if dict(arguments) != dict(expected):
            raise NslRuntimeAdapterError(
                "NSL Tool arguments differ from the authoritative product binding."
            )
        return result

    return handler


def _principal_document(
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


def _validated_eos_authority(
    eos: Mapping[str, Any], *, request: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    project = eos.get("project")
    accounts = eos.get("accounts")
    if (
        not isinstance(project, Mapping)
        or project.get("project_code") != request["project_code"]
        or project.get("status") != "ACTIVE"
        or not isinstance(accounts, list)
        or len(accounts) != 2
    ):
        raise ProductControlledSkillError("EOS Project authority is invalid.")
    if any(not isinstance(item, Mapping) for item in accounts):
        raise ProductControlledSkillError("EOS Account authority is invalid.")
    debit, credit = (dict(accounts[0]), dict(accounts[1]))
    if (
        debit.get("account_code") != request["account_codes"][0]
        or credit.get("account_code") != request["account_codes"][1]
        or debit.get("status") != "ACTIVE"
        or credit.get("status") != "ACTIVE"
    ):
        raise ProductControlledSkillError("EOS Account authority is invalid.")
    return dict(project), debit, credit


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
        result_contract_ref=PRODUCT_RESULT_CONTRACT,
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


def _bundle_hash(bundle: NslRuntimeBundle) -> str:
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


def _resolve_admission_lock(
    manifest_path: Path, bundle: NslRuntimeBundle
) -> Path:
    candidates = (
        manifest_path.parents[1] / bundle.admission_lock,
        manifest_path.parent / Path(bundle.admission_lock).name,
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise ProductControlledSkillError("NSL wheel admission lock is unavailable.")


def _json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProductControlledSkillError("JSON authority is unavailable.") from exc
    if not isinstance(value, Mapping):
        raise ProductControlledSkillError("JSON authority must be an object.")
    return dict(value)


def _json_mapping(value: object, label: str) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ProductControlledSkillError(f"Persisted {label} is malformed.") from exc
    if not isinstance(value, Mapping):
        raise ProductControlledSkillError(f"Persisted {label} must be an object.")
    return dict(value)


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ProductControlledSkillError(f"{label} must be an object.")
    return dict(value)


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ProductControlledSkillError("Authorization string set is invalid.")
    return tuple(sorted(set(value)))


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _retryable(exc: Exception) -> bool:
    return isinstance(exc, (httpx.HTTPError, OSError)) or bool(
        getattr(exc, "retryable", False)
    )
