from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import httpx
import nex_ae_api.m1_installed_skill_runtime as installed
import nex_ae_api.mybee_m1_skill_runtime as skill_runtime
import nex_ae_api.product_runtime_profile as runtime_profile
import pytest
from mybee_ax.integrations import M1_D04_CAPABILITY_ID, M1_D12_CAPABILITY_ID
from nex_ae_api.controlled_skill_runtime import (
    ControlledSkillRuntimeError,
    principal_document,
)
from nex_ae_api.m1_installed_skill_runtime import (
    M1InstalledSkillRuntime,
    _required_write_tool_version,
)
from nex_ae_api.multi_step_engine import StepExecutionContext
from nex_ae_api.mybee_m1_skill_runtime import build_mybee_m1_verified_skill_catalog
from nex_ae_api.nsl_eos_project_work_code_read import (
    EosProjectWorkCodeReadError,
    HttpEosProjectWorkCodeReadAdapter,
)
from nex_ae_api.product_runtime_profile import (
    VERIFIED_PRODUCT_RELEASE_PROFILE,
    build_product_runtime_executor_profile,
    load_verified_product_runtime_config,
)
from nex_ae_api.product_skill_catalog import (
    ProductOperationAdapterRegistration,
    ProductOperationAdapterRegistry,
    ProductOperationAdapterSet,
    ProductSkillCatalogError,
)
from nex_ae_api.step_executors import (
    LocalSkillExecutorDependencies,
    P5StepExecutorError,
)
from nex_runtime.nsl_runtime_adapter import NslExecutionBinding
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
TENANT = "V101"
PROJECT_ID = "11111111-1111-4111-8111-111111111114"
EXECUTION_ID = "22222222-2222-4222-8222-222222222224"
STEP_ID = "33333333-3333-4333-8333-333333333334"
BUSINESS_OPERATION_ID = "44444444-4444-4444-8444-444444444444"
NSL_EXECUTION_ID = "55555555-5555-4555-8555-555555555555"
HASH = "sha256:" + "a" * 64


def _environment() -> dict[str, str]:
    return {
        "NEX_AE_PRODUCT_RUNTIME_PROFILE": VERIFIED_PRODUCT_RELEASE_PROFILE,
        "NEX_AE_PRODUCT_CAPABILITY_REGISTRY_PATH": str(
            ROOT
            / "deployment/environments/ae-product-capability-registry.mybee-m1.v3.json"
        ),
        "NEX_OA_BASE_URL": "https://oa.example",
        "NEX_EOS_BASE_URL": "https://eos.example",
        "NEX_WC_BASE_URL": "https://wc.example",
        "NEX_AE_TO_OA_SERVICE_TOKEN": "oa-token",
        "NEX_AE_TO_EOS_SERVICE_TOKEN": "eos-token",
        "NEX_AE_TO_WC_SERVICE_TOKEN": "wc-token",
        "NEX_AE_NSL_STATE_ROOT": "/tmp/nex-ae-m1-runtime-test",
    }


def _sessions():
    return sessionmaker(bind=create_engine("sqlite+pysqlite:///:memory:"))


def _runtime() -> M1InstalledSkillRuntime:
    environment = _environment()
    return M1InstalledSkillRuntime(
        _sessions(),
        catalog=build_mybee_m1_verified_skill_catalog(environment),
        config=load_verified_product_runtime_config(environment),
    )


