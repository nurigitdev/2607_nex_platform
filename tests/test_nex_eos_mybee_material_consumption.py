from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import test_nex_eos_mybee_material_commitment as commitment_fixture
import test_nex_eos_mybee_voucher_candidate as posting
from nex_eos import (
    EOS_COST_SOURCE_POOL_TABLE,
    EOS_JOURNAL_HEADER_TABLE,
    EOS_JOURNAL_LINE_TABLE,
    EOS_MATERIAL_COMMITMENT_TABLE,
    EOS_MATERIAL_CONSUMPTION_TABLE,
    EOS_MATERIAL_RELEASE_TABLE,
    EosMaterialConsumptionError,
    EosMaterialConsumptionService,
    MaterialConsumptionInput,
    MaterialReleaseInput,
    ProjectPnlRebuildRequest,
    SqlAlchemyEosMaterialConsumptionRepository,
    SqlAlchemyEosProjectPnlProjectionSource,
    build_direct_allocation_projection,
)
from nex_eos import material_consumptions as consumption_module
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from run_migrations import load_migrations

POOL_A = "77510000-0000-4000-8000-000000000001"
POOL_B = "77510000-0000-4000-8000-000000000002"
HASH = "sha256:" + "7" * 64


def test_material_consumption_migration_contract_is_append_only_and_bounded() -> None:
    migration = next(
        item
        for item in load_migrations("nex-eos")
        if item.version == "2547_eos_material_consumption"
    )
    compact = " ".join(migration.sql.lower().split())
    assert "create table if not exists eos_material_consumption" in compact
    assert "create table if not exists eos_material_release" in compact
    assert "material consumption records are append-only" in compact
    assert "valuation_variance_functional = recognized_cost_functional" in compact
    assert Path(migration.path).name == "2547_eos_material_consumption.sql"
    assert all(
        constraint.name is None or len(constraint.name) <= 63
        for table in (EOS_MATERIAL_CONSUMPTION_TABLE, EOS_MATERIAL_RELEASE_TABLE)
        for constraint in table.constraints
    )


def _seed_pool(
    sessions,
    journal_id: str,
    *,
    pool_id: str = POOL_A,
    amount: Decimal = Decimal("1100.0000"),
    source_kind: str = "PURCHASE",
    allocation_mode: str = "DIRECT",
    pool_state: str = "ALLOCATED",
    project_id: str = posting.PROJECT_ID,
    project_code: str = posting.PROJECT_CODE,
):
    with sessions.begin() as session:
        header = session.execute(
            select(EOS_JOURNAL_HEADER_TABLE).where(
                EOS_JOURNAL_HEADER_TABLE.c.journal_id == journal_id
            )
        ).mappings().one()
        line = session.execute(
            select(EOS_JOURNAL_LINE_TABLE).where(
                EOS_JOURNAL_LINE_TABLE.c.journal_id == journal_id,
                EOS_JOURNAL_LINE_TABLE.c.line_no == 1,
            )
        ).mappings().one()
        session.execute(
            EOS_COST_SOURCE_POOL_TABLE.insert().values(
                tenant_id=posting.TENANT,
                company_id=posting.COMPANY_ID,
                pool_id=pool_id,
                journal_id=journal_id,
                journal_line_no=1,
                eligible_component_id=f"MATERIAL-CONSUMPTION:{pool_id}",
                source_business_operation_id=header["business_operation_id"],
                source_project_id=project_id,
                source_project_code=project_code,
                source_kind=source_kind,
                allocation_mode=allocation_mode,
                source_amount_functional=amount,
                eligible_amount_functional=amount,
                functional_currency="KRW",
                account_id=line["account_id"],
                account_category="EXPENSE",
                monetary_class="NON_MONETARY",
                recognition_date=header["recognition_date"],
                recognized_at=posting.NOW + timedelta(minutes=6),
                period_id=header["period_id"],
                source_record_ref=f"material-consumption:{pool_id}",
                source_hash=HASH,
                eligibility_policy_hash=posting.POLICY_HASH,
                pool_state=pool_state,
                source_journal_hash=header["journal_hash"],
                created_at=posting.NOW + timedelta(minutes=6),
            )
        )
    return str(header["period_id"])


