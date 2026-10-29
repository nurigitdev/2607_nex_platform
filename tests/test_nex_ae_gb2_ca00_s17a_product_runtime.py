from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import nex_ae_api.product_controlled_skill as controlled
import nex_ae_api.product_runtime_profile as profile
import nex_runtime.nsl_runtime_adapter as nsl_adapter
import pytest
from nex_ae_api.multi_step_engine import StepExecutionContext
from nex_ae_api.product_capabilities import load_product_capability_registry
from nex_ae_api.product_controlled_skill import (
    PRODUCT_CAPABILITY_ID,
    ProductControlledSkillRuntime,
    _product_business_binding,
    _product_handlers,
)
from nex_ae_api.step_executors import LocalSkillExecutorDependencies
from nex_runtime.nsl_runtime_bundle import (
    NslRuntimeBundleError,
    load_nsl_runtime_bundle,
    verify_nsl_runtime_bundle,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from run_product_runtime_deployment_audit import (
    ACTIVE_DEPLOYMENT_PATHS,
    CANONICAL_DEPLOYMENT_ENTRYPOINTS,
    LEGACY_DEPLOYMENT_WRAPPERS,
    PRODUCT_RUNTIME_PATHS,
    audit_product_runtime_deployment,
)
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "deployment/locks/ae-product-nsl-runtime-bundle.v1.json"
REGISTRY = ROOT / "deployment/environments/ae-product-capability-registry.v1.json"
WHEEL = (
    ROOT
    / "reports/deployment/p8-nsl-v0.2.1-wheel"
    / "nex_skill_language-0.2.1-py3-none-any.whl"
)
SKILL = Path("/home/tprover/2608_nsl/examples/golden_a_voucher_draft")


def _parameters(amount: str = "125000.00") -> list[dict[str, str]]:
    return [
        {"name": "amount", "value": amount},
        {"name": "currency", "value": "KRW"},
        {"name": "transaction_date", "value": "2026-10-28"},
        {"name": "voucher_type", "value": "GENERAL"},
        {"name": "economic_category", "value": "TRAVEL"},
        {"name": "settlement_method", "value": "CASH"},
    ]


def _work_intent(execution_id: str, amount: str = "125000.00") -> dict:
    value = {
        "execution_id": execution_id,
        "entity_selectors": [{"entity_type": "PROJECT", "raw_text": "PROJECT-A-2"}],
        "parameter_candidates": _parameters(amount),
        "constraints": [],
    }
    value["intent_hash"] = semantic_sha256_hash_ref(value)
    return value


def _eos_authority() -> dict:
    return {
        "project": {
            "project_id": "82000000-0000-4000-8000-000000000001",
            "project_code": "PROJECT-A-2",
            "name": "Travel Project",
            "status": "ACTIVE",
        },
        "accounts": [
            {
                "account_id": "83000000-0000-4000-8000-000000000001",
                "account_code": "TRAVEL",
                "status": "ACTIVE",
            },
            {
                "account_id": "83000000-0000-4000-8000-000000000002",
                "account_code": "CASH",
                "status": "ACTIVE",
            },
        ],
    }


def _config(tmp_path: Path) -> controlled.ProductControlledSkillConfig:
    return controlled.ProductControlledSkillConfig(
        manifest_path=BUNDLE,
        wheel_path=WHEEL,
        platform_lock_path=ROOT / "deployment/locks/python-production.lock",
        skill_root=SKILL,
        state_root=tmp_path / "state",
        oa_base_url="https://oa.example",
        eos_base_url="https://eos.example",
        ae_to_oa_service_token="oa-token",
        ae_to_eos_service_token="eos-token",
    )


def test_product_bundle_is_fixture_free_and_digest_admitted(tmp_path: Path) -> None:
    bundle = load_nsl_runtime_bundle(BUNDLE)
    result = verify_nsl_runtime_bundle(
        bundle,
        wheel_path=WHEEL,
        skill_root=SKILL,
    )

    assert result["status"] == "PASS"
    assert bundle.bundle_id.startswith("nex-product-nsl-")
    assert not any("fixture" in name.lower() for name in bundle.skill_files)

    damaged = deepcopy(json.loads(BUNDLE.read_text(encoding="utf-8")))
    damaged["demo_fixture"] = {"path": "forbidden.json"}
    path = tmp_path / "invalid-product-bundle.json"
    path.write_text(json.dumps(damaged), encoding="utf-8")
    with pytest.raises(NslRuntimeBundleError, match="fields"):
        load_nsl_runtime_bundle(path)


def test_product_business_binding_uses_registry_and_authority_not_fixture() -> None:
    registration = load_product_capability_registry(
        {"NEX_AE_PRODUCT_CAPABILITY_REGISTRY_PATH": str(REGISTRY)}
    ).resolve(PRODUCT_CAPABILITY_ID, required=True)
    assert registration is not None

    product = _product_business_binding(
        tenant_id="VO00",
        work_intent=_work_intent("execution-1"),
        registration=registration,
        principal_id="employee-1001",
        eos=_eos_authority(),
    )
    handlers = _product_handlers(product)

    assert product["project"]["project_code"] == "PROJECT-A-2"
    assert product["canonical_payload"]["tenant_id"] == "VO00"
    assert product["canonical_payload"]["lines"][0]["signed_amount"] == ("125000.00")
    assert product["canonical_payload"]["transaction_date"] == "2026-10-28"
    assert product["accounts"][0]["account_code"] == "TRAVEL"
    assert product["accounts"][1]["account_code"] == "CASH"
    assert (
        handlers["PROJECT.GET_PROJECT"]({"project_code": "PROJECT-A-2"})["status"]
        == "ACTIVE"
    )
    with pytest.raises(Exception, match="authoritative product binding"):
        handlers["PROJECT.GET_PROJECT"]({"project_code": "DRIFT"})


def test_product_profile_builds_local_skill_registry_without_demo_inputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    backend = SimpleNamespace(
        backend_profile="NSL_V02_IN_PROCESS",
        execute=lambda **_values: {},
    )
    dependencies = LocalSkillExecutorDependencies(
        artifact_gateway=SimpleNamespace(resolve_verified=lambda **_values: {}),
        binding_repository=SimpleNamespace(bind_request=lambda **_values: {}),
        request_builder=lambda **_values: {},
        backend=backend,
        result_mapper=lambda value: value,
    )
    runtime = SimpleNamespace(
        dependencies=dependencies,
        initial=lambda *_args: None,
        resume=lambda *_args: None,
        backend_profile=backend.backend_profile,
        package_readiness={"status": "PASS"},
    )
    observed: dict[str, object] = {}

    def fake_runtime(sessions, config, *, environ):
        observed.update(sessions=sessions, config=config, environ=environ)
        return runtime

    monkeypatch.setattr(profile, "ProductControlledSkillRuntime", fake_runtime)
    environment = {
        "NEX_AE_NSL_BUNDLE_MANIFEST": str(BUNDLE),
        "NEX_AE_NSL_WHEEL": str(WHEEL),
        "NEX_AE_NSL_PLATFORM_LOCK": str(
            ROOT / "deployment/locks/python-production.lock"
        ),
        "NEX_AE_NSL_SKILL_ROOT": str(SKILL),
        "NEX_AE_NSL_STATE_ROOT": str(tmp_path / "state"),
        "NEX_AE_PRODUCT_CAPABILITY_REGISTRY_PATH": str(REGISTRY),
        "NEX_OA_BASE_URL": "https://oa.example",
        "NEX_EOS_BASE_URL": "https://eos.example",
        "NEX_AE_TO_OA_SERVICE_TOKEN": "oa-token",
        "NEX_AE_TO_EOS_SERVICE_TOKEN": "eos-token",
    }
    result = profile.build_product_runtime_executor_profile(
        SimpleNamespace(), environment
    )

    assert "LOCAL_SKILL" in result.executor_kinds
    assert result.backend_profiles == ("NSL_V02_IN_PROCESS",)
    assert result.package_readiness == {"status": "PASS"}
    assert observed["environ"] is environment
    config = observed["config"]
    assert config.state_root == tmp_path / "state"
    assert not any(name.startswith("NEX_AE_DEMO_") for name in environment)


def test_product_runtime_config_requires_authoritative_service_inputs() -> None:
    with pytest.raises(ValueError, match="NEX_OA_BASE_URL"):
        profile.load_product_controlled_skill_config({})


def test_product_runtime_deployment_audit_passes_and_detects_residue(
    tmp_path: Path,
) -> None:
    result = audit_product_runtime_deployment(ROOT)

    assert result["status"] == "PASS"
    assert result["business_fixture_runtime_use"] is False
    assert result["authoritative_sources"] == [
        "PRODUCT_CAPABILITY_REGISTRY",
        "AE_POSTGRESQL",
        "OA",
        "WC",
        "EOS",
    ]

    for relative in (
        "deployment/compose",
        "deployment/oci",
        "scripts/deployment",
        "services/nex-ae-api/nex_ae_api",
        "deployment/locks",
        "deployment/environments",
    ):
        (tmp_path / relative).mkdir(parents=True, exist_ok=True)
    for relative in (
        *ACTIVE_DEPLOYMENT_PATHS,
        *CANONICAL_DEPLOYMENT_ENTRYPOINTS,
        *LEGACY_DEPLOYMENT_WRAPPERS,
        *PRODUCT_RUNTIME_PATHS,
        "deployment/locks/ae-product-nsl-runtime-bundle.v1.json",
        "deployment/environments/ae-product-capability-registry.v1.json",
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    compose = tmp_path / "deployment/compose/canonical-platform.override.yaml"
    compose.write_text(
        compose.read_text(encoding="utf-8").replace(
            "nex_ae_api.agent_runtime_process", "nex_ae_api.demo_runtime"
        ),
        encoding="utf-8",
    )

    failed = audit_product_runtime_deployment(tmp_path)
    assert failed["status"] == "FAIL"
    assert any("Demo runtime" in issue for issue in failed["issues"])


def test_product_runtime_type_is_explicitly_fixture_free() -> None:
    annotations = ProductControlledSkillRuntime.__init__.__annotations__
    assert "demo_fixture" not in repr(annotations)
    source = (
        ROOT / "services/nex-ae-api/nex_ae_api/product_controlled_skill.py"
    ).read_text(encoding="utf-8")
    assert "finance_golden_a_activation" not in source
    assert "authority_profile_path" not in source
    assert "protected_input" not in source


def test_product_runtime_loads_admitted_package_and_registry(tmp_path: Path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    sessions = sessionmaker(bind=engine)
    runtime = ProductControlledSkillRuntime(
        sessions,
        _config(tmp_path),
        environ={"NEX_AE_PRODUCT_CAPABILITY_REGISTRY_PATH": str(REGISTRY)},
    )

    assert runtime.bundle_readiness["status"] == "PASS"
    assert runtime.package_readiness["status"] == "PASS"
    assert runtime.backend_profile == "NSL_V02_IN_PROCESS"
    assert runtime.dependencies.backend is runtime
    with pytest.raises(controlled.ProductControlledSkillError, match="installed"):
        runtime.execute()


def test_product_initial_uses_canonical_context_provenance() -> None:
    observed: dict[str, object] = {}

    class BindingRepository:
        def bind_request(self, **values):
            observed.update(values)
            raise RuntimeError("stop after provenance capture")

    runtime = object.__new__(ProductControlledSkillRuntime)
    runtime._resolve_authority = lambda _context: SimpleNamespace(  # type: ignore[method-assign]
        context_projection={},
        canonical_write_payload={"tenant_id": "VO00"},
    )
    dependencies = SimpleNamespace(
        artifact_gateway=SimpleNamespace(
            resolve_verified=lambda **_values: {"artifact_ref": "artifact:1"}
        ),
        binding_repository=BindingRepository(),
    )
    context = StepExecutionContext(
        job={"tenant_id": "VO00"},
        attempt={},
        step={
            "executable_step_id": "50000000-0000-4000-8000-000000000010",
            "skill_binding": {
                "skill_id": "FINANCE.VOUCHER_DRAFT_CREATE",
                "exact_skill_version": "1.1.0",
                "skill_semantic_hash": "sha256:" + "1" * 64,
                "runtime_contract_ref": "contract://nex/example/v1",
                "trust_policy_id": "policy-1",
            },
        },
        dependency_results=(),
        existing_result=None,
    )

    with pytest.raises(controlled.P5StepExecutorError):
        runtime.initial(context, dependencies)

    assert observed["input_provenance"] == {"canonical_write_payload": "CONTEXT"}


def test_product_authority_resolves_persisted_intent_oa_and_eos(
    tmp_path: Path,
) -> None:
    execution_id = "10000000-0000-4000-8000-000000000010"
    work_intent_id = "20000000-0000-4000-8000-000000000010"
    agent_id = "30000000-0000-4000-8000-000000000010"
    context_id = "40000000-0000-4000-8000-000000000010"
    intent = _work_intent(execution_id)
    context_document = {
        "identity": {
            "principal_id": "employee-1001",
            "agent_id": agent_id,
        }
    }
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE ae_work_intent (tenant_id TEXT, work_intent_id TEXT, "
                "intent_json TEXT)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE ae_agent_context (tenant_id TEXT, context_id TEXT, "
                "context_generation INTEGER, context_hash TEXT, context_json TEXT, "
                "principal_id TEXT, agent_id TEXT, agent_execution_id TEXT, "
                "work_intent_id TEXT)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO ae_work_intent VALUES "
                "(:tenant_id, :work_intent_id, :intent_json)"
            ),
            {
                "tenant_id": "VO00",
                "work_intent_id": work_intent_id,
                "intent_json": json.dumps(intent),
            },
        )
        connection.execute(
            text(
                "INSERT INTO ae_agent_context VALUES "
                "(:tenant_id, :context_id, 1, :context_hash, :context_json, "
                ":principal_id, :agent_id, :execution_id, :work_intent_id)"
            ),
            {
                "tenant_id": "VO00",
                "context_id": context_id,
                "context_hash": semantic_sha256_hash_ref(context_document),
                "context_json": json.dumps(context_document),
                "principal_id": "employee-1001",
                "agent_id": agent_id,
                "execution_id": execution_id,
                "work_intent_id": work_intent_id,
            },
        )
    sessions = sessionmaker(bind=engine)
    runtime = ProductControlledSkillRuntime(
        sessions,
        _config(tmp_path),
        environ={"NEX_AE_PRODUCT_CAPABILITY_REGISTRY_PATH": str(REGISTRY)},
    )
    revision = "sha256:" + "1" * 64
    runtime._oa = SimpleNamespace(
        effective_authorization=lambda **_values: {
            "roles": ["employee"],
            "scopes": ["finance:voucher-draft:create"],
            "revision_hash": revision,
        }
    )
    eos_authority = _eos_authority()
    project = eos_authority["project"]
    accounts = eos_authority["accounts"]
    runtime._eos = SimpleNamespace(
        resolve=lambda **_values: {
            "project": {**project, "status": "ACTIVE"},
            "accounts": accounts,
        }
    )
    context = StepExecutionContext(
        job={"tenant_id": "VO00"},
        attempt={"runtime_job_attempt_id": "attempt-1"},
        step={
            "agent_execution_id": execution_id,
            "executable_step_id": "50000000-0000-4000-8000-000000000010",
        },
        dependency_results=(),
        existing_result=None,
    )

    authority = runtime._resolve_authority(context)

    assert authority.project_id == project["project_id"]
    assert authority.agent_id == agent_id
    assert authority.org_scope_refs == ()
    assert authority.execution_binding.input_document["amount"]["amount"] == (
        "125000.00"
    )
    assert authority.canonical_write_payload["attachments"] == []


def test_persisted_identifier_comparison_normalizes_postgresql_uuid() -> None:
    identifier = UUID("30000000-0000-4000-8000-000000000010")

    assert controlled._same_persisted_identifier(str(identifier), identifier)
    assert controlled._same_persisted_identifier(" employee-1001 ", "employee-1001")
    assert not controlled._same_persisted_identifier(str(identifier), UUID(int=0))
    assert not controlled._same_persisted_identifier("", identifier)
    assert not controlled._same_persisted_identifier(None, identifier)
    assert not controlled._same_persisted_identifier(str(identifier), None)


@pytest.mark.parametrize(
    ("commit_state", "verification", "terminal", "error_ref"),
    (
        ("COMMITTED", "VERIFIED", "SUCCEEDED", None),
        ("NOT_COMMITTED", None, "FAILED", "eos.write_not_committed"),
        (
            "UNKNOWN_COMMIT_STATE",
            "UNKNOWN",
            "BLOCKED",
            "eos.write_outcome_requires_reconciliation",
        ),
    ),
)
def test_controlled_write_outcome_preserves_commit_semantics(
    commit_state: str,
    verification: str | None,
    terminal: str,
    error_ref: str | None,
) -> None:
    result = SimpleNamespace(
        outcome=SimpleNamespace(commit_state=SimpleNamespace(value=commit_state)),
        verification=(
            None
            if verification is None
            else SimpleNamespace(status=SimpleNamespace(value=verification))
        ),
        write_request=SimpleNamespace(idempotency_key="idem-1"),
    )

    outcome = controlled._controlled_write_outcome(
        result, business_operation_id="business-1"
    )

    assert outcome.state == terminal
    assert outcome.error_ref == error_ref
    assert outcome.result_payload["commit_state"] == commit_state
    assert outcome.evidence_refs == ("AE:WRITE_REQUESTED:idem-1",)


def test_product_input_and_authority_guards_fail_closed() -> None:
    registration = load_product_capability_registry(
        {"NEX_AE_PRODUCT_CAPABILITY_REGISTRY_PATH": str(REGISTRY)}
    ).resolve(PRODUCT_CAPABILITY_ID, required=True)
    assert registration is not None

    for amount in ("invalid", "0"):
        with pytest.raises(controlled.ProductControlledSkillError):
            _product_business_binding(
                tenant_id="VO00",
                work_intent=_work_intent("execution-1", amount),
                registration=registration,
                principal_id="employee-1001",
                eos=_eos_authority(),
            )
    drifted_eos = _eos_authority()
    drifted_eos["accounts"][0]["account_code"] = "DRIFT"
    with pytest.raises(controlled.ProductControlledSkillError, match="Account"):
        _product_business_binding(
            tenant_id="VO00",
            work_intent=_work_intent("execution-1"),
            registration=registration,
            principal_id="employee-1001",
            eos=drifted_eos,
        )
    with pytest.raises(controlled.ProductControlledSkillError, match="string set"):
        controlled._string_tuple(["valid", ""])
    with pytest.raises(controlled.ProductControlledSkillError, match="string set"):
        controlled._string_tuple(None)


def test_product_bundle_and_http_authority_adapters(monkeypatch) -> None:
    bundle = load_nsl_runtime_bundle(BUNDLE)
    resolver = controlled._BundleResolver(bundle)
    package = resolver.resolve(
        skill_id=bundle.skill_id, skill_version=bundle.skill_version
    )
    admission = controlled._BundleAdmissionSource(bundle).current_admission(
        package_id="package-1",
        package_hash=package.package_hash,
        signing_key_id=package.signer_key_id,
        trust_policy_id="policy-1",
    )
    assert admission["admission_decision"]["decision"] == "ADMITTED"
    with pytest.raises(controlled.ProductControlledSkillError, match="selector"):
        resolver.resolve(skill_id="OTHER", skill_version=bundle.skill_version)

    monkeypatch.setattr(
        controlled,
        "resolve_ae_outbound_service_token",
        lambda token, **_kwargs: token,
    )

    class Response:
        def __init__(self, value):
            self.value = value

        def raise_for_status(self):
            return None

        def json(self):
            return self.value

    calls = []

    def get(url, **values):
        calls.append((url, values))
        if "/authorization" in url:
            return Response({"authorization": {"revision_hash": "revision-1"}})
        if "/projects?" in url:
            return Response(
                {
                    "items": [
                        {
                            "project_id": "project-1",
                            "project_code": "PROJECT-A-2",
                            "status": "ACTIVE",
                        }
                    ]
                }
            )
        account_code = "TRAVEL" if "TRAVEL" in url else "CASH"
        return Response(
            {
                "account_id": "account-" + account_code.lower(),
                "account_code": account_code,
                "status": "ACTIVE",
            }
        )

    monkeypatch.setattr(controlled.httpx, "get", get)
    oa = controlled._HttpOaAuthoritySource(
        base_url="https://oa.example/", service_token="oa-token"
    )
    eos = controlled._HttpEosBusinessAuthoritySource(
        base_url="https://eos.example/", service_token="eos-token"
    )

    assert (
        oa.effective_authorization(tenant_id="VO00", subject_id="employee-1001")[
            "active"
        ]
        is True
    )
    resolved = eos.resolve(
        tenant_id="VO00",
        subject_id="employee-1001",
        project_code="PROJECT-A-2",
        account_codes=("TRAVEL", "CASH"),
        effective_at="2026-10-28",
    )
    assert len(resolved["accounts"]) == 2
    assert len(calls) == 4


def test_product_miscellaneous_fail_closed_helpers(tmp_path: Path) -> None:
    with pytest.raises(controlled.ProductControlledSkillError, match="JSON authority"):
        controlled._json_object(tmp_path / "missing.json")
    with pytest.raises(controlled.ProductControlledSkillError, match="malformed"):
        controlled._json_mapping("{", "record")
    with pytest.raises(controlled.ProductControlledSkillError, match="object"):
        controlled._mapping([], "record")
    assert controlled._retryable(OSError("offline")) is True
    assert controlled._retryable(RuntimeError("bad input")) is False
    now = datetime.now(UTC)
    assert controlled._time(now).endswith("Z")


def _installed_binding() -> nsl_adapter.NslExecutionBinding:
    registration = load_product_capability_registry(
        {"NEX_AE_PRODUCT_CAPABILITY_REGISTRY_PATH": str(REGISTRY)}
    ).resolve(PRODUCT_CAPABILITY_ID, required=True)
    assert registration is not None
    product = _product_business_binding(
        tenant_id="VO00",
        work_intent=_work_intent("10000000-0000-4000-8000-000000000010"),
        registration=registration,
        principal_id="employee-1001",
        eos=_eos_authority(),
    )
    authorization = {
        "roles": ["employee"],
        "scopes": ["finance:voucher-draft:create"],
        "revision_hash": "sha256:" + "1" * 64,
    }
    return nsl_adapter.NslExecutionBinding(
        input_document=product["nsl_input"],
        principal_document=controlled._principal_document(
            tenant_id="VO00",
            principal_id="employee-1001",
            authorization=authorization,
        ),
        handlers=_product_handlers(product),
        write_tool_id=PRODUCT_CAPABILITY_ID,
        write_tool_version="1.1.0",
        precondition_evidence_ref="product-authority:sha256:" + "2" * 64,
    )


def test_installed_nsl_adapter_runs_to_durable_approval_checkpoint(
    tmp_path: Path,
) -> None:
    bundle = load_nsl_runtime_bundle(BUNDLE)
    package = nsl_adapter.InstalledNslPackage(bundle, SKILL, tmp_path / "state")
    binding = _installed_binding()
    values = {
        "tenant_id": "VO00",
        "agent_execution_id": "10000000-0000-4000-8000-000000000010",
        "executable_step_id": "20000000-0000-4000-8000-000000000010",
        "nsl_execution_id": "30000000-0000-4000-8000-000000000010",
        "business_operation_id": "40000000-0000-4000-8000-000000000010",
        "binding": binding,
    }
    execution = package.execution(**values)

    assert execution.existing_approval_request() is None
    session = asyncio.run(execution.start(execution.file_state_port))
    assert session.approval_request is not None
    assert session.checkpoint is not None
    assert execution.checkpoint_version >= 1
    assert execution.existing_approval_request() is not None

    replay = package.execution(**values)
    assert replay.checkpoint_path == execution.checkpoint_path
    drifted_input = deepcopy(dict(binding.input_document))
    drifted_input["description_text"] = "collision"
    with pytest.raises(nsl_adapter.NslRuntimeAdapterError, match="collision"):
        package.execution(
            **{
                **values,
                "binding": replace(binding, input_document=drifted_input),
            }
        )


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({"write_tool_id": ""}, "write_tool_id"),
        ({"write_tool_version": None}, "write_tool_version"),
        ({"precondition_evidence_ref": "  "}, "precondition_evidence_ref"),
        ({"provider_guarantee_ref": 1}, "provider_guarantee_ref"),
        ({"input_document": []}, "input document"),
        ({"principal_document": []}, "principal document"),
        ({"handlers": {}}, "unavailable"),
        ({"handlers": {"TOOL": object()}}, "callable"),
    ),
)
def test_nsl_execution_binding_rejects_malformed_authority(
    changes: dict, message: str
) -> None:
    binding = _installed_binding()
    with pytest.raises(nsl_adapter.NslRuntimeAdapterError, match=message):
        replace(binding, **changes)