def test_verified_product_release_profile_is_fail_closed_and_ready(
    tmp_path: Path,
) -> None:
    profile = build_product_runtime_executor_profile(_sessions(), _environment())

    assert profile.executor_kinds == (
        "DETERMINISTIC_AGGREGATE",
        "DETERMINISTIC_REPORT",
        "LOCAL_SKILL",
        "P4_CHAT_RAG_COMPATIBILITY",
        "WC_DELEGATE_WORK",
    )
    assert profile.executor_backends["WC_DELEGATE_WORK"] == "NSL_V02_IN_PROCESS"
    assert profile.package_readiness == {
        "status": "READY",
        "backend_profile": "NSL_V02_IN_PROCESS",
        "release_id": "nex-mybee-m1-d04-d12-checkpoint-v2",
        "release_hash": "sha256:df57c14d1693dc5469f18a09a1e9bdaeef404b23d601263d533c3c38cb92c234",
        "catalog_hash": "sha256:6f17db256b58fbd0cf6ec390564c9c4ca459b7216e10fc3602043bea98b87bf2",
        "capabilities": tuple(sorted((M1_D04_CAPABILITY_ID, M1_D12_CAPABILITY_ID))),
        "runtime_profile": VERIFIED_PRODUCT_RELEASE_PROFILE,
        "admission_hash": "sha256:812f68e387069654f7598bb891d14626107631008d8520f75bf3aa26612a905a",
        "activation_hash": "sha256:bef2cb2f4314b0fd177fce1195c2bdd93c833330b3d7b00cd8908ce4cd0974f3",
        "transaction_preparation": {
            "schema_version": "ae.m1_transaction_preparation_runtime.v1",
            "status": "READY",
            "provider_service_id": "nex-eos",
            "adapter_id": "MYBEE.M1.AUTHORITATIVE_TRANSACTION_PREPARATION",
            "adapter_version": "1.0.0",
            "adapter_source_identity": (
                "mybee:m1-preparation:"
                "MYBEE.M1.AUTHORITATIVE_TRANSACTION_PREPARATION:1.0.0:"
                    "sha256:5eef656e73f922c16c39c17808503fc5cae477b00f9c64f832215d7acda8e2fe"
            ),
            "operations": [
                "BUSINESS.DOCUMENT_APPROVED.GET",
                "FINANCE.ACCOUNTING_APPROVAL.REQUEST",
                "FINANCE.VOUCHER_CANDIDATE.CREATE_V2",
                "FINANCE.VOUCHER_CANDIDATE.VALIDATE",
                "FINANCE.VOUCHER_CANDIDATE.REVIEW_GET",
                "FINANCE.VOUCHER_POSTING.ADMIT",
            ],
            "timeout_seconds": 15.0,
            "content_included": False,
            "secret_included": False,
            "readiness_hash": (
                "sha256:72fa3c033aecfdd6cf54118790b0086edcd67cb07ded89d67a50119179d03c6e"
            ),
        },
        "allocation_plan_resolution": {
            "schema_version": "ae.approved_allocation_plan_resolution_runtime.v1",
            "status": "READY",
            "provider_service_id": "nex-eos",
            "operation": "FINANCE.COST_ALLOCATION_PLAN.RESOLVE",
            "authority_schema": "mybee.approved_allocation_plan_authority.v1",
            "timeout_seconds": 15.0,
            "business_defaults_included": False,
            "content_included": False,
            "secret_included": False,
            "readiness_hash": (
                "sha256:9b52623852ed5b733e587e43ae872c5f08699905932b73ad720c1aaa2901ce5b"
            ),
        },
    }
    assert profile.in_process_package_readiness is not None
    assert profile.in_process_package_readiness["status"] == "PASS"
    assert (
        profile.in_process_package_readiness["schema_version"]
        == "nsl_installed_package_readiness.v2"
    )
    assert profile.in_process_package_readiness["package_version"] == "0.2.1"

    drifted = json.loads(
        (ROOT / "deployment/locks/ae-mybee-m1-runtime-activation.v3.json").read_text(
            encoding="utf-8"
        )
    )
    drifted["runtime_admission_hash"] = HASH
    path = tmp_path / "activation.json"
    path.write_text(json.dumps(drifted), encoding="utf-8")
    environment = {
        **_environment(),
        "NEX_AE_PRODUCT_RUNTIME_ACTIVATION_PATH": str(path),
    }
    with pytest.raises(ValueError, match="admission hash"):
        build_product_runtime_executor_profile(_sessions(), environment)


def test_signed_d04_prefix_suspends_only_after_real_checks_pass(
    tmp_path: Path,
) -> None:
    runtime = _runtime()
    package = replace(
        runtime._packages[M1_D04_CAPABILITY_ID],
        state_root=tmp_path,
    )
    execution = package.execution(
        tenant_id=TENANT,
        agent_execution_id=EXECUTION_ID,
        executable_step_id=STEP_ID,
        nsl_execution_id=NSL_EXECUTION_ID,
        business_operation_id=BUSINESS_OPERATION_ID,
        binding=NslExecutionBinding(
            input_document={
                "schema_version": "eos.journal_posting_command.v1",
                "tenant_id": TENANT,
                "company_id": "company-101",
                "candidate_id": "candidate-101",
                "expected_candidate_version": 1,
                "expected_candidate_revision": 1,
                "expected_candidate_hash": HASH,
                "accounting_approval_evidence_id": "approval-evidence-101",
            },
            principal_document=principal_document(
                tenant_id=TENANT,
                principal_id="employee-101",
                authorization={"roles": [], "scopes": [], "revision_hash": HASH},
            ),
            handlers={M1_D04_CAPABILITY_ID: lambda _arguments: {}},
            write_tool_id=M1_D04_CAPABILITY_ID,
            write_tool_version="1.0.0",
            precondition_evidence_ref="EOS:VOUCHER_CANDIDATE:candidate-101",
        ),
    )

    session = asyncio.run(execution.start(execution.file_state_port))

    assert session.result.validation.status.value == "ALL_PASS"
    assert session.checkpoint is not None
    assert session.approval_request is not None
    assert execution.existing_approval_request() is not None


def test_d04_skill_version_does_not_replace_required_tool_contract_version() -> None:
    selection = _runtime()._catalog.select(M1_D04_CAPABILITY_ID)

    assert selection.release_skill.skill_version == "1.0.1"
    assert _required_write_tool_version(selection) == "1.0.0"

    invalid_skill = replace(selection.verified_skill.skill, required_tools=())
    invalid_selection = replace(
        selection,
        verified_skill=replace(selection.verified_skill, skill=invalid_skill),
    )
    with pytest.raises(
        ProductSkillCatalogError,
        match="exactly one matching Tool contract",
    ):
        _required_write_tool_version(invalid_selection)


class _Gateway:
    def resolve_verified(self, **_values):
        return {"artifact_ref": "AE:NSL_ARTIFACT:m1-d12"}


