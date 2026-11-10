from __future__ import annotations

import json
import os
import uuid
from dataclasses import replace
from datetime import date

import psycopg
import pytest
from fastapi.testclient import TestClient
from nex_eos import (
    EOS_ACCOUNT_CATALOG_RELEASE_TABLE,
    EOS_ACCOUNT_TABLE,
    EOS_COA_ACCOUNT_BINDING_TABLE,
    EOS_COA_CODE_IDENTITY_TABLE,
    EOS_COA_COMPANY_ADOPTION_TABLE,
    EOS_COA_DEFINITION_RELEASE_TABLE,
    EOS_COA_ENTRY_TABLE,
    EOS_COMPANY_ACCOUNT_POLICY_TABLE,
    EOS_METADATA,
    EOS_OUTBOX_TABLE,
    AccountCatalogReleaseInput,
    AccountInput,
    CoaDefinitionReleaseInput,
    CoaEntryInput,
    CompanyAccountPolicyInput,
    LegalEntityInput,
    PostingRuleReleaseInput,
    SqlAlchemyEosAccountCatalogRepository,
    SqlAlchemyEosAccountRepository,
    SqlAlchemyEosLegalEntityRepository,
    SqlAlchemyEosUnifiedCoaRepository,
    build_eos_database_runtime,
    coa_operations,
    create_eos_app,
)
from nex_eos.authorization import AuthorizationSubjectDenied
from nex_eos.business_transactions import SqlAlchemyEosBusinessTransactionCoordinator
from nex_eos.coa_operations import (
    EosCoaOperationError,
    EosCoaOperationsService,
    PinnedCoaPublicationAdmission,
    SqlAlchemyEosCoaOperationsRepository,
)
from nex_runtime import issue_mock_service_token, psycopg_database_url
from psycopg import sql
from run_migrations import run_service_migrations
from sqlalchemy import create_engine, func, make_url, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
POSTGRES_SMOKE = os.getenv("NEX_EOS_MYBEE_COA_03_POSTGRES_SMOKE") == "1"
POSTGRES_EXTENSION_SMOKE = (
    os.getenv("NEX_EOS_MYBEE_COA_04_POSTGRES_SMOKE") == "1"
)

ACTOR_TENANT = "product-tenant"
TENANT_ID = "tenant-a"
SUBJECT_ID = "product-accounting-owner"
COMPANY_ID = "d1000000-0000-4000-8000-000000000001"
RELEASE_ID = "d2000000-0000-4000-8000-000000000001"
ROOT_ID = "d3000000-0000-4000-8000-000000000001"
GROUP_ID = "d3000000-0000-4000-8000-000000000002"
FAMILY_ID = "d3000000-0000-4000-8000-000000000003"
LEAF_ID = "d3000000-0000-4000-8000-000000000004"
CATALOG_ID = "d4000000-0000-4000-8000-000000000001"
RULE_ID = "d5000000-0000-4000-8000-000000000001"
ACCOUNT_ID = "d6000000-0000-4000-8000-000000000001"
POLICY_ID = "d7000000-0000-4000-8000-000000000001"
ADOPTION_ID = "d8000000-0000-4000-8000-000000000001"
BINDING_ID = "d9000000-0000-4000-8000-000000000001"
EXTENSION_RELEASE_ID = "da100000-0000-4000-8000-000000000001"
EXTENSION_ENTRY_ID = "da200000-0000-4000-8000-000000000001"
OTHER_RELEASE_ID = "da300000-0000-4000-8000-000000000001"
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64
START = date(2026, 1, 1)


class AuthorizationSource:
    def __init__(self) -> None:
        self.scopes = {"finance:catalog:publish", "finance:account:manage"}
        self.denied = False
        self.unavailable = False

    def effective_authorization(self, *, tenant_id: str, subject_id: str):
        if self.unavailable:
            raise RuntimeError("private OA failure")
        if self.denied:
            raise AuthorizationSubjectDenied("inactive")
        return {
            "active": True,
            "tenant_id": tenant_id,
            "subject_id": subject_id,
            "scopes": sorted(self.scopes),
            "revision_hash": "d" * 64,
        }


@pytest.fixture
def runtime():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    EOS_METADATA.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    auth = AuthorizationSource()
    service = EosCoaOperationsService(
        repository=SqlAlchemyEosCoaOperationsRepository(),
        coordinator=SqlAlchemyEosBusinessTransactionCoordinator(factory),
        authorization_source=auth,
        publication_admission=_publication_admission(),
    )
    yield engine, factory, auth, service
    engine.dispose()


def _publication_admission() -> PinnedCoaPublicationAdmission:
    return PinnedCoaPublicationAdmission(
        [
            {
                "source_reference": "approved-standard-chart.v1.json",
                "source_hash": HASH_A,
                "approved_proof_ref": HASH_B,
                "content_hash": HASH_C,
            }
        ]
    )


def _release() -> CoaDefinitionReleaseInput:
    return CoaDefinitionReleaseInput(
        definition_release_id=RELEASE_ID,
        scope_type="GLOBAL",
        chart_profile="MYBEE-KIFRS",
        release_version="2026.01",
        effective_from=START,
        source_reference="approved-standard-chart.v1.json",
        source_hash=HASH_A,
        approved_proof_ref=HASH_B,
        content_hash=HASH_C,
        created_by=SUBJECT_ID,
    )


