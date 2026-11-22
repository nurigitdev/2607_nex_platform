from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
import test_nex_eos_mybee_voucher_candidate as posting
from nex_eos import (
    EOS_ACCOUNT_TABLE,
    EOS_COMPANY_ACCOUNT_POLICY_TABLE,
    EOS_JOURNAL_HEADER_TABLE,
    EOS_PROJECT_COMPANY_BINDING_TABLE,
    EOS_PROJECT_TABLE,
    EosMaterialCommitmentError,
    EosMaterialCommitmentService,
    MaterialAttributionInput,
    MaterialCommitmentInput,
    ProjectInput,
    ProjectPnlRebuildRequest,
    SqlAlchemyEosMaterialCommitmentRepository,
    SqlAlchemyEosProjectPnlProjectionSource,
    SqlAlchemyEosProjectRepository,
    build_direct_allocation_projection,
)
from nex_eos import material_commitments as material_module
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

PROJECT_B = "76510000-0000-4000-8000-000000000002"
PROJECT_CODE_B = "VO00D260002"
HASH = "sha256:" + "a" * 64


def _runtime():
    return _runtime_for_engine(None)


def _runtime_for_engine(engine):
    engine, sessions, candidates, command, _authorization = posting._runtime(
        engine=engine, debit_category="ASSET"
    )
    projects = SqlAlchemyEosProjectRepository(sessions)
    projects.create_project(
        ProjectInput(
            posting.TENANT,
            PROJECT_B,
            PROJECT_CODE_B,
            "Material Target B",
            nvt_project_id=posting.NVT_ID,
            status="ACTIVE",
            start_date=date(2026, 1, 1),
            currency="KRW",
            project_request_code="VO00R260002",
            purpose_type="D",
            origin="APPROVED_APPLICATION",
            approval_evidence_ref="eos.project-approval:material-b",
            approval_evidence_hash=posting.PROOF_HASH,
            project_owner_subject_id="employee-owner-b",
            project_manager_subject_id="employee-manager-b",
        )
    )
    with sessions.begin() as session:
        for project_id in (posting.PROJECT_ID, PROJECT_B):
            session.execute(
                EOS_PROJECT_COMPANY_BINDING_TABLE.insert().values(
                    tenant_id=posting.TENANT,
                    binding_id=(
                        "76510000-0000-4000-8000-000000000011"
                        if project_id == posting.PROJECT_ID
                        else "76510000-0000-4000-8000-000000000012"
                    ),
                    project_id=project_id,
                    company_id=posting.COMPANY_ID,
                    valid_from=date(2026, 1, 1),
                    valid_until=None,
                    approved_proof_hash=posting.PROOF_HASH,
                    state="APPROVED",
                    version=1,
                    created_at=posting.NOW,
                    updated_at=posting.NOW,
                )
            )
    command.execute(posting._payload(), caller=posting.CALLER)
    posting_service, payload = posting._prepare_atomic_posting(
        sessions, candidates, debit_is_monetary=False
    )
    committed = posting_service.execute(posting.CANDIDATE_ID, payload)
    journal_id = committed["result"]["journal_id"]
    service = EosMaterialCommitmentService(
        SqlAlchemyEosMaterialCommitmentRepository(
            sessions, clock=lambda: posting.NOW + timedelta(minutes=5)
        )
    )
    return engine, sessions, service, journal_id


