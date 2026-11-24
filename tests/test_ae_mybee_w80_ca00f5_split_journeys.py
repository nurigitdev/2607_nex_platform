from __future__ import annotations

import json
import os
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import nex_ae_api.accounting_allocation_plan as allocation_plan_module
import psycopg
import pytest
from mybee_ax.integrations import M1_ALLOCATION_CAPABILITY_ID
from nex_ae_api.accounting_allocation_authority import (
    build_accounting_allocation_work_intent,
    validate_accounting_allocation_work_intent,
)
from nex_ae_api.accounting_allocation_plan import (
    AccountingAllocationPlanError,
    build_accounting_allocation_runtime_work_intent,
    build_installed_accounting_allocation_plan_activation,
    materialize_accounting_allocation_plan,
)
from nex_ae_api.m1_installed_skill_runtime import M1InstalledSkillRuntime
from nex_ae_api.mybee_m1_skill_runtime import (
    build_mybee_m1_runtime_admission,
    build_mybee_m1_verified_skill_catalog,
)
from nex_ae_api.planning_capabilities import build_capability_snapshot
from nex_ae_api.product_plan_activation import (
    InstalledProductPlanActivation,
    ProductPlanActivationError,
)
from nex_ae_api.product_runtime_profile import _verify_activation_lock
from nex_ae_api.step_executors import StepExecutionContext
from nex_ae_api.work_intent import WorkIntentError
from nex_runtime import psycopg_database_url
from nex_runtime.semantic_hashes import canonical_json, semantic_sha256_hash_ref
from psycopg import sql
from run_migrations import load_migrations, run_service_migrations
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from test_ae_mybee_w70_cp_m1_e2e_fx_01b5_plan_materialization import (
    _agent_context as _persisted_agent_context,
)
from test_ae_mybee_w70_cp_m1_e2e_fx_01b5_plan_materialization import (
    _work_intent as _existing_work_intent,
)
from test_ae_mybee_w70_cp_m1_e2e_fx_01b6b4_postgres import _seed_lineage

ROOT = Path(__file__).resolve().parents[1]
TENANT = "VO00"
SUBJECT = "employee-501"
COMPANY = "51000000-0000-4000-8000-000000000001"
EXECUTION = "51000000-0000-4000-8000-000000000002"
WORK_INTENT = "51000000-0000-4000-8000-000000000003"
JOURNAL = "51000000-0000-4000-8000-000000000004"
CONTEXT = "51000000-0000-4000-8000-000000000005"
SNAPSHOT = "51000000-0000-4000-8000-000000000006"
NOW = "2026-11-25T01:00:00Z"
DATABASE_URL = os.getenv("NEX_AE_TEST_DATABASE_URL", "")
POSTGRES_SMOKE = os.getenv("NEX_AE_MYBEE_W80_CA00F5_POSTGRES_SMOKE") == "1"


def _environment() -> dict[str, str]:
    return {
        "NEX_AE_M1_SIGNED_SKILL_LOCK": str(
            ROOT / "deployment/locks/ae-mybee-m1-signed-skill-checkpoint.v4.json"
        ),
        "NEX_AE_PRODUCT_CAPABILITY_REGISTRY_PATH": str(
            ROOT
            / "deployment/environments/ae-product-capability-registry.mybee-m1.v5.json"
        ),
    }


def _catalog():
    return build_mybee_m1_verified_skill_catalog(_environment())


def _allocation_intent(**overrides):
    values = {
        "tenant_id": TENANT,
        "company_id": COMPANY,
        "subject_id": SUBJECT,
        "execution_id": EXECUTION,
        "work_intent_id": WORK_INTENT,
        "journal_id": JOURNAL,
        "source_record_line_ref": f"eos.posted-journal-line:{JOURNAL}:1",
        "source_kind": "SERVICE",
        "projects": [
            {"project_code": "VO00D260111", "allocation_ratio": "0.25"},
            {"project_code": "VO00O260112", "allocation_ratio": "0.75"},
        ],
        "source_ref": "ia.workspace:conversation-501",
        "requested_at": NOW,
        "publication_target": "ACCOUNTING_WORKSPACE",
        "publication_target_ref": "accounting.workspace:team-1",
    }
    return validate_accounting_allocation_work_intent(
        build_accounting_allocation_work_intent(**{**values, **overrides})
    )