def _entries() -> list[CoaEntryInput]:
    common = {
        "category": "ASSET",
        "normal_balance": "DR",
        "is_contra": False,
        "is_monetary_default": True,
        "source_lineage": "approved-standard-chart.v1",
        "source_row_hash": HASH_A,
    }
    return [
        CoaEntryInput(
            ROOT_ID,
            "10000000",
            "MB-COA-ASSET",
            "Assets",
            1,
            account_type="ACCOUNT_GROUP",
            is_postable=False,
            **common,
        ),
        CoaEntryInput(
            GROUP_ID,
            "10100000",
            "MB-COA-CURRENT-ASSET",
            "Current assets",
            2,
            account_type="ACCOUNT_GROUP",
            is_postable=False,
            parent_entry_id=ROOT_ID,
            **common,
        ),
        CoaEntryInput(
            FAMILY_ID,
            "10101000",
            "MB-COA-CASH-FAMILY",
            "Cash family",
            3,
            account_type="ACCOUNT_GROUP",
            is_postable=False,
            parent_entry_id=GROUP_ID,
            **common,
        ),
        CoaEntryInput(
            LEAF_ID,
            "10101001",
            "MB-COA-CASH",
            "Cash",
            4,
            account_type="CASH",
            is_postable=True,
            parent_entry_id=FAMILY_ID,
            **common,
        ),
    ]


def _publish_payload() -> dict[str, object]:
    return {
        "business_operation_id": "da000000-0000-4000-8000-000000000001",
        "idempotency_key": "coa-publish-2026-01",
        "definition_release_id": RELEASE_ID,
        "source_reference": "approved-standard-chart.v1.json",
        "source_hash": HASH_A,
        "approved_proof_ref": HASH_B,
        "content_hash": HASH_C,
    }


def _extension_publish_payload() -> dict[str, object]:
    return {
        "business_operation_id": "da000000-0000-4000-8000-000000000003",
        "idempotency_key": "coa-extension-tenant-a-2026-01",
        "definition_release_id": EXTENSION_RELEASE_ID,
        "source_reference": "tenant-extension.v1.json",
        "source_hash": HASH_A,
        "approved_proof_ref": HASH_B,
        "content_hash": HASH_C,
    }


def _adopt_payload() -> dict[str, object]:
    return {
        "business_operation_id": "da000000-0000-4000-8000-000000000002",
        "idempotency_key": "coa-adopt-tenant-a-2026-01",
        "adoption_id": ADOPTION_ID,
        "company_id": COMPANY_ID,
        "global_release_id": RELEASE_ID,
        "effective_from": "2026-01-01",
        "approved_proof_ref": HASH_B,
        "bindings": [
            {
                "binding_id": BINDING_ID,
                "entry_id": LEAF_ID,
                "account_id": ACCOUNT_ID,
                "approved_proof_ref": HASH_B,
            }
        ],
    }


def _seed_draft(factory) -> None:
    SqlAlchemyEosUnifiedCoaRepository(factory).create_draft_release(
        release=_release(), entries=_entries()
    )


def _publish(service: EosCoaOperationsService) -> dict[str, object]:
    return service.publish_approved(
        actor_tenant_id=ACTOR_TENANT,
        requester_subject_id=SUBJECT_ID,
        payload=_publish_payload(),
    )


def _seed_company_account_policy(factory) -> None:
    SqlAlchemyEosLegalEntityRepository(factory).create_legal_entity(
        LegalEntityInput(
            TENANT_ID,
            COMPANY_ID,
            "NURI-KR",
            "NURI Korea",
            "KRW",
            "KRW",
            "Asia/Seoul",
            START,
        )
    )
    catalog = SqlAlchemyEosAccountCatalogRepository(factory)
    catalog.create_catalog_release(
        AccountCatalogReleaseInput(
            TENANT_ID,
            CATALOG_ID,
            "approved-standard-chart.v1.json",
            "2026.01",
            HASH_A,
            START,
            SUBJECT_ID,
            HASH_B,
        )
    )
    catalog.create_posting_rule_release(
        PostingRuleReleaseInput(
            TENANT_ID,
            RULE_ID,
            COMPANY_ID,
            CATALOG_ID,
            "MYBEE-DEFAULT",
            1,
            HASH_A,
            START,
            HASH_C,
            HASH_B,
        )
    )
    catalog.create_approved_account(
        account=AccountInput(
            TENANT_ID,
            ACCOUNT_ID,
            "CASH",
            "Cash",
            "ASSET",
            "CASH",
            START,
        ),
        policy=CompanyAccountPolicyInput(
            TENANT_ID,
            POLICY_ID,
            COMPANY_ID,
            ACCOUNT_ID,
            CATALOG_ID,
            RULE_ID,
            True,
            True,
            "ASSET.CASH",
            ["KRW"],
            START,
            HASH_B,
        ),
    )


def _seed_tenant_extension(
    factory, *, base_release_id: str = RELEASE_ID, publish: bool = True
) -> None:
    SqlAlchemyEosUnifiedCoaRepository(factory).create_draft_release(
        release=CoaDefinitionReleaseInput(
            definition_release_id=EXTENSION_RELEASE_ID,
            scope_type="TENANT",
            owner_tenant_id=TENANT_ID,
            base_global_release_id=base_release_id,
            chart_profile="MYBEE-KIFRS",
            release_version="2026.01-tenant-a",
            effective_from=START,
            source_reference="tenant-extension.v1.json",
            source_hash=HASH_A,
            approved_proof_ref=HASH_B,
            content_hash=HASH_C,
            created_by=SUBJECT_ID,
        ),
        entries=[
            CoaEntryInput(
                EXTENSION_ENTRY_ID,
                "10101800",
                "MB-COA-TENANT-CASH",
                "Tenant cash",
                4,
                category="ASSET",
                account_type="CASH",
                normal_balance="DR",
                is_contra=False,
                is_postable=True,
                is_monetary_default=True,
                source_lineage="tenant-extension.v1",
                source_row_hash=HASH_A,
                parent_entry_id=FAMILY_ID,
            )
        ],
    )
    if publish:
        with factory.begin() as session:
            session.execute(
                EOS_COA_DEFINITION_RELEASE_TABLE.update()
                .where(
                    EOS_COA_DEFINITION_RELEASE_TABLE.c.definition_release_id
                    == EXTENSION_RELEASE_ID
                )
                .values(status="PUBLISHED")
            )


