from __future__ import annotations

import copy
import json
from pathlib import Path

import nex_ae_api.nsl_step_executions as execution_module
import pytest
from jsonschema import Draft202012Validator, FormatChecker
from nex_ae_api.nsl_step_executions import (
    NSLStepExecutionError,
    SqlAlchemyNSLStepExecutionRepository,
    build_context_projection,
    build_skill_execution_request,
    nsl_step_execution_table_sql,
    validate_context_projection,
    validate_nsl_step_execution_binding,
    validate_skill_execution_request,
)
from nex_ae_api.skill_artifacts import (
    SqlAlchemySkillArtifactRepository,
    skill_artifact_table_sql,
)
from nex_ae_api.step_results import (
    SqlAlchemyStepResultRepository,
    StepResultError,
    build_step_result,
    validate_step_result_contract,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]
P6 = ROOT / "docs/transition/P6/contracts"
EXAMPLES = P6 / "examples"
MIGRATION = ROOT / "database/nex-ae-api/migrations/2202_ae_nsl_step_execution.sql"
TENANT = "tenant-p6-golden"
EXECUTION_ID = "11111111-1111-4111-8111-111111111111"
PLAN_ID = "22222222-2222-4222-8222-222222222222"
STEP_ID = "33333333-3333-4333-8333-333333333333"
CONTEXT_ID = "44444444-4444-4444-8444-444444444444"
NSL_ID = "66666666-6666-4666-8666-666666666666"
BOI = "77777777-7777-4777-8777-777777777777"
NOW = "2026-10-14T07:00:00Z"