class _Bindings:
    def __init__(self) -> None:
        self.states: list[str] = []

    def bind_request(self, **_values):
        self.states.append("REQUEST_BOUND")
        return {
            "binding": {
                "business_operation_id": BUSINESS_OPERATION_ID,
                "nsl_execution_id": NSL_EXECUTION_ID,
            }
        }

    def mark_invocation_started(self, **_values):
        self.states.append("RUNNING")

    def mark_result_terminal(self, **values):
        self.states.append(values["state"])


def _read_context(runtime: M1InstalledSkillRuntime, *, project_id: str = PROJECT_ID):
    selection = runtime._catalog.select(M1_D12_CAPABILITY_ID)
    binding = selection.capability.capability["local_skill_binding"]
    step = {
        "agent_execution_id": EXECUTION_ID,
        "executable_step_id": STEP_ID,
        "required_capability": M1_D12_CAPABILITY_ID,
        "output_contract_ref": selection.release_skill.output_contract_ref,
        "skill_binding": {
            "skill_id": selection.release_skill.skill_id,
            "exact_skill_version": selection.release_skill.skill_version,
            "skill_semantic_hash": selection.release_skill.semantic_hash,
            "trust_policy_id": selection.release_skill.trust_policy_id,
            "runtime_contract_ref": binding["runtime_contract_ref"],
        },
        "compiled_input_bindings": [
            {"target_name": "tenant_id", "binding_type": "LITERAL", "value": TENANT},
            {
                "target_name": "requester_subject_id",
                "binding_type": "LITERAL",
                "value": "employee-101",
            },
            {
                "target_name": "project_id",
                "binding_type": "LITERAL",
                "value": project_id,
            },
            {
                "target_name": "effective_on",
                "binding_type": "LITERAL",
                "value": "2026-11-15",
            },
        ],
    }
    return StepExecutionContext(
        job={"tenant_id": TENANT},
        attempt={"attempt_no": 1},
        step=step,
        dependency_results=(),
        existing_result=None,
    )


def _write_inputs(*, tenant_id: str = TENANT) -> dict[str, object]:
    return {
        "schema_version": "eos.journal_posting_command.v1",
        "tenant_id": tenant_id,
        "company_id": "77777777-7777-4777-8777-777777777777",
        "candidate_id": "88888888-8888-4888-8888-888888888888",
        "expected_candidate_version": 1,
        "expected_candidate_revision": 1,
        "expected_candidate_hash": HASH,
        "accounting_approval_evidence_id": ("99999999-9999-4999-8999-999999999999"),
    }


def _write_context(runtime: M1InstalledSkillRuntime, **input_overrides: object):
    selection = runtime._catalog.select(M1_D04_CAPABILITY_ID)
    inputs = {**_write_inputs(), **input_overrides}
    return StepExecutionContext(
        job={"tenant_id": TENANT},
        attempt={"attempt_no": 1},
        step={
            "agent_execution_id": EXECUTION_ID,
            "executable_step_id": STEP_ID,
            "required_capability": M1_D04_CAPABILITY_ID,
            "output_contract_ref": selection.release_skill.output_contract_ref,
            "skill_binding": {
                "skill_id": selection.release_skill.skill_id,
                "exact_skill_version": selection.release_skill.skill_version,
                "skill_semantic_hash": selection.release_skill.semantic_hash,
                "trust_policy_id": selection.release_skill.trust_policy_id,
            },
            "compiled_input_bindings": [
                {
                    "target_name": name,
                    "binding_type": "LITERAL",
                    "value": value,
                }
                for name, value in inputs.items()
            ],
        },
        dependency_results=(),
        existing_result=None,
    )


def test_installed_runtime_executes_exact_d12_skill_and_durable_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime()
    bindings = _Bindings()
    dependencies = LocalSkillExecutorDependencies(
        artifact_gateway=_Gateway(),
        binding_repository=bindings,
        request_builder=lambda **_values: {},
        backend=runtime,
        result_mapper=lambda value: value,
    )
    monkeypatch.setattr(
        installed,
        "_execution_context",
        lambda *_args, **_values: {
            "context_ref": "AE:AGENT_CONTEXT:m1:1",
            "context_hash": HASH,
            "principal_id": "employee-101",
            "agent_id": "66666666-6666-4666-8666-666666666666",
            "project_id": PROJECT_ID,
        },
    )
    runtime._oa = SimpleNamespace(
        effective_authorization=lambda **_values: {
            "roles": ["project_member"],
            "scopes": ["project:work-code:read"],
            "org_scope_refs": ["ORG:FINANCE"],
            "revision_hash": HASH,
        }
    )
    adapter = HttpEosProjectWorkCodeReadAdapter(
        base_url="https://eos.example",
        service_token="eos-token",
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={
                    "tenant_id": TENANT,
                    "project_id": PROJECT_ID,
                    "revision": 7,
                    "state": "APPROVED",
                    "work_set_hash": HASH,
                },
            )
        ),
    )
    monkeypatch.setattr(
        skill_runtime,
        "HttpEosProjectWorkCodeReadAdapter",
        lambda **_values: adapter,
    )

    result = runtime.initial(_read_context(runtime), dependencies)

    assert result.state == "SUCCEEDED"
    assert result.business_operation_id == BUSINESS_OPERATION_ID
    assert result.result_payload == {
        "project_id": PROJECT_ID,
        "revision": 7,
        "state": "APPROVED",
        "work_set_hash": HASH,
    }
    assert bindings.states == ["REQUEST_BOUND", "RUNNING", "SUCCEEDED"]