def test_nsl_adapter_rejects_package_identity_json_and_path_drift(
    tmp_path: Path,
) -> None:
    bundle = load_nsl_runtime_bundle(BUNDLE)
    with pytest.raises(nsl_adapter.NslRuntimeAdapterError, match="identity"):
        nsl_adapter.InstalledNslPackage(
            replace(bundle, skill_id="FINANCE.WRONG"),
            SKILL,
            tmp_path / "state",
        )

    array_path = tmp_path / "array.json"
    array_path.write_text("[]", encoding="utf-8")
    with pytest.raises(nsl_adapter.NslRuntimeAdapterError, match="object"):
        nsl_adapter._json_object(array_path)
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{", encoding="utf-8")
    with pytest.raises(nsl_adapter.NslRuntimeAdapterError, match="unavailable"):
        nsl_adapter._json_object(malformed)
    with pytest.raises(nsl_adapter.NslRuntimeAdapterError, match="identity"):
        nsl_adapter._identity(" ")
    for value in (".", "..", "tenant/escape"):
        with pytest.raises(nsl_adapter.NslRuntimeAdapterError, match="path identity"):
            nsl_adapter._path_segment(value)


def test_installed_nsl_adapter_builds_controlled_write_request_and_rejects_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import nsl.audit
    import nsl.core
    import nsl.replay
    import nsl.runtime
    import nsl.runtime_models
    import nsl.tools
    import nsl.validation

    registration = load_product_capability_registry(
        {"NEX_AE_PRODUCT_CAPABILITY_REGISTRY_PATH": str(REGISTRY)}
    ).resolve(PRODUCT_CAPABILITY_ID, required=True)
    assert registration is not None
    product = _product_business_binding(
        tenant_id="VO00",
        work_intent=_work_intent("10000000-0000-4000-8000-000000000010"),
        registration=registration,
        principal_id="employee-1001",
        eos=_eos_authority(),
    )
    package = nsl_adapter.InstalledNslPackage(
        load_nsl_runtime_bundle(BUNDLE), SKILL, tmp_path / "state"
    )
    execution = package.execution(
        tenant_id="VO00",
        agent_execution_id="10000000-0000-4000-8000-000000000010",
        executable_step_id="20000000-0000-4000-8000-000000000010",
        nsl_execution_id="30000000-0000-4000-8000-000000000010",
        business_operation_id="40000000-0000-4000-8000-000000000010",
        binding=_installed_binding(),
    )
    intent = SimpleNamespace(
        payload_hash=nsl_adapter.nsl_write_payload_hash_ref(
            product["canonical_payload"]
        ),
        node_id="write-1",
        tool_id=PRODUCT_CAPABILITY_ID,
        write_intent_hash="sha256:" + "3" * 64,
    )

    class RuntimeEngine:
        def __init__(self, *_args, **_kwargs):
            pass

        async def prepare_controlled_write_intent(self, _context, _tools):
            return intent

    class Evidence:
        def __init__(self, **values):
            self.values = values

    monkeypatch.setattr(nsl.runtime, "RuntimeEngine", RuntimeEngine)
    monkeypatch.setattr(nsl.audit, "InMemorySnapshotStore", lambda: object())
    monkeypatch.setattr(nsl.replay, "RecordingToolExecutor", lambda *_a: object())
    monkeypatch.setattr(nsl.tools, "MockToolExecutor", lambda *_a: object())
    monkeypatch.setattr(
        nsl.runtime_models.ValidationSummary,
        "from_checks",
        lambda checks: ("validated", tuple(checks)),
    )
    monkeypatch.setattr(nsl.validation, "WriteContractEvidence", Evidence)
    monkeypatch.setattr(nsl.validation, "BusinessPreconditionEvidence", Evidence)
    monkeypatch.setattr(nsl.validation, "PreWriteEvidence", Evidence)
    monkeypatch.setattr(nsl.core, "ApprovalRequestId", lambda value: f"request:{value}")
    invocation = SimpleNamespace(
        outcome=SimpleNamespace(
            context=SimpleNamespace(
                checks=("check-1",),
                identity=SimpleNamespace(
                    business_operation_id=execution.business_operation_id
                ),
            )
        ),
        resume_token=SimpleNamespace(approval_evidence="approval-evidence"),
        approval_request_id="approval-1",
    )
    public_api = SimpleNamespace(
        provider_idempotency_evidence=lambda **values: Evidence(**values)
    )

    request = execution.controlled_write_request(
        invocation=invocation,
        public_api=public_api,
        request_factory=lambda **values: values,
        canonical_write_payload=product["canonical_payload"],
        authority_hash="sha256:" + "4" * 64,
    )

    assert request["intent"] is intent
    assert request["approval_request_id"] == "request:approval-1"
    assert request["approval_evidence"] == "approval-evidence"
    assert request["business_preconditions"].values["tenant_id"] == "VO00"
    assert (
        request["provider_idempotency_evidence"].values["provider_guarantee_ref"]
        == "eos:idempotency:product"
    )

    with pytest.raises(nsl_adapter.NslRuntimeAdapterError, match="differs"):
        execution.controlled_write_request(
            invocation=invocation,
            public_api=public_api,
            request_factory=lambda **values: values,
            canonical_write_payload={"tenant_id": "DRIFT"},
            authority_hash="sha256:" + "4" * 64,
        )


def test_product_controlled_state_and_approval_binding_ports() -> None:
    calls: list[tuple[str, object]] = []

    class FilePort:
        async def save(self, value):
            calls.append(("file.save", value))

        async def publish(self, value):
            calls.append(("file.publish", value))

    class Publication:
        async def publish(self, value):
            calls.append(("platform.publish", value))

    execution = SimpleNamespace(
        file_state_port=FilePort(),
        tenant_id="VO00",
        nsl_execution_id="nsl-1",
        business_operation_id="business-1",
        checkpoint_version=7,
    )
    state = controlled._PlatformControlledStatePort(
        execution=execution, publication=Publication()
    )
    asyncio.run(state.save("checkpoint"))
    asyncio.run(state.publish("request-1"))
    asyncio.run(state.publish_platform("request-2"))

    context = StepExecutionContext(
        job={"tenant_id": "VO00"},
        attempt={},
        step={
            "agent_execution_id": "agent-execution-1",
            "executable_step_id": "step-1",
        },
        dependency_results=(),
        existing_result=None,
    )
    binding = controlled._ApprovalBindingSource(
        context=context,
        execution=execution,
        approver_role="finance-approver",
    ).resolve({})

    assert calls == [
        ("file.save", "checkpoint"),
        ("file.publish", "request-1"),
        ("platform.publish", "request-1"),
        ("platform.publish", "request-2"),
    ]
    assert binding["checkpoint_version"] == 7
    assert binding["target_role_ref"] == "finance-approver"


def test_governed_write_source_allows_fresh_authority_and_denies_drift() -> None:
    evaluated_at = datetime.now(UTC)
    authorization = {
        "scopes": ["finance:voucher-draft:create"],
        "revision_hash": "sha256:" + "1" * 64,
        "roles": ["employee"],
    }
    source = controlled._GovernedWriteSource(
        authorization_source=SimpleNamespace(
            effective_authorization=lambda **_values: authorization
        ),
        platform_evidence={
            "agent_execution_id": "execution-1",
            "executable_step_id": "step-1",
        },
        evaluated_at=evaluated_at,
        agent_id="agent-1",
        org_scope_refs=("org-1",),
        project_id="project-1",
    )
    decision = source.resolve(
        SimpleNamespace(
            tenant_id="VO00",
            subject_id="employee-1001",
            business_operation_id="business-1",
        )
    )

    assert decision["oa_allowed"] is True
    assert decision["operation_trust_decision"]["decision"] == "ALLOW"
    assert decision["protected_operation"]["org_scope_refs"] == ["org-1"]
    assert decision["oa_decision_ref"].startswith("oa-authz:sha256:")

    with pytest.raises(controlled.ProductControlledSkillError, match="missing"):
        controlled._GovernedWriteSource(
            authorization_source=source.authorization_source,
            platform_evidence=None,
            evaluated_at=evaluated_at,
            agent_id="agent-1",
            org_scope_refs=(),
            project_id="project-1",
        )
    source.authorization_source = SimpleNamespace(
        effective_authorization=lambda **_values: {"scopes": []}
    )
    with pytest.raises(controlled.ProductControlledSkillError, match="denied"):
        source.resolve(
            SimpleNamespace(
                tenant_id="VO00",
                subject_id="employee-1001",
                business_operation_id="business-1",
            )
        )


def test_product_intent_authority_and_attachment_guards_cover_conflicts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(controlled.ProductControlledSkillError, match="selector"):
        controlled._product_business_request({"entity_selectors": None})
    with pytest.raises(controlled.ProductControlledSkillError, match="one Project"):
        controlled._product_business_request(
            {
                "entity_selectors": [
                    {"entity_type": "PROJECT", "raw_text": "A"},
                    {"entity_type": "PROJECT", "raw_text": "B"},
                ],
                "parameter_candidates": _parameters(),
            }
        )
    with pytest.raises(controlled.ProductControlledSkillError, match="parameters"):
        controlled._work_intent_parameters({"parameter_candidates": None})
    with pytest.raises(controlled.ProductControlledSkillError, match="incomplete"):
        controlled._work_intent_parameters(
            {"parameter_candidates": [{"name": "amount", "value": "1"}]}
        )
    with pytest.raises(
        controlled.ProductControlledSkillError, match="transaction_date"
    ):
        controlled._iso_date("not-a-date")

    request = {
        "project_code": "PROJECT-A-2",
        "account_codes": ("TRAVEL", "CASH"),
    }
    with pytest.raises(controlled.ProductControlledSkillError, match="Project"):
        controlled._validated_eos_authority({}, request=request)
    invalid_accounts = _eos_authority()
    invalid_accounts["accounts"] = [object(), object()]
    with pytest.raises(controlled.ProductControlledSkillError, match="Account"):
        controlled._validated_eos_authority(invalid_accounts, request=request)

    binding = {
        "attachment_batch_id": "batch-1",
        "attachment_manifest_hash": "sha256:" + "2" * 64,
    }
    monkeypatch.setattr(
        controlled, "work_intent_manifest_binding", lambda _intent: binding
    )
    repository = SimpleNamespace(get_batch=lambda **_values: None)
    monkeypatch.setattr(
        controlled,
        "SqlAlchemyVoucherAttachmentRepository",
        lambda _sessions: repository,
    )
    with pytest.raises(controlled.ProductControlledSkillError, match="approval-locked"):
        controlled._persisted_attachment_manifest(
            object(), tenant_id="VO00", work_intent={}
        )

    repository.get_batch = lambda **_values: {"state": "LOCKED"}
    monkeypatch.setattr(
        controlled,
        "build_attachment_manifest",
        lambda _batch: {"attachment_manifest_hash": "sha256:" + "3" * 64},
    )
    with pytest.raises(controlled.ProductControlledSkillError, match="differs"):
        controlled._persisted_attachment_manifest(
            object(), tenant_id="VO00", work_intent={}
        )
    expected = {"attachment_manifest_hash": binding["attachment_manifest_hash"]}
    monkeypatch.setattr(
        controlled, "build_attachment_manifest", lambda _batch: expected
    )
    assert (
        controlled._persisted_attachment_manifest(
            object(), tenant_id="VO00", work_intent={}
        )
        == expected
    )


def test_product_runtime_lineage_and_bundle_guards() -> None:
    context = StepExecutionContext(
        job={"tenant_id": "VO00"},
        attempt={"runtime_job_attempt_id": "attempt-1"},
        step={
            "agent_execution_id": "execution-1",
            "executable_step_id": "step-1",
        },
        dependency_results=(),
        existing_result=None,
    )
    claim = controlled._claim_from_context(context)
    assert claim.job["tenant_id"] == "VO00"
    assert controlled._approval_wait_id(
        context=context,
        approval_request_id="approval-1",
        checkpoint_version=2,
    )

    bundle = load_nsl_runtime_bundle(BUNDLE)
    runtime = object.__new__(ProductControlledSkillRuntime)
    runtime._bundle = bundle
    runtime._registration = SimpleNamespace(
        skill_artifact={
            "bundle_id": "wrong",
            "skill_id": bundle.skill_id,
            "exact_skill_version": bundle.skill_version,
            "skill_semantic_hash": bundle.skill_semantic_hash,
        }
    )
    with pytest.raises(controlled.ProductControlledSkillError, match="differs"):
        runtime._require_registration_matches_bundle()

    with pytest.raises(controlled.ProductControlledSkillError, match="unavailable"):
        controlled._resolve_admission_lock(Path("/tmp/missing/manifest.json"), bundle)


def _runtime_context() -> StepExecutionContext:
    return StepExecutionContext(
        job={"tenant_id": "VO00"},
        attempt={"runtime_job_attempt_id": "attempt-1"},
        step={
            "agent_execution_id": "execution-1",
            "executable_step_id": "step-1",
            "skill_binding": {
                "skill_id": "FINANCE.VOUCHER_DRAFT_CREATE",
                "exact_skill_version": "1.1.0",
                "skill_semantic_hash": "sha256:" + "1" * 64,
                "runtime_contract_ref": "contract://product/v1",
                "trust_policy_id": "policy-1",
            },
        },
        dependency_results=(),
        existing_result=None,
    )


@pytest.mark.parametrize("existing", (False, True))
def test_product_initial_enters_or_replays_approval_wait(
    monkeypatch: pytest.MonkeyPatch,
    existing: bool,
) -> None:
    request = SimpleNamespace(approval_request_id="approval-1")
    publication_calls: list[object] = []

    class Execution:
        tenant_id = "VO00"
        nsl_execution_id = "nsl-1"
        business_operation_id = "business-1"
        checkpoint_version = 2
        file_state_port = SimpleNamespace()

        def existing_approval_request(self):
            return request if existing else None

        async def start(self, _state_port):
            return SimpleNamespace(approval_request=request, checkpoint=object())

    class Publication:
        def __init__(self, **_values):
            pass

        async def publish(self, value):
            publication_calls.append(value)

    monkeypatch.setattr(controlled, "P8NSLApprovalPort", Publication)
    monkeypatch.setattr(
        controlled, "SqlAlchemyWaitRegistrationRepository", lambda _sessions: object()
    )
    monkeypatch.setattr(
        controlled, "build_default_wc_approval_work_item_client", lambda: object()
    )
    runtime = object.__new__(ProductControlledSkillRuntime)
    runtime._sessions = object()
    runtime._request_store = object()
    runtime._config = SimpleNamespace(approver_role="finance-approver")
    runtime._resolve_authority = lambda _context: SimpleNamespace(
        context_projection={"context": "projection"},
        canonical_write_payload={"tenant_id": "VO00"},
        execution_binding=object(),
    )
    runtime._execution = lambda **_values: Execution()
    dependencies = SimpleNamespace(
        artifact_gateway=SimpleNamespace(
            resolve_verified=lambda **_values: {"artifact_ref": "artifact-1"}
        ),
        binding_repository=SimpleNamespace(
            bind_request=lambda **_values: {
                "binding": {
                    "nsl_execution_id": "nsl-1",
                    "business_operation_id": "business-1",
                }
            }
        ),
    )

    outcome = runtime.initial(_runtime_context(), dependencies)

    assert outcome.state == "WAITING"
    assert outcome.business_operation_id == "business-1"
    assert outcome.wait_external_ref == "approval-1"
    assert bool(publication_calls) is existing


def test_product_initial_fails_closed_when_skill_does_not_suspend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Execution:
        tenant_id = "VO00"
        nsl_execution_id = "nsl-1"
        business_operation_id = "business-1"
        checkpoint_version = 1
        file_state_port = SimpleNamespace()

        def existing_approval_request(self):
            return None

        async def start(self, _state_port):
            return SimpleNamespace(approval_request=None, checkpoint=None)

    monkeypatch.setattr(
        controlled,
        "P8NSLApprovalPort",
        lambda **_values: SimpleNamespace(publish=lambda _request: None),
    )
    monkeypatch.setattr(
        controlled, "SqlAlchemyWaitRegistrationRepository", lambda _sessions: object()
    )
    monkeypatch.setattr(
        controlled, "build_default_wc_approval_work_item_client", lambda: object()
    )
    runtime = object.__new__(ProductControlledSkillRuntime)
    runtime._sessions = object()
    runtime._request_store = object()
    runtime._config = SimpleNamespace(approver_role="finance-approver")
    runtime._resolve_authority = lambda _context: SimpleNamespace(
        context_projection={},
        canonical_write_payload={"tenant_id": "VO00"},
        execution_binding=object(),
    )
    runtime._execution = lambda **_values: Execution()
    dependencies = SimpleNamespace(
        artifact_gateway=SimpleNamespace(
            resolve_verified=lambda **_values: {"artifact_ref": "artifact-1"}
        ),
        binding_repository=SimpleNamespace(
            bind_request=lambda **_values: {
                "binding": {
                    "nsl_execution_id": "nsl-1",
                    "business_operation_id": "business-1",
                }
            }
        ),
    )

    with pytest.raises(controlled.P5StepExecutorError) as caught:
        runtime.initial(_runtime_context(), dependencies)
    assert caught.value.error_code == "ae.product_controlled_skill_initial_failed"


@pytest.mark.parametrize("approved", (False, True))
def test_product_resume_maps_denial_and_controlled_write_outcomes(
    monkeypatch: pytest.MonkeyPatch,
    approved: bool,
) -> None:
    resume = {
        "tenant_id": "VO00",
        "agent_execution_id": "execution-1",
        "executable_step_id": "step-1",
        "nsl_execution_id": "nsl-1",
        "business_operation_id": "business-1",
    }
    source = SimpleNamespace(resolve=lambda _claim: resume)
    monkeypatch.setattr(
        controlled, "SqlAlchemyNslApprovalResumeSource", lambda _sessions: source
    )
    monkeypatch.setattr(
        controlled,
        "PlatformApprovalEvidenceVerifier",
        lambda **_values: object(),
    )
    monkeypatch.setattr(
        controlled,
        "PersistedApprovalEventAuthoritySource",
        lambda _evidence: object(),
    )
    invocation = SimpleNamespace(
        outcome=SimpleNamespace(
            validation=SimpleNamespace(
                approval_gate_passed=approved,
                approval_status=SimpleNamespace(
                    value="APPROVED" if approved else "DENIED"
                ),
                reason_code=None if approved else "REJECTED",
            )
        ),
        business_operation_id="business-1",
    )

    class Integration:
        def __init__(self, **_values):
            pass

        async def resume(self, *_args, **_values):
            return invocation

    monkeypatch.setattr(controlled, "NslApprovalResumeIntegration", Integration)
    execution = SimpleNamespace(
        skill=object(),
        request=object(),
        file_state_port=object(),
    )
    runtime = object.__new__(ProductControlledSkillRuntime)
    runtime._sessions = object()
    runtime._request_store = object()
    runtime._evidence = object()
    runtime.public_api = object()
    runtime._oa = object()
    runtime._package = SimpleNamespace(execution=lambda **_values: execution)
    authority = SimpleNamespace(execution_binding=object())
    runtime._resolve_authority = lambda _context: authority
    controlled_result = SimpleNamespace(
        outcome=SimpleNamespace(commit_state=SimpleNamespace(value="COMMITTED")),
        verification=SimpleNamespace(status=SimpleNamespace(value="VERIFIED")),
        write_request=SimpleNamespace(idempotency_key="idem-1"),
    )
    runtime._execute_controlled_write = lambda **_values: controlled_result

    outcome = runtime.resume(_runtime_context(), object(), object())

    assert outcome.state == ("SUCCEEDED" if approved else "FAILED")
    assert outcome.business_operation_id == "business-1"