def _example(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


@pytest.fixture
def store():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.execute(
            text("""
            CREATE TABLE ae_executable_step (
                tenant_id TEXT NOT NULL, executable_step_id TEXT NOT NULL,
                agent_execution_id TEXT NOT NULL, executable_plan_id TEXT,
                step_type TEXT, executor_kind TEXT, required_capability TEXT,
                capability_version TEXT, correlation_id TEXT NOT NULL,
                causation_id TEXT, compiled_step_key TEXT, logical_step_id TEXT,
                state TEXT NOT NULL, skill_binding_json TEXT,
                PRIMARY KEY (tenant_id, executable_step_id)
            )
        """)
        )
        connection.execute(
            text("""
            CREATE TABLE ae_agent_context (
                tenant_id TEXT NOT NULL, context_id TEXT NOT NULL,
                context_generation INTEGER NOT NULL, agent_execution_id TEXT NOT NULL,
                context_hash TEXT NOT NULL, PRIMARY KEY (tenant_id, context_id)
            )
        """)
        )
        connection.execute(
            text("""
            CREATE TABLE ae_step_result (
                tenant_id TEXT NOT NULL, step_result_id TEXT NOT NULL,
                agent_execution_id TEXT NOT NULL, executable_plan_id TEXT NOT NULL,
                executable_step_id TEXT NOT NULL, compiled_step_key TEXT NOT NULL,
                logical_step_id TEXT NOT NULL, attempt_no INTEGER NOT NULL,
                status TEXT NOT NULL, result_contract_ref TEXT NOT NULL,
                result_payload TEXT NOT NULL, external_refs TEXT NOT NULL,
                artifact_refs TEXT NOT NULL, evidence_refs TEXT NOT NULL,
                error_ref TEXT, business_operation_id TEXT,
                operation_fingerprint TEXT, executor_kind TEXT,
                started_at TEXT NOT NULL, completed_at TEXT NOT NULL,
                result_hash TEXT NOT NULL, result_json TEXT NOT NULL, created_at TEXT,
                PRIMARY KEY (tenant_id, step_result_id),
                UNIQUE (tenant_id, executable_step_id)
            )
        """)
        )
        for statement in skill_artifact_table_sql("sqlite"):
            connection.execute(text(statement))
        for statement in nsl_step_execution_table_sql("sqlite"):
            connection.execute(text(statement))
        context = _example("p6-golden-context-projection-v1.json")
        connection.execute(
            text("INSERT INTO ae_agent_context VALUES (:t, :c, 1, :e, :h)"),
            {
                "t": TENANT,
                "c": CONTEXT_ID,
                "e": EXECUTION_ID,
                "h": context["agent_context_hash"],
            },
        )
        connection.execute(
            text("""
                INSERT INTO ae_executable_step VALUES (
                    :t, :s, :e, :p, 'LOCAL_SKILL', 'LOCAL_SKILL_UNAVAILABLE',
                    'FINANCE.PROJECT_BUDGET_CHECK', '1.0.0',
                    'p6-golden-correlation', 'p6-golden-prompt', 'E1', 'S1', 'READY', NULL
                )
            """),
            {"t": TENANT, "s": STEP_ID, "e": EXECUTION_ID, "p": PLAN_ID},
        )
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    SqlAlchemySkillArtifactRepository(factory).save(
        tenant_id=TENANT,
        artifact=_example("p6-golden-verified-artifact-v1.json"),
    )
    yield engine, factory
    engine.dispose()


def _repository(factory) -> SqlAlchemyNSLStepExecutionRepository:
    ids = iter((NSL_ID, BOI))
    return SqlAlchemyNSLStepExecutionRepository(factory, id_factory=ids.__next__)


def _bind(repository: SqlAlchemyNSLStepExecutionRepository, **overrides):
    values = {
        "tenant_id": TENANT,
        "executable_step_id": STEP_ID,
        "verified_artifact_ref": _example("p6-golden-verified-artifact-v1.json")[
            "artifact_ref"
        ],
        "context_projection": _example("p6-golden-context-projection-v1.json"),
        "compiled_inputs": {"year": 2026},
        "input_provenance": {"year": "USER"},
        "now": NOW,
    }
    return repository.bind_request(**{**values, **overrides})


def test_builders_match_frozen_golden_request_and_projection() -> None:
    golden_context = _example("p6-golden-context-projection-v1.json")
    projection = build_context_projection(
        agent_context_ref=golden_context["agent_context_ref"],
        agent_context_hash=golden_context["agent_context_hash"],
        runtime_context_entries=golden_context["runtime_context_entries"],
        explicit_resource_refs=golden_context["explicit_resource_refs"],
        verified_principal=golden_context["verified_principal"],
        authority=golden_context["authority"],
        data_policy=golden_context["data_policy"],
    )
    assert projection == golden_context

    request = build_skill_execution_request(
        tenant_id=TENANT,
        agent_execution_id=EXECUTION_ID,
        executable_plan_id=PLAN_ID,
        executable_step_id=STEP_ID,
        nsl_execution_id=NSL_ID,
        business_operation_id=BOI,
        artifact=_example("p6-golden-verified-artifact-v1.json"),
        compiled_inputs={"year": 2026},
        input_provenance={"year": "USER"},
        context_projection=projection,
        context_projection_ref=f"AE:NSL_CONTEXT_PROJECTION:{STEP_ID}",
        correlation_id="p6-golden-correlation",
        causation_id="p6-golden-prompt",
    )
    assert request == _example("p6-golden-skill-execution-request-v1.json")
    assert (
        semantic_sha256_hash_ref(request)
        == _example("p6-golden-step-execution-binding-v1.json")["request_hash"]
    )


def test_frozen_contract_validators_accept_golden_documents() -> None:
    pairs = (
        (
            "p6-context-projection-v1.schema.json",
            "p6-golden-context-projection-v1.json",
            validate_context_projection,
        ),
        (
            "p6-skill-execution-request-v1.schema.json",
            "p6-golden-skill-execution-request-v1.json",
            validate_skill_execution_request,
        ),
        (
            "p6-nsl-step-execution-binding-v1.schema.json",
            "p6-golden-step-execution-binding-v1.json",
            validate_nsl_step_execution_binding,
        ),
    )
    for schema_name, example_name, validator in pairs:
        value = _example(example_name)
        validator(value)
        schema = json.loads((P6 / schema_name).read_text(encoding="utf-8"))
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)