@pytest.mark.parametrize(
    ("failure", "expected_code", "expected_retryable"),
    [
        (
            EosProjectWorkCodeReadError(
                "ae.nsl_eos_project_work_code.rejected",
                "private EOS rejection detail",
                True,
                503,
            ),
            "ae.nsl_eos_project_work_code.rejected",
            True,
        ),
        (
            RuntimeError("private unexpected detail"),
            "ae.nsl_tool_handler_failed",
            False,
        ),
    ],
)
def test_installed_runtime_preserves_bounded_d12_tool_failure(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
    expected_code: str,
    expected_retryable: bool,
) -> None:
    runtime = _runtime()
    bindings = _Bindings()
    dependencies = LocalSkillExecutorDependencies(
        artifact_gateway=_Gateway(),
        binding_repository=bindings,
        request_builder=lambda **_values: {},
        backend=runtime,
        result_mapper=lambda value: value,
    )
    monkeypatch.setattr(
        installed,
        "_execution_context",
        lambda *_args, **_values: {
            "context_ref": "AE:AGENT_CONTEXT:m1:1",
            "context_hash": HASH,
            "principal_id": "employee-101",
            "agent_id": "66666666-6666-4666-8666-666666666666",
            "project_id": PROJECT_ID,
        },
    )
    runtime._oa = SimpleNamespace(
        effective_authorization=lambda **_values: {
            "roles": ["project_member"],
            "scopes": ["project:work-code:read"],
            "org_scope_refs": ["ORG:FINANCE"],
            "revision_hash": HASH,
        }
    )

    def fail(_arguments):
        raise failure

    monkeypatch.setattr(
        skill_runtime,
        "HttpEosProjectWorkCodeReadAdapter",
        lambda **_values: fail,
    )

    with pytest.raises(P5StepExecutorError) as captured:
        runtime.initial(_read_context(runtime), dependencies)

    assert captured.value.error_code == expected_code
    assert captured.value.retryable is expected_retryable
    assert captured.value.detail == "Product READ Tool execution failed."
    assert "private" not in str(captured.value)


def test_installed_runtime_read_stage_preserves_typed_error_and_bounds_unknown() -> None:
    typed = EosProjectWorkCodeReadError(
        "ae.nsl_eos_project_work_code.timeout",
        "private timeout detail",
        True,
    )

    with pytest.raises(P5StepExecutorError) as captured:
        installed._read_stage(
            "ae.product_m1_read_fallback",
            "Bounded stage failure.",
            lambda: (_ for _ in ()).throw(typed),
        )

    assert captured.value.error_code == "ae.nsl_eos_project_work_code.timeout"
    assert captured.value.retryable is True
    assert captured.value.detail == "Bounded stage failure."

    with pytest.raises(P5StepExecutorError) as captured:
        installed._read_stage(
            "ae.product_m1_read_context_resolution_failed",
            "Context resolution failed.",
            lambda: (_ for _ in ()).throw(RuntimeError("private context detail")),
        )

    assert (
        captured.value.error_code
        == "ae.product_m1_read_context_resolution_failed"
    )
    assert captured.value.retryable is False
    assert "private" not in str(captured.value)


def test_installed_runtime_read_stage_preserves_existing_worker_error() -> None:
    existing = P5StepExecutorError("ae.existing", "existing bounded detail", True)

    with pytest.raises(P5StepExecutorError) as captured:
        installed._read_stage(
            "ae.product_m1_read_fallback",
            "fallback",
            lambda: (_ for _ in ()).throw(existing),
        )

    assert captured.value is existing


def test_installed_runtime_rejects_cross_binding_and_unknown_capability() -> None:
    runtime = _runtime()
    context = _read_context(runtime)
    context.step["skill_binding"]["skill_semantic_hash"] = HASH
    with pytest.raises(P5StepExecutorError, match="differs"):
        runtime.initial(context, runtime.dependencies)

    context = _read_context(runtime)
    context.step.pop("skill_binding")
    with pytest.raises(P5StepExecutorError, match="differs"):
        runtime.initial(context, runtime.dependencies)

    context = _read_context(runtime)
    context.step["required_capability"] = "UNKNOWN.CAPABILITY.GET"
    with pytest.raises(P5StepExecutorError) as captured:
        runtime.initial(context, runtime.dependencies)
    assert captured.value.error_code == "PRODUCT_SKILL_CAPABILITY_NOT_ADMITTED"
    assert captured.value.detail == "Product capability selection failed."


