from __future__ import annotations

import asyncio
import json
import re
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import Any

from mybee_ax.integrations import (
    M1_ALLOCATION_CAPABILITY_ID,
    M1_D04_CAPABILITY_ID,
    HttpCostAllocationProviderTransport,
    HttpProjectPnlProviderTransport,
    HttpProjectPnlRefreshProviderTransport,
    NexCostAllocationClient,
    NexProjectPnlClient,
    NexProjectPnlRefreshClient,
)
from mybee_ax.orchestration import M1FinancialResultIntegrator
from nex_runtime.business_context import (
    BusinessContextValidationError,
    validate_business_request_context,
)
from nex_runtime.nsl_package_admission import inspect_installed_nsl_package
from nex_runtime.nsl_runtime_adapter import (
    InstalledNslExecution,
    NslExecutionBinding,
    NslRuntimeToolError,
    execute_installed_nsl_read,
    load_installed_nsl_tool_catalog,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from nex_ae_api.accounting_allocation_plan import (
    materialize_accounting_allocation_plan,
)
from nex_ae_api.allocation_plan_resolution_runtime import (
    InstalledApprovedAllocationPlanResolution,
)
from nex_ae_api.business_result_summary import build_voucher_draft_summary
from nex_ae_api.controlled_skill_runtime import (
    ControlledExecutionAuthority,
    ControlledSkillRuntime,
    ControlledSkillRuntimeError,
    HttpOaAuthoritySource,
    principal_document,
)
from nex_ae_api.m1_accounting_allocation_runtime import (
    InstalledAccountingAllocationRuntime,
)
from nex_ae_api.m1_allocation_plan_composition import (
    resolve_accounting_allocation_plan_authority,
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
_WORKER_ERROR_CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_JOURNAL_REQUEST_SCOPE = "finance:journal:request-approval"
_JOURNAL_APPROVE_SCOPE = "finance:journal:approve"


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
        self.accounting_allocation = None
        if allocation_plan_resolution is not None:
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
                authority_resolver=self.resolve_accounting_allocation_plan_authority,
                registration=(
                    None
                    if transaction_preparation is None
                    else transaction_preparation.adapter.registration
                ),
            )
            self.accounting_allocation = InstalledAccountingAllocationRuntime(
                integrator=financial_result,
                authority=self._oa,
            )
        nsl_package_readiness = inspect_installed_nsl_package(
            _json_object(config.wheel_lock_path),
            platform_lock_path=config.platform_lock_path,
        )
        self.nsl_package_readiness = MappingProxyType(dict(nsl_package_readiness))
        self.public_api = load_nsl_v02_public_api(nsl_package_readiness)
        self._writers = {
            selection.capability.capability_id: _M1JournalControlledRuntime(
                sessions,
                selection=selection,
                package=self._packages[selection.capability.capability_id],
                gateway=self._gateway,
                config=config,
                public_api=self.public_api,
                catalog_hash=catalog.catalog_hash,
            )
            for selection in catalog.selections
            if selection.capability.capability_id == M1_D04_CAPABILITY_ID
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
        if self.accounting_allocation is not None:
            readiness["accounting_allocation"] = dict(
                self.accounting_allocation.readiness()
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
        product_planning_proposal_ref: Mapping[str, Any] | None = None,
    ):
        return materialize_m1_transaction_plan(
            work_intent=work_intent,
            agent_context=agent_context,
            capability_snapshot=capability_snapshot,
            preparation_checkpoint=preparation_checkpoint,
            product_planning_proposal_ref=product_planning_proposal_ref,
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

    def materialize_accounting_allocation_plan(
        self,
        *,
        work_intent: Mapping[str, Any],
        allocation_work_intent: Mapping[str, Any],
        agent_context: Mapping[str, Any],
        capability_snapshot: Mapping[str, Any],
    ):
        selection = self._catalog.select(M1_ALLOCATION_CAPABILITY_ID)
        return materialize_accounting_allocation_plan(
            work_intent=work_intent,
            allocation_work_intent=allocation_work_intent,
            agent_context=agent_context,
            capability_snapshot=capability_snapshot,
            installed_capability=selection.capability.capability,
        )

    def resolve_accounting_allocation_plan_authority(
        self,
        *,
        work_intent: Mapping[str, Any],
        allocation_authority_checkpoint: Mapping[str, Any],
        source_pool: Mapping[str, Any],
        correlation_id: str,
        existing_checkpoint: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        if self.allocation_plan_resolution is None:
            raise ProductSkillCatalogError(
                "PRODUCT_ALLOCATION_PLAN_RESOLVER_REQUIRED",
                "Installed AllocationPlan resolution is unavailable.",
            )
        return resolve_accounting_allocation_plan_authority(
            self.allocation_plan_resolution,
            work_intent=work_intent,
            allocation_authority_checkpoint=allocation_authority_checkpoint,
            source_pool=source_pool,
            correlation_id=correlation_id,
            existing_checkpoint=existing_checkpoint,
        )

    def initial(
        self,
        context: Any,
        dependencies: LocalSkillExecutorDependencies,
    ) -> P5ExecutorOutcome:
        selection = _read_stage(
            "ae.product_m1_capability_selection_failed",
            "Product capability selection failed.",
            lambda: self._selection(context),
        )
        if selection.operation_adapter.operation_semantics == "READ":
            return self._execute_read(context, dependencies, selection)
        if selection.capability.capability_id == M1_ALLOCATION_CAPABILITY_ID:
            return self._execute_accounting_allocation(context)
        writer = self._writers.get(selection.capability.capability_id)
        if writer is None:
            raise _worker_error("Product WRITE handler is unavailable.")
        return writer.initial(context, dependencies)

    def _execute_accounting_allocation(self, context: Any) -> P5ExecutorOutcome:
        if self.accounting_allocation is None:
            raise _worker_error("Accounting allocation runtime is unavailable.")
        persisted = _read_stage(
            "ae.product_accounting_allocation_context_resolution_failed",
            "Accounting allocation execution context resolution failed.",
            lambda: _allocation_execution_context(
                self._sessions,
                tenant_id=context.job["tenant_id"],
                execution_id=context.step["agent_execution_id"],
            ),
        )
        inputs = _read_stage(
            "ae.product_accounting_allocation_input_resolution_failed",
            "Accounting allocation input resolution failed.",
            lambda: _compiled_inputs(context),
        )
        encoded_intent = inputs.get("allocation_work_intent_json")
        if set(inputs) != {"allocation_work_intent_json"} or not isinstance(
            encoded_intent, str
        ):
            raise _worker_error("Accounting allocation input contract differs.")
        try:
            allocation_intent = json.loads(encoded_intent)
        except (TypeError, ValueError) as exc:
            raise _worker_error(
                "Accounting allocation WorkIntent JSON is invalid."
            ) from exc
        if (
            allocation_intent.get("work_intent_id")
            != persisted["work_intent"]["work_intent_id"]
            or allocation_intent.get("execution_id")
            != context.step["agent_execution_id"]
            or allocation_intent.get("subject_id") != persisted["principal_id"]
            or allocation_intent.get("tenant_id") != context.job["tenant_id"]
        ):
            raise _worker_error("Accounting allocation persisted lineage differs.")
        result = _read_stage(
            "ae.product_accounting_allocation_execution_failed",
            "Accounting allocation execution failed.",
            lambda: self.accounting_allocation.execute(
                tenant_id=context.job["tenant_id"],
                company_id=allocation_intent["company_id"],
                subject_id=persisted["principal_id"],
                correlation_id=persisted["correlation_id"],
                journal_id=allocation_intent["journal_id"],
                work_intent=allocation_intent,
                runtime_job=context.job,
            ),
        )
        financial = result.get("financial_result")
        if not isinstance(financial, Mapping):
            raise _worker_error("Accounting allocation financial result is invalid.")
        projects = financial.get("project_results")
        if not isinstance(projects, (list, tuple)):
            raise _worker_error("Accounting allocation result references are invalid.")
        external_refs = tuple(
            sorted(
                {
                    str(result["journal_ref"]),
                    str(financial["allocation_batch_ref"]),
                    *(
                        f"eos.project-pnl-projection:{item['projection_id']}"
                        for item in projects
                        if isinstance(item, Mapping) and item.get("projection_id")
                    ),
                }
            )
        )
        return P5ExecutorOutcome(
            state="SUCCEEDED",
            result_contract_ref=str(context.step["output_contract_ref"]),
            result_payload=dict(result),
            external_refs=external_refs,
            evidence_refs=(
                f"release:{self._catalog.release_hash}",
                f"allocation-authority:{result['allocation_execution_authority_hash']}",
            ),
            business_operation_id=str(financial["allocation_business_operation_id"]),
        )

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
        persisted = _read_stage(
            "ae.product_m1_read_context_resolution_failed",
            "Product READ execution context resolution failed.",
            lambda: _execution_context(
                self._sessions,
                tenant_id=context.job["tenant_id"],
                execution_id=context.step["agent_execution_id"],
            ),
        )
        authorization = _read_stage(
            "ae.product_m1_read_authorization_failed",
            "Product READ authorization resolution failed.",
            lambda: self._oa.effective_authorization(
                tenant_id=context.job["tenant_id"],
                subject_id=persisted["principal_id"],
            ),
        )
        required_scope = _read_stage(
            "ae.product_m1_read_scope_contract_failed",
            "Product READ scope contract resolution failed.",
            lambda: str(
                selection.verified_skill.skill.required_tools[0].required_scope
            ),
        )
        if required_scope not in authorization.get("scopes", ()):
            raise _worker_error("OA denied the product READ scope.")
        inputs = _read_stage(
            "ae.product_m1_read_input_resolution_failed",
            "Product READ input resolution failed.",
            lambda: _compiled_inputs(context),
        )
        context_projection = _read_stage(
            "ae.product_m1_read_context_projection_failed",
            "Product READ context projection failed.",
            lambda: _context_projection(
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
            ),
        )
        adapters = _read_stage(
            "ae.product_m1_read_adapter_composition_failed",
            "Product READ adapter composition failed.",
            lambda: selection.build_adapters(
                ProductOperationAdapterContext(
                    environ={
                        "NEX_EOS_BASE_URL": self._config.eos_base_url,
                        "NEX_AE_TO_EOS_SERVICE_TOKEN": (
                            self._config.ae_to_eos_service_token
                        ),
                    }
                )
            ),
        )
        artifact = _read_stage(
            "ae.product_m1_read_artifact_admission_failed",
            "Product READ Skill artifact admission failed.",
            lambda: dependencies.artifact_gateway.resolve_verified(
                tenant_id=context.job["tenant_id"],
                skill_id=selection.release_skill.skill_id,
                exact_version=selection.release_skill.skill_version,
                expected_semantic_hash=selection.release_skill.semantic_hash,
                runtime_contract_ref=selection.capability.capability[
                    "local_skill_binding"
                ]["runtime_contract_ref"],
                trust_policy_id=selection.release_skill.trust_policy_id,
                environment="staging",
                observed_at=_now(),
            ),
        )
        bound = _read_stage(
            "ae.product_m1_read_binding_failed",
            "Product READ execution binding failed.",
            lambda: dependencies.binding_repository.bind_request(
                tenant_id=context.job["tenant_id"],
                executable_step_id=context.step["executable_step_id"],
                verified_artifact_ref=artifact["artifact_ref"],
                context_projection=context_projection,
                compiled_inputs=inputs,
                input_provenance={name: "EXECUTABLE_PLAN" for name in inputs},
                now=_now(),
            ),
        )
        binding = bound["binding"]
        _read_stage(
            "ae.product_m1_read_binding_failed",
            "Product READ invocation binding failed.",
            lambda: dependencies.binding_repository.mark_invocation_started(
                tenant_id=context.job["tenant_id"],
                executable_step_id=context.step["executable_step_id"],
                now=_now(),
            ),
        )
        business_operation_id = str(binding["business_operation_id"])
        try:
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
        except NslRuntimeToolError as exc:
            raise _bounded_worker_error(
                exc,
                fallback_code="ae.product_m1_read_execution_failed",
                detail="Product READ Tool execution failed.",
            ) from exc
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
    ) -> None:
        self._sessions = sessions
        self._selection = selection
        self._write_tool_version = _required_write_tool_version(selection)
        self._package = package
        self._gateway = gateway
        self._config = SimpleNamespace(
            approver_role=config.approver_role,
            eos_base_url=config.eos_base_url,
            ae_to_eos_service_token=config.ae_to_eos_service_token,
        )
        self.public_api = public_api
        self._registry_hash = catalog_hash
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
        if _JOURNAL_REQUEST_SCOPE not in authorization.get("scopes", ()):
            raise ControlledSkillRuntimeError(
                "OA denied Journal approval request authority."
            )
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
            write_tool_version=self._write_tool_version,
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
            business_result_seed=_journal_business_result_seed(
                work_intent=persisted["work_intent"],
                preparation=preparation,
            ),
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
        seed = authority.business_result_seed
        if not isinstance(seed, Mapping):
            raise ControlledSkillRuntimeError(
                "Journal business-result seed is unavailable."
            )
        journal = (
            _committed_journal_projection(result, project_code=seed["project_code"])
            if base.state == "SUCCEEDED"
            else None
        )
        summary = build_voucher_draft_summary(
            commit_state=str(base.result_payload["commit_state"]),
            verification_status=base.result_payload.get("verification_status"),
            approval_state="APPROVED",
            business_operation_id=business_operation_id,
            voucher_number=None if journal is None else journal["journal_no"],
            amount=seed["amount"],
            currency=str(seed["currency"]),
            account_codes=seed["account_codes"],
            project_code=str(seed["project_code"]),
        )
        if base.state != "SUCCEEDED":
            return P5ExecutorOutcome(
                state=base.state,
                result_contract_ref=base.result_contract_ref,
                result_payload={
                    **dict(base.result_payload),
                    "business_summary": summary,
                },
                external_refs=base.external_refs,
                artifact_refs=base.artifact_refs,
                evidence_refs=base.evidence_refs,
                error_ref=base.error_ref,
                business_operation_id=base.business_operation_id,
            )
        assert journal is not None
        journal_id = journal["journal_id"]
        deferred = _deferred_accounting_operations(authority.runtime_metadata)
        return P5ExecutorOutcome(
            state=base.state,
            result_contract_ref=base.result_contract_ref,
            result_payload={
                **dict(base.result_payload),
                "journal_id": journal_id,
                "journal_ref": f"eos.posted_journal:{journal_id}",
                "deferred_operations": list(deferred),
                "business_summary": summary,
            },
            external_refs=tuple(
                sorted(
                    {
                        *base.external_refs,
                        f"eos.posted_journal:{journal_id}",
                    }
                )
            ),
            artifact_refs=base.artifact_refs,
            evidence_refs=base.evidence_refs,
            error_ref=base.error_ref,
            business_operation_id=base.business_operation_id,
        )


def _deferred_accounting_operations(
    runtime_metadata: Mapping[str, Any] | None,
) -> tuple[str, ...]:
    work_intent = (
        runtime_metadata.get("work_intent")
        if isinstance(runtime_metadata, Mapping)
        else None
    )
    context = (
        work_intent.get("business_request_context")
        if isinstance(work_intent, Mapping)
        else None
    )
    allocations = (
        context.get("requested_allocation") if isinstance(context, Mapping) else None
    )
    return ("FINANCE.COST_ALLOCATION.RUN",) if allocations else ()


def _journal_business_result_seed(
    *,
    work_intent: Mapping[str, Any],
    preparation: object,
) -> dict[str, Any]:
    context_value = work_intent.get("business_request_context")
    try:
        context = validate_business_request_context(context_value)
    except BusinessContextValidationError as exc:
        raise ControlledSkillRuntimeError(
            "Journal business context is invalid for result projection."
        ) from exc
    if (
        not isinstance(preparation, Mapping)
        or preparation.get("schema_version")
        != "nex.mybee.m1-transaction-preparation.v1"
        or preparation.get("stage") != "READY_FOR_D04"
        or preparation.get("business_context_hash") != context["context_hash"]
    ):
        raise ControlledSkillRuntimeError(
            "Journal preparation checkpoint differs from its business context."
        )
    authority = preparation.get("authority")
    if (
        not isinstance(authority, Mapping)
        or authority.get("schema_version") != "nex.mybee.m1-preparation-authority.v1"
    ):
        raise ControlledSkillRuntimeError(
            "Journal preparation authority is invalid for result projection."
        )
    project_code = context.get("primary_project_code")
    authority_project_code = authority.get("primary_project_code")
    if project_code is None:
        project_code = authority_project_code
    if not isinstance(project_code, str) or authority_project_code != project_code:
        raise ControlledSkillRuntimeError(
            "Journal Project authority differs from its business context."
        )
    debit_key = authority.get("debit_semantic_key")
    credit_key = authority.get("credit_semantic_key")
    if any(
        not isinstance(value, str) or not value.strip()
        for value in (debit_key, credit_key)
    ):
        raise ControlledSkillRuntimeError(
            "Journal account authority is invalid for result projection."
        )
    transaction = context["transaction"]
    return {
        "amount": transaction["amount"],
        "currency": transaction["currency"],
        "account_codes": [debit_key, credit_key],
        "project_code": project_code,
    }


@dataclass(frozen=True)
class _JournalAuthorizationSource:
    oa: Any = field(repr=False)
    evidence: Mapping[str, Any] | None = field(repr=False)
    authority: ControlledExecutionAuthority = field(repr=False)
    evaluated_at: datetime

    def resolve(self, request: Any) -> Mapping[str, Any]:
        if self.evidence is None:
            raise ControlledSkillRuntimeError("Platform approval evidence is missing.")
        approver_id = self.evidence.get("approver_id")
        evidence_integrity = self.evidence.get("evidence_integrity")
        if (
            not isinstance(approver_id, str)
            or not approver_id
            or not isinstance(evidence_integrity, str)
            or not evidence_integrity
        ):
            raise ControlledSkillRuntimeError(
                "Platform approval principal evidence is invalid."
            )
        if approver_id == request.subject_id:
            raise ControlledSkillRuntimeError(
                "Journal requester and approver must be different principals."
            )
        requester = self.oa.effective_authorization(
            tenant_id=request.tenant_id, subject_id=request.subject_id
        )
        if _JOURNAL_REQUEST_SCOPE not in requester.get("scopes", ()):
            raise ControlledSkillRuntimeError(
                "OA denied current Journal request authority."
            )
        approver = self.oa.effective_authorization(
            tenant_id=request.tenant_id, subject_id=approver_id
        )
        if _JOURNAL_APPROVE_SCOPE not in approver.get("scopes", ()):
            raise ControlledSkillRuntimeError(
                "OA denied current Journal approver authority."
            )
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
            "typed_parameters": {
                "operation": "JOURNAL_POST",
                "approver_ref": approver_id,
            },
            "business_object_type": "POSTED_JOURNAL",
        }
        descriptor["operation_fingerprint"] = semantic_sha256_hash_ref(descriptor)
        authority_revision = semantic_sha256_hash_ref(
            {
                "requester_revision_hash": requester["revision_hash"],
                "approver_revision_hash": approver["revision_hash"],
                "approval_evidence_integrity": evidence_integrity,
            }
        )
        return {
            "tenant_id": request.tenant_id,
            "business_operation_id": str(request.business_operation_id),
            "oa_decision_ref": f"oa-journal-write:{authority_revision}",
            "oa_allowed": True,
            "protected_operation": descriptor,
            "operation_trust_decision": {
                "decision": "ALLOW",
                "decision_mode": "RULE_EVALUATED",
                "assurance_level": "HIGH",
                "operation_fingerprint": descriptor["operation_fingerprint"],
                "rule_set_ref": "policy:nex-product-journal-write",
                "rule_set_version": "1",
                "facts_hash": semantic_sha256_hash_ref(
                    {
                        "requester_authorization": requester,
                        "approver_authorization": approver,
                        "approval_evidence_integrity": evidence_integrity,
                    }
                ),
                "proof_ref": f"approval-evidence:{evidence_integrity}",
                "reason_code": None,
                "decision_hash": semantic_sha256_hash_ref(
                    {
                        "descriptor": descriptor,
                        "authority_revision": authority_revision,
                    }
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


def _allocation_execution_context(
    sessions: sessionmaker[Session], *, tenant_id: str, execution_id: str
) -> dict[str, Any]:
    with sessions() as session:
        row = (
            session.execute(
                text(
                    "SELECT context.principal_id, execution.correlation_id, "
                    "intent.intent_json FROM ae_agent_context AS context "
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
    work_intent = row["intent_json"]
    if isinstance(work_intent, str):
        work_intent = json.loads(work_intent)
    if not isinstance(work_intent, Mapping):
        raise ControlledSkillRuntimeError("Persisted WorkIntent is invalid.")
    return {
        "principal_id": str(row["principal_id"]),
        "correlation_id": str(row["correlation_id"]),
        "work_intent": dict(work_intent),
    }


def _committed_journal_projection(result: Any, *, project_code: str) -> dict[str, Any]:
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
        journal_id = str(uuid.UUID(candidate))
    except (ValueError, AttributeError) as exc:
        raise ControlledSkillRuntimeError(
            "Committed Journal result reference is invalid."
        ) from exc
    envelope = getattr(write_result, "value", None)
    value = getattr(envelope, "value", None)
    journal_no = value.get("journal_no") if isinstance(value, Mapping) else None
    project_codes = value.get("project_codes") if isinstance(value, Mapping) else None
    if (
        not isinstance(journal_no, str)
        or not journal_no.strip()
        or not isinstance(project_codes, list)
        or project_code not in project_codes
    ):
        raise ControlledSkillRuntimeError(
            "Committed Journal result projection is invalid."
        )
    return {
        "journal_id": journal_id,
        "journal_no": journal_no.strip(),
        "project_codes": list(project_codes),
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


def _required_write_tool_version(selection: ProductSkillSelection) -> str:
    capability_id = selection.capability.capability_id
    required_tools = tuple(
        tool
        for tool in selection.verified_skill.skill.required_tools
        if tool.tool_id == capability_id
    )
    if len(required_tools) != 1 or not str(required_tools[0].version).strip():
        raise ProductSkillCatalogError(
            "PRODUCT_SKILL_WRITE_TOOL_CONTRACT_INVALID",
            "The signed WRITE Skill must require exactly one matching Tool contract.",
        )
    return str(required_tools[0].version)


def _worker_error(detail: str) -> P5StepExecutorError:
    return P5StepExecutorError("ae.product_m1_runtime_invalid", detail)


def _read_stage(
    fallback_code: str,
    detail: str,
    callback: Callable[[], Any],
) -> Any:
    try:
        return callback()
    except P5StepExecutorError:
        raise
    except Exception as exc:
        raise _bounded_worker_error(
            exc,
            fallback_code=fallback_code,
            detail=detail,
        ) from exc


def _bounded_worker_error(
    exc: Exception,
    *,
    fallback_code: str,
    detail: str,
) -> P5StepExecutorError:
    candidate = getattr(exc, "error_code", None)
    error_code = (
        candidate
        if isinstance(candidate, str) and _WORKER_ERROR_CODE.fullmatch(candidate)
        else fallback_code
    )
    return P5StepExecutorError(
        error_code,
        detail,
        getattr(exc, "retryable", False) is True,
    )


def _json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return value


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