def test_coa_03_publish_is_atomic_idempotent_and_records_stable_identity(runtime) -> None:
    engine, factory, _auth, service = runtime
    _seed_draft(factory)
    created = _publish(service)
    replayed = _publish(service)

    assert created["created"] is True
    assert created["result"]["status"] == "PUBLISHED"
    assert created["result"]["entry_count"] == 4
    assert replayed["created"] is False
    assert replayed["result"] == created["result"]
    with engine.connect() as connection:
        assert connection.execute(
            select(func.count()).select_from(EOS_COA_CODE_IDENTITY_TABLE)
        ).scalar_one() == 4
        assert connection.execute(
            select(func.count()).select_from(EOS_OUTBOX_TABLE)
        ).scalar_one() == 1


def test_coa_03_publish_rejects_source_drift_and_missing_scope(runtime) -> None:
    _engine, factory, auth, service = runtime
    _seed_draft(factory)
    payload = _publish_payload()
    payload["content_hash"] = "sha256:" + "e" * 64
    with pytest.raises(EosCoaOperationError) as source_error:
        service.publish_approved(
            actor_tenant_id=ACTOR_TENANT,
            requester_subject_id=SUBJECT_ID,
            payload=payload,
        )
    assert source_error.value.error_code == "EOS_COA_SOURCE_NOT_APPROVED"

    auth.scopes.remove("finance:catalog:publish")
    with pytest.raises(EosCoaOperationError) as scope_error:
        _publish(service)
    assert scope_error.value.status_code == 403


def test_coa_03_publish_fails_closed_on_oa_and_admission_configuration(runtime) -> None:
    _engine, factory, auth, service = runtime
    _seed_draft(factory)
    auth.unavailable = True
    with pytest.raises(EosCoaOperationError) as unavailable:
        _publish(service)
    assert unavailable.value.error_code == "EOS_COA_AUTHORITY_UNAVAILABLE"
    with pytest.raises(EosCoaOperationError):
        PinnedCoaPublicationAdmission.from_json("not-json")
    with pytest.raises(EosCoaOperationError):
        PinnedCoaPublicationAdmission.from_json(json.dumps({"bad": True}))
    parsed = PinnedCoaPublicationAdmission.from_json(
        json.dumps(
            [
                {
                    "source_reference": "approved-standard-chart.v1.json",
                    "source_hash": HASH_A,
                    "approved_proof_ref": HASH_B,
                    "content_hash": HASH_C,
                }
            ]
        )
    )
    assert isinstance(parsed, PinnedCoaPublicationAdmission)
    with pytest.raises(EosCoaOperationError):
        PinnedCoaPublicationAdmission(["not-an-object"])  # type: ignore[list-item]


@pytest.mark.parametrize(
    "evidence",
    [
        None,
        {"active": False},
        {
            "active": True,
            "tenant_id": "wrong",
            "subject_id": SUBJECT_ID,
            "scopes": ["finance:catalog:publish"],
            "revision_hash": "d" * 64,
        },
        {
            "active": True,
            "tenant_id": ACTOR_TENANT,
            "subject_id": SUBJECT_ID,
            "scopes": "finance:catalog:publish",
            "revision_hash": "d" * 64,
        },
        {
            "active": True,
            "tenant_id": ACTOR_TENANT,
            "subject_id": SUBJECT_ID,
            "scopes": [1],
            "revision_hash": "d" * 64,
        },
        {
            "active": True,
            "tenant_id": ACTOR_TENANT,
            "subject_id": SUBJECT_ID,
            "scopes": ["finance:catalog:publish"],
            "revision_hash": "bad",
        },
    ],
)
def test_coa_03_authorization_evidence_is_fail_closed(evidence) -> None:
    with pytest.raises(EosCoaOperationError):
        coa_operations._admit_authorization(
            evidence,
            tenant_id=ACTOR_TENANT,
            subject_id=SUBJECT_ID,
            required_scope="finance:catalog:publish",
        )


@pytest.mark.parametrize(
    ("mutate", "detail"),
    [
        (lambda value: value.update(bindings="bad"), "non-empty array"),
        (lambda value: value.update(bindings=[]), "non-empty array"),
        (lambda value: value.update(bindings=["bad"]), "must be an object"),
        (lambda value: value.update(adoption_id="bad"), "must be a UUID"),
        (lambda value: value.update(effective_from="bad"), "ISO date"),
        (
            lambda value: value.update(effective_until="2025-12-31"),
            "must follow",
        ),
        (lambda value: value.update(approved_proof_ref="bad"), "SHA-256"),
    ],
)
def test_coa_03_adoption_command_validation(runtime, mutate, detail) -> None:
    _engine, _factory, _auth, service = runtime
    payload = _adopt_payload()
    mutate(payload)
    with pytest.raises(EosCoaOperationError, match=detail):
        service.adopt_approved(
            tenant_id=TENANT_ID,
            requester_subject_id=SUBJECT_ID,
            payload=payload,
        )


def test_coa_03_duplicate_binding_and_missing_transaction_are_rejected(runtime) -> None:
    _engine, _factory, _auth, service = runtime
    payload = _adopt_payload()
    payload["bindings"] = [payload["bindings"][0], payload["bindings"][0]]
    with pytest.raises(EosCoaOperationError, match="duplicate identities"):
        service.adopt_approved(
            tenant_id=TENANT_ID,
            requester_subject_id=SUBJECT_ID,
            payload=payload,
        )
    with pytest.raises(EosCoaOperationError, match="durable EOS transaction"):
        SqlAlchemyEosCoaOperationsRepository.publish_release(
            None,
            coa_operations._publication_command(
                _publish_payload(), published_by=SUBJECT_ID
            ),
        )