def _runtime():
    engine, sessions, commitments, journal_id = commitment_fixture._runtime()
    admitted = commitments.admit(commitment_fixture._input(journal_id))
    period_id = _seed_pool(sessions, journal_id)
    service = EosMaterialConsumptionService(
        SqlAlchemyEosMaterialConsumptionRepository(
            sessions, clock=lambda: posting.NOW + timedelta(minutes=8)
        )
    )
    return engine, sessions, service, admitted, journal_id, period_id


def _input(admitted, **overrides) -> MaterialConsumptionInput:
    values = {
        "tenant_id": posting.TENANT,
        "company_id": posting.COMPANY_ID,
        "consumption_ref": "inventory-issue:2026-0001",
        "consumption_revision": 1,
        "component_ref": "material:STEEL-001:issue:1",
        "cost_pool_id": POOL_A,
        "project_id": posting.PROJECT_ID,
        "project_code": posting.PROJECT_CODE,
        "work_code": "FL0004011",
        "material_ref": "material:STEEL-001",
        "quantity_unit": "KG",
        "consumed_quantity": Decimal("10.0000"),
        "evidence_ref": "wa.inventory-issue:2026-0001",
        "evidence_hash": HASH,
        "approval_ref": "wc.approval:inventory-issue:2026-0001",
        "approval_hash": posting.PROOF_HASH,
        "policy_hash": posting.POLICY_HASH,
        "consumed_at": posting.NOW + timedelta(minutes=7),
        "releases": (
            MaterialReleaseInput(
                admitted["commitment_id"],
                1,
                Decimal("10.0000"),
                Decimal("1000.0000"),
            ),
        ),
    }
    values.update(overrides)
    return MaterialConsumptionInput(**values)


def _pnl_request(period_id: str) -> ProjectPnlRebuildRequest:
    return ProjectPnlRebuildRequest(
        posting.TENANT,
        posting.COMPANY_ID,
        posting.PROJECT_ID,
        posting.PROJECT_CODE,
        period_id,
        1,
        "KRW",
        posting.NOW + timedelta(minutes=10),
        posting.NOW + timedelta(minutes=10),
    )


def test_consumption_releases_commitment_and_reconciles_posted_cost() -> None:
    _engine, sessions, service, admitted, _journal_id, period_id = _runtime()
    created = service.reconcile(_input(admitted))
    assert created["disposition"] == "CREATED"
    assert created["recognized_cost_functional"] == "1100.0000"
    assert created["released_carrying_amount_functional"] == "1000.0000"
    assert created["valuation_variance_functional"] == "100.0000"
    assert service.reconcile(_input(admitted))["disposition"] == "EXACT_REPLAY"
    assert service.get(
        tenant_id=posting.TENANT,
        company_id=posting.COMPANY_ID,
        consumption_id=created["consumption_id"],
    )["consumption_hash"] == created["consumption_hash"]

    request = _pnl_request(period_id)
    snapshot = SqlAlchemyEosProjectPnlProjectionSource(sessions).load(request)
    assert len(snapshot.material_releases) == 1
    draft, components = build_direct_allocation_projection(request, snapshot)
    assert [
        (item.classification, item.source_kind, item.functional_amount)
        for item in components
    ] == [
        ("MATERIAL_COMMITTED", "MATERIAL", Decimal("3000.0000")),
        ("POSTED_DIRECT_COST", "MATERIAL", Decimal("1100.0000")),
    ]
    assert draft.reconciliation_status == "VERIFIED"