def test_installed_runtime_rejects_missing_handlers_and_invalid_read_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime()
    with pytest.raises(ProductSkillCatalogError, match="worker handler"):
        runtime.execute()

    runtime._writers = {}
    with pytest.raises(P5StepExecutorError, match="WRITE handler"):
        runtime.initial(_write_context(runtime), runtime.dependencies)
    with pytest.raises(P5StepExecutorError, match="cannot consume"):
        runtime.resume(_read_context(runtime), runtime.dependencies, object())

    monkeypatch.setattr(
        installed,
        "_execution_context",
        lambda *_args, **_values: {
            "context_ref": "AE:AGENT_CONTEXT:m1:1",
            "context_hash": HASH,
            "principal_id": "employee-101",
            "agent_id": "66666666-6666-4666-8666-666666666666",
            "project_id": PROJECT_ID,
        },
    )
    runtime._oa = SimpleNamespace(
        effective_authorization=lambda **_values: {
            "roles": [],
            "scopes": [],
            "org_scope_refs": [],
            "revision_hash": HASH,
        }
    )
    with pytest.raises(P5StepExecutorError, match="denied"):
        runtime.initial(_read_context(runtime), runtime.dependencies)

    runtime._oa = SimpleNamespace(
        effective_authorization=lambda **_values: {
            "roles": ["project_member"],
            "scopes": ["project:work-code:read"],
            "org_scope_refs": [],
            "revision_hash": HASH,
        }
    )
    monkeypatch.setattr(
        installed,
        "execute_installed_nsl_read",
        lambda **_values: {"status": "COMPLETED", "outputs": []},
    )
    with pytest.raises(P5StepExecutorError, match="exactly once"):
        runtime.initial(
            _read_context(runtime),
            LocalSkillExecutorDependencies(
                artifact_gateway=_Gateway(),
                binding_repository=_Bindings(),
                request_builder=lambda **_values: {},
                backend=runtime,
                result_mapper=lambda value: value,
            ),
        )

    monkeypatch.setattr(
        installed,
        "execute_installed_nsl_read",
        lambda **_values: {
            "status": "FAILED",
            "outputs": [{"fields": []}],
        },
    )
    with pytest.raises(P5StepExecutorError, match="exactly once"):
        runtime.initial(
            _read_context(runtime),
            LocalSkillExecutorDependencies(
                artifact_gateway=_Gateway(),
                binding_repository=_Bindings(),
                request_builder=lambda **_values: {},
                backend=runtime,
                result_mapper=lambda value: value,
            ),
        )


def test_installed_runtime_delegates_write_initial_and_resume() -> None:
    runtime = _runtime()
    calls: list[str] = []
    writer = SimpleNamespace(
        initial=lambda *_args: calls.append("initial") or "INITIAL",
        resume=lambda *_args: calls.append("resume") or "RESUMED",
    )
    runtime._writers[M1_D04_CAPABILITY_ID] = writer
    context = _write_context(runtime)

    assert runtime.initial(context, runtime.dependencies) == "INITIAL"
    assert runtime.resume(context, runtime.dependencies, object()) == "RESUMED"
    assert calls == ["initial", "resume"]


@pytest.mark.parametrize(
    ("bindings", "dependencies", "message"),
    (
        ([], (), "inputs are unavailable"),
        (
            [
                {"target_name": "x", "binding_type": "LITERAL", "value": 1},
                {"target_name": "x", "binding_type": "LITERAL", "value": 2},
            ],
            (),
            "binding is invalid",
        ),
        (
            [
                {
                    "target_name": "x",
                    "binding_type": "COMPILED_STEP_OUTPUT",
                    "source_ref": "missing:result",
                }
            ],
            (),
            "dependency output is unavailable",
        ),
        (
            [{"target_name": "x", "binding_type": "RUNTIME", "value": 1}],
            (),
            "resolved literal inputs",
        ),
        (
            [{"binding_type": "LITERAL", "value": 1}],
            (),
            "binding is invalid",
        ),
    ),
)
def test_compiled_inputs_fail_closed(bindings, dependencies, message) -> None:
    context = SimpleNamespace(
        step={"compiled_input_bindings": bindings},
        dependency_results=dependencies,
    )
    with pytest.raises(P5StepExecutorError, match=message):
        installed._compiled_inputs(context)


def test_compiled_inputs_resolve_exact_dependency_output() -> None:
    context = SimpleNamespace(
        step={
            "compiled_input_bindings": [
                {
                    "target_name": "upstream",
                    "binding_type": "COMPILED_STEP_OUTPUT",
                    "source_ref": "S1:result",
                }
            ]
        },
        dependency_results=(
            {"compiled_step_key": "S1", "result_payload": {"state": "READY"}},
        ),
    )
    assert installed._compiled_inputs(context) == {"upstream": {"state": "READY"}}


class _ContextRows:
    def __init__(self, row) -> None:
        self._row = row

    def mappings(self):
        return self

    def one(self):
        return self._row


class _ContextSession:
    def __init__(self, row) -> None:
        self._row = row

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, *_args, **_kwargs):
        return _ContextRows(self._row)


def _context_sessions(context_json):
    row = {
        "context_id": "context-1",
        "context_generation": 2,
        "context_hash": HASH,
        "context_json": context_json,
        "principal_id": "employee-101",
        "agent_id": "66666666-6666-4666-8666-666666666666",
        "correlation_id": "corr-m1-runtime",
        "intent_json": {"intent_hash": HASH},
    }
    return lambda: _ContextSession(row)