def test_coa_03_publish_repository_state_rejections(runtime) -> None:
    engine, factory, _auth, _service = runtime
    command = coa_operations._publication_command(
        _publish_payload(), published_by=SUBJECT_ID
    )
    with factory.begin() as session, pytest.raises(
        EosCoaOperationError, match="not found"
    ):
        SqlAlchemyEosCoaOperationsRepository.publish_release(session, command)

    _seed_draft(factory)
    with engine.begin() as connection:
        connection.execute(
            coa_operations.EOS_COA_ENTRY_TABLE.delete().where(
                coa_operations.EOS_COA_ENTRY_TABLE.c.definition_release_id
                == RELEASE_ID
            )
        )
    with factory.begin() as session, pytest.raises(
        EosCoaOperationError, match="has no entries"
    ):
        SqlAlchemyEosCoaOperationsRepository.publish_release(session, command)


def test_coa_03_publish_repository_scope_hash_and_state_rejections(runtime) -> None:
    engine, factory, _auth, _service = runtime
    _seed_draft(factory)
    command = coa_operations._publication_command(
        _publish_payload(), published_by=SUBJECT_ID
    )
    drifted = coa_operations.CoaPublicationCommand(
        **{**command.__dict__, "content_hash": "sha256:" + "e" * 64}
    )
    with factory.begin() as session, pytest.raises(
        EosCoaOperationError
    ) as mismatch:
        SqlAlchemyEosCoaOperationsRepository.publish_release(session, drifted)
    assert mismatch.value.error_code == "EOS_COA_CATALOG_HASH_MISMATCH"

    with engine.begin() as connection:
        connection.execute(
            coa_operations.EOS_COA_DEFINITION_RELEASE_TABLE.update()
            .where(
                coa_operations.EOS_COA_DEFINITION_RELEASE_TABLE.c.definition_release_id
                == RELEASE_ID
            )
            .values(scope_type="TENANT", owner_tenant_id=TENANT_ID)
        )
    with factory.begin() as session, pytest.raises(
        EosCoaOperationError, match="GLOBAL release"
    ):
        SqlAlchemyEosCoaOperationsRepository.publish_release(session, command)

    with engine.begin() as connection:
        connection.execute(
            coa_operations.EOS_COA_DEFINITION_RELEASE_TABLE.update()
            .where(
                coa_operations.EOS_COA_DEFINITION_RELEASE_TABLE.c.definition_release_id
                == RELEASE_ID
            )
            .values(scope_type="GLOBAL", owner_tenant_id=None, status="SUPERSEDED")
        )
    with factory.begin() as session, pytest.raises(
        EosCoaOperationError, match="current state"
    ):
        SqlAlchemyEosCoaOperationsRepository.publish_release(session, command)


def test_coa_03_direct_published_release_replay(runtime) -> None:
    _engine, factory, _auth, service = runtime
    _seed_draft(factory)
    _publish(service)
    command = coa_operations._publication_command(
        _publish_payload(), published_by=SUBJECT_ID
    )
    with factory.begin() as session:
        result = SqlAlchemyEosCoaOperationsRepository.publish_release(session, command)
    assert result["replayed"] is True


def test_coa_03_stable_code_identity_replay_and_reassignment_guard(runtime) -> None:
    _engine, factory, _auth, service = runtime
    _seed_draft(factory)
    _publish(service)
    with factory.begin() as session:
        release = session.execute(
            select(EOS_COA_DEFINITION_RELEASE_TABLE).where(
                EOS_COA_DEFINITION_RELEASE_TABLE.c.definition_release_id == RELEASE_ID
            )
        ).mappings().one()
        entry = session.execute(
            select(EOS_COA_ENTRY_TABLE).where(
                EOS_COA_ENTRY_TABLE.c.entry_id == LEAF_ID
            )
        ).mappings().one()
        coa_operations._admit_code_identity(session, release=release, entry=entry)
        with pytest.raises(EosCoaOperationError) as conflict:
            coa_operations._admit_code_identity(
                session,
                release=release,
                entry={**entry, "semantic_key": "MB-COA-CASH-REASSIGNED"},
            )
    assert conflict.value.error_code == "EOS_COA_CODE_SEMANTIC_CONFLICT"


def test_coa_03_published_release_scope_and_presence_are_fail_closed(runtime) -> None:
    _engine, factory, _auth, _service = runtime
    with factory.begin() as session, pytest.raises(
        EosCoaOperationError, match="not found"
    ):
        coa_operations._published_release(
            session,
            OTHER_RELEASE_ID,
            effective_on=START,
            scope_type="GLOBAL",
            owner_tenant_id=None,
        )
    _seed_draft(factory)
    with factory.begin() as session, pytest.raises(
        EosCoaOperationError, match="not published"
    ):
        coa_operations._published_release(
            session,
            RELEASE_ID,
            effective_on=START,
            scope_type="GLOBAL",
            owner_tenant_id=None,
        )


def test_coa_03_company_adoption_requires_effective_policy_and_replays(runtime) -> None:
    engine, factory, _auth, service = runtime
    _seed_draft(factory)
    _publish(service)
    _seed_company_account_policy(factory)

    created = service.adopt_approved(
        tenant_id=TENANT_ID,
        requester_subject_id=SUBJECT_ID,
        payload=_adopt_payload(),
    )
    replayed = service.adopt_approved(
        tenant_id=TENANT_ID,
        requester_subject_id=SUBJECT_ID,
        payload=_adopt_payload(),
    )
    assert created["created"] is True
    assert created["result"]["binding_count"] == 1
    assert replayed["created"] is False
    with engine.connect() as connection:
        assert connection.execute(
            select(func.count()).select_from(EOS_COA_COMPANY_ADOPTION_TABLE)
        ).scalar_one() == 1
        assert connection.execute(
            select(func.count()).select_from(EOS_COA_ACCOUNT_BINDING_TABLE)
        ).scalar_one() == 1
        assert connection.execute(
            select(func.count()).select_from(EOS_ACCOUNT_CATALOG_RELEASE_TABLE)
        ).scalar_one() == 1