def _context(work_intent: dict) -> dict:
    value = {
        "context_id": CONTEXT,
        "context_generation": 1,
        "execution_id": EXECUTION,
        "identity": {
            "tenant_id": TENANT,
            "principal_id": SUBJECT,
            "agent_id": "51000000-0000-4000-8000-000000000007",
            "agent_type": "IA",
        },
        "runtime_policy_ref": {
            "policy_id": "accounting-allocation",
            "rule_hash": "sha256:" + "a" * 64,
        },
        "authority_ref": "oa.authorization:allocation",
        "resolved_entities": [],
        "conflicts": [],
        "degradations": [],
    }
    value["context_hash"] = semantic_sha256_hash_ref(value)
    return value


def _snapshot(catalog) -> dict:
    return build_capability_snapshot(
        tenant_id=TENANT,
        capability_snapshot_id=SNAPSHOT,
        snapshot_version=1,
        created_at=NOW,
        capabilities=tuple(
            selection.capability.capability for selection in catalog.selections
        ),
    )


def _materialized():
    catalog = _catalog()
    allocation = _allocation_intent()
    work_intent = build_accounting_allocation_runtime_work_intent(allocation)
    context = _context(work_intent)
    return materialize_accounting_allocation_plan(
        work_intent=work_intent,
        allocation_work_intent=allocation,
        agent_context=context,
        capability_snapshot=_snapshot(catalog),
        installed_capability=catalog.select(
            M1_ALLOCATION_CAPABILITY_ID
        ).capability.capability,
    )


def test_ca00f5_admits_signed_allocation_capability_without_changing_old_skills():
    catalog = _catalog()
    assert [item.capability.capability_id for item in catalog.selections] == [
        M1_ALLOCATION_CAPABILITY_ID,
        "FINANCE.VOUCHER.APPROVE_AND_POST",
        "PROJECT.WORK_CODE_SET.GET",
    ]
    allocation = catalog.select(M1_ALLOCATION_CAPABILITY_ID)
    assert allocation.release_skill.skill_id == "MYBEE.D04.ACCOUNTING_ALLOCATION"
    assert allocation.operation_adapter.adapter_id == (
        "nex-ae:eos-accounting-allocation:v1"
    )
    assert allocation.build_adapters(SimpleNamespace()).write_port is None


def test_ca00f5_runtime_locks_and_installed_topology_select_exact_v4_release():
    admission = json.loads(
        (ROOT / "deployment/locks/ae-mybee-m1-runtime-admission.v5.json").read_text()
    )
    activation = json.loads(
        (ROOT / "deployment/locks/ae-mybee-m1-runtime-activation.v5.json").read_text()
    )
    assert admission == build_mybee_m1_runtime_admission(_environment())
    _verify_activation_lock(
        activation,
        admission=admission,
        repository_root=ROOT,
    )
    compose = (ROOT / "deployment/compose/canonical-platform.override.yaml").read_text()
    image = (
        ROOT / "deployment/oci/canonical-platform-ae-runtime.Containerfile"
    ).read_text()
    for value in (
        "ae-mybee-m1-signed-skill-checkpoint.v4.json",
        "ae-mybee-m1-runtime-admission.v5.json",
        "ae-mybee-m1-runtime-activation.v5.json",
        "ae-product-capability-registry.mybee-m1.v5.json",
        "tool_catalog.v2.json",
    ):
        assert value in compose
        assert value in image


def test_ca00f5_materializes_deterministic_independent_allocation_plan():
    first = _materialized()
    replay = _materialized()
    assert first == replay
    assert first.validation_result["status"] == "VALID"
    assert len(first.executable_plan["steps"]) == 1
    step = first.executable_plan["steps"][0]
    assert step["required_capability"] == M1_ALLOCATION_CAPABILITY_ID
    assert step["executor_kind"] == "LOCAL_SKILL"
    encoded = step["compiled_input_bindings"][0]["value"]
    assert json.loads(encoded)["projects"] == [
        {"allocation_ratio": "0.250000000000", "project_code": "VO00D260111"},
        {"allocation_ratio": "0.750000000000", "project_code": "VO00O260112"},
    ]