def test_execution_context_accepts_serialized_single_project_and_rejects_ambiguity() -> (
    None
):
    document = {
        "resolved_entities": [
            {
                "resource_ref": {
                    "resource_type": "PROJECT",
                    "resource_id": PROJECT_ID,
                }
            }
        ]
    }
    observed = installed._execution_context(
        _context_sessions(json.dumps(document)),
        tenant_id=TENANT,
        execution_id=EXECUTION_ID,
    )
    assert observed["project_id"] == PROJECT_ID
    assert observed["context_ref"] == "AE:AGENT_CONTEXT:context-1:2"

    with pytest.raises(ControlledSkillRuntimeError, match="One trusted Project"):
        installed._execution_context(
            _context_sessions({"resolved_entities": []}),
            tenant_id=TENANT,
            execution_id=EXECUTION_ID,
        )

    mixed = {
        "resolved_entities": [
            "invalid",
            {"resource_ref": "invalid"},
            {
                "resource_ref": {
                    "resource_type": "DOCUMENT",
                    "resource_id": "document-1",
                }
            },
            document["resolved_entities"][0],
        ]
    }
    assert (
        installed._execution_context(
            _context_sessions(mixed),
            tenant_id=TENANT,
            execution_id=EXECUTION_ID,
        )["project_id"]
        == PROJECT_ID
    )


def test_release_resolver_and_json_object_fail_closed(tmp_path: Path) -> None:
    catalog = _runtime()._catalog
    selection = catalog.select(M1_D12_CAPABILITY_ID)
    resolved = installed._ReleaseResolver(catalog).resolve(
        skill_id=selection.release_skill.skill_id,
        skill_version=selection.release_skill.skill_version,
    )
    assert resolved.package_hash == catalog.package_hash
    with pytest.raises(ProductSkillCatalogError, match="unavailable"):
        installed._ReleaseResolver(catalog).resolve(
            skill_id="UNKNOWN.SKILL", skill_version="1.0.0"
        )

    invalid = tmp_path / "invalid.json"
    invalid.write_text("[]", encoding="utf-8")
    with pytest.raises(TypeError, match="JSON object"):
        installed._json_object(invalid)


def test_journal_authorization_requires_evidence_and_fresh_scope() -> None:
    request = SimpleNamespace(
        tenant_id=TENANT,
        subject_id="employee-101",
        business_operation_id=BUSINESS_OPERATION_ID,
    )
    authority = SimpleNamespace(
        agent_id="66666666-6666-4666-8666-666666666666",
        org_scope_refs=("ORG:FINANCE",),
        project_id=PROJECT_ID,
        canonical_write_payload={"candidate_id": "candidate-1"},
    )
    now = datetime(2026, 11, 15, tzinfo=UTC)
    with pytest.raises(ControlledSkillRuntimeError, match="evidence is missing"):
        installed._JournalAuthorizationSource(
            oa=object(), evidence=None, authority=authority, evaluated_at=now
        ).resolve(request)

    with pytest.raises(ControlledSkillRuntimeError, match="principal evidence"):
        installed._JournalAuthorizationSource(
            oa=object(),
            evidence={
                "agent_execution_id": EXECUTION_ID,
                "executable_step_id": STEP_ID,
            },
            authority=authority,
            evaluated_at=now,
        ).resolve(request)

    denied = installed._JournalAuthorizationSource(
        oa=SimpleNamespace(
            effective_authorization=lambda **_values: {
                "scopes": [],
                "revision_hash": HASH,
            }
        ),
        evidence={
            "agent_execution_id": EXECUTION_ID,
            "executable_step_id": STEP_ID,
            "approver_id": "employee-202",
            "evidence_integrity": HASH,
        },
        authority=authority,
        evaluated_at=now,
    )
    with pytest.raises(ControlledSkillRuntimeError, match="request authority"):
        denied.resolve(request)

    def denied_approver(*, subject_id: str, **_values):
        return {
            "scopes": (
                ["finance:journal:request-approval"]
                if subject_id == "employee-101"
                else []
            ),
            "revision_hash": HASH,
        }

    with pytest.raises(ControlledSkillRuntimeError, match="approver authority"):
        installed._JournalAuthorizationSource(
            oa=SimpleNamespace(effective_authorization=denied_approver),
            evidence={
                "agent_execution_id": EXECUTION_ID,
                "executable_step_id": STEP_ID,
                "approver_id": "employee-202",
                "evidence_integrity": HASH,
            },
            authority=authority,
            evaluated_at=now,
        ).resolve(request)

    observed_subjects: list[str] = []

    def authorization(*, subject_id: str, **_values):
        observed_subjects.append(subject_id)
        return {
            "scopes": (
                ["finance:journal:request-approval"]
                if subject_id == "employee-101"
                else ["finance:journal:approve"]
            ),
            "revision_hash": HASH if subject_id == "employee-101" else "sha256:" + "b" * 64,
        }

    allowed = installed._JournalAuthorizationSource(
        oa=SimpleNamespace(effective_authorization=authorization),
        evidence={
            "agent_execution_id": EXECUTION_ID,
            "executable_step_id": STEP_ID,
            "approver_id": "employee-202",
            "evidence_integrity": HASH,
        },
        authority=authority,
        evaluated_at=now,
    ).resolve(request)
    assert allowed["oa_allowed"] is True
    assert allowed["operation_trust_decision"]["decision"] == "ALLOW"
    assert allowed["protected_operation"]["actor_ref"] == "employee-101"
    assert allowed["protected_operation"]["typed_parameters"]["approver_ref"] == (
        "employee-202"
    )
    assert observed_subjects == ["employee-101", "employee-202"]

    with pytest.raises(ControlledSkillRuntimeError, match="different principals"):
        installed._JournalAuthorizationSource(
            oa=SimpleNamespace(effective_authorization=authorization),
            evidence={
                "agent_execution_id": EXECUTION_ID,
                "executable_step_id": STEP_ID,
                "approver_id": "employee-101",
                "evidence_integrity": HASH,
            },
            authority=authority,
            evaluated_at=now,
        ).resolve(request)