def test_multiple_consumptions_can_fully_release_the_original_commitment() -> None:
    _engine, sessions, service, admitted, journal_id, period_id = _runtime()
    service.reconcile(_input(admitted))
    _seed_pool(sessions, journal_id, pool_id=POOL_B, amount=Decimal("3000.0000"))
    second = _input(
        admitted,
        consumption_ref="inventory-issue:2026-0002",
        component_ref="material:STEEL-001:issue:2",
        cost_pool_id=POOL_B,
        consumed_quantity=Decimal("30.0000"),
        releases=(
            MaterialReleaseInput(
                admitted["commitment_id"], 1, Decimal(30), Decimal(3000)
            ),
        ),
    )
    service.reconcile(second)
    _draft, components = build_direct_allocation_projection(
        _pnl_request(period_id),
        SqlAlchemyEosProjectPnlProjectionSource(sessions).load(
            _pnl_request(period_id)
        ),
    )
    assert [item.classification for item in components] == [
        "POSTED_DIRECT_COST",
        "POSTED_DIRECT_COST",
    ]
    assert sum((item.functional_amount for item in components), Decimal()) == Decimal(
        "4100.0000"
    )


def test_consumption_rejects_semantic_drift_pool_reuse_and_over_release() -> None:
    _engine, sessions, service, admitted, journal_id, _period_id = _runtime()
    service.reconcile(_input(admitted))
    with pytest.raises(EosMaterialConsumptionError) as drift:
        service.reconcile(_input(admitted, material_ref="material:COPPER-001"))
    assert drift.value.error_code == "MATERIAL_CONSUMPTION_INVALID"

    with pytest.raises(EosMaterialConsumptionError) as pool_reuse:
        service.reconcile(
            _input(
                admitted,
                consumption_ref="inventory-issue:2026-0002",
                component_ref="material:STEEL-001:issue:2",
            )
        )
    assert pool_reuse.value.error_code == "MATERIAL_COST_SOURCE_ALREADY_CONSUMED"

    _seed_pool(sessions, journal_id, pool_id=POOL_B)
    with pytest.raises(EosMaterialConsumptionError) as over_release:
        service.reconcile(
            _input(
                admitted,
                consumption_ref="inventory-issue:2026-0003",
                component_ref="material:STEEL-001:issue:3",
                cost_pool_id=POOL_B,
                consumed_quantity=Decimal(31),
                releases=(
                    MaterialReleaseInput(
                        admitted["commitment_id"], 1, Decimal(31), Decimal(3100)
                    ),
                ),
            )
        )
    assert over_release.value.error_code == "MATERIAL_COMMITMENT_OVER_RELEASED"


def test_consumption_replay_detects_header_semantic_drift() -> None:
    _engine, _sessions, service, admitted, _journal_id, _period_id = _runtime()
    service.reconcile(_input(admitted))
    with pytest.raises(EosMaterialConsumptionError) as drift:
        service.reconcile(
            _input(admitted, evidence_hash="sha256:" + "8" * 64)
        )
    assert drift.value.error_code == "MATERIAL_CONSUMPTION_CONFLICT"


@pytest.mark.parametrize(
    ("pool_overrides", "message"),
    [
        ({"source_kind": "SERVICE"}, "DIRECT PURCHASE"),
        ({"allocation_mode": "MANAGEMENT_ALLOCATION"}, "DIRECT PURCHASE"),
        ({"pool_state": "ON_HOLD"}, "DIRECT PURCHASE"),
        (
            {
                "project_id": commitment_fixture.PROJECT_B,
                "project_code": commitment_fixture.PROJECT_CODE_B,
            },
            "Project differs",
        ),
    ],
)
def test_consumption_rejects_ineligible_cost_source(pool_overrides, message) -> None:
    engine, sessions, commitments, journal_id = commitment_fixture._runtime()
    admitted = commitments.admit(commitment_fixture._input(journal_id))
    _seed_pool(sessions, journal_id, **pool_overrides)
    service = EosMaterialConsumptionService(
        SqlAlchemyEosMaterialConsumptionRepository(sessions)
    )
    with pytest.raises(EosMaterialConsumptionError, match=message):
        service.reconcile(_input(admitted))
    engine.dispose()


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"releases": ()}, "releases"),
        ({"reconciliation_state": "PENDING"}, "VERIFIED"),
        ({"quantity_unit": "bad unit"}, "quantity_unit"),
        ({"consumed_quantity": Decimal(0)}, "positive"),
        ({"work_code": "INVALID"}, "work_code"),
        ({"consumed_at": posting.NOW.replace(tzinfo=None)}, "timezone-aware"),
        ({"consumed_at": posting.NOW + timedelta(hours=1)}, "future"),
    ],
)
def test_consumption_rejects_invalid_header(overrides, message) -> None:
    _engine, _sessions, service, admitted, _journal_id, _period_id = _runtime()
    with pytest.raises(EosMaterialConsumptionError, match=message):
        service.reconcile(_input(admitted, **overrides))