def test_ca00f5_rejects_cross_principal_and_capability_drift():
    catalog = _catalog()
    allocation = _allocation_intent()
    work_intent = build_accounting_allocation_runtime_work_intent(allocation)
    context = _context(work_intent)
    context["identity"]["principal_id"] = "employee-other"
    context["context_hash"] = semantic_sha256_hash_ref(
        {k: v for k, v in context.items() if k != "context_hash"}
    )
    with pytest.raises(AccountingAllocationPlanError):
        materialize_accounting_allocation_plan(
            work_intent=work_intent,
            allocation_work_intent=allocation,
            agent_context=context,
            capability_snapshot=_snapshot(catalog),
            installed_capability=catalog.select(
                M1_ALLOCATION_CAPABILITY_ID
            ).capability.capability,
        )


def test_ca00f5_allocation_plan_rejects_invalid_inputs_and_release_drift(
    monkeypatch,
):
    catalog = _catalog()
    allocation = _allocation_intent()
    work_intent = build_accounting_allocation_runtime_work_intent(allocation)
    context = _context(work_intent)
    snapshot = _snapshot(catalog)
    installed = dict(
        catalog.select(M1_ALLOCATION_CAPABILITY_ID).capability.capability
    )

    with pytest.raises(AccountingAllocationPlanError, match="planning input"):
        materialize_accounting_allocation_plan(
            work_intent={},
            allocation_work_intent=allocation,
            agent_context=context,
            capability_snapshot=snapshot,
            installed_capability=installed,
        )

    wrong_identity = {**installed, "capability_id": "FINANCE.OTHER.RUN"}
    with pytest.raises(AccountingAllocationPlanError, match="identity differs"):
        materialize_accounting_allocation_plan(
            work_intent=work_intent,
            allocation_work_intent=allocation,
            agent_context=context,
            capability_snapshot=snapshot,
            installed_capability=wrong_identity,
        )

    missing_version = {**installed, "capability_version": "999.0.0"}
    with pytest.raises(AccountingAllocationPlanError, match="unavailable"):
        materialize_accounting_allocation_plan(
            work_intent=work_intent,
            allocation_work_intent=allocation,
            agent_context=context,
            capability_snapshot=snapshot,
            installed_capability=missing_version,
        )

    changed_contract = {**installed, "output_contract_ref": "contract://drift"}
    with pytest.raises(AccountingAllocationPlanError, match="differs from the release"):
        materialize_accounting_allocation_plan(
            work_intent=work_intent,
            allocation_work_intent=allocation,
            agent_context=context,
            capability_snapshot=snapshot,
            installed_capability=changed_contract,
        )

    monkeypatch.setattr(
        allocation_plan_module,
        "validate_agent_plan",
        lambda **_values: {"status": "INVALID", "issues": ["denied"]},
    )
    with pytest.raises(AccountingAllocationPlanError, match="compile authority"):
        materialize_accounting_allocation_plan(
            work_intent=work_intent,
            allocation_work_intent=allocation,
            agent_context=context,
            capability_snapshot=snapshot,
            installed_capability=installed,
        )


def test_ca00f5_runtime_work_intent_and_activation_wrapper_fail_closed(monkeypatch):
    allocation = _allocation_intent()
    invalid = {**allocation, "intent_hash": "sha256:" + "0" * 64}
    with pytest.raises(AccountingAllocationPlanError, match="WorkIntent is invalid"):
        build_accounting_allocation_runtime_work_intent(invalid)

    monkeypatch.setattr(
        allocation_plan_module,
        "validate_work_intent",
        lambda _value: (_ for _ in ()).throw(
            WorkIntentError("WORK_INTENT_INVALID", "invalid")
        ),
    )
    with pytest.raises(AccountingAllocationPlanError, match="runtime WorkIntent"):
        build_accounting_allocation_runtime_work_intent(allocation)

    with pytest.raises(AccountingAllocationPlanError, match="dependencies"):
        allocation_plan_module.InstalledAccountingAllocationPlanActivation(
            materializer=object(), activation=object()
        )

    calls = []

    class _Materializer:
        def materialize_accounting_allocation_plan(self, **values):
            calls.append(("materialize", values))
            return "materialized"

    class _Activation:
        def activate(self, **values):
            calls.append(("activate", values))
            return {"status": "ACTIVATED"}

    wrapper = allocation_plan_module.InstalledAccountingAllocationPlanActivation(
        materializer=_Materializer(), activation=_Activation()
    )
    result = wrapper.activate(
        work_intent={"work_intent_id": WORK_INTENT},
        allocation_work_intent=allocation,
        agent_context={"context_id": CONTEXT},
        capability_snapshot={"capability_snapshot_id": SNAPSHOT},
    )
    assert result == {"status": "ACTIVATED"}
    assert calls[1][1]["tenant_id"] == TENANT
    assert calls[1][1]["execution_id"] == EXECUTION
    assert calls[1][1]["activation_ref"] == (
        f"accounting-allocation:{allocation['intent_hash']}"
    )


