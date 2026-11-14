from __future__ import annotations

import json
import uuid
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from nex_eos import (
    EOS_ACCOUNT_TABLE,
    EOS_ACCOUNTING_PERIOD_TABLE,
    EOS_LEGAL_ENTITY_TABLE,
    EOS_NVT_PROJECT_TABLE,
    EOS_PROJECT_PNL_COMPONENT_TABLE,
    EOS_PROJECT_PNL_PROJECTION_TABLE,
    EOS_PROJECT_TABLE,
    PROJECT_PNL_CLASSIFICATIONS,
    PROJECT_PNL_DATA_CLASSIFICATIONS,
    PROJECT_PNL_FRESHNESS_STATUSES,
    PROJECT_PNL_PROJECTION_SCHEMA,
    PROJECT_PNL_RECONCILIATION_STATUSES,
    PROJECT_PNL_ROLLUP_CLASSES,
    PROJECT_PNL_SOURCE_KINDS,
    EosProjectPnlPersistenceError,
    ProjectPnlComponentDraft,
    ProjectPnlProjectionDraft,
    SqlAlchemyEosProjectPnlRepository,
    build_project_pnl_records,
    create_eos_app,
)
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = (
    ROOT / "contracts/schemas/service/nex_eos/project_pnl_projection.v1.schema.json"
)
MIGRATION_PATH = (
    ROOT / "database/nex-eos/migrations/2543_eos_project_pnl_projection.sql"
)

TENANT = "W601"
COMPANY_ID = "76000000-0000-4000-8000-000000000001"
NVT_ID = "76000000-0000-4000-8000-000000000002"
PROJECT_ID = "76000000-0000-4000-8000-000000000003"
PERIOD_ID = "76000000-0000-4000-8000-000000000004"
PROJECTION_ID = "76000000-0000-4000-8000-000000000005"
ACCOUNT_ID = "76000000-0000-4000-8000-000000000006"
NOW = datetime(2026, 11, 14, 9, 0, tzinfo=UTC)
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