def test_consumption_rejects_release_mismatch_duplicate_and_cross_project() -> None:
    _engine, _sessions, service, admitted, _journal_id, _period_id = _runtime()
    source = MaterialReleaseInput(
        admitted["commitment_id"], 1, Decimal(5), Decimal(500)
    )
    with pytest.raises(EosMaterialConsumptionError, match="consumed quantity"):
        service.reconcile(
            _input(admitted, releases=(source,), consumed_quantity=Decimal(10))
        )
    with pytest.raises(EosMaterialConsumptionError, match="duplicate"):
        service.reconcile(
            _input(admitted, releases=(source, source), consumed_quantity=Decimal(10))
        )
    with pytest.raises(EosMaterialConsumptionError, match="Project differs"):
        service.reconcile(
            _input(
                admitted,
                project_id=commitment_fixture.PROJECT_B,
                project_code=commitment_fixture.PROJECT_CODE_B,
                work_code=None,
                releases=(
                    MaterialReleaseInput(
                        admitted["commitment_id"], 1, Decimal(10), Decimal(1000)
                    ),
                ),
            )
        )


def test_consumption_rejects_currency_source_state_and_missing_attribution() -> None:
    _engine, sessions, service, admitted, _journal_id, _period_id = _runtime()
    with sessions.begin() as session:
        session.execute(
            update(EOS_COST_SOURCE_POOL_TABLE)
            .where(EOS_COST_SOURCE_POOL_TABLE.c.pool_id == POOL_A)
            .values(functional_currency="USD")
        )
    with pytest.raises(EosMaterialConsumptionError, match="currencies differ"):
        service.reconcile(_input(admitted))

    with sessions.begin() as session:
        session.execute(
            update(EOS_COST_SOURCE_POOL_TABLE)
            .where(EOS_COST_SOURCE_POOL_TABLE.c.pool_id == POOL_A)
            .values(functional_currency="KRW")
        )
        session.execute(
            update(EOS_MATERIAL_COMMITMENT_TABLE)
            .where(
                EOS_MATERIAL_COMMITMENT_TABLE.c.commitment_id
                == admitted["commitment_id"]
            )
            .values(reconciliation_state="PENDING")
        )
    with pytest.raises(EosMaterialConsumptionError, match="VERIFIED commitment"):
        service.reconcile(_input(admitted))

    with sessions.begin() as session:
        session.execute(
            update(EOS_MATERIAL_COMMITMENT_TABLE)
            .where(
                EOS_MATERIAL_COMMITMENT_TABLE.c.commitment_id
                == admitted["commitment_id"]
            )
            .values(reconciliation_state="VERIFIED")
        )
    with pytest.raises(EosMaterialConsumptionError) as missing:
        service.reconcile(
            _input(
                admitted,
                releases=(
                    MaterialReleaseInput(
                        admitted["commitment_id"], 99, Decimal(10), Decimal(1000)
                    ),
                ),
            )
        )
    assert missing.value.error_code == "MATERIAL_COMMITMENT_SOURCE_NOT_FOUND"


