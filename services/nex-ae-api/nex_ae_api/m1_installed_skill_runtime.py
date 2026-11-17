from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import Any

from mybee_ax.integrations import (
    HttpCostAllocationProviderTransport,
    HttpProjectPnlProviderTransport,
    HttpProjectPnlRefreshProviderTransport,
    NexCostAllocationClient,
    NexProjectPnlClient,
    NexProjectPnlRefreshClient,
)
from mybee_ax.orchestration import M1FinancialResultIntegrator
from nex_runtime.nsl_package_admission import inspect_installed_nsl_package
from nex_runtime.nsl_runtime_adapter import (
    InstalledNslExecution,
    NslExecutionBinding,
    execute_installed_nsl_read,
    load_installed_nsl_tool_catalog,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from nex_ae_api.allocation_plan_resolution_runtime import (
    InstalledApprovedAllocationPlanResolution,
)
from nex_ae_api.business_result_summary import build_project_allocation_summary
from nex_ae_api.controlled_skill_runtime import (
    ControlledExecutionAuthority,
    ControlledSkillRuntime,
    ControlledSkillRuntimeError,
    HttpOaAuthoritySource,
    principal_document,
)
from nex_ae_api.m1_allocation_plan_composition import (
    resolve_m1_allocation_plan_authority,
)
from nex_ae_api.m1_plan_materialization import materialize_m1_transaction_plan
from nex_ae_api.m1_transaction_preparation_runtime import (
    InstalledM1TransactionPreparation,
)
from nex_ae_api.nsl_controlled_write_integration import (
    NslControlledWriteIntegration,
    NslControlledWriteRequest,
)
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
from nex_ae_api.product_skill_catalog import (
    ProductOperationAdapterContext,
    ProductSkillCatalogError,
    ProductSkillSelection,
    VerifiedProductSkillCatalog,
)
from nex_ae_api.skill_artifacts import (
    SkillArtifactGateway,
    SqlAlchemySkillArtifactRepository,
)
from nex_ae_api.step_executors import (
    LocalSkillExecutorDependencies,
    P5ExecutorOutcome,
    P5StepExecutorError,
)

M1_BACKEND_PROFILE = "NSL_V02_IN_PROCESS"
_READ_RESULT_CONTRACT = "contract://nex/mybee/project-work-code-set/v1"
_WRITE_INPUTS = frozenset(
    {
        "schema_version",
        "tenant_id",
        "company_id",
        "candidate_id",
        "expected_candidate_version",
        "expected_candidate_revision",
        "expected_candidate_hash",
        "accounting_approval_evidence_id",
    }
)
_PREPARATION_INPUT = "m1_preparation_checkpoint"


@dataclass(frozen=True)
class M1InstalledSkillRuntimeConfig:
    wheel_lock_path: Path
    wheel_path: Path
    platform_lock_path: Path
    tool_catalog_path: Path
    context_path: Path
    state_root: Path
    oa_base_url: str
    eos_base_url: str
    ae_to_oa_service_token: str
    ae_to_eos_service_token: str
    approver_role: str = "finance_approver"


@dataclass(frozen=True)
class _VerifiedPackageView:
    selection: ProductSkillSelection = field(repr=False)
    catalog: Any = field(repr=False)
    skill_root: Path
    state_root: Path

    @property
    def skill(self) -> Any:
        return self.selection.verified_skill.skill

    def execution(self, **values: Any) -> InstalledNslExecution:
        return InstalledNslExecution(package=self, **values)


class M1InstalledSkillRuntime:
    """Capability-selected installed runtime over exact signed D12/D04 Skills."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        catalog: VerifiedProductSkillCatalog,
        config: M1InstalledSkillRuntimeConfig,
        transaction_preparation: InstalledM1TransactionPreparation | None = None,
        allocation_plan_resolution: InstalledApprovedAllocationPlanResolution
        | None = None,
    ) -> None:
        self._sessions = sessions
        self._catalog = catalog
        self._config = config
        self.transaction_preparation = transaction_preparation
        self.allocation_plan_resolution = allocation_plan_resolution
        self._tool_catalog = load_installed_nsl_tool_catalog(config.tool_catalog_path)
        self._packages = {
            selection.capability.capability_id: _VerifiedPackageView(
                selection=selection,
                catalog=self._tool_catalog,
                skill_root=config.context_path.parent,
                state_root=config.state_root,
            )
            for selection in catalog.selections
        }
        self._gateway = SkillArtifactGateway(
            resolver=_ReleaseResolver(catalog),
            admission_source=_ReleaseAdmissionSource(catalog),
            repository=SqlAlchemySkillArtifactRepository(sessions),
        )
        self._bindings = SqlAlchemyNSLStepExecutionRepository(sessions)
        self._oa = HttpOaAuthoritySource(
            base_url=config.oa_base_url,
            service_token=config.ae_to_oa_service_token,
        )
        financial_result = None
        if (
            transaction_preparation is not None
            and allocation_plan_resolution is not None
        ):
            financial_result = M1FinancialResultIntegrator(
                allocation_client=NexCostAllocationClient(
                    HttpCostAllocationProviderTransport(
                        eos_base_url=config.eos_base_url,
                        service_token=config.ae_to_eos_service_token,
                    )
                ),
                refresh_client=NexProjectPnlRefreshClient(
                    HttpProjectPnlRefreshProviderTransport(
                        eos_base_url=config.eos_base_url,
                        service_token=config.ae_to_eos_service_token,
                    )
                ),
                pnl_client=NexProjectPnlClient(
                    HttpProjectPnlProviderTransport(
                        eos_base_url=config.eos_base_url,
                        service_token=config.ae_to_eos_service_token,
                    )
                ),
                authority_resolver=self.resolve_allocation_plan_authority,
                registration=transaction_preparation.adapter.registration,
            )
        self.public_api = load_nsl_v02_public_api(
            inspect_installed_nsl_package(
                _json_object(config.wheel_lock_path),
                platform_lock_path=config.platform_lock_path,
            )
        )
        self._writers = {
            selection.capability.capability_id: _M1JournalControlledRuntime(
                sessions,
                selection=selection,
                package=self._packages[selection.capability.capability_id],
                gateway=self._gateway,
                config=config,
                public_api=self.public_api,
                catalog_hash=catalog.catalog_hash,
                financial_result=financial_result,
            )
            for selection in catalog.selections
            if selection.operation_adapter.operation_semantics == "WRITE"
        }
        readiness = {
            "status": "READY",
            "backend_profile": M1_BACKEND_PROFILE,
            "release_id": catalog.release_id,
            "release_hash": catalog.release_hash,
            "catalog_hash": catalog.catalog_hash,
            "capabilities": tuple(
                item.capability.capability_id for item in catalog.selections
            ),
        }
        if transaction_preparation is not None:
            readiness["transaction_preparation"] = transaction_preparation.readiness()
        if allocation_plan_resolution is not None:
            readiness["allocation_plan_resolution"] = (
                allocation_plan_resolution.readiness()
            )
        self.package_readiness = MappingProxyType(readiness)

    @property
    def backend_profile(self) -> str:
        return M1_BACKEND_PROFILE

    @property
    def dependencies(self) -> LocalSkillExecutorDependencies:
        return LocalSkillExecutorDependencies(
            artifact_gateway=self._gateway,
            binding_repository=self._bindings,
            request_builder=lambda **_values: {},
            backend=self,
            result_mapper=lambda value: value,
        )

    def execute(self, **_values: Any) -> dict[str, Any]:
        raise ProductSkillCatalogError(
            "PRODUCT_RUNTIME_HANDLER_REQUIRED",
            "Installed product execution requires the worker handler.",
        )

    def materialize_transaction_plan(
        self,
        *,
        work_intent: Mapping[str, Any],
        agent_context: Mapping[str, Any],
        capability_snapshot: Mapping[str, Any],
        preparation_checkpoint: Mapping[str, Any],
    ):
        return materialize_m1_transaction_plan(
            work_intent=work_intent,
            agent_context=agent_context,
            capability_snapshot=capability_snapshot,
            preparation_checkpoint=preparation_checkpoint,
            installed_capabilities={
                item.capability.capability_id: item.capability.capability
                for item in self._catalog.selections
            },
        )

    def resolve_allocation_plan_authority(
        self,
        *,
        work_intent: Mapping[str, Any],
        preparation_checkpoint: Mapping[str, Any],
        source_pool: Mapping[str, Any],
        correlation_id: str,
        existing_checkpoint: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        if self.allocation_plan_resolution is None:
            raise ProductSkillCatalogError(
                "PRODUCT_ALLOCATION_PLAN_RESOLVER_REQUIRED",
                "Installed AllocationPlan resolution is unavailable.",
            )
        return resolve_m1_allocation_plan_authority(
            self.allocation_plan_resolution,
            work_intent=work_intent,
            preparation_checkpoint=preparation_checkpoint,
            source_pool=source_pool,
            correlation_id=correlation_id,
            existing_checkpoint=existing_checkpoint,
        )

    def initial(
        self,
        context: Any,
        dependencies: LocalSkillExecutorDependencies,
    ) -> P5ExecutorOutcome:
        selection = self._selection(context)
        if selection.operation_adapter.operation_semantics == "READ":
            return self._execute_read(context, dependencies, selection)
        writer = self._writers.get(selection.capability.capability_id)
        if writer is None:
            raise _worker_error("Product WRITE handler is unavailable.")
        return writer.initial(context, dependencies)

    def resume(
        self,
        context: Any,
        dependencies: LocalSkillExecutorDependencies,
        continuation: Any,
    ) -> P5ExecutorOutcome:
        selection = self._selection(context)
        writer = self._writers.get(selection.capability.capability_id)
        if writer is None:
            raise _worker_error("Product READ Skill cannot consume a continuation.")
        return writer.resume(context, dependencies, continuation)

    def _selection(self, context: Any) -> ProductSkillSelection:
        capability_id = str(context.step.get("required_capability") or "")
        selection = self._catalog.select(capability_id)
        binding = context.step.get("skill_binding")
        if not isinstance(binding, Mapping) or (
            binding.get("skill_id"),
            binding.get("exact_skill_version"),
            binding.get("skill_semantic_hash"),
            binding.get("trust_policy_id"),
        ) != (
            selection.release_skill.skill_id,
            selection.release_skill.skill_version,
            selection.release_skill.semantic_hash,
            selection.release_skill.trust_policy_id,
        ):
            raise _worker_error("ExecutableStep differs from the signed Skill catalog.")
        return selection

    def _execute_read(
        self,
        context: Any,
        dependencies: LocalSkillExecutorDependencies,
        selection: ProductSkillSelection,
    ) -> P5ExecutorOutcome:
        persisted = _execution_context(
            self._sessions,
            tenant_id=context.job["tenant_id"],
            execution_id=context.step["agent_execution_id"],
        )
        authorization = self._oa.effective_authorization(
            tenant_id=context.job["tenant_id"], subject_id=persisted["principal_id"]
        )
        required_scope = str(
            selection.verified_skill.skill.required_tools[0].required_scope
        )
        if required_scope not in authorization.get("scopes", ()):
            raise _worker_error("OA denied the product READ scope.")
        inputs = _compiled_inputs(context)
        context_projection = _context_projection(
            persisted=persisted,
            principal_document={
                **principal_document(
                    tenant_id=context.job["tenant_id"],
                    principal_id=persisted["principal_id"],
                    authorization=authorization,
                ),
                "on_behalf_of": None,
            },
            authorization=authorization,
        )
        adapters = selection.build_adapters(
            ProductOperationAdapterContext(
                environ={
                    "NEX_EOS_BASE_URL": self._config.eos_base_url,
                    "NEX_AE_TO_EOS_SERVICE_TOKEN": self._config.ae_to_eos_service_token,
                }
            )
        )
        artifact = dependencies.artifact_gateway.resolve_verified(
            tenant_id=context.job["tenant_id"],
            skill_id=selection.release_skill.skill_id,
            exact_version=selection.release_skill.skill_version,
            expected_semantic_hash=selection.release_skill.semantic_hash,
            runtime_contract_ref=selection.capability.capability["local_skill_binding"][
                "runtime_contract_ref"
            ],
            trust_policy_id=selection.release_skill.trust_policy_id,
            environment="staging",
            observed_at=_now(),
        )
        bound = dependencies.binding_repository.bind_request(
            tenant_id=context.job["tenant_id"],
            executable_step_id=context.step["executable_step_id"],
            verified_artifact_ref=artifact["artifact_ref"],
            context_projection=context_projection,
            compiled_inputs=inputs,
            input_provenance={name: "EXECUTABLE_PLAN" for name in inputs},
            now=_now(),
        )
        binding = bound["binding"]
        dependencies.binding_repository.mark_invocation_started(
            tenant_id=context.job["tenant_id"],
            executable_step_id=context.step["executable_step_id"],
            now=_now(),
        )
        business_operation_id = str(binding["business_operation_id"])
        data = execute_installed_nsl_read(
            skill=selection.verified_skill.skill,
            tool_catalog=self._tool_catalog,
            principal_document=dict(context_projection["verified_principal"]),
            execution_id=str(context.step["executable_step_id"]),
            inputs=inputs,
            runtime_context=_json_object(self._config.context_path),
            business_operation_id=business_operation_id,
            handlers=adapters.tool_handlers,
        )
        if data.get("status") != "COMPLETED" or len(data.get("outputs", ())) != 1:
            raise _worker_error("Product READ Skill did not complete exactly once.")
        payload = {item["name"]: item["value"] for item in data["outputs"][0]["fields"]}
        result_hash = semantic_sha256_hash_ref(payload)
        dependencies.binding_repository.mark_result_terminal(
            tenant_id=context.job["tenant_id"],
            executable_step_id=context.step["executable_step_id"],
            state="SUCCEEDED",
            result_summary_ref=f"AE:NSL_RESULT:{binding['nsl_execution_id']}",
            result_summary_hash=result_hash,
            completed_at=_now(),
        )
        return P5ExecutorOutcome(
            state="SUCCEEDED",
            result_contract_ref=str(
                context.step.get("output_contract_ref") or _READ_RESULT_CONTRACT
            ),
            result_payload=payload,
            evidence_refs=(
                artifact["artifact_ref"],
                f"release:{self._catalog.release_hash}",
            ),
            business_operation_id=business_operation_id,
        )


class _M1JournalControlledRuntime(ControlledSkillRuntime):
    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        selection: ProductSkillSelection,
        package: _VerifiedPackageView,
        gateway: SkillArtifactGateway,
        config: M1InstalledSkillRuntimeConfig,
        public_api: Any,
        catalog_hash: str,
        financial_result: M1FinancialResultIntegrator | None,
    ) -> None:
        self._sessions = sessions
        self._selection = selection
        self._package = package
        self._gateway = gateway
        self._config = SimpleNamespace(
            approver_role=config.approver_role,
            eos_base_url=config.eos_base_url,
            ae_to_eos_service_token=config.ae_to_eos_service_token,
        )
        self.public_api = public_api
        self._registry_hash = catalog_hash
        self._financial_result = financial_result
        self._evidence = SqlAlchemyPlatformApprovalEvidenceRepository(sessions)
        from nex_ae_api.nsl_approval_requests import (
            SqlAlchemyProtectedApprovalRequestStore,
        )

        self._request_store = SqlAlchemyProtectedApprovalRequestStore(sessions)
        self._oa = HttpOaAuthoritySource(
            base_url=config.oa_base_url,
            service_token=config.ae_to_oa_service_token,
        )

    @property
    def dependencies(self) -> LocalSkillExecutorDependencies:
        return LocalSkillExecutorDependencies(
            artifact_gateway=self._gateway,
            binding_repository=SqlAlchemyNSLStepExecutionRepository(self._sessions),
            request_builder=lambda **_values: {},
            backend=self,
            result_mapper=lambda value: value,
        )

    def _resolve_authority(self, context: Any) -> ControlledExecutionAuthority:
        persisted = _execution_context(
            self._sessions,
            tenant_id=context.job["tenant_id"],
            execution_id=context.step["agent_execution_id"],
        )
        inputs = _compiled_inputs(context)
        preparation = inputs.pop(_PREPARATION_INPUT, None)
        if (
            set(inputs) != _WRITE_INPUTS
            or inputs.get("tenant_id") != context.job["tenant_id"]
        ):
            raise ControlledSkillRuntimeError(
                "Journal Skill inputs do not match the admitted business contract."
            )
        authorization = self._oa.effective_authorization(
            tenant_id=context.job["tenant_id"], subject_id=persisted["principal_id"]
        )
        if "finance:journal:approve" not in authorization.get("scopes", ()):
            raise ControlledSkillRuntimeError("OA denied Journal approval authority.")
        principal = principal_document(
            tenant_id=context.job["tenant_id"],
            principal_id=persisted["principal_id"],
            authorization=authorization,
        )
        authority_hash = semantic_sha256_hash_ref(
            {
                "catalog_hash": self._registry_hash,
                "context_hash": persisted["context_hash"],
                "inputs": inputs,
                "oa_revision_hash": authorization["revision_hash"],
            }
        )
        binding = NslExecutionBinding(
            input_document=inputs,
            principal_document=principal,
            handlers={
                self._selection.capability.capability_id: lambda _arguments: {
                    "business_result_ref": "pending",
                    "journal_id": "00000000-0000-4000-8000-000000000000",
                    "journal_no": "pending",
                }
            },
            write_tool_id=self._selection.capability.capability_id,
            write_tool_version=self._selection.release_skill.skill_version,
            precondition_evidence_ref=f"product-authority:{authority_hash}",
        )
        return ControlledExecutionAuthority(
            context_projection=build_context_projection(
                agent_context_ref=persisted["context_ref"],
                agent_context_hash=persisted["context_hash"],
                runtime_context_entries=(),
                explicit_resource_refs=(f"EOS:PROJECT:{persisted['project_id']}",),
                verified_principal={
                    **principal,
                    "roles": list(principal["roles"]),
                    "scopes": list(principal["scopes"]),
                    "on_behalf_of": None,
                },
                authority={
                    "effective_role_bindings": list(principal["roles"]),
                    "org_scope": list(authorization.get("org_scope_refs", ())),
                    "project_scope": [persisted["project_id"]],
                },
                data_policy={
                    "policy_ref": "OA:DATA_POLICY:M1_JOURNAL_WRITE",
                    "max_trace_classification": "CONFIDENTIAL",
                    "snapshot_retention_days": 30,
                    "audit_retention_days": 90,
                },
            ),
            execution_binding=binding,
            canonical_write_payload=inputs,
            authority_hash=authority_hash,
            project_id=persisted["project_id"],
            agent_id=persisted["agent_id"],
            org_scope_refs=tuple(authorization.get("org_scope_refs", ())),
            business_result_seed=None,
            runtime_metadata={
                "work_intent": persisted["work_intent"],
                "preparation_checkpoint": preparation,
                "principal_id": persisted["principal_id"],
                "correlation_id": persisted["correlation_id"],
            },
        )

    def _execute_controlled_write(
        self,
        *,
        execution: InstalledNslExecution,
        invocation: Any,
        authority: ControlledExecutionAuthority,
    ) -> Any:
        contract = execution.contract
        adapters = self._selection.build_adapters(
            ProductOperationAdapterContext(
                environ={
                    "NEX_EOS_BASE_URL": self._config.eos_base_url,
                    "NEX_AE_TO_EOS_SERVICE_TOKEN": self._config.ae_to_eos_service_token,
                },
                public_api=self.public_api,
                result_type=contract.output_type,
                result_classification=contract.output_classification,
            )
        )
        if adapters.write_port is None or adapters.verification_port is None:
            raise ControlledSkillRuntimeError(
                "Journal operation adapters are incomplete."
            )
        request = execution.controlled_write_request(
            invocation=invocation,
            public_api=self.public_api,
            request_factory=NslControlledWriteRequest,
            canonical_write_payload=authority.canonical_write_payload,
            authority_hash=authority.authority_hash,
        )
        return asyncio.run(
            NslControlledWriteIntegration(
                public_api=self.public_api,
                policy_port=PlatformRuntimePolicyAdapter(
                    authorization_source=_JournalAuthorizationSource(
                        oa=self._oa,
                        evidence=self._evidence.get(
                            tenant_id=execution.tenant_id,
                            approval_request_id=invocation.approval_request_id,
                        ),
                        authority=authority,
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
                write_port=adapters.write_port,
                verification_port=adapters.verification_port,
            ).execute(request)
        )

    def _controlled_write_outcome(
        self,
        *,
        context: Any,
        result: Any,
        authority: ControlledExecutionAuthority,
        business_operation_id: str,
    ) -> P5ExecutorOutcome:
        base = super()._controlled_write_outcome(
            context=context,
            result=result,
            authority=authority,
            business_operation_id=business_operation_id,
        )
        if base.state != "SUCCEEDED":
            return base
        if self._financial_result is None or authority.runtime_metadata is None:
            raise ControlledSkillRuntimeError(
                "M1 financial result integration is not installed."
            )
        metadata = authority.runtime_metadata
        preparation = metadata.get("preparation_checkpoint")
        work_intent = metadata.get("work_intent")
        if not isinstance(preparation, Mapping) or not isinstance(
            work_intent, Mapping
        ):
            raise ControlledSkillRuntimeError(
                "M1 durable preparation lineage is unavailable."
            )
        financial = self._financial_result.integrate(
            tenant_id=str(context.job["tenant_id"]),
            company_id=str(authority.canonical_write_payload["company_id"]),
            subject_id=str(metadata["principal_id"]),
            correlation_id=str(metadata["correlation_id"]),
            journal_id=_committed_journal_id(result),
            work_intent=work_intent,
            preparation_checkpoint=preparation,
        )
        summary = build_project_allocation_summary(financial)
        return P5ExecutorOutcome(
            state=base.state,
            result_contract_ref=base.result_contract_ref,
            result_payload={
                **dict(base.result_payload),
                "financial_result": dict(financial),
                "business_summary": summary,
            },
            external_refs=tuple(
                sorted(
                    {
                        *base.external_refs,
                        str(financial["journal_ref"]),
                        str(financial["source_pool_ref"]),
                        str(financial["allocation_batch_ref"]),
                    }
                )
            ),
            artifact_refs=base.artifact_refs,
            evidence_refs=tuple(
                sorted(
                    {
                        *base.evidence_refs,
                        f"EOS:PNL_REFRESH:{financial['pnl_refresh_hash']}",
                        *(
                            f"EOS:PROJECT_PNL:{item['projection_id']}:v{item['projection_version']}"
                            for item in financial["project_results"]
                        ),
                    }
                )
            ),
            error_ref=base.error_ref,
            business_operation_id=base.business_operation_id,
        )


@dataclass(frozen=True)
class _JournalAuthorizationSource:
    oa: Any = field(repr=False)
    evidence: Mapping[str, Any] | None = field(repr=False)
    authority: ControlledExecutionAuthority = field(repr=False)
    evaluated_at: datetime

    def resolve(self, request: Any) -> Mapping[str, Any]:
        if self.evidence is None:
            raise ControlledSkillRuntimeError("Platform approval evidence is missing.")
        current = self.oa.effective_authorization(
            tenant_id=request.tenant_id, subject_id=request.subject_id
        )
        if "finance:journal:approve" not in current.get("scopes", ()):
            raise ControlledSkillRuntimeError("OA denied current Journal authority.")
        descriptor = {
            "tenant_id": request.tenant_id,
            "agent_execution_id": self.evidence["agent_execution_id"],
            "executable_step_id": self.evidence["executable_step_id"],
            "business_operation_id": str(request.business_operation_id),
            "actor_ref": request.subject_id,
            "agent_ref": self.authority.agent_id,
            "org_scope_refs": list(self.authority.org_scope_refs),
            "project_ref": self.authority.project_id,
            "resource_refs": [
                f"voucher_candidate:{self.authority.canonical_write_payload['candidate_id']}"
            ],
            "capability": "WRITE",
            "operation_class": "CREATE",
            "data_classification": "CONFIDENTIAL",
            "typed_parameters": {"operation": "JOURNAL_POST"},
            "business_object_type": "POSTED_JOURNAL",
        }
        descriptor["operation_fingerprint"] = semantic_sha256_hash_ref(descriptor)
        revision = str(current["revision_hash"])
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
                "rule_set_ref": "policy:nex-product-journal-write",
                "rule_set_version": "1",
                "facts_hash": semantic_sha256_hash_ref(current),
                "proof_ref": f"oa-revision:{revision}",
                "reason_code": None,
                "decision_hash": semantic_sha256_hash_ref(
                    {"descriptor": descriptor, "authorization_revision_hash": revision}
                ),
                "evaluated_at": _time(self.evaluated_at),
                "expires_at": _time(self.evaluated_at + timedelta(minutes=10)),
            },
            "required_assurance_level": "HIGH",
        }


class _ReleaseResolver:
    def __init__(self, catalog: VerifiedProductSkillCatalog) -> None:
        self._catalog = catalog

    def resolve(self, *, skill_id: str, skill_version: str) -> Any:
        matches = [
            item
            for item in self._catalog.selections
            if item.release_skill.skill_id == skill_id
            and item.release_skill.skill_version == skill_version
        ]
        if len(matches) != 1:
            raise ProductSkillCatalogError(
                "PRODUCT_VERIFIED_SKILL_REQUIRED", "Exact signed Skill is unavailable."
            )
        selection = matches[0]
        return SimpleNamespace(
            skill=selection.verified_skill.skill,
            package_hash=self._catalog.package_hash,
            signer_key_id=self._catalog.signing_key_id,
        )


class _ReleaseAdmissionSource:
    def __init__(self, catalog: VerifiedProductSkillCatalog) -> None:
        self._catalog = catalog

    def current_admission(self, **values: Any) -> Mapping[str, Any]:
        decided_at = self._catalog.admitted_at
        trust = {
            "evidence_ref": f"release:{self._catalog.release_id}",
            "package_id": values["package_id"],
            "package_hash": values["package_hash"],
            "publisher_id": "nex-platform-release",
            "signing_key_id": values["signing_key_id"],
            "verified_at": decided_at,
            "trust_policy_id": values["trust_policy_id"],
            "trust_status": "VALID",
            "governance_status": "ACTIVE",
            "governance_decision_ref": f"release-admission:{self._catalog.release_id}",
        }
        return {
            "trust_evidence": trust,
            "admission_decision": {
                "decision_id": f"release-admission:{self._catalog.release_id}",
                "decision": "ADMITTED",
                "package_id": values["package_id"],
                "package_hash": values["package_hash"],
                "publisher_id": trust["publisher_id"],
                "signing_key_id": values["signing_key_id"],
                "governance_status": "ACTIVE",
                "trust_policy_id": values["trust_policy_id"],
                "package_trust_evidence_ref": trust["evidence_ref"],
                "reason_codes": [],
                "decided_at": decided_at,
            },
        }


def _execution_context(
    sessions: sessionmaker[Session], *, tenant_id: str, execution_id: str
) -> dict[str, Any]:
    with sessions() as session:
        row = (
            session.execute(
                text(
                    "SELECT context.context_id, context.context_generation, "
                    "context.context_hash, context.context_json, "
                    "context.principal_id, context.agent_id, "
                    "execution.correlation_id, intent.intent_json "
                    "FROM ae_agent_context AS context "
                    "JOIN ae_agent_execution AS execution "
                    "ON execution.tenant_id = context.tenant_id "
                    "AND execution.agent_execution_id = context.agent_execution_id "
                    "JOIN ae_work_intent AS intent "
                    "ON intent.tenant_id = context.tenant_id "
                    "AND intent.work_intent_id = context.work_intent_id "
                    "WHERE context.tenant_id = :tenant_id "
                    "AND context.agent_execution_id = :execution_id "
                    "ORDER BY context.context_generation DESC LIMIT 1"
                ),
                {"tenant_id": tenant_id, "execution_id": execution_id},
            )
            .mappings()
            .one()
        )
    context = row["context_json"]
    if isinstance(context, str):
        context = json.loads(context)
    work_intent = row["intent_json"]
    if isinstance(work_intent, str):
        work_intent = json.loads(work_intent)
    if not isinstance(work_intent, Mapping):
        raise ControlledSkillRuntimeError("Persisted WorkIntent is invalid.")
    entities = (
        context.get("resolved_entities") if isinstance(context, Mapping) else None
    )
    projects = [
        item["resource_ref"]["resource_id"]
        for item in entities or ()
        if isinstance(item, Mapping)
        and isinstance(item.get("resource_ref"), Mapping)
        and item["resource_ref"].get("resource_type") == "PROJECT"
    ]
    if len(projects) != 1:
        raise ControlledSkillRuntimeError("One trusted Project context is required.")
    return {
        "context_ref": f"AE:AGENT_CONTEXT:{row['context_id']}:{row['context_generation']}",
        "context_hash": str(row["context_hash"]),
        "principal_id": str(row["principal_id"]),
        "agent_id": str(row["agent_id"]),
        "project_id": str(projects[0]),
        "correlation_id": str(row["correlation_id"]),
        "work_intent": dict(work_intent),
    }


def _committed_journal_id(result: Any) -> str:
    outcome = getattr(result, "outcome", None)
    write_result = getattr(outcome, "result", None)
    reference = str(getattr(write_result, "business_reference", ""))
    prefix = "eos.posted_journal:"
    if not reference.startswith(prefix):
        raise ControlledSkillRuntimeError(
            "Committed Journal result reference is unavailable."
        )
    candidate = reference[len(prefix) :]
    try:
        return str(uuid.UUID(candidate))
    except (ValueError, AttributeError) as exc:
        raise ControlledSkillRuntimeError(
            "Committed Journal result reference is invalid."
        ) from exc


def _compiled_inputs(context: Any) -> dict[str, Any]:
    dependencies = {
        item["compiled_step_key"]: item for item in context.dependency_results
    }
    values: dict[str, Any] = {}
    for binding in context.step.get("compiled_input_bindings", ()):
        name = str(binding.get("target_name") or "")
        kind = binding.get("binding_type")
        if not name or name in values:
            raise _worker_error("Compiled product input binding is invalid.")
        if kind == "LITERAL":
            values[name] = binding.get("value")
        elif kind == "COMPILED_STEP_OUTPUT":
            source = str(binding.get("source_ref") or "").split(":", 1)[0]
            if source not in dependencies:
                raise _worker_error("Product dependency output is unavailable.")
            values[name] = dependencies[source]["result_payload"]
        else:
            raise _worker_error("Product runtime requires resolved literal inputs.")
    if not values:
        raise _worker_error("Product runtime inputs are unavailable.")
    return values


def _context_projection(
    *,
    persisted: Mapping[str, Any],
    principal_document: Mapping[str, Any],
    authorization: Mapping[str, Any],
) -> dict[str, Any]:
    return build_context_projection(
        agent_context_ref=str(persisted["context_ref"]),
        agent_context_hash=str(persisted["context_hash"]),
        runtime_context_entries=(),
        explicit_resource_refs=(f"EOS:PROJECT:{persisted['project_id']}",),
        verified_principal={
            **principal_document,
            "roles": list(principal_document.get("roles", ())),
            "scopes": list(principal_document.get("scopes", ())),
        },
        authority={
            "effective_role_bindings": list(principal_document.get("roles", ())),
            "org_scope": list(authorization.get("org_scope_refs", ())),
            "project_scope": [persisted["project_id"]],
        },
        data_policy={
            "policy_ref": "OA:DATA_POLICY:M1_PRODUCT_RUNTIME",
            "max_trace_classification": "CONFIDENTIAL",
            "snapshot_retention_days": 30,
            "audit_retention_days": 90,
        },
    )


def _worker_error(detail: str) -> P5StepExecutorError:
    return P5StepExecutorError("ae.product_m1_runtime_invalid", detail)


def _json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return value


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