class _Store:
    def __init__(self):
        self.values = {}

    def get(self, **values):
        identity = next(value for key, value in values.items() if key != "tenant_id")
        return self.values.get(identity)

    def save(self, **values):
        value = dict(values.get("agent_plan") or values.get("executable_plan"))
        identity = value.get("agent_plan_id") or value["executable_plan_id"]
        self.values[identity] = value
        return value

    def save_and_apply_runtime(self, **values):
        value = dict(values["result"])
        self.values[value["validation_result_id"]] = value
        return value


class _Executions:
    def get(self, tenant_id, execution_id):
        return {
            "tenant_id": tenant_id,
            "agent_execution_id": execution_id,
            "version": 3,
        }


class _Scheduler:
    def __init__(self):
        self.calls = []

    def schedule_next(self, **values):
        self.calls.append(values)
        return {
            "runtime_job_id": "runtime-job-501",
            "execution_id": values["execution_id"],
        }


class _NoJobScheduler(_Scheduler):
    def schedule_next(self, **values):
        self.calls.append(values)


def test_ca00f5_common_product_activation_persists_schedules_and_replays():
    plans, validations, executables = _Store(), _Store(), _Store()
    scheduler = _Scheduler()
    activation = InstalledProductPlanActivation(
        agent_plans=plans,
        validations=validations,
        executable_plans=executables,
        executions=_Executions(),
        scheduler=scheduler,
        clock=lambda: datetime(2026, 11, 25, 1, 1, tzinfo=UTC),
    )
    materialized = _materialized()
    first = activation.activate(
        tenant_id=TENANT,
        execution_id=EXECUTION,
        activation_ref="accounting-allocation:501",
        materialized=materialized,
    )
    replay = activation.activate(
        tenant_id=TENANT,
        execution_id=EXECUTION,
        activation_ref="accounting-allocation:501",
        materialized=materialized,
    )
    assert first["replayed"] == {
        "agent_plan": False,
        "validation": False,
        "executable_plan": False,
    }
    assert replay["replayed"] == {
        "agent_plan": True,
        "validation": True,
        "executable_plan": True,
    }
    assert first["activation_hash"] == replay["activation_hash"]
    assert len(scheduler.calls) == 2

    changed = deepcopy(materialized.agent_plan)
    changed["goal"] = "drift"
    with pytest.raises(ProductPlanActivationError):
        activation.activate(
            tenant_id=TENANT,
            execution_id=EXECUTION,
            activation_ref="accounting-allocation:501",
            materialized=SimpleNamespace(
                agent_plan=changed,
                validation_result=materialized.validation_result,
                executable_plan=materialized.executable_plan,
            ),
        )