def test_consumption_not_found_and_persistence_failures(monkeypatch) -> None:
    _engine, sessions, service, admitted, _journal_id, _period_id = _runtime()
    missing = replace(_input(admitted), cost_pool_id=POOL_B)
    with pytest.raises(EosMaterialConsumptionError) as not_found:
        service.reconcile(missing)
    assert not_found.value.error_code == "MATERIAL_COST_SOURCE_NOT_FOUND"
    assert service.get(
        tenant_id=posting.TENANT,
        company_id=posting.COMPANY_ID,
        consumption_id=POOL_A,
    ) is None

    repository = SqlAlchemyEosMaterialConsumptionRepository(sessions)
    monkeypatch.setattr(
        repository,
        "_race_replay",
        lambda *_args: (_ for _ in ()).throw(
            EosMaterialConsumptionError(
                "MATERIAL_CONSUMPTION_CONFLICT", "race", status_code=409
            )
        ),
    )
    monkeypatch.setattr(
        consumption_module,
        "_require_pool_available",
        lambda *_args: (_ for _ in ()).throw(IntegrityError("x", {}, None)),
    )
    with pytest.raises(EosMaterialConsumptionError, match="race"):
        repository.append(_input(admitted))

    class BrokenFactory:
        def begin(self):
            raise SQLAlchemyError("offline")

        def __call__(self):
            raise SQLAlchemyError("offline")

    broken = SqlAlchemyEosMaterialConsumptionRepository(BrokenFactory())
    with pytest.raises(EosMaterialConsumptionError) as unavailable:
        broken.append(_input(admitted))
    assert unavailable.value.status_code == 503

    with pytest.raises(EosMaterialConsumptionError):
        repository.get(
            tenant_id=posting.TENANT,
            company_id=posting.COMPANY_ID,
            consumption_id="not-a-uuid",
        )

    with pytest.raises(EosMaterialConsumptionError) as get_unavailable:
        broken.get(
            tenant_id=posting.TENANT,
            company_id=posting.COMPANY_ID,
            consumption_id=POOL_A,
        )
    assert get_unavailable.value.status_code == 503


def test_race_replay_paths_are_exact_or_fail_closed() -> None:
    _engine, sessions, _service, admitted, _journal_id, _period_id = _runtime()
    repository = SqlAlchemyEosMaterialConsumptionRepository(
        sessions, clock=lambda: posting.NOW + timedelta(minutes=8)
    )
    value = _input(admitted)
    created, _ = repository.append(value)
    replay, was_created = repository._race_replay(
        value, posting.NOW + timedelta(minutes=8), IntegrityError("x", {}, None)
    )
    assert not was_created
    assert replay["consumption_id"] == created["consumption_id"]

    with pytest.raises(EosMaterialConsumptionError) as missing:
        repository._race_replay(
            replace(
                value,
                consumption_ref="inventory-issue:race-missing",
                component_ref="material:STEEL-001:race-missing",
            ),
            posting.NOW + timedelta(minutes=8),
            IntegrityError("x", {}, None),
        )
    assert missing.value.error_code == "MATERIAL_CONSUMPTION_CONFLICT"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tenant_id", "bad tenant!"),
        ("company_id", "bad-uuid"),
        ("consumption_ref", "bad ref!"),
        ("consumption_revision", True),
        ("consumption_revision", 0),
        ("project_code", "BAD"),
        ("evidence_hash", "bad-hash"),
    ],
)
def test_consumption_rejects_malformed_identity_fields(field, value) -> None:
    _engine, _sessions, service, admitted, _journal_id, _period_id = _runtime()
    with pytest.raises(EosMaterialConsumptionError):
        service.reconcile(_input(admitted, **{field: value}))


def test_material_consumption_decimal_helpers_fail_closed() -> None:
    with pytest.raises(EosMaterialConsumptionError):
        consumption_module._positive_int("revision", object())
    with pytest.raises(EosMaterialConsumptionError):
        consumption_module._positive_decimal("quantity", object(), Decimal("0.0001"))
    with pytest.raises(EosMaterialConsumptionError):
        consumption_module._money(object())
    with pytest.raises(EosMaterialConsumptionError):
        consumption_module._money(Decimal("NaN"))


def test_consumption_rows_are_append_only_by_contract() -> None:
    _engine, sessions, service, admitted, _journal_id, _period_id = _runtime()
    created = service.reconcile(_input(admitted))
    with sessions() as session:
        assert session.scalar(
            select(func.count()).select_from(EOS_MATERIAL_CONSUMPTION_TABLE)
        ) == 1
        assert session.scalar(
            select(func.count()).select_from(EOS_MATERIAL_RELEASE_TABLE)
        ) == 1
        assert session.scalar(
            select(EOS_MATERIAL_RELEASE_TABLE.c.consumption_id)
        ) == created["consumption_id"]