def test_request_and_projection_reject_private_unbounded_or_untrusted_material() -> (
    None
):
    request = _example("p6-golden-skill-execution-request-v1.json")
    request["input_provenance"] = {}
    with pytest.raises(NSLStepExecutionError, match="provenance"):
        validate_skill_execution_request(request)

    request = _example("p6-golden-skill-execution-request-v1.json")
    request["compiled_inputs"] = {"api_key": "secret"}
    request["input_provenance"] = {"api_key": "USER"}
    with pytest.raises(NSLStepExecutionError, match="private"):
        validate_skill_execution_request(request)

    request = _example("p6-golden-skill-execution-request-v1.json")
    request["compiled_inputs"] = {"items": [{"api_key": "secret"}]}
    request["input_provenance"] = {"items": "USER"}
    with pytest.raises(NSLStepExecutionError, match="private"):
        validate_skill_execution_request(request)

    context = _example("p6-golden-context-projection-v1.json")
    context["verified_principal"]["verification"] = "UNVERIFIED"
    with pytest.raises(NSLStepExecutionError, match="not verified"):
        validate_context_projection(context)

    context = _example("p6-golden-context-projection-v1.json")
    context["runtime_context_entries"][0]["path"] = "raw_prompt"
    with pytest.raises(NSLStepExecutionError, match="private"):
        validate_context_projection(context)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.update(schema_version="2.0"), "fields"),
        (lambda value: value.update(runtime_context_entries="bad"), "bounded array"),
        (
            lambda value: value.update(runtime_context_entries=[{"path": "x"}]),
            "runtime entry",
        ),
        (
            lambda value: value["runtime_context_entries"][0].update(path="bad-path"),
            "path is invalid",
        ),
        (
            lambda value: value.update(
                runtime_context_entries=value["runtime_context_entries"] * 2
            ),
            "duplicated",
        ),
        (
            lambda value: value["runtime_context_entries"][0].update(
                classification="SECRET"
            ),
            "classification",
        ),
        (lambda value: value.update(explicit_resource_refs=["z", "a"]), "canonical"),
        (lambda value: value.update(verified_principal={}), "verified principal"),
        (lambda value: value.update(authority={}), "authority"),
        (lambda value: value.update(data_policy={}), "data policy"),
        (
            lambda value: value["data_policy"].update(
                max_trace_classification="SECRET"
            ),
            "classification",
        ),
        (
            lambda value: value.update(projection_hash="sha256:" + "0" * 64),
            "does not match",
        ),
    ],
)
def test_context_projection_rejects_contract_boundary_mutations(
    mutation, message
) -> None:
    context = _example("p6-golden-context-projection-v1.json")
    mutation(context)
    if message != "does not match":
        context["projection_hash"] = semantic_sha256_hash_ref(
            {key: item for key, item in context.items() if key != "projection_hash"}
        )
    with pytest.raises(NSLStepExecutionError, match=message):
        validate_context_projection(context)


def test_context_projection_accepts_bounded_project_scope_and_on_behalf_of() -> None:
    context = _example("p6-golden-context-projection-v1.json")
    context["authority"]["project_scope"] = ["PROJECT-1"]
    context["verified_principal"]["on_behalf_of"] = "employee-200"
    context["projection_hash"] = semantic_sha256_hash_ref(
        {key: item for key, item in context.items() if key != "projection_hash"}
    )
    assert validate_context_projection(context)["authority"]["project_scope"] == [
        "PROJECT-1"
    ]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.pop("mode"), "fields"),
        (
            lambda value: value.update(business_operation_id=value["nsl_execution_id"]),
            "distinct",
        ),
        (lambda value: value.update(compiled_inputs=[]), "inputs"),
        (
            lambda value: value.update(input_provenance={"bad-name": "USER"}),
            "provenance",
        ),
        (
            lambda value: value.update(
                compiled_inputs={"year": 2026, "month": 10},
                input_provenance={"year": "USER", "month": "UNTRUSTED"},
            ),
            "provenance",
        ),
        (lambda value: value.update(explicit_resource_refs=["z", "a"]), "canonical"),
        (lambda value: value.update(mode="RESUME"), "mode"),
    ],
)
def test_skill_request_rejects_contract_boundary_mutations(mutation, message) -> None:
    request = _example("p6-golden-skill-execution-request-v1.json")
    mutation(request)
    with pytest.raises(NSLStepExecutionError, match=message):
        validate_skill_execution_request(request)