def _input(journal_id: str, **overrides) -> MaterialCommitmentInput:
    values = {
        "tenant_id": posting.TENANT,
        "company_id": posting.COMPANY_ID,
        "acquisition_ref": "inventory-receipt:2026-0001",
        "acquisition_revision": 1,
        "component_ref": "material:STEEL-001:lot:20261114",
        "journal_id": journal_id,
        "journal_line_no": 1,
        "material_ref": "material:STEEL-001",
        "lot_ref": "lot:STEEL-001:20261114",
        "quantity_unit": "KG",
        "acquired_quantity": Decimal("100.0000"),
        "acquisition_amount_functional": Decimal("10000.0000"),
        "evidence_ref": "wa.receipt:2026-0001",
        "evidence_hash": HASH,
        "approval_ref": "wc.approval:2026-0001",
        "approval_hash": posting.PROOF_HASH,
        "policy_hash": posting.POLICY_HASH,
        "acquired_at": posting.NOW + timedelta(minutes=4),
        "attributions": (
            MaterialAttributionInput(
                "PROJECT",
                Decimal(40),
                Decimal(4000),
                "DIRECT_PROJECT",
                "material-plan:project-a",
                HASH,
                posting.PROJECT_ID,
                posting.PROJECT_CODE,
                "FL0004011",
            ),
            MaterialAttributionInput(
                "PROJECT",
                Decimal(40),
                Decimal(4000),
                "APPROVED_RATIO",
                "material-plan:project-b",
                HASH,
                PROJECT_B,
                PROJECT_CODE_B,
            ),
            MaterialAttributionInput(
                "UNASSIGNED",
                Decimal(20),
                Decimal(2000),
                "UNASSIGNED",
                "inventory:unassigned",
                HASH,
            ),
        ),
    }
    values.update(overrides)
    return MaterialCommitmentInput(**values)


def test_material_commitment_conserves_project_and_unassigned_inventory() -> None:
    _engine, sessions, service, journal_id = _runtime()
    created = service.admit(_input(journal_id))
    assert created["disposition"] == "CREATED"
    assert created["assigned_amount_functional"] == "8000.0000"
    assert created["unassigned_amount_functional"] == "2000.0000"
    assert [line["attribution_kind"] for line in created["attributions"]] == [
        "PROJECT",
        "PROJECT",
        "UNASSIGNED",
    ]
    replay = service.admit(_input(journal_id))
    assert replay["disposition"] == "EXACT_REPLAY"
    assert service.get(
        tenant_id=posting.TENANT,
        company_id=posting.COMPANY_ID,
        commitment_id=created["commitment_id"],
    )["commitment_hash"] == created["commitment_hash"]

    with sessions() as session:
        period_id = session.execute(
            select(EOS_JOURNAL_HEADER_TABLE.c.period_id).where(
                EOS_JOURNAL_HEADER_TABLE.c.journal_id == journal_id
            )
        ).scalar_one()
    snapshot = SqlAlchemyEosProjectPnlProjectionSource(sessions).load(
        ProjectPnlRebuildRequest(
            posting.TENANT,
            posting.COMPANY_ID,
            posting.PROJECT_ID,
            posting.PROJECT_CODE,
            str(period_id),
            1,
            "KRW",
            posting.NOW + timedelta(minutes=10),
            posting.NOW + timedelta(minutes=10),
        )
    )
    draft, components = build_direct_allocation_projection(
        ProjectPnlRebuildRequest(
            posting.TENANT,
            posting.COMPANY_ID,
            posting.PROJECT_ID,
            posting.PROJECT_CODE,
            str(period_id),
            1,
            "KRW",
            posting.NOW + timedelta(minutes=10),
            posting.NOW + timedelta(minutes=10),
        ),
        snapshot,
    )
    assert [(item.classification, item.functional_amount) for item in components] == [
        ("MATERIAL_COMMITTED", Decimal("4000.0000"))
    ]
    assert draft.material_commitment_watermark is not None


def test_material_commitment_rejects_drift_overcommit_and_invalid_targets() -> None:
    _engine, _sessions, service, journal_id = _runtime()
    service.admit(_input(journal_id))
    with pytest.raises(EosMaterialCommitmentError) as conflict:
        service.admit(_input(journal_id, material_ref="material:COPPER-001"))
    assert conflict.value.error_code == "MATERIAL_COMMITMENT_CONFLICT"

    with pytest.raises(EosMaterialCommitmentError) as overcommit:
        service.admit(
            _input(
                journal_id,
                acquisition_ref="inventory-receipt:2026-0002",
                component_ref="material:STEEL-002",
                acquisition_amount_functional=Decimal(1),
                acquired_quantity=Decimal(1),
                attributions=(
                    MaterialAttributionInput(
                        "UNASSIGNED",
                        Decimal(1),
                        Decimal(1),
                        "UNASSIGNED",
                        "inventory:unassigned:2",
                        HASH,
                    ),
                ),
            )
        )
    assert overcommit.value.error_code == "MATERIAL_SOURCE_OVERCOMMITTED"

    bad_line = MaterialAttributionInput(
        "PROJECT",
        Decimal(100),
        Decimal(10000),
        "UNASSIGNED",
        "bad:basis",
        HASH,
        posting.PROJECT_ID,
        posting.PROJECT_CODE,
    )
    with pytest.raises(EosMaterialCommitmentError, match="approved allocation basis"):
        service.admit(
            _input(
                journal_id,
                acquisition_ref="inventory-receipt:2026-0003",
                component_ref="material:STEEL-003",
                attributions=(bad_line,),
            )
        )


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"attributions": ()}, "must not be empty"),
        ({"quantity_unit": "bad-unit"}, "quantity_unit"),
        ({"acquired_quantity": Decimal(0)}, "must be positive"),
        ({"reconciliation_state": "UNKNOWN"}, "unsupported"),
    ],
)
def test_material_commitment_rejects_invalid_header(override, message) -> None:
    _engine, _sessions, service, journal_id = _runtime()
    with pytest.raises(EosMaterialCommitmentError, match=message):
        service.admit(_input(journal_id, **override))


