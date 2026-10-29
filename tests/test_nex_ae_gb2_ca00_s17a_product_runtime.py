from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import nex_ae_api.product_controlled_skill as controlled
import nex_ae_api.product_runtime_profile as profile
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
    runtime._oa = SimpleNamespace(  # noqa: SLF001 - focused boundary test
        effective_authorization=lambda **_values: {
            "roles": ["employee"],
            "scopes": ["finance:voucher-draft:create"],
            "revision_hash": revision,
        }
    )
    eos_authority = _eos_authority()
    project = eos_authority["project"]
    accounts = eos_authority["accounts"]
    runtime._eos = SimpleNamespace(  # noqa: SLF001 - focused boundary test
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

    authority = runtime._resolve_authority(context)  # noqa: SLF001

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