def test_binding_validator_rejects_identity_collapse_and_invalid_state_evidence() -> (
    None
):
    binding = _example("p6-golden-step-execution-binding-v1.json")
    binding["business_operation_id"] = binding["nsl_execution_id"]
    with pytest.raises(NSLStepExecutionError, match="distinct"):
        validate_nsl_step_execution_binding(binding)

    binding = _example("p6-golden-step-execution-binding-v1.json")
    binding["result_summary_ref"] = None
    with pytest.raises(NSLStepExecutionError, match="complete result"):
        validate_nsl_step_execution_binding(binding)

    binding = _example("p6-golden-step-execution-binding-v1.json")
    binding.update(
        state="REQUEST_BOUND",
        invocation_started_at=None,
        completed_at=None,
        result_summary_ref=None,
        result_summary_hash=None,
    )
    assert validate_nsl_step_execution_binding(binding)["state"] == "REQUEST_BOUND"


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"schema_version": "2.0"}, "fields"),
        ({"backend_profile": "DIRECT"}, "profile"),
        ({"state": "ALLOCATED"}, "request-bound"),
        ({"state": "REQUEST_BOUND", "request_bound_at": None}, "request_bound_at"),
        (
            {
                "state": "RUNNING",
                "result_summary_ref": None,
                "result_summary_hash": None,
                "completed_at": None,
                "invocation_started_at": None,
            },
            "invocation_started_at",
        ),
        (
            {
                "state": "REQUEST_BOUND",
                "result_summary_ref": "AE:NSL_RESULT:unexpected",
                "result_summary_hash": None,
                "completed_at": None,
                "invocation_started_at": None,
            },
            "terminal result",
        ),
    ],
)
def test_binding_rejects_state_machine_boundary_mutations(changes, message) -> None:
    binding = _example("p6-golden-step-execution-binding-v1.json")
    binding.update(changes)
    with pytest.raises(NSLStepExecutionError, match=message):
        validate_nsl_step_execution_binding(binding)


def test_repository_persists_one_restart_safe_binding_per_step(store) -> None:
    engine, factory = store
    repository = _repository(factory)
    first = _bind(repository)
    replay = _bind(SqlAlchemyNSLStepExecutionRepository(factory))
    restarted = SqlAlchemyNSLStepExecutionRepository(factory).get(
        tenant_id=TENANT, executable_step_id=STEP_ID
    )

    assert first == replay == restarted
    assert first["binding"]["state"] == "REQUEST_BOUND"
    assert first["binding"]["nsl_execution_id"] == NSL_ID
    assert first["binding"]["business_operation_id"] == BOI
    assert first["binding"]["backend_profile"] == "NSL_V01_PROCESS_ISOLATED"
    assert first["request"] == _example("p6-golden-skill-execution-request-v1.json")
    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT count(*) FROM ae_nsl_step_execution")
            ).scalar_one()
            == 1
        )