def test_coa_03_adoption_without_effective_account_policy_rolls_back(runtime) -> None:
    engine, factory, _auth, service = runtime
    _seed_draft(factory)
    _publish(service)
    SqlAlchemyEosLegalEntityRepository(factory).create_legal_entity(
        LegalEntityInput(
            TENANT_ID,
            COMPANY_ID,
            "NURI-KR",
            "NURI Korea",
            "KRW",
            "KRW",
            "Asia/Seoul",
            START,
        )
    )
    with pytest.raises(EosCoaOperationError, match="Account was not found"):
        service.adopt_approved(
            tenant_id=TENANT_ID,
            requester_subject_id=SUBJECT_ID,
            payload=_adopt_payload(),
        )
    with engine.connect() as connection:
        assert connection.execute(
            select(func.count()).select_from(EOS_COA_COMPANY_ADOPTION_TABLE)
        ).scalar_one() == 0


def test_coa_03_adoption_requires_active_company(runtime) -> None:
    engine, factory, _auth, service = runtime
    _seed_draft(factory)
    _publish(service)
    with pytest.raises(EosCoaOperationError, match="LegalEntity was not found"):
        service.adopt_approved(
            tenant_id=TENANT_ID,
            requester_subject_id=SUBJECT_ID,
            payload=_adopt_payload(),
        )
    SqlAlchemyEosLegalEntityRepository(factory).create_legal_entity(
        LegalEntityInput(
            TENANT_ID,
            COMPANY_ID,
            "NURI-KR",
            "NURI Korea",
            "KRW",
            "KRW",
            "Asia/Seoul",
            START,
            status="INACTIVE",
        )
    )
    with pytest.raises(EosCoaOperationError, match="not active"):
        service.adopt_approved(
            tenant_id=TENANT_ID,
            requester_subject_id=SUBJECT_ID,
            payload=_adopt_payload(),
        )
    with engine.connect() as connection:
        assert connection.execute(
            select(func.count()).select_from(EOS_COA_COMPANY_ADOPTION_TABLE)
        ).scalar_one() == 0


def test_coa_03_adoption_extension_lineage_is_enforced(runtime) -> None:
    _engine, factory, _auth, service = runtime
    _seed_draft(factory)
    _publish(service)
    _seed_company_account_policy(factory)
    _seed_tenant_extension(factory)
    payload = _adopt_payload()
    payload["extension_release_id"] = EXTENSION_RELEASE_ID
    result = service.adopt_approved(
        tenant_id=TENANT_ID,
        requester_subject_id=SUBJECT_ID,
        payload=payload,
    )
    assert result["result"]["extension_release_id"] == EXTENSION_RELEASE_ID


def test_coa_03_adoption_rejects_wrong_extension_lineage(runtime) -> None:
    _engine, factory, _auth, service = runtime
    _seed_draft(factory)
    _publish(service)
    _seed_company_account_policy(factory)
    _seed_tenant_extension(factory, base_release_id=OTHER_RELEASE_ID)
    payload = _adopt_payload()
    payload["extension_release_id"] = EXTENSION_RELEASE_ID
    with pytest.raises(EosCoaOperationError, match="does not derive"):
        service.adopt_approved(
            tenant_id=TENANT_ID,
            requester_subject_id=SUBJECT_ID,
            payload=payload,
        )


def test_coa_03_adoption_binding_scope_account_and_policy_are_enforced(runtime) -> None:
    engine, factory, _auth, service = runtime
    _seed_draft(factory)
    _publish(service)
    _seed_company_account_policy(factory)

    outside = _adopt_payload()
    outside["bindings"][0]["entry_id"] = str(uuid.uuid4())  # type: ignore[index]
    with pytest.raises(EosCoaOperationError, match="outside the adopted"):
        service.adopt_approved(
            tenant_id=TENANT_ID,
            requester_subject_id=SUBJECT_ID,
            payload=outside,
        )

    with engine.begin() as connection:
        connection.execute(
            EOS_ACCOUNT_TABLE.update()
            .where(
                EOS_ACCOUNT_TABLE.c.tenant_id == TENANT_ID,
                EOS_ACCOUNT_TABLE.c.account_id == ACCOUNT_ID,
            )
            .values(status="INACTIVE")
        )
    inactive = _adopt_payload()
    inactive["business_operation_id"] = str(uuid.uuid4())
    inactive["idempotency_key"] = "coa-adopt-inactive-account"
    with pytest.raises(EosCoaOperationError, match="not active"):
        service.adopt_approved(
            tenant_id=TENANT_ID,
            requester_subject_id=SUBJECT_ID,
            payload=inactive,
        )

    with engine.begin() as connection:
        connection.execute(
            EOS_ACCOUNT_TABLE.update()
            .where(
                EOS_ACCOUNT_TABLE.c.tenant_id == TENANT_ID,
                EOS_ACCOUNT_TABLE.c.account_id == ACCOUNT_ID,
            )
            .values(status="ACTIVE")
        )
        connection.execute(EOS_COMPANY_ACCOUNT_POLICY_TABLE.delete())
    no_policy = _adopt_payload()
    no_policy["business_operation_id"] = str(uuid.uuid4())
    no_policy["idempotency_key"] = "coa-adopt-no-policy"
    with pytest.raises(EosCoaOperationError, match="requires effective"):
        service.adopt_approved(
            tenant_id=TENANT_ID,
            requester_subject_id=SUBJECT_ID,
            payload=no_policy,
        )


