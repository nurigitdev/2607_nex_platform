from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DECISION = ROOT / (
    "docs/transition/MyBee_Phase1/"
    "NeX_MyBee_CP_M1_E2E_FX_01B_6B_1A_"
    "Durable_Product_Preparation_Checkpoint_and_Approval_Event_"
    "Persistence_Decision_v1.0.md"
)
README = ROOT / "docs/transition/MyBee_Phase1/README.md"
WAIT_FOUNDATION = ROOT / "database/nex-ae-api/migrations/2402_ae_wait_registration.sql"
WAIT_TYPES = ROOT / (
    "database/nex-ae-api/migrations/2502_ae_wait_registration_generalization.sql"
)
NSL_WAIT = ROOT / (
    "database/nex-ae-api/migrations/2503_ae_nsl_approval_wait_binding.sql"
)
EVENT_TYPES = ROOT / (
    "database/nex-ae-api/migrations/2505_ae_nsl_approval_event_inbox.sql"
)
RUNTIME_JOBS = ROOT / "services/nex-ae-api/nex_ae_api/runtime_jobs.py"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _prose(path: Path) -> str:
    return " ".join(_text(path).split())


def test_decision_selects_shared_envelopes_and_typed_product_bindings() -> None:
    decision = _text(DECISION)

    for required in (
        "generic envelope",
        "typed binding",
        "ae_wait_registration",
        "ae_external_event_inbox",
        "ae_runtime_job",
        "ae_product_prep_checkpoint",
        "ae_product_prep_wait_binding",
        "ae_product_prep_event_binding",
        "WORK_RESULT",
        "NSL_APPROVAL",
        "PRODUCT_PREPARATION",
    ):
        assert required in decision

    assert "ae_product_prep_event_inbox` as a second event state machine" in decision
    assert "a Product Preparation job queue" in decision
    assert "an M1 resume daemon" in decision


def test_decision_freezes_incremental_compatibility_and_generic_routing() -> None:
    decision = _text(DECISION)

    for required in (
        "EXECUTABLE_STEP",
        "PRODUCT_COORDINATOR",
        "resume_target_kind",
        "wait_contract_ref",
        "event_family",
        "RESUME_EXECUTION",
        "handler registry",
        "CONTRACT_ONLY",
    ):
        assert required in decision

    assert "preserve current WorkResult and NSL columns, constraints, APIs" in decision
    assert "defer normalization of legacy WorkResult/NSL-specific columns" in decision
    assert "No new Product Preparation job type is authorized" in decision


def test_decision_is_backed_by_current_wait_event_and_job_constraints() -> None:
    wait_foundation = _text(WAIT_FOUNDATION)
    wait_types = _text(WAIT_TYPES)
    nsl_wait = _text(NSL_WAIT)
    event_types = _text(EVENT_TYPES)
    runtime_jobs = _text(RUNTIME_JOBS)

    assert "executable_step_id TEXT NOT NULL" in wait_foundation
    assert "REFERENCES ae_executable_step" in wait_foundation
    assert "wait_type IN ('WORK_RESULT', 'NSL_APPROVAL')" in wait_types
    assert "ck_ae_wait_nsl_approval_lineage" in nsl_wait
    assert (
        "event_type IN ('WORK_RESULT_SUBMITTED', 'NSL_APPROVAL_DECIDED')" in event_types
    )
    assert (
        'RUNTIME_JOB_TYPES = P4_RUNTIME_JOB_TYPES | {"RESUME_EXECUTION"}'
        in runtime_jobs
    )
    assert (
        'RESUME_TARGET_KINDS = frozenset({"EXECUTABLE_STEP", "PRODUCT_COORDINATOR"})'
        in runtime_jobs
    )
    assert "RESUME_EXECUTION requires wait_id" in runtime_jobs
    assert (
        "PRODUCT_COORDINATOR resume jobs cannot reference executable_step_id"
        in runtime_jobs
    )


def test_authorized_migration_scope_is_bounded_and_identifiers_are_safe() -> None:
    decision = _text(DECISION)
    table_names = (
        "ae_product_prep_checkpoint",
        "ae_product_prep_wait_binding",
        "ae_product_prep_event_binding",
    )

    assert "2517_ae_product_preparation_resume" in decision
    assert "one NeX-AE migration" in decision
    assert "create or change WC, OA, EOS, or WA tables" in decision
    assert "add a second wait, inbox, job queue, or worker" in decision
    assert all(len(name.encode("utf-8")) <= 63 for name in table_names)


def test_checkpoint_and_event_contracts_remain_authority_safe() -> None:
    decision = _prose(DECISION)

    for required in (
        "append-only",
        "preceding checkpoint ID and hash",
        "business context hash",
        "coordinator registration identity",
        "semantic checkpoint hash",
        "BUSINESS_APPROVAL_CHANGED",
        "ACCOUNTING_APPROVAL_CHANGED",
        "does not prove approval",
        "reload fresh authority",
        "zero mutation",
    ):
        assert required in decision

    assert "contains no raw prompt, document, voucher, payroll, account" in decision
    assert (
        "RuntimeJob payload is transport metadata, not checkpoint or approval"
        in decision
    )


def test_plan_and_registration_policies_close_6b1_gaps() -> None:
    decision = _prose(DECISION)

    for required in (
        "Provider PLAN output remains semantic evidence only",
        "AgentPlan version `1`",
        "checkpoint schema version",
        "replay policy",
        "supported executor kinds",
        "installed Skill bundle locks",
    ):
        assert required in decision

    assert "Overwrite and silent version `2` fallback are prohibited" in decision


def test_readme_admits_decision_before_6b2_without_claiming_activation() -> None:
    readme = _text(README)
    filename = DECISION.name

    assert filename in readme
    assert "generic-envelope and typed-binding architecture" in readme
    assert "The decision authorizes one" in readme
    assert "it does not activate M1" in readme