def _runtime():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for table in (
        EOS_LEGAL_ENTITY_TABLE,
        EOS_NVT_PROJECT_TABLE,
        EOS_PROJECT_TABLE,
        EOS_ACCOUNT_TABLE,
        EOS_ACCOUNTING_PERIOD_TABLE,
        EOS_PROJECT_PNL_PROJECTION_TABLE,
        EOS_PROJECT_PNL_COMPONENT_TABLE,
    ):
        table.create(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    runtime = SimpleNamespace(
        engine=engine,
        sessions=sessions,
        repository=SqlAlchemyEosProjectPnlRepository(sessions),
    )
    _seed(runtime)
    return runtime


def _seed(runtime) -> None:
    with runtime.sessions.begin() as session:
        session.execute(
            EOS_LEGAL_ENTITY_TABLE.insert().values(
                tenant_id=TENANT,
                company_id=COMPANY_ID,
                company_code="W601",
                name="W60 Company",
                functional_currency="KRW",
                presentation_currency="KRW",
                business_timezone="Asia/Seoul",
                status="ACTIVE",
                effective_from=date(2026, 1, 1),
                version=1,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.execute(
            EOS_NVT_PROJECT_TABLE.insert().values(
                tenant_id=TENANT,
                nvt_project_id=NVT_ID,
                nvt_project_code="W601-NVT",
                name="W60 NVT",
                status="ACTIVE",
                version=1,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.execute(
            EOS_PROJECT_TABLE.insert().values(
                tenant_id=TENANT,
                project_id=PROJECT_ID,
                project_code="W601D260001",
                project_request_code="W601R260001",
                purpose_type="D",
                origin="APPROVED_APPLICATION",
                approval_evidence_ref="eos.approval:w60-project",
                approval_evidence_hash=HASH_A,
                project_owner_subject_id="employee-owner",
                project_manager_subject_id="employee-pm",
                agent_sync_state="IN_SYNC",
                authorization_sync_state="IN_SYNC",
                authorization_version=1,
                name="W60 Project",
                parent_project_id=None,
                nvt_project_id=NVT_ID,
                hierarchy_depth=1,
                status="ACTIVE",
                start_date=date(2026, 1, 1),
                end_date=None,
                currency="KRW",
                version=1,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.execute(
            EOS_ACCOUNT_TABLE.insert().values(
                tenant_id=TENANT,
                account_id=ACCOUNT_ID,
                account_code="5100",
                name="Project expense",
                category="EXPENSE",
                account_type="PROJECT_EXPENSE",
                status="ACTIVE",
                effective_from=date(2026, 1, 1),
                effective_until=None,
                version=1,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.execute(
            EOS_ACCOUNTING_PERIOD_TABLE.insert().values(
                tenant_id=TENANT,
                company_id=COMPANY_ID,
                period_id=PERIOD_ID,
                fiscal_year=2026,
                period_no=11,
                start_date=date(2026, 11, 1),
                end_date=date(2026, 11, 30),
                state="OPEN",
                version=1,
                close_proof_ref=None,
                closed_at=None,
                ledger_cutoff_watermark=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )


def _draft(**overrides):
    value = ProjectPnlProjectionDraft(
        tenant_id=TENANT,
        company_id=COMPANY_ID,
        projection_id=PROJECTION_ID,
        project_id=PROJECT_ID,
        project_code="W601D260001",
        period_id=PERIOD_ID,
        projection_version=1,
        functional_currency="KRW",
        as_of=NOW,
        posting_watermark="eos.journal:watermark:11",
        posting_watermark_at=NOW - timedelta(seconds=5),
        allocation_watermark="eos.allocation:watermark:7",
        allocation_watermark_at=NOW - timedelta(seconds=4),
        budget_watermark="eos.budget:watermark:2",
        budget_watermark_at=NOW - timedelta(seconds=3),
        reconciliation_status="VERIFIED",
        freshness_status="CURRENT",
        staleness_seconds=5,
        data_classification="CONFIDENTIAL_FINANCIAL",
    )
    return replace(value, **overrides)


def _components():
    return (
        ProjectPnlComponentDraft(
            classification="POSTED_REVENUE",
            source_kind="REVENUE",
            functional_amount=Decimal("1000.0000"),
            source_ref="eos.journal:revenue:line:1",
            source_hash=HASH_A,
            account_id=ACCOUNT_ID,
        ),
        ProjectPnlComponentDraft(
            classification="POSTED_DIRECT_COST",
            source_kind="SERVICE",
            functional_amount=Decimal("100.0000"),
            source_ref="eos.journal:service:line:2",
            source_hash=HASH_B,
            account_id=ACCOUNT_ID,
            work_code="FL0004001",
        ),
        ProjectPnlComponentDraft(
            classification="POSTED_LABOR_ALLOCATED",
            source_kind="PAYROLL",
            functional_amount=Decimal("300.0000"),
            source_ref="eos.allocation:payroll:line:1",
            source_hash="sha256:" + "c" * 64,
            data_classification="PAYROLL_SENSITIVE",
        ),
        ProjectPnlComponentDraft(
            classification="POSTED_PAYROLL_UNALLOCATED",
            source_kind="PAYROLL",
            functional_amount=Decimal("25.0000"),
            source_ref="eos.pool:payroll:residual",
            source_hash="sha256:" + "d" * 64,
            data_classification="PAYROLL_SENSITIVE",
        ),
        ProjectPnlComponentDraft(
            classification="PLANNED_BUDGET",
            source_kind="OTHER",
            functional_amount=Decimal("500.0000"),
            source_ref="eos.budget:w60",
            source_hash="sha256:" + "e" * 64,
        ),
        ProjectPnlComponentDraft(
            classification="PLANNED_LABOR",
            source_kind="PAYROLL",
            functional_amount=Decimal("50.0000"),
            source_ref="eos.work-assignment:w60",
            source_hash="sha256:" + "f" * 64,
            data_classification="PAYROLL_SENSITIVE",
        ),
        ProjectPnlComponentDraft(
            classification="MATERIAL_COMMITTED",
            source_kind="MATERIAL",
            functional_amount=Decimal("75.0000"),
            source_ref="eos.material-commitment:w60",
            source_hash="sha256:" + "1" * 64,
        ),
    )


def test_projection_contract_and_migration_define_foundation() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    migration = MIGRATION_PATH.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS eos_project_pnl_projection" in migration
    assert "CREATE TABLE IF NOT EXISTS eos_project_pnl_component" in migration
    assert "2543_eos_project_pnl_projection" in migration
    assert "material_commitment_watermark" in migration
    assert "payroll_evidence_watermark" in migration
    assert (
        max(
            len(item.name)
            for table in (
                EOS_PROJECT_PNL_PROJECTION_TABLE,
                EOS_PROJECT_PNL_COMPONENT_TABLE,
            )
            for item in table.constraints
            if item.name
        )
        < 64
    )


def test_classification_catalog_is_closed_and_has_required_boundaries() -> None:
    assert {
        "POSTED_REVENUE",
        "POSTED_DIRECT_COST",
        "POSTED_ALLOCATED_COST",
        "POSTED_LABOR_ALLOCATED",
        "POSTED_PAYROLL_UNALLOCATED",
        "LABOR_ALLOCATION_PROVISIONAL",
        "MATERIAL_COMMITTED",
        "UNASSIGNED_INVENTORY",
        "BOM_FORECAST",
    } <= PROJECT_PNL_CLASSIFICATIONS
    assert PROJECT_PNL_RECONCILIATION_STATUSES == {
        "VERIFIED",
        "PENDING",
        "BLOCKED",
        "PARTIAL",
    }
    assert PROJECT_PNL_FRESHNESS_STATUSES == {"CURRENT", "STALE", "UNKNOWN"}
    assert "PAYROLL_SENSITIVE" in PROJECT_PNL_DATA_CLASSIFICATIONS
    assert "PAYROLL" in PROJECT_PNL_SOURCE_KINDS
    assert "COMMITMENT" in PROJECT_PNL_ROLLUP_CLASSES


def test_build_records_is_deterministic_and_separates_actual_from_outlook() -> None:
    header, lines = build_project_pnl_records(_draft(), _components())
    repeated_header, repeated_lines = build_project_pnl_records(_draft(), _components())
    assert header == repeated_header
    assert lines == repeated_lines
    assert header["posted_revenue"] == Decimal("1000.0000")
    assert header["posted_direct_cost"] == Decimal("100.0000")
    assert header["posted_allocated_cost"] == Decimal("300.0000")
    assert header["posted_operating_result"] == Decimal("600.0000")
    assert header["operating_unallocated_cost"] == Decimal("25.0000")
    assert header["planned_budget"] == Decimal("500.0000")
    assert header["budget_actual"] == Decimal("400.0000")
    assert header["budget_variance"] == Decimal("100.0000")
    assert header["forecast"] == Decimal("50.0000")
    committed = next(
        item for item in lines if item["classification"] == "MATERIAL_COMMITTED"
    )
    assert committed["rollup_class"] == "COMMITMENT"
    assert committed["confirmed"] is False
    assert header["projection_hash"].startswith("sha256:")
    assert len({item["component_hash"] for item in lines}) == len(lines)


def test_repository_append_exact_replay_and_next_version() -> None:
    runtime = _runtime()
    try:
        created = runtime.repository.append(_draft(), _components())
        replay = runtime.repository.append(_draft(), _components())
        assert replay == created
        assert created["as_of"].endswith("+00:00")
        assert created["schema_version"] == PROJECT_PNL_PROJECTION_SCHEMA
        assert created["posted_operating_result"] == "600.0000"
        assert len(created["components"]) == 7
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(created)

        second = runtime.repository.append(
            _draft(
                projection_id=str(uuid.uuid4()),
                projection_version=2,
                as_of=NOW + timedelta(minutes=1),
            ),
            _components()
            + (
                ProjectPnlComponentDraft(
                    classification="FORECAST",
                    source_kind="OTHER",
                    functional_amount=Decimal("10.0000"),
                    source_ref="eos.forecast:w60:v2",
                    source_hash="sha256:" + "2" * 64,
                ),
            ),
        )
        assert second["projection_version"] == 2
        assert second["forecast"] == "60.0000"
        assert (
            runtime.repository.get(
                tenant_id=TENANT,
                company_id=COMPANY_ID,
                project_id=PROJECT_ID,
                period_id=PERIOD_ID,
            )
            == second
        )
        assert (
            runtime.repository.get(
                tenant_id=TENANT,
                company_id=COMPANY_ID,
                project_id=PROJECT_ID,
                period_id=PERIOD_ID,
                projection_version=1,
            )
            == created
        )
        with runtime.sessions() as session:
            assert (
                session.scalar(
                    select(func.count()).select_from(EOS_PROJECT_PNL_PROJECTION_TABLE)
                )
                == 2
            )
            assert (
                session.scalar(
                    select(func.count()).select_from(EOS_PROJECT_PNL_COMPONENT_TABLE)
                )
                == 15
            )
    finally:
        runtime.engine.dispose()


def test_repository_rejects_changed_replay_and_version_gap() -> None:
    runtime = _runtime()
    try:
        runtime.repository.append(_draft(), _components())
        with pytest.raises(EosProjectPnlPersistenceError) as changed:
            runtime.repository.append(
                _draft(),
                _components()
                + (
                    ProjectPnlComponentDraft(
                        classification="FORECAST",
                        source_kind="OTHER",
                        functional_amount=Decimal("1.0000"),
                        source_ref="eos.forecast:changed",
                        source_hash="sha256:" + "3" * 64,
                    ),
                ),
            )
        assert changed.value.error_code == "PROJECT_PNL_CONFLICT"
        with pytest.raises(EosProjectPnlPersistenceError) as gap:
            runtime.repository.append(
                _draft(projection_id=str(uuid.uuid4()), projection_version=3),
                _components(),
            )
        assert "next immutable revision 2" in gap.value.detail
    finally:
        runtime.engine.dispose()


@pytest.mark.parametrize(
    ("draft", "components", "field"),
    [
        (_draft(project_code="bad"), _components(), "project_code"),
        (_draft(freshness_status="fresh"), _components(), "freshness_status"),
        (_draft(staleness_seconds=-1), _components(), "staleness_seconds"),
        (
            _draft(budget_watermark="eos.budget:only", budget_watermark_at=None),
            _components(),
            "budget_watermark",
        ),
        (
            _draft(posting_watermark_at=NOW + timedelta(seconds=1)),
            _components(),
            "as_of",
        ),
        (
            _draft(as_of=NOW.replace(tzinfo=None)),
            _components(),
            "as_of",
        ),
        (
            _draft(),
            (
                ProjectPnlComponentDraft(
                    classification="UNKNOWN",
                    source_kind="OTHER",
                    functional_amount=Decimal("1.0000"),
                    source_ref="eos.invalid:1",
                    source_hash=HASH_A,
                ),
            ),
            "classification",
        ),
        (
            _draft(),
            (
                ProjectPnlComponentDraft(
                    classification="FORECAST",
                    source_kind="UNKNOWN",
                    functional_amount=Decimal("1.0000"),
                    source_ref="eos.invalid:2",
                    source_hash=HASH_A,
                ),
            ),
            "source_kind",
        ),
        (
            _draft(),
            (
                ProjectPnlComponentDraft(
                    classification="POSTED_DIRECT_COST",
                    source_kind="SERVICE",
                    functional_amount=Decimal("-1.0000"),
                    source_ref="eos.invalid:3",
                    source_hash=HASH_A,
                ),
            ),
            "functional_amount",
        ),
        (
            _draft(),
            (
                ProjectPnlComponentDraft(
                    classification="POSTED_DIRECT_COST",
                    source_kind="SERVICE",
                    functional_amount=Decimal("0.0000"),
                    source_ref="eos.invalid:4",
                    source_hash=HASH_A,
                ),
            ),
            "functional_amount",
        ),
    ],
)
def test_build_records_rejects_invalid_boundaries(draft, components, field) -> None:
    with pytest.raises(EosProjectPnlPersistenceError) as error:
        build_project_pnl_records(draft, components)
    assert field in error.value.detail
    assert error.value.status_code == 400


@pytest.mark.parametrize(
    ("override", "detail"),
    [
        ({"functional_currency": "USD"}, "functional currency"),
        ({"project_code": "W601M260001"}, "Project Code"),
        ({"project_id": str(uuid.uuid4())}, "Project was not found"),
        ({"period_id": str(uuid.uuid4())}, "AccountingPeriod was not found"),
        ({"company_id": str(uuid.uuid4())}, "LegalEntity was not found"),
    ],
)
def test_repository_fails_closed_on_authority_mismatch(override, detail) -> None:
    runtime = _runtime()
    try:
        with pytest.raises(EosProjectPnlPersistenceError) as error:
            runtime.repository.append(_draft(**override), _components())
        assert detail in error.value.detail
        assert error.value.status_code in {404, 409}
    finally:
        runtime.engine.dispose()


def test_empty_projection_is_valid_and_missing_read_returns_none() -> None:
    runtime = _runtime()
    try:
        created = runtime.repository.append(_draft(), ())
        assert created["posted_operating_result"] == "0.0000"
        assert created["components"] == []
        assert (
            runtime.repository.get(
                tenant_id=TENANT,
                company_id=COMPANY_ID,
                project_id=str(uuid.uuid4()),
                period_id=PERIOD_ID,
            )
            is None
        )
    finally:
        runtime.engine.dispose()


def test_runtime_wires_repository_only_when_database_is_configured() -> None:
    app = create_eos_app(environ={"NEX_PROFILE": "test"})
    assert app.state.eos_project_pnl_repository is None


@pytest.mark.parametrize(
    ("draft", "components", "field"),
    [
        (_draft(tenant_id="bad tenant"), _components(), "tenant_id"),
        (_draft(company_id="not-a-uuid"), _components(), "company_id"),
        (_draft(functional_currency="KR"), _components(), "functional_currency"),
        (_draft(projection_version=True), _components(), "projection_version"),
        (_draft(projection_version="bad"), _components(), "projection_version"),
        (_draft(projection_version=0), _components(), "projection_version"),
        (_draft(staleness_seconds=True), _components(), "staleness_seconds"),
        (_draft(staleness_seconds="bad"), _components(), "staleness_seconds"),
        (_draft(posting_watermark=""), _components(), "posting_watermark"),
        (
            _draft(budget_watermark=None, budget_watermark_at=NOW),
            _components(),
            "budget_watermark",
        ),
        (
            _draft(reconciliation_status="invalid"),
            _components(),
            "reconciliation_status",
        ),
        (_draft(data_classification="PUBLIC"), _components(), "data_classification"),
        (
            _draft(),
            (
                ProjectPnlComponentDraft(
                    classification="POSTED_DIRECT_COST",
                    source_kind="SERVICE",
                    functional_amount="not-money",
                    source_ref="eos.invalid:money",
                    source_hash=HASH_A,
                ),
            ),
            "functional_amount",
        ),
        (
            _draft(),
            (
                ProjectPnlComponentDraft(
                    classification="POSTED_DIRECT_COST",
                    source_kind="SERVICE",
                    functional_amount=Decimal("Infinity"),
                    source_ref="eos.invalid:finite",
                    source_hash=HASH_A,
                ),
            ),
            "functional_amount",
        ),
        (
            _draft(),
            (
                ProjectPnlComponentDraft(
                    classification="POSTED_DIRECT_COST",
                    source_kind="SERVICE",
                    functional_amount=Decimal(1),
                    source_ref="",
                    source_hash=HASH_A,
                ),
            ),
            "source_ref",
        ),
        (
            _draft(),
            (
                ProjectPnlComponentDraft(
                    classification="POSTED_DIRECT_COST",
                    source_kind="SERVICE",
                    functional_amount=Decimal(1),
                    source_ref="eos.invalid:hash",
                    source_hash="sha256:bad",
                ),
            ),
            "source_hash",
        ),
        (
            _draft(),
            (
                ProjectPnlComponentDraft(
                    classification="POSTED_DIRECT_COST",
                    source_kind="SERVICE",
                    functional_amount=Decimal(1),
                    source_ref="eos.invalid:account",
                    source_hash=HASH_A,
                    account_id="not-a-uuid",
                ),
            ),
            "account_id",
        ),
        (
            _draft(),
            (
                ProjectPnlComponentDraft(
                    classification="POSTED_DIRECT_COST",
                    source_kind="SERVICE",
                    functional_amount=Decimal(1),
                    source_ref="eos.invalid:work-code",
                    source_hash=HASH_A,
                    work_code="",
                ),
            ),
            "work_code",
        ),
    ],
)
def test_extended_validation_matrix_is_fail_closed(draft, components, field) -> None:
    with pytest.raises(EosProjectPnlPersistenceError) as error:
        build_project_pnl_records(draft, components)
    assert field in error.value.detail
    assert error.value.status_code == 400


def test_get_rejects_invalid_scope_and_version() -> None:
    runtime = _runtime()
    try:
        invalid_calls = (
            {"tenant_id": "bad tenant"},
            {"company_id": "bad"},
            {"project_id": "bad"},
            {"period_id": "bad"},
            {"projection_version": False},
        )
        base = {
            "tenant_id": TENANT,
            "company_id": COMPANY_ID,
            "project_id": PROJECT_ID,
            "period_id": PERIOD_ID,
        }
        for override in invalid_calls:
            with pytest.raises(EosProjectPnlPersistenceError) as error:
                runtime.repository.get(**(base | override))
            assert error.value.status_code == 400
    finally:
        runtime.engine.dispose()


class _BrokenSessionFactory:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def begin(self):
        raise self.error

    def __call__(self):
        raise self.error


def test_repository_maps_integrity_and_database_failures() -> None:
    integrity = IntegrityError("insert", {}, RuntimeError("collision"))
    unavailable = OperationalError("select", {}, RuntimeError("offline"))

    repository = SqlAlchemyEosProjectPnlRepository(_BrokenSessionFactory(integrity))
    with pytest.raises(EosProjectPnlPersistenceError) as conflict:
        repository.append(_draft(), _components())
    assert conflict.value.error_code == "PROJECT_PNL_CONFLICT"
    assert conflict.value.status_code == 409

    repository = SqlAlchemyEosProjectPnlRepository(_BrokenSessionFactory(unavailable))
    with pytest.raises(EosProjectPnlPersistenceError) as failed_append:
        repository.append(_draft(), _components())
    assert failed_append.value.error_code == "PROJECT_PNL_UNAVAILABLE"
    with pytest.raises(EosProjectPnlPersistenceError) as failed_read:
        repository.get(
            tenant_id=TENANT,
            company_id=COMPANY_ID,
            project_id=PROJECT_ID,
            period_id=PERIOD_ID,
        )
    assert failed_read.value.error_code == "PROJECT_PNL_UNAVAILABLE"