def test_journal_authority_rejects_input_and_scope_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime()
    writer = runtime._writers[M1_D04_CAPABILITY_ID]
    monkeypatch.setattr(
        installed,
        "_execution_context",
        lambda *_args, **_values: {
            "context_ref": "AE:AGENT_CONTEXT:m1:1",
            "context_hash": HASH,
            "principal_id": "employee-101",
            "agent_id": "66666666-6666-4666-8666-666666666666",
            "project_id": PROJECT_ID,
            "correlation_id": "corr-m1-runtime",
            "work_intent": {"intent_hash": HASH},
        },
    )
    invalid = _write_context(runtime)
    invalid.step["compiled_input_bindings"].pop()
    with pytest.raises(ControlledSkillRuntimeError, match="business contract"):
        writer._resolve_authority(invalid)

    with pytest.raises(ControlledSkillRuntimeError, match="business contract"):
        writer._resolve_authority(_write_context(runtime, tenant_id="OTHER"))

    writer._oa = SimpleNamespace(
        effective_authorization=lambda **_values: {
            "roles": [],
            "scopes": [],
            "org_scope_refs": [],
            "revision_hash": HASH,
        }
    )
    with pytest.raises(ControlledSkillRuntimeError, match="denied"):
        writer._resolve_authority(_write_context(runtime))

    writer._oa = SimpleNamespace(
        effective_authorization=lambda **_values: {
            "roles": ["employee"],
            "scopes": ["finance:journal:request-approval"],
            "org_scope_refs": ["ORG:FINANCE"],
            "revision_hash": HASH,
        }
    )
    authority = writer._resolve_authority(_write_context(runtime))
    assert authority.project_id == PROJECT_ID
    assert authority.business_result_seed is None


def test_controlled_skill_initial_preserves_authority_stage_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime()
    writer = runtime._writers[M1_D04_CAPABILITY_ID]

    def fail_authority(_context):
        raise ControlledSkillRuntimeError("private authority detail")

    monkeypatch.setattr(writer, "_resolve_authority", fail_authority)
    with pytest.raises(P5StepExecutorError) as captured:
        writer.initial(_write_context(runtime), writer.dependencies)

    assert captured.value.error_code == "ae.product_controlled_skill_authority_failed"
    assert captured.value.detail == (
        "Product controlled Skill authority resolution failed."
    )
    assert "private" not in captured.value.detail


def test_activation_lock_and_runtime_config_fail_closed(tmp_path: Path) -> None:
    admission = json.loads(
        (ROOT / "deployment/locks/ae-mybee-m1-runtime-admission.v3.json").read_text(
            encoding="utf-8"
        )
    )
    activation = json.loads(
        (ROOT / "deployment/locks/ae-mybee-m1-runtime-activation.v3.json").read_text(
            encoding="utf-8"
        )
    )
    cases = (
        ("schema_version", "wrong", "schema"),
        ("activation_state", "INACTIVE", "not active"),
        ("runtime_profile", "UNSUPPORTED", "profile has drifted"),
        ("runtime_admission_hash", HASH, "admission hash"),
    )
    for key, value, message in cases:
        drifted = deepcopy(activation)
        drifted[key] = value
        with pytest.raises(ValueError, match=message):
            runtime_profile._verify_activation_lock(
                drifted, admission=admission, repository_root=ROOT
            )

    drifted = deepcopy(activation)
    drifted["rollback_target"] = []
    with pytest.raises(TypeError, match="receipt is required"):
        runtime_profile._verify_activation_lock(
            drifted, admission=admission, repository_root=ROOT
        )

    drifted = deepcopy(activation)
    drifted["rollback_target"]["receipt_ref"] = ""
    with pytest.raises(ValueError, match="reference is invalid"):
        runtime_profile._verify_activation_lock(
            drifted, admission=admission, repository_root=ROOT
        )

    drifted = deepcopy(activation)
    drifted["rollback_target"]["receipt_ref"] = "missing.json"
    with pytest.raises(ValueError, match="receipt has drifted"):
        runtime_profile._verify_activation_lock(
            drifted, admission=admission, repository_root=tmp_path
        )

    receipt = tmp_path / "receipt.json"
    receipt.write_text("{}", encoding="utf-8")
    drifted = deepcopy(activation)
    drifted["rollback_target"]["receipt_ref"] = "receipt.json"
    with pytest.raises(ValueError, match="receipt has drifted"):
        runtime_profile._verify_activation_lock(
            drifted, admission=admission, repository_root=tmp_path
        )

    drifted = deepcopy(activation)
    drifted["decision_id"] = "drifted"
    with pytest.raises(ValueError, match="activation hash"):
        runtime_profile._verify_activation_lock(
            drifted, admission=admission, repository_root=ROOT
        )

    missing = tmp_path / "missing"
    assert runtime_profile._path({}, "OPTIONAL", missing, require_existing=False) == (
        missing
    )
    with pytest.raises(ValueError, match="REQUIRED is unavailable"):
        runtime_profile._path({}, "REQUIRED", missing)
    with pytest.raises(ValueError, match="VALUE is required"):
        runtime_profile._text({}, "VALUE")
    invalid_json = tmp_path / "array.json"
    invalid_json.write_text("[]", encoding="utf-8")
    with pytest.raises(TypeError, match="JSON object"):
        runtime_profile._json_object(invalid_json)
    with pytest.raises(ValueError, match="not admitted"):
        runtime_profile.build_product_runtime_executor_profile(
            _sessions(), {"NEX_AE_PRODUCT_RUNTIME_PROFILE": "UNKNOWN"}
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("capability_id", ""),
        ("operation_semantics", ""),
        ("backend_profile", ""),
        ("adapter_id", ""),
    ),
)
def test_operation_registration_rejects_blank_identity(field: str, value: str) -> None:
    values = {
        "capability_id": "PROJECT.WORK_CODE_SET.GET",
        "operation_semantics": "READ",
        "backend_profile": "NSL_V02_IN_PROCESS",
        "adapter_id": "adapter",
        "operation_ids": ("PROJECT.WORK_CODE_SET.GET",),
        "factory": lambda _context: ProductOperationAdapterSet(),
    }
    values[field] = value
    with pytest.raises(ProductSkillCatalogError, match="non-empty string"):
        ProductOperationAdapterRegistration(**values)