def test_coa_03_repository_replay_requires_exact_semantics(runtime) -> None:
    engine, factory, _auth, service = runtime
    _seed_draft(factory)
    _publish(service)
    _seed_company_account_policy(factory)
    command = coa_operations._adoption_command(
        _adopt_payload(), tenant_id=TENANT_ID, created_by=SUBJECT_ID
    )
    with factory.begin() as session:
        SqlAlchemyEosCoaOperationsRepository.adopt_release(session, command)
    with factory.begin() as session:
        replayed = SqlAlchemyEosCoaOperationsRepository.adopt_release(session, command)
    assert replayed["replayed"] is True

    changed = replace(command, approved_proof_ref="sha256:" + "e" * 64)
    with factory.begin() as session, pytest.raises(
        EosCoaOperationError, match="different semantics"
    ):
        SqlAlchemyEosCoaOperationsRepository.adopt_release(session, changed)

    changed_binding = replace(
        command,
        bindings=(
            replace(command.bindings[0], approved_proof_ref="sha256:" + "e" * 64),
        ),
    )
    with factory.begin() as session, pytest.raises(
        EosCoaOperationError, match="different semantics"
    ):
        SqlAlchemyEosCoaOperationsRepository.adopt_release(session, changed_binding)

    with engine.begin() as connection:
        connection.execute(EOS_COA_ACCOUNT_BINDING_TABLE.delete())
    with factory.begin() as session, pytest.raises(
        EosCoaOperationError, match="different binding count"
    ):
        SqlAlchemyEosCoaOperationsRepository.adopt_release(session, command)


def test_coa_03_subject_denial_and_invalid_stable_inputs_are_rejected(runtime) -> None:
    _engine, _factory, auth, service = runtime
    auth.denied = True
    with pytest.raises(EosCoaOperationError) as denied:
        _publish(service)
    assert denied.value.status_code == 403
    auth.denied = False
    with pytest.raises(EosCoaOperationError, match="stable-reference"):
        service.publish_approved(
            actor_tenant_id="",
            requester_subject_id=SUBJECT_ID,
            payload=_publish_payload(),
        )
    payload = _publish_payload()
    payload["idempotency_key"] = ""
    with pytest.raises(EosCoaOperationError, match="1..256"):
        service.publish_approved(
            actor_tenant_id=ACTOR_TENANT,
            requester_subject_id=SUBJECT_ID,
            payload=payload,
        )


def test_coa_03_routes_require_service_trust_and_expose_committed_result(runtime) -> None:
    _engine, factory, _auth, service = runtime
    _seed_draft(factory)
    app = create_eos_app(
        environ={
            "NEX_PROFILE": "test",
            "NEX_VERSION": "test",
            "NEX_BUILD_SHA": "test",
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
        }
    )
    app.state.eos_coa_operations_service = service
    client = TestClient(app)
    path = f"/internal/v2/finance/coa/releases/{RELEASE_ID}/publish"
    payload = _publish_payload()
    payload.pop("definition_release_id")
    missing = client.post(
        path,
        json=payload,
        headers={
            "X-NeX-Tenant-Id": ACTOR_TENANT,
            "X-NeX-Subject-Id": SUBJECT_ID,
        },
    )
    assert missing.status_code == 401

    token = issue_mock_service_token(service_id="nex-ae-api", audience="nex-eos")
    response = client.post(
        path,
        json=payload,
        headers={
            "Authorization": f"Bearer {token.access_token}",
            "X-NeX-Tenant-Id": ACTOR_TENANT,
            "X-NeX-Subject-Id": SUBJECT_ID,
        },
    )
    assert response.status_code == 201
    assert response.json()["result"]["status"] == "PUBLISHED"

    _seed_company_account_policy(factory)
    adoption_headers = {
        "Authorization": f"Bearer {token.access_token}",
        "X-NeX-Tenant-Id": TENANT_ID,
        "X-NeX-Subject-Id": SUBJECT_ID,
    }
    adopted = client.post(
        "/internal/v2/finance/coa/adoptions",
        json=_adopt_payload(),
        headers=adoption_headers,
    )
    replayed = client.post(
        "/internal/v2/finance/coa/adoptions",
        json=_adopt_payload(),
        headers=adoption_headers,
    )
    assert adopted.status_code == 201
    assert replayed.status_code == 200


def test_coa_03_routes_fail_closed_when_unconfigured_or_denied(runtime) -> None:
    _engine, _factory, auth, service = runtime
    app = create_eos_app(
        environ={
            "NEX_PROFILE": "test",
            "NEX_VERSION": "test",
            "NEX_BUILD_SHA": "test",
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
        }
    )
    client = TestClient(app)
    token = issue_mock_service_token(service_id="nex-ae-api", audience="nex-eos")
    headers = {
        "Authorization": f"Bearer {token.access_token}",
        "X-NeX-Tenant-Id": ACTOR_TENANT,
        "X-NeX-Subject-Id": SUBJECT_ID,
    }
    path = f"/internal/v2/finance/coa/releases/{RELEASE_ID}/publish"
    payload = _publish_payload()
    payload.pop("definition_release_id")
    unavailable = client.post(path, json=payload, headers=headers)
    assert unavailable.status_code == 503
    assert unavailable.json()["error_code"] == "EOS_COA_SERVICE_UNAVAILABLE"

    app.state.eos_coa_operations_service = service
    auth.scopes.remove("finance:catalog:publish")
    denied = client.post(path, json=payload, headers=headers)
    assert denied.status_code == 403
    assert denied.json()["error_code"] == "EOS_COA_AUTHORIZATION_DENIED"

    auth.scopes.add("finance:catalog:publish")
    adoption_token = issue_mock_service_token(
        service_id="nex-ae-api", audience="nex-eos"
    )
    adoption_error = client.post(
        "/internal/v2/finance/coa/adoptions",
        json=_adopt_payload(),
        headers={
            "Authorization": f"Bearer {adoption_token.access_token}",
            "X-NeX-Tenant-Id": TENANT_ID,
            "X-NeX-Subject-Id": SUBJECT_ID,
        },
    )
    assert adoption_error.status_code == 404
    assert adoption_error.json()["error_code"] == "EOS_COA_NOT_FOUND"