def test_repository_persists_exact_compiled_profile_and_rejects_profile_rewrite(
    store,
) -> None:
    engine, factory = store
    artifact = _example("p6-golden-verified-artifact-v1.json")
    binding = {
        "skill_id": artifact["skill_id"],
        "exact_skill_version": artifact["skill_version"],
        "skill_semantic_hash": artifact["skill_semantic_hash"],
        "runtime_contract_ref": artifact["runtime_contract_ref"],
        "trust_policy_id": artifact["trust_evidence"]["trust_policy_id"],
        "backend_profile": "NSL_V01_IN_PROCESS",
        "package_requirement": "SIGNED_TRUSTED_ACTIVE",
    }
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE ae_executable_step SET executor_kind = 'LOCAL_SKILL', "
                "skill_binding_json = :binding"
            ),
            {"binding": json.dumps(binding, sort_keys=True)},
        )

    saved = _bind(_repository(factory))
    restarted = SqlAlchemyNSLStepExecutionRepository(factory).get(
        tenant_id=TENANT, executable_step_id=STEP_ID
    )

    assert saved == restarted
    assert saved["binding"]["backend_profile"] == "NSL_V01_IN_PROCESS"

    binding["backend_profile"] = "NSL_V01_PROCESS_ISOLATED"
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE ae_executable_step SET skill_binding_json = :binding"),
            {"binding": json.dumps(binding, sort_keys=True)},
        )
    with pytest.raises(NSLStepExecutionError) as caught:
        _bind(SqlAlchemyNSLStepExecutionRepository(factory))
    assert caught.value.error_code == "ae.nsl_binding_immutable_conflict"


def test_repository_rejects_cross_tenant_lineage_and_immutable_replay(store) -> None:
    _engine, factory = store
    repository = _repository(factory)
    _bind(repository)
    with pytest.raises(NSLStepExecutionError) as caught:
        _bind(
            SqlAlchemyNSLStepExecutionRepository(factory),
            compiled_inputs={"year": 2027},
        )
    assert caught.value.error_code == "ae.nsl_binding_immutable_conflict"
    assert "request, request_hash" in caught.value.detail

    assert (
        SqlAlchemyNSLStepExecutionRepository(factory).get(
            tenant_id="other-tenant", executable_step_id=STEP_ID
        )
        is None
    )
    with pytest.raises(NSLStepExecutionError) as caught:
        _bind(_repository(factory), tenant_id="other-tenant")
    assert caught.value.error_code == "ae.nsl_binding_step_not_found"


def test_repository_fails_closed_when_insert_cannot_be_reloaded(
    store, monkeypatch
) -> None:
    _engine, factory = store
    original = execution_module._load_bundle
    calls = 0

    def fail_second_load(session, tenant_id, step_id):
        nonlocal calls
        calls += 1
        loaded = original(session, tenant_id, step_id)
        return None if calls == 2 else loaded

    monkeypatch.setattr(execution_module, "_load_bundle", fail_second_load)
    with pytest.raises(NSLStepExecutionError) as caught:
        _bind(_repository(factory))
    assert caught.value.error_code == "ae.nsl_binding_write_conflict"
    assert caught.value.retryable is True


def test_repository_rejects_missing_artifact_context_and_selector_mismatch(
    store,
) -> None:
    engine, factory = store
    with pytest.raises(NSLStepExecutionError) as caught:
        _bind(_repository(factory), verified_artifact_ref="AE:NSL_ARTIFACT:missing")
    assert caught.value.error_code == "ae.nsl_binding_artifact_not_found"

    with engine.begin() as connection:
        connection.execute(
            text("UPDATE ae_executable_step SET capability_version = '2.0.0'")
        )
    with pytest.raises(NSLStepExecutionError) as caught:
        _bind(_repository(factory))
    assert caught.value.error_code == "ae.nsl_binding_artifact_mismatch"

    with engine.begin() as connection:
        connection.execute(
            text("UPDATE ae_executable_step SET capability_version = '1.0.0'")
        )
        connection.execute(text("DELETE FROM ae_agent_context"))
    with pytest.raises(NSLStepExecutionError) as caught:
        _bind(_repository(factory))
    assert caught.value.error_code == "ae.nsl_binding_context_not_found"