def test_operation_registry_rejects_malformed_entries_and_handlers() -> None:
    with pytest.raises(ProductSkillCatalogError, match="callable"):
        ProductOperationAdapterSet(tool_handlers={"tool": None})

    values = {
        "capability_id": "PROJECT.WORK_CODE_SET.GET",
        "operation_semantics": "READ",
        "backend_profile": "NSL_V02_IN_PROCESS",
        "adapter_id": "adapter",
        "factory": lambda _context: ProductOperationAdapterSet(),
    }
    with pytest.raises(ProductSkillCatalogError, match="non-empty and unique"):
        ProductOperationAdapterRegistration(
            **values,
            operation_ids=("PROJECT.WORK_CODE_SET.GET",) * 2,
        )
    with pytest.raises(ProductSkillCatalogError, match="non-empty strings"):
        ProductOperationAdapterRegistration(**values, operation_ids=("",))
    with pytest.raises(ProductSkillCatalogError, match="factory must be callable"):
        ProductOperationAdapterRegistration(
            **{**values, "factory": None},
            operation_ids=("PROJECT.WORK_CODE_SET.GET",),
        )
    with pytest.raises(ProductSkillCatalogError, match="entries are invalid"):
        ProductOperationAdapterRegistry((object(),))

    registry = ProductOperationAdapterRegistry(
        (
            ProductOperationAdapterRegistration(
                **values,
                operation_ids=("PROJECT.WORK_CODE_SET.GET",),
            ),
        )
    )
    assert registry.resolve("UNKNOWN.CAPABILITY") is None


def test_canonical_oci_and_compose_select_same_verified_release() -> None:
    compose = (ROOT / "deployment/compose/canonical-platform.override.yaml").read_text(
        encoding="utf-8"
    )
    containerfile = (
        ROOT / "deployment/oci/canonical-platform-ae-runtime.Containerfile"
    ).read_text(encoding="utf-8")
    for expected in (
        "VERIFIED_PRODUCT_RELEASE",
        "ae-mybee-m1-runtime-admission.v3.json",
        "ae-mybee-m1-runtime-activation.v3.json",
        "ae-product-capability-registry.mybee-m1.v3.json",
        "mybee-m1-d04-d12.v2.nsp",
        "tool_catalog.v1.json",
    ):
        assert expected in containerfile
    for expected in (
        "VERIFIED_PRODUCT_RELEASE",
        "ae-mybee-m1-runtime-admission.v3.json",
        "ae-mybee-m1-runtime-activation.v3.json",
        "ae-product-capability-registry.mybee-m1.v3.json",
        "tool_catalog.v1.json",
    ):
        assert expected in compose
    assert (
        compose.count(
            "/app/deployment/product/repository/deployment/environments/"
            "ae-product-capability-registry.mybee-m1.v3.json"
        )
        == 2
    )
    assert "golden-a-selection-freeze.v1.json" not in compose
    assert "/app/deployment/environments/ae-product-capability-registry" not in compose
    assert "/app/deployment/product/config/golden-a-selection-freeze" not in compose


def test_active_m1_runtime_has_no_demo_fixture_or_fixed_business_values() -> None:
    active_sources = (
        ROOT / "services/nex-ae-api/nex_ae_api/m1_installed_skill_runtime.py",
        ROOT / "services/nex-ae-api/nex_ae_api/mybee_m1_skill_runtime.py",
        ROOT / "services/nex-ae-api/nex_ae_api/product_skill_catalog.py",
    )
    forbidden = (
        "scripts/smoke/data",
        "scripts/deployment/data",
        "NEX_AE_DEMO_",
        "NEX_.*_FIXTURE",
        "p8_demo_semantic_activation",
        "p8_demo_controlled_skill",
        "golden_a_approval_journey",
        'tenant == "VO00"',
    )
    content = "\n".join(path.read_text(encoding="utf-8") for path in active_sources)
    assert all(value not in content for value in forbidden)