def test_coa_04_tenant_extension_publish_and_legacy_bridge_preserve_v1(runtime) -> None:
    engine, factory, _auth, service = runtime
    _seed_draft(factory)
    _publish(service)
    _seed_tenant_extension(factory, publish=False)

    created = service.publish_extension_approved(
        tenant_id=TENANT_ID,
        requester_subject_id=SUBJECT_ID,
        payload=_extension_publish_payload(),
    )
    replayed = service.publish_extension_approved(
        tenant_id=TENANT_ID,
        requester_subject_id=SUBJECT_ID,
        payload=_extension_publish_payload(),
    )
    assert created["created"] is True
    assert created["result"]["status"] == "PUBLISHED"
    assert replayed["created"] is False

    _seed_company_account_policy(factory)
    adopted = service.adopt_approved(
        tenant_id=TENANT_ID,
        requester_subject_id=SUBJECT_ID,
        payload={**_adopt_payload(), "extension_release_id": EXTENSION_RELEASE_ID},
    )
    assert adopted["result"]["binding_count"] == 1
    with engine.connect() as connection:
        account = connection.execute(
            select(EOS_ACCOUNT_TABLE).where(
                EOS_ACCOUNT_TABLE.c.tenant_id == TENANT_ID,
                EOS_ACCOUNT_TABLE.c.account_id == ACCOUNT_ID,
            )
        ).mappings().one()
        assert account["account_code"] == "CASH"
        assert connection.execute(
            select(func.count()).select_from(EOS_COA_CODE_IDENTITY_TABLE)
        ).scalar_one() == 5


def test_coa_04_extension_rejects_cross_tenant_and_missing_scope(runtime) -> None:
    _engine, factory, auth, service = runtime
    _seed_draft(factory)
    _publish(service)
    _seed_tenant_extension(factory, publish=False)
    with pytest.raises(EosCoaOperationError) as cross_tenant:
        service.publish_extension_approved(
            tenant_id="tenant-b",
            requester_subject_id=SUBJECT_ID,
            payload=_extension_publish_payload(),
        )
    assert cross_tenant.value.status_code == 403

    auth.scopes.remove("finance:account:manage")
    with pytest.raises(EosCoaOperationError) as denied:
        service.publish_extension_approved(
            tenant_id=TENANT_ID,
            requester_subject_id=SUBJECT_ID,
            payload=_extension_publish_payload(),
        )
    assert denied.value.status_code == 403


@pytest.mark.parametrize("failure", ["legacy_code_collision", "wrong_parent"])
def test_coa_04_extension_namespace_and_parent_are_fail_closed(runtime, failure) -> None:
    engine, factory, _auth, service = runtime
    _seed_draft(factory)
    _publish(service)
    _seed_tenant_extension(factory, publish=False)
    if failure == "legacy_code_collision":
        SqlAlchemyEosAccountRepository(factory).create_account(
            AccountInput(
                TENANT_ID,
                str(uuid.uuid4()),
                "10101800",
                "Legacy collision",
                "ASSET",
                "CASH",
                START,
            )
        )
        detail = "collides"
    else:
        with engine.begin() as connection:
            connection.execute(
                EOS_COA_ENTRY_TABLE.update()
                .where(EOS_COA_ENTRY_TABLE.c.entry_id == EXTENSION_ENTRY_ID)
                .values(parent_entry_id=ROOT_ID)
            )
        detail = "GLOBAL family parent"
    with pytest.raises(EosCoaOperationError, match=detail):
        service.publish_extension_approved(
            tenant_id=TENANT_ID,
            requester_subject_id=SUBJECT_ID,
            payload=_extension_publish_payload(),
        )


@pytest.mark.parametrize(
    ("failure", "detail"),
    [
        ("missing", "not found"),
        ("profile", "chart profile"),
        ("empty", "has no entries"),
        ("published", "PUBLISHED"),
        ("superseded", "from its state"),
        ("namespace", "governed namespace"),
    ],
)
def test_coa_04_extension_repository_state_matrix(runtime, failure, detail) -> None:
    engine, factory, _auth, service = runtime
    command = coa_operations._publication_command(
        _extension_publish_payload(), published_by=SUBJECT_ID
    )
    if failure == "missing":
        with factory.begin() as session, pytest.raises(
            EosCoaOperationError, match=detail
        ):
            SqlAlchemyEosCoaOperationsRepository.publish_extension(
                session, tenant_id=TENANT_ID, command=command
            )
        return
    _seed_draft(factory)
    _publish(service)
    _seed_tenant_extension(factory, publish=False)
    if failure == "profile":
        with engine.begin() as connection:
            connection.execute(
                EOS_COA_DEFINITION_RELEASE_TABLE.update()
                .where(
                    EOS_COA_DEFINITION_RELEASE_TABLE.c.definition_release_id
                    == EXTENSION_RELEASE_ID
                )
                .values(chart_profile="OTHER-PROFILE")
            )
    elif failure == "empty":
        with engine.begin() as connection:
            connection.execute(
                EOS_COA_ENTRY_TABLE.delete().where(
                    EOS_COA_ENTRY_TABLE.c.definition_release_id
                    == EXTENSION_RELEASE_ID
                )
            )
    elif failure == "published":
        service.publish_extension_approved(
            tenant_id=TENANT_ID,
            requester_subject_id=SUBJECT_ID,
            payload=_extension_publish_payload(),
        )
    elif failure == "superseded":
        with engine.begin() as connection:
            connection.execute(
                EOS_COA_DEFINITION_RELEASE_TABLE.update()
                .where(
                    EOS_COA_DEFINITION_RELEASE_TABLE.c.definition_release_id
                    == EXTENSION_RELEASE_ID
                )
                .values(status="SUPERSEDED")
            )
    else:
        with engine.begin() as connection:
            connection.execute(
                EOS_COA_ENTRY_TABLE.update()
                .where(EOS_COA_ENTRY_TABLE.c.entry_id == EXTENSION_ENTRY_ID)
                .values(owner_tenant_id="tenant-b")
            )
    with factory.begin() as session:
        if failure == "published":
            result = SqlAlchemyEosCoaOperationsRepository.publish_extension(
                session, tenant_id=TENANT_ID, command=command
            )
            assert result["status"] == detail
        else:
            with pytest.raises(EosCoaOperationError, match=detail):
                SqlAlchemyEosCoaOperationsRepository.publish_extension(
                    session, tenant_id=TENANT_ID, command=command
                )