def test_repository_rejects_non_local_step_and_context_mismatch(store) -> None:
    engine, factory = store
    with engine.begin() as connection:
        connection.execute(text("UPDATE ae_executable_step SET step_type = 'REPORT'"))
    with pytest.raises(NSLStepExecutionError, match="planned LOCAL_SKILL"):
        _bind(_repository(factory))

    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE ae_executable_step SET step_type = 'LOCAL_SKILL', "
                "executor_kind = 'DETERMINISTIC_REPORT'"
            )
        )
    with pytest.raises(NSLStepExecutionError, match="non-local-Skill"):
        _bind(_repository(factory))

    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE ae_executable_step SET executor_kind = 'LOCAL_SKILL_UNAVAILABLE'"
            )
        )
    context = _example("p6-golden-context-projection-v1.json")
    context["agent_context_hash"] = "sha256:" + "1" * 64
    context["projection_hash"] = semantic_sha256_hash_ref(
        {key: item for key, item in context.items() if key != "projection_hash"}
    )
    with pytest.raises(NSLStepExecutionError) as caught:
        _bind(_repository(factory), context_projection=context)
    assert caught.value.error_code == "ae.nsl_binding_context_mismatch"


def test_active_local_skill_binding_requires_exact_runtime_artifact_lineage(
    store,
) -> None:
    engine, factory = store
    artifact = _example("p6-golden-verified-artifact-v1.json")
    skill_binding = {
        "skill_id": artifact["skill_id"],
        "exact_skill_version": artifact["skill_version"],
        "skill_semantic_hash": artifact["skill_semantic_hash"],
        "runtime_contract_ref": artifact["runtime_contract_ref"],
        "trust_policy_id": artifact["trust_evidence"]["trust_policy_id"],
        "backend_profile": "NSL_V01_PROCESS_ISOLATED",
        "package_requirement": "SIGNED_TRUSTED_ACTIVE",
    }
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE ae_executable_step SET executor_kind = 'LOCAL_SKILL'")
        )
    with pytest.raises(NSLStepExecutionError, match="exact compiled binding"):
        _bind(_repository(factory))

    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE ae_executable_step SET executor_kind = 'LOCAL_SKILL', "
                "skill_binding_json = :binding"
            ),
            {"binding": json.dumps(skill_binding, sort_keys=True)},
        )
    assert _bind(_repository(factory))["binding"]["state"] == "REQUEST_BOUND"

    changed = {**skill_binding, "runtime_contract_ref": "contract://wrong/v1"}
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM ae_nsl_step_execution"))
        connection.execute(
            text("UPDATE ae_executable_step SET skill_binding_json = :binding"),
            {"binding": json.dumps(changed, sort_keys=True)},
        )
    with pytest.raises(NSLStepExecutionError) as caught:
        _bind(_repository(factory))
    assert caught.value.error_code == "ae.nsl_binding_artifact_mismatch"


def test_active_local_skill_binding_allows_distinct_capability_and_skill_ids(
    store,
) -> None:
    engine, factory = store
    artifact = _example("p6-golden-verified-artifact-v1.json")
    capability_id = "FINANCE.PROJECT_BUDGET_REVIEW"
    skill_binding = {
        "capability_id": capability_id,
        "skill_id": artifact["skill_id"],
        "exact_skill_version": artifact["skill_version"],
        "skill_semantic_hash": artifact["skill_semantic_hash"],
        "runtime_contract_ref": artifact["runtime_contract_ref"],
        "trust_policy_id": artifact["trust_evidence"]["trust_policy_id"],
        "backend_profile": "NSL_V01_PROCESS_ISOLATED",
        "package_requirement": "SIGNED_TRUSTED_ACTIVE",
    }
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE ae_executable_step SET executor_kind = 'LOCAL_SKILL', "
                "required_capability = :capability_id, skill_binding_json = :binding"
            ),
            {
                "capability_id": capability_id,
                "binding": json.dumps(skill_binding, sort_keys=True),
            },
        )

    saved = _bind(_repository(factory))

    assert saved["binding"]["skill_id"] == artifact["skill_id"]
    assert saved["binding"]["state"] == "REQUEST_BOUND"

    skill_binding["capability_id"] = "FINANCE.OTHER_CAPABILITY"
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM ae_nsl_step_execution"))
        connection.execute(
            text("UPDATE ae_executable_step SET skill_binding_json = :binding"),
            {"binding": json.dumps(skill_binding, sort_keys=True)},
        )
    with pytest.raises(NSLStepExecutionError) as caught:
        _bind(_repository(factory))
    assert caught.value.error_code == "ae.nsl_binding_artifact_mismatch"