def test_material_commitment_read_not_found_and_source_not_found() -> None:
    _engine, _sessions, service, _journal_id = _runtime()
    assert service.get(
        tenant_id=posting.TENANT,
        company_id=posting.COMPANY_ID,
        commitment_id="76510000-0000-4000-8000-000000000099",
    ) is None
    with pytest.raises(EosMaterialCommitmentError) as exc:
        service.admit(
            _input(
                "76510000-0000-4000-8000-000000000098",
            )
        )
    assert exc.value.error_code == "MATERIAL_SOURCE_NOT_FOUND"


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("EXPENSE_ACCOUNT", "non-monetary ASSET"),
        ("MONETARY_POLICY", "non-monetary ASSET"),
        ("EXPIRED_POLICY", "effective approved"),
        ("NO_BINDING", "company binding"),
        ("INACTIVE_PROJECT", "not cost eligible"),
    ],
)
def test_material_commitment_rejects_ineligible_authoritative_source(
    mutation, expected
) -> None:
    _engine, sessions, service, journal_id = _runtime()
    with sessions.begin() as session:
        if mutation == "EXPENSE_ACCOUNT":
            session.execute(
                update(EOS_ACCOUNT_TABLE)
                .where(EOS_ACCOUNT_TABLE.c.account_id == posting.DEBIT_ID)
                .values(category="EXPENSE")
            )
        elif mutation == "MONETARY_POLICY":
            session.execute(
                update(EOS_COMPANY_ACCOUNT_POLICY_TABLE)
                .where(
                    EOS_COMPANY_ACCOUNT_POLICY_TABLE.c.account_id == posting.DEBIT_ID
                )
                .values(is_monetary=True)
            )
        elif mutation == "EXPIRED_POLICY":
            session.execute(
                update(EOS_COMPANY_ACCOUNT_POLICY_TABLE)
                .where(
                    EOS_COMPANY_ACCOUNT_POLICY_TABLE.c.account_id == posting.DEBIT_ID
                )
                .values(valid_until=date(2026, 1, 31))
            )
        elif mutation == "NO_BINDING":
            session.execute(
                update(EOS_PROJECT_COMPANY_BINDING_TABLE)
                .where(EOS_PROJECT_COMPANY_BINDING_TABLE.c.project_id == PROJECT_B)
                .values(valid_until=date(2026, 1, 31))
            )
        else:
            session.execute(
                update(EOS_PROJECT_TABLE)
                .where(EOS_PROJECT_TABLE.c.project_id == PROJECT_B)
                .values(status="INACTIVE")
            )
    with pytest.raises(EosMaterialCommitmentError, match=expected):
        service.admit(_input(journal_id))


def test_material_commitment_rejects_credit_asset_line() -> None:
    _engine, sessions, service, journal_id = _runtime()
    with sessions.begin() as session:
        session.execute(
            update(EOS_COMPANY_ACCOUNT_POLICY_TABLE)
            .where(EOS_COMPANY_ACCOUNT_POLICY_TABLE.c.account_id == posting.CREDIT_ID)
            .values(is_monetary=False)
        )
    with pytest.raises(EosMaterialCommitmentError, match="positive debit"):
        service.admit(_input(journal_id, journal_line_no=2))