def test_ca00f5_common_product_activation_rejects_invalid_runtime_boundaries():
    materialized = _materialized()
    with pytest.raises(ProductPlanActivationError, match="dependency"):
        InstalledProductPlanActivation(
            agent_plans=object(),
            validations=object(),
            executable_plans=object(),
            executions=object(),
            scheduler=object(),
        )

    with pytest.raises(ProductPlanActivationError, match="AgentPlan is unavailable"):
        InstalledProductPlanActivation(
            agent_plans=_Store(),
            validations=_Store(),
            executable_plans=_Store(),
            executions=_Executions(),
            scheduler=_Scheduler(),
        ).activate(
            tenant_id=TENANT,
            execution_id=EXECUTION,
            activation_ref="allocation:invalid",
            materialized=SimpleNamespace(),
        )

    invalid_lineage = deepcopy(materialized.validation_result)
    invalid_lineage["status"] = "INVALID"
    with pytest.raises(ProductPlanActivationError, match="lineage differs"):
        InstalledProductPlanActivation(
            agent_plans=_Store(),
            validations=_Store(),
            executable_plans=_Store(),
            executions=_Executions(),
            scheduler=_Scheduler(),
        ).activate(
            tenant_id=TENANT,
            execution_id=EXECUTION,
            activation_ref="allocation:invalid",
            materialized=SimpleNamespace(
                agent_plan=materialized.agent_plan,
                validation_result=invalid_lineage,
                executable_plan=materialized.executable_plan,
            ),
        )

    class _MissingExecution:
        def get(self, _tenant_id, _execution_id):
            return None

    with pytest.raises(ProductPlanActivationError, match="persistence lineage"):
        InstalledProductPlanActivation(
            agent_plans=_Store(),
            validations=_Store(),
            executable_plans=_Store(),
            executions=_MissingExecution(),
            scheduler=_Scheduler(),
        ).activate(
            tenant_id=TENANT,
            execution_id=EXECUTION,
            activation_ref="allocation:invalid",
            materialized=materialized,
        )

    with pytest.raises(ProductPlanActivationError, match="timezone-aware"):
        InstalledProductPlanActivation(
            agent_plans=_Store(),
            validations=_Store(),
            executable_plans=_Store(),
            executions=_Executions(),
            scheduler=_Scheduler(),
            clock=lambda: datetime(2026, 11, 25, 1, 1, tzinfo=UTC).replace(
                tzinfo=None
            ),
        ).activate(
            tenant_id=TENANT,
            execution_id=EXECUTION,
            activation_ref="allocation:invalid",
            materialized=materialized,
        )

    no_job = InstalledProductPlanActivation(
        agent_plans=_Store(),
        validations=_Store(),
        executable_plans=_Store(),
        executions=_Executions(),
        scheduler=_NoJobScheduler(),
        clock=lambda: datetime(2026, 11, 25, 1, 1, tzinfo=UTC),
    ).activate(
        tenant_id=TENANT,
        execution_id=EXECUTION,
        activation_ref="accounting-allocation:no-job",
        materialized=materialized,
    )
    assert no_job["runtime_job"] is None

    with pytest.raises(ProductPlanActivationError, match="activation_ref is invalid"):
        InstalledProductPlanActivation(
            agent_plans=_Store(),
            validations=_Store(),
            executable_plans=_Store(),
            executions=_Executions(),
            scheduler=_Scheduler(),
            clock=lambda: datetime(2026, 11, 25, 1, 1, tzinfo=UTC),
        ).activate(
            tenant_id=TENANT,
            execution_id=EXECUTION,
            activation_ref=" ",
            materialized=materialized,
        )


def test_ca00f5_installed_handler_publishes_allocation_and_pnl_refs(monkeypatch):
    import nex_ae_api.m1_installed_skill_runtime as runtime_module

    catalog = _catalog()
    allocation = _allocation_intent()
    work_intent = build_accounting_allocation_runtime_work_intent(allocation)
    runtime = object.__new__(M1InstalledSkillRuntime)
    runtime._catalog = catalog
    runtime._sessions = None

    class _AllocationRuntime:
        def execute(self, **values):
            assert values["runtime_job"]["state"] == "RUNNING"
            return {
                "journal_ref": f"eos.posted_journal:{JOURNAL}",
                "allocation_execution_authority_hash": "sha256:" + "b" * 64,
                "financial_result": {
                    "allocation_batch_ref": "eos.cost-allocation-batch:batch-501",
                    "allocation_business_operation_id": "allocation-op-501",
                    "project_results": [
                        {"projection_id": "pnl-501"},
                        {"projection_id": "pnl-502"},
                    ],
                },
                "result_hash": "sha256:" + "c" * 64,
            }

    runtime.accounting_allocation = _AllocationRuntime()
    monkeypatch.setattr(
        runtime_module,
        "_allocation_execution_context",
        lambda *_args, **_kwargs: {
            "principal_id": SUBJECT,
            "correlation_id": "correlation-501",
            "work_intent": work_intent,
        },
    )
    selection = catalog.select(M1_ALLOCATION_CAPABILITY_ID)
    context = StepExecutionContext(
        job={
            "tenant_id": TENANT,
            "runtime_job_id": "runtime-job-501",
            "job_type": "START_EXECUTION",
            "state": "RUNNING",
            "execution_id": EXECUTION,
            "dedup_key": "allocation:501",
        },
        attempt={"attempt_no": 1},
        step={
            "agent_execution_id": EXECUTION,
            "executable_step_id": "51000000-0000-4000-8000-000000000008",
            "required_capability": M1_ALLOCATION_CAPABILITY_ID,
            "output_contract_ref": selection.release_skill.output_contract_ref,
            "skill_binding": {
                "skill_id": selection.release_skill.skill_id,
                "exact_skill_version": selection.release_skill.skill_version,
                "skill_semantic_hash": selection.release_skill.semantic_hash,
                "trust_policy_id": selection.release_skill.trust_policy_id,
            },
            "compiled_input_bindings": [
                {
                    "target_name": "allocation_work_intent_json",
                    "binding_type": "LITERAL",
                    "value": canonical_json(allocation),
                }
            ],
        },
        dependency_results=(),
        existing_result=None,
    )
    outcome = runtime.initial(context, SimpleNamespace())
    assert outcome.state == "SUCCEEDED"
    assert outcome.business_operation_id == "allocation-op-501"
    assert set(outcome.external_refs) == {
        f"eos.posted_journal:{JOURNAL}",
        "eos.cost-allocation-batch:batch-501",
        "eos.project-pnl-projection:pnl-501",
        "eos.project-pnl-projection:pnl-502",
    }