def test_p6_step_result_v12_writer_reader_and_p5_compatibility(store) -> None:
    engine, factory = store
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE ae_executable_step SET executor_kind = 'LOCAL_SKILL', state = 'SUCCEEDED'"
            )
        )
    result = build_step_result(
        step_result_id="88888888-8888-4888-8888-888888888888",
        execution_id=EXECUTION_ID,
        executable_plan_id=PLAN_ID,
        executable_step_id=STEP_ID,
        compiled_step_key="E1",
        logical_step_ref="S1",
        executor_kind="LOCAL_SKILL",
        attempt_no=1,
        status="SUCCEEDED",
        result_contract_ref="contract://nex/ae/nsl-read-result/v1",
        result_payload={
            "nsl_result_summary_ref": f"AE:NSL_RESULT_SUMMARY:{NSL_ID}",
            "nsl_execution_id": NSL_ID,
            "execution_status": "COMPLETED",
        },
        artifact_refs=(
            _example("p6-golden-verified-artifact-v1.json")["artifact_ref"],
        ),
        evidence_refs=(f"NSL:AUDIT:{NSL_ID}", f"NSL:SNAPSHOT:{NSL_ID}"),
        business_operation_id=BOI,
        started_at=NOW,
        completed_at="2026-10-14T07:00:01Z",
    )
    assert result == _example("p6-golden-step-result-v1.2.json")
    repository = SqlAlchemyStepResultRepository(factory)
    assert repository.save(tenant_id=TENANT, step_result=result) == result
    assert (
        repository.get_by_step(tenant_id=TENANT, executable_step_id=STEP_ID) == result
    )

    historical = copy.deepcopy(result)
    historical["schema_version"] = "1.1"
    historical.pop("executor_kind")
    historical["business_operation_id"] = None
    historical["result_hash"] = semantic_sha256_hash_ref(
        {
            key: value
            for key, value in historical.items()
            if key
            not in {"step_result_id", "started_at", "completed_at", "result_hash"}
        }
    )
    assert validate_step_result_contract(historical)["schema_version"] == "1.1"


def test_p6_step_result_rejects_missing_or_misplaced_business_operation_id() -> None:
    values = {
        "step_result_id": "88888888-8888-4888-8888-888888888888",
        "execution_id": EXECUTION_ID,
        "executable_plan_id": PLAN_ID,
        "executable_step_id": STEP_ID,
        "compiled_step_key": "E1",
        "logical_step_ref": "S1",
        "attempt_no": 1,
        "status": "SUCCEEDED",
        "result_contract_ref": "contract://nex/ae/nsl-read-result/v1",
        "result_payload": {},
        "started_at": NOW,
        "completed_at": "2026-10-14T07:00:01Z",
    }
    with pytest.raises(StepResultError, match="UUID"):
        build_step_result(**values, executor_kind="LOCAL_SKILL")
    with pytest.raises(StepResultError, match="remain null"):
        build_step_result(
            **values,
            executor_kind="DETERMINISTIC_REPORT",
            business_operation_id=BOI,
        )

    report = build_step_result(
        **values,
        executor_kind="DETERMINISTIC_REPORT",
        business_operation_id=None,
    )
    assert report["business_operation_id"] is None

    with pytest.raises(StepResultError, match="executor_kind"):
        build_step_result(**values, executor_kind="UNKNOWN")

    local = build_step_result(
        **values,
        executor_kind="LOCAL_SKILL",
        business_operation_id=BOI,
    )
    local["operation_fingerprint"] = "forbidden"
    with pytest.raises(StepResultError, match="fingerprint"):
        validate_step_result_contract(local)