def test_material_attribution_shape_and_conservation_rejections() -> None:
    _engine, _sessions, service, journal_id = _runtime()
    project = _input(journal_id).attributions[0]
    unassigned = _input(journal_id).attributions[2]
    cases = (
        (
            (replace(project, attribution_kind="UNKNOWN"),),
            "kind or basis",
        ),
        (
            (replace(unassigned, project_id=posting.PROJECT_ID),),
            "must not carry Project",
        ),
        (
            (project, replace(project, basis_ref="duplicate:target")),
            "duplicate Project/work target",
        ),
        (
            (unassigned, replace(unassigned, basis_ref="unassigned:2")),
            "At most one UNASSIGNED",
        ),
        (
            (replace(unassigned, attributed_quantity=Decimal(99)),),
            "conserve acquired quantity",
        ),
        (
            (
                replace(
                    unassigned,
                    attributed_quantity=Decimal(100),
                    attributed_amount_functional=Decimal(9999),
                ),
            ),
            "conserve acquisition amount",
        ),
        (
            (
                replace(
                    project,
                    attributed_quantity=Decimal(100),
                    attributed_amount_functional=Decimal(10000),
                    project_code="VO00D260009",
                ),
            ),
            "differs from authority",
        ),
    )
    for index, (lines, message) in enumerate(cases, start=1):
        with pytest.raises(EosMaterialCommitmentError, match=message):
            service.admit(
                _input(
                    journal_id,
                    acquisition_ref=f"inventory-receipt:invalid:{index}",
                    component_ref=f"material:invalid:{index}",
                    attributions=lines,
                )
            )


@pytest.mark.parametrize(
    ("call", "message"),
    [
        (lambda: material_module._tenant("!"), "tenant_id"),
        (lambda: material_module._uuid("value", "bad"), "UUID"),
        (lambda: material_module._ref("value", "bad value"), "invalid"),
        (lambda: material_module._hash("value", "sha256:bad"), "sha256"),
        (lambda: material_module._project_code("BAD"), "project_code"),
        (lambda: material_module._optional_work_code("BAD"), "work_code"),
        (lambda: material_module._positive_int("value", True), "positive integer"),
        (
            lambda: material_module._positive_decimal(
                "value", "not-decimal", Decimal("0.0001")
            ),
            "decimal",
        ),
        (
            lambda: material_module._utc(
                "value", datetime(2026, 11, 14, 12, 0)  # noqa: DTZ001
            ),
            "timezone-aware",
        ),
    ],
)
def test_material_validation_helpers_fail_closed(call, message) -> None:
    with pytest.raises(EosMaterialCommitmentError, match=message):
        call()


def test_material_validation_helpers_normalize_optional_values() -> None:
    assert material_module._optional_ref("lot_ref", None) is None
    assert material_module._optional_ref("lot_ref", "lot:1") == "lot:1"
    assert material_module._optional_work_code(None) is None
    assert material_module._utc("value", posting.NOW).tzinfo == UTC


def test_material_commitment_concurrent_replay_and_persistence_errors() -> None:
    engine, _sessions, service, journal_id = _runtime()
    created = service.admit(_input(journal_id))
    repository = service._repository
    replay, inserted = repository._race_replay(
        material_module._validate_input(_input(journal_id)),
        posting.NOW + timedelta(minutes=5),
        IntegrityError("insert", {}, RuntimeError("duplicate")),
    )
    assert inserted is False
    assert replay["disposition"] == "EXACT_REPLAY"
    assert replay["commitment_id"] == created["commitment_id"]

    with pytest.raises(EosMaterialCommitmentError, match="UUID"):
        service.get(
            tenant_id=posting.TENANT,
            company_id=posting.COMPANY_ID,
            commitment_id="bad",
        )
    engine.dispose()
    with pytest.raises(EosMaterialCommitmentError) as unavailable:
        service.get(
            tenant_id=posting.TENANT,
            company_id=posting.COMPANY_ID,
            commitment_id=created["commitment_id"],
        )
    assert unavailable.value.error_code == "MATERIAL_COMMITMENT_UNAVAILABLE"
    assert unavailable.value.retryable is True