@pytest.mark.skipif(
    not DATABASE_URL or not POSTGRES_SMOKE,
    reason="Protected W80 CA00F.5 AE PostgreSQL smoke is disabled",
)
def test_ca00f5_actual_postgres_activation_restart_replay_and_zero_residue():
    target = make_url(DATABASE_URL)
    assert (target.username, target.database) == ("nex_ae_user", "nex_ae_test")
    schema_name = f"mybee_w80_ca00f5_{uuid.uuid4().hex}"
    postgres_url = psycopg_database_url(DATABASE_URL)
    with psycopg.connect(postgres_url, autocommit=True) as connection:
        assert connection.execute(
            "SELECT current_database(), current_user"
        ).fetchone() == ("nex_ae_test", "nex_ae_user")
        connection.execute(
            sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name))
        )
    scoped_url = target.update_query_dict(
        {"options": f"-csearch_path={schema_name},public"}
    ).render_as_string(hide_password=False)
    engines = []
    try:
        migration = run_service_migrations(
            "nex-ae-api", database_url=scoped_url, profile="test"
        )
        assert migration.applied[-1] == load_migrations("nex-ae-api")[-1].version
        base = _existing_work_intent()
        allocation = _allocation_intent(
            subject_id="employee-100",
            execution_id=base["execution_id"],
            work_intent_id=base["work_intent_id"],
        )
        work_intent = build_accounting_allocation_runtime_work_intent(allocation)
        context = _persisted_agent_context(work_intent)
        catalog = _catalog()
        snapshot = _snapshot(catalog)

        engine = create_engine(scoped_url, poolclass=NullPool, pool_pre_ping=True)
        engines.append(engine)
        sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        _seed_lineage(
            sessions,
            work_intent=work_intent,
            agent_context=context,
            capability_snapshot=snapshot,
        )
        runtime = object.__new__(M1InstalledSkillRuntime)
        runtime._catalog = catalog
        activation = build_installed_accounting_allocation_plan_activation(
            sessions, materializer=runtime
        )
        values = {
            "work_intent": work_intent,
            "allocation_work_intent": allocation,
            "agent_context": context,
            "capability_snapshot": snapshot,
        }
        first = activation.activate(**values)

        engine.dispose()
        engine = create_engine(scoped_url, poolclass=NullPool, pool_pre_ping=True)
        engines.append(engine)
        sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        replay_runtime = object.__new__(M1InstalledSkillRuntime)
        replay_runtime._catalog = catalog
        replay = build_installed_accounting_allocation_plan_activation(
            sessions, materializer=replay_runtime
        ).activate(**values)
        assert replay["activation_hash"] == first["activation_hash"]
        assert replay["runtime_job"] == first["runtime_job"]
        assert replay["replayed"] == {
            "agent_plan": True,
            "validation": True,
            "executable_plan": True,
        }
        with sessions() as session:
            counts = {
                table: int(
                    session.execute(
                        text(f"SELECT count(*) FROM {table} WHERE tenant_id=:tenant"),
                        {"tenant": TENANT},
                    ).scalar_one()
                )
                for table in (
                    "ae_agent_plan",
                    "ae_plan_validation",
                    "ae_executable_plan",
                    "ae_executable_step",
                    "ae_runtime_job",
                )
            }
        assert counts == {
            "ae_agent_plan": 1,
            "ae_plan_validation": 1,
            "ae_executable_plan": 1,
            "ae_executable_step": 1,
            "ae_runtime_job": 1,
        }
    finally:
        for engine in engines:
            engine.dispose()
        with psycopg.connect(postgres_url, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema_name)
                )
            )
            assert connection.execute(
                "SELECT to_regnamespace(%s)", (schema_name,)
            ).fetchone() == (None,)