def test_migration_uses_short_names_and_adds_binding_and_v12_support() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    names = (
        "ae_nsl_step_execution",
        "ux_ae_nsl_step_nsl_id",
        "ux_ae_nsl_step_boi",
        "ux_ae_nsl_step_request",
        "fk_ae_nsl_step_step",
        "fk_ae_nsl_step_execution",
        "fk_ae_nsl_step_plan",
        "fk_ae_nsl_step_context",
        "fk_ae_nsl_step_artifact",
        "ck_ae_nsl_step_json",
        "idx_ae_nsl_step_state",
        "ck_ae_step_result_v12",
        "ck_ae_step_result_json_v12",
        "idx_ae_step_result_boi",
    )
    assert "2202_ae_nsl_step_execution" in sql
    assert (
        "UNIQUE (tenant_id, executable_step_id)" not in sql
    )  # primary key is authoritative
    assert "ADD COLUMN IF NOT EXISTS executor_kind" in sql
    assert all(len(name) <= 30 for name in names)


def test_repository_maps_unavailable_store() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    repository = SqlAlchemyNSLStepExecutionRepository(factory)
    with pytest.raises(NSLStepExecutionError) as caught:
        repository.get(tenant_id=TENANT, executable_step_id=STEP_ID)
    assert caught.value.error_code == "ae.nsl_binding_store_unavailable"
    assert caught.value.retryable is True
    engine.dispose()


def test_low_level_validation_and_store_failure_branches(store) -> None:
    engine, factory = store
    execution_module._reject_private_material([])
    with pytest.raises(NSLStepExecutionError, match="must be an object"):
        validate_context_projection([])  # type: ignore[arg-type]
    with pytest.raises(NSLStepExecutionError, match="canonical JSON"):
        validate_context_projection({"bad": {"not-json"}})
    with pytest.raises(NSLStepExecutionError, match="not an object"):
        execution_module._json_object("fixture", [])
    with pytest.raises(NSLStepExecutionError, match="bounded reference"):
        execution_module._refs("refs", "bad", 1)
    with pytest.raises(NSLStepExecutionError, match="duplicate"):
        execution_module._refs("refs", ["same", "same"], 2)
    with pytest.raises(NSLStepExecutionError, match="bounded text"):
        execution_module._text_list("roles", "bad", 1)
    with pytest.raises(NSLStepExecutionError, match="duplicate"):
        execution_module._text_list("roles", ["same", "same"], 2)
    for value in (None, "not-a-uuid"):
        with pytest.raises(NSLStepExecutionError, match="UUID"):
            execution_module._uuid("id", value)
    with pytest.raises(NSLStepExecutionError, match="SHA-256"):
        execution_module._hash("hash", "bad")
    with pytest.raises(NSLStepExecutionError, match="ASCII selector"):
        execution_module._selector("selector", "has space")
    with pytest.raises(NSLStepExecutionError, match="bounded string"):
        execution_module._text("text", "", 3)
    with pytest.raises(NSLStepExecutionError, match="supported range"):
        execution_module._bounded_int("count", True, 0, 1)
    for value in (None, "not-a-time", "2026-10-14T07:00:00"):
        with pytest.raises(NSLStepExecutionError, match="date-time|timezone"):
            execution_module._timestamp("time", value)
    assert "JSONB" in execution_module.nsl_step_execution_table_sql("postgresql")[0]
    assert "CAST(:binding_json AS JSONB)" in execution_module._insert_sql("postgresql")

    with engine.begin() as connection:
        connection.execute(text("DROP TABLE ae_nsl_step_execution"))
    with pytest.raises(NSLStepExecutionError) as caught:
        _bind(_repository(factory))
    assert caught.value.error_code == "ae.nsl_binding_store_unavailable"