def test_coa_04_extension_route_is_service_protected(runtime) -> None:
    _engine, factory, _auth, service = runtime
    _seed_draft(factory)
    _publish(service)
    _seed_tenant_extension(factory, publish=False)
    app = create_eos_app(
        environ={
            "NEX_PROFILE": "test",
            "NEX_VERSION": "test",
            "NEX_BUILD_SHA": "test",
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
        }
    )
    app.state.eos_coa_operations_service = service
    client = TestClient(app)
    token = issue_mock_service_token(service_id="nex-ae-api", audience="nex-eos")
    payload = _extension_publish_payload()
    payload.pop("definition_release_id")
    path = f"/internal/v2/finance/coa/extensions/{EXTENSION_RELEASE_ID}/publish"
    missing = client.post(
        path,
        json=payload,
        headers={
            "X-NeX-Tenant-Id": TENANT_ID,
            "X-NeX-Subject-Id": SUBJECT_ID,
        },
    )
    created = client.post(
        path,
        json=payload,
        headers={
            "Authorization": f"Bearer {token.access_token}",
            "X-NeX-Tenant-Id": TENANT_ID,
            "X-NeX-Subject-Id": SUBJECT_ID,
        },
    )
    assert missing.status_code == 401
    assert created.status_code == 201
    assert created.json()["result"]["entry_count"] == 1


@pytest.mark.skipif(
    not DATABASE_URL or not POSTGRES_EXTENSION_SMOKE,
    reason="Protected COA-04 EOS PostgreSQL smoke is disabled",
)
def test_coa_04_actual_postgres_extension_publish_and_zero_residue() -> None:
    schema_name = f"mybee_coa04_{uuid.uuid4().hex}"
    psycopg_url = psycopg_database_url(DATABASE_URL)
    with (
        psycopg.connect(psycopg_url, autocommit=True) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SELECT current_database(), current_user")
        assert cursor.fetchone() == ("nex_eos_test", "nex_eos_user")
        cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
    scoped_url = make_url(DATABASE_URL).update_query_dict(
        {"options": f"-csearch_path={schema_name}"}
    ).render_as_string(hide_password=False)
    try:
        result = run_service_migrations(
            "nex-eos", database_url=scoped_url, profile="test"
        )
        assert "2518_eos_unified_coa" in result.applied
        db = build_eos_database_runtime(
            environ={"NEX_EOS_TEST_DATABASE_URL": scoped_url},
            database_env="NEX_EOS_TEST_DATABASE_URL",
        )
        service = EosCoaOperationsService(
            repository=SqlAlchemyEosCoaOperationsRepository(),
            coordinator=SqlAlchemyEosBusinessTransactionCoordinator(
                db.session_factory
            ),
            authorization_source=AuthorizationSource(),
            publication_admission=_publication_admission(),
        )
        _seed_draft(db.session_factory)
        _publish(service)
        _seed_tenant_extension(db.session_factory, publish=False)
        published = service.publish_extension_approved(
            tenant_id=TENANT_ID,
            requester_subject_id=SUBJECT_ID,
            payload=_extension_publish_payload(),
        )
        assert published["result"]["scope_type"] == "TENANT"
        db.dispose()
    finally:
        with (
            psycopg.connect(psycopg_url, autocommit=True) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema_name)
                )
            )


@pytest.mark.skipif(
    not DATABASE_URL or not POSTGRES_SMOKE,
    reason="Protected COA-03 EOS PostgreSQL smoke is disabled",
)
def test_coa_03_actual_postgres_publish_adopt_and_zero_residue() -> None:
    schema_name = f"mybee_coa03_{uuid.uuid4().hex}"
    psycopg_url = psycopg_database_url(DATABASE_URL)
    with (
        psycopg.connect(psycopg_url, autocommit=True) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SELECT current_database(), current_user")
        assert cursor.fetchone() == ("nex_eos_test", "nex_eos_user")
        cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
    scoped_url = make_url(DATABASE_URL).update_query_dict(
        {"options": f"-csearch_path={schema_name}"}
    )
    scoped_url = scoped_url.render_as_string(hide_password=False)
    try:
        result = run_service_migrations(
            "nex-eos", database_url=scoped_url, profile="test"
        )
        assert "2518_eos_unified_coa" in result.applied
        db = build_eos_database_runtime(
            environ={"NEX_EOS_TEST_DATABASE_URL": scoped_url},
            database_env="NEX_EOS_TEST_DATABASE_URL",
        )
        auth = AuthorizationSource()
        service = EosCoaOperationsService(
            repository=SqlAlchemyEosCoaOperationsRepository(),
            coordinator=SqlAlchemyEosBusinessTransactionCoordinator(
                db.session_factory
            ),
            authorization_source=auth,
            publication_admission=_publication_admission(),
        )
        _seed_draft(db.session_factory)
        assert _publish(service)["result"]["status"] == "PUBLISHED"
        _seed_company_account_policy(db.session_factory)
        adopted = service.adopt_approved(
            tenant_id=TENANT_ID,
            requester_subject_id=SUBJECT_ID,
            payload=_adopt_payload(),
        )
        assert adopted["result"]["binding_count"] == 1
        db.dispose()
    finally:
        with (
            psycopg.connect(psycopg_url, autocommit=True) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(schema_name)
                )
            )
