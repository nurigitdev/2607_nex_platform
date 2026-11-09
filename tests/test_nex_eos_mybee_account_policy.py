from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, date, datetime
from pathlib import Path

import psycopg
import pytest
import yaml
from fastapi.testclient import TestClient
from nex_eos import (
    EOS_ACCOUNT_CATALOG_RELEASE_TABLE,
    EOS_ACCOUNT_TABLE,
    EOS_COMPANY_ACCOUNT_POLICY_TABLE,
    EOS_LEGAL_ENTITY_TABLE,
    EOS_METADATA,
    EOS_POSTING_RULE_RELEASE_TABLE,
    AccountCatalogReleaseInput,
    AccountInput,
    CompanyAccountPolicyInput,
    EosAccountCatalogError,
    EosAccountCatalogService,
    LegalEntityInput,
    PostingRuleReleaseInput,
    SqlAlchemyEosAccountCatalogRepository,
    SqlAlchemyEosAccountRepository,
    SqlAlchemyEosLegalEntityRepository,
    build_eos_database_runtime,
    create_eos_app,
)
from nex_eos.authorization import AuthorizationSubjectDenied
from nex_runtime import issue_mock_service_token, psycopg_database_url
from psycopg import sql
from run_migrations import load_migrations, run_service_migrations
from sqlalchemy import create_engine, func, make_url, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = (
    ROOT / "domains/mybee/config/account_catalog/approved_seed_manifest.json"
)
OPENAPI_PATH = ROOT / "contracts/openapi/nex-eos.openapi.yaml"
TENANT_ID = "tenant-a"
OTHER_TENANT_ID = "tenant-b"
COMPANY_ID = "b1000000-0000-4000-8000-000000000001"
RELEASE_ID = "b2000000-0000-4000-8000-000000000001"
DRAFT_RELEASE_ID = "b2000000-0000-4000-8000-000000000002"
RULE_ID = "b3000000-0000-4000-8000-000000000001"
DRAFT_RULE_ID = "b3000000-0000-4000-8000-000000000002"
ACCOUNT_ID = "b4000000-0000-4000-8000-000000000001"
PARENT_ACCOUNT_ID = "b4000000-0000-4000-8000-000000000002"
CHILD_ACCOUNT_ID = "b4000000-0000-4000-8000-000000000003"
POLICY_ID = "b5000000-0000-4000-8000-000000000001"
PARENT_POLICY_ID = "b5000000-0000-4000-8000-000000000002"
CHILD_POLICY_ID = "b5000000-0000-4000-8000-000000000003"
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64
START = date(2026, 1, 1)
DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
POSTGRES_SMOKE = os.getenv("NEX_EOS_MYBEE_S1_02_POSTGRES_SMOKE") == "1"


class AuthorizationSource:
    def __init__(self) -> None:
        self.denied = False
        self.unavailable = False
        self.scopes = {"finance:account:read", "finance:account:manage"}

    def effective_authorization(self, *, tenant_id: str, subject_id: str):
        if self.unavailable:
            raise RuntimeError("private OA detail")
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
def repository():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    EOS_METADATA.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    legal_entities = SqlAlchemyEosLegalEntityRepository(factory)
    legal_entities.create_legal_entity(
        LegalEntityInput(
            tenant_id=TENANT_ID,
            company_id=COMPANY_ID,
            company_code="NURI-KR",
            name="NURI Korea",
            functional_currency="KRW",
            presentation_currency="KRW",
            business_timezone="Asia/Seoul",
            effective_from=START,
        )
    )
    return engine, factory, SqlAlchemyEosAccountCatalogRepository(factory)


def _release(
    *,
    release_id: str = RELEASE_ID,
    source_version: str = "2026.01",
    status: str = "PUBLISHED",
    tenant_id: str = TENANT_ID,
) -> AccountCatalogReleaseInput:
    return AccountCatalogReleaseInput(
        tenant_id=tenant_id,
        release_id=release_id,
        source_reference="urn:mybee:approved-chart-of-accounts",
        source_version=source_version,
        source_hash=HASH_A,
        effective_from=START,
        published_by="accounting-controller",
        approved_proof_ref=HASH_B,
        status=status,
    )


def _rule(
    *,
    posting_rule_id: str = RULE_ID,
    catalog_release_id: str = RELEASE_ID,
    status: str = "PUBLISHED",
    rule_version: int = 1,
) -> PostingRuleReleaseInput:
    return PostingRuleReleaseInput(
        tenant_id=TENANT_ID,
        posting_rule_id=posting_rule_id,
        company_id=COMPANY_ID,
        catalog_release_id=catalog_release_id,
        rule_code="KIFRS-BASE",
        rule_version=rule_version,
        rule_hash=HASH_B,
        effective_date=START,
        account_mapping_hash=HASH_C,
        approved_proof_ref=HASH_A,
        status=status,
    )


def _account(
    *,
    account_id: str = ACCOUNT_ID,
    account_code: str = "TRAVEL-EXPENSE",
    category: str = "EXPENSE",
    account_type: str = "OPERATING_EXPENSE",
) -> AccountInput:
    return AccountInput(
        tenant_id=TENANT_ID,
        account_id=account_id,
        account_code=account_code,
        name=account_code.replace("-", " ").title(),
        category=category,
        account_type=account_type,
        effective_from=START,
    )


def _policy(
    *,
    policy_id: str = POLICY_ID,
    account_id: str = ACCOUNT_ID,
    parent_account_id: str | None = None,
    is_postable_leaf: bool = True,
    allowed_currencies: tuple[str, ...] = ("KRW",),
    catalog_release_id: str = RELEASE_ID,
    posting_rule_id: str = RULE_ID,
    valid_from: date = START,
    valid_until: date | None = None,
    state: str = "APPROVED",
) -> CompanyAccountPolicyInput:
    return CompanyAccountPolicyInput(
        tenant_id=TENANT_ID,
        policy_id=policy_id,
        company_id=COMPANY_ID,
        account_id=account_id,
        catalog_release_id=catalog_release_id,
        posting_rule_id=posting_rule_id,
        parent_account_id=parent_account_id,
        is_postable_leaf=is_postable_leaf,
        is_monetary=False,
        statement_line_ref="PL-OPERATING-EXPENSE",
        allowed_currencies=allowed_currencies,
        valid_from=valid_from,
        valid_until=valid_until,
        approved_proof_ref=HASH_B,
        state=state,
    )


def _admit(repository: SqlAlchemyEosAccountCatalogRepository) -> None:
    repository.create_catalog_release(_release())
    repository.create_posting_rule_release(_rule())


def _api_payload() -> dict:
    return {
        "account": {
            "account_id": ACCOUNT_ID,
            "account_code": "TRAVEL-EXPENSE",
            "name": "Travel expense",
            "category": "EXPENSE",
            "account_type": "OPERATING_EXPENSE",
            "effective_from": "2026-01-01",
        },
        "policy": {
            "policy_id": POLICY_ID,
            "company_id": COMPANY_ID,
            "catalog_release_id": RELEASE_ID,
            "posting_rule_id": RULE_ID,
            "is_postable_leaf": True,
            "is_monetary": False,
            "statement_line_ref": "PL-OPERATING-EXPENSE",
            "allowed_currencies": ["KRW"],
            "valid_from": "2026-01-01",
            "approved_proof_ref": HASH_B,
        },
    }


def test_s1_02_manifest_fails_closed_without_inventing_kifrs_codes() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    assert manifest["admission_status"] == "SOURCE_PENDING_NOT_ADMITTED"
    assert manifest["runtime_seed_allowed"] is False
    assert manifest["accounts"] == []
    assert manifest["source_hash"] is None
    assert "must not invent" in manifest["blocking_reason"]


def test_s1_02_migration_freezes_catalog_policy_rule_and_shared_period_schema() -> None:
    migration = next(
        item
        for item in load_migrations("nex-eos")
        if item.version == "2517_eos_account_catalog_accounting_period"
    )
    compact = " ".join(migration.sql.lower().split())

    assert "create table if not exists eos_account_catalog_release" in compact
    assert "create table if not exists eos_company_account_policy" in compact
    assert "create table if not exists eos_posting_rule_release" in compact
    assert "foreign key (tenant_id, company_id)" in compact
    assert "foreign key (tenant_id, account_id)" in compact
    assert "eos_reject_company_account_overlap" in compact
    assert "create table if not exists eos_accounting_period" in compact
    assert "s1-03 owns runtime activation" in migration.sql.lower()


def test_s1_02_openapi_freezes_read_and_governed_create_contract() -> None:
    spec = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    catalog = spec["paths"]["/internal/v2/finance/account-catalog"]["get"]
    create = spec["paths"]["/internal/v2/finance/accounts/approved"]["post"]

    assert catalog["operationId"] == "FINANCE.ACCOUNT.CATALOG_GET"
    assert catalog["x-nex-business-scope"] == "finance:account:read"
    assert create["operationId"] == "FINANCE.ACCOUNT.CREATE_APPROVED"
    assert create["x-nex-business-scope"] == "finance:account:manage"
    assert create["x-nex-work-code"] == "FL0004011"
    assert create["x-nex-route-class"] == "WRITE"


def test_release_and_posting_rule_are_exact_replayable(repository) -> None:
    _engine, _factory, catalog = repository
    release = catalog.create_catalog_release(_release())
    replay = catalog.create_catalog_release(_release())
    rule = catalog.create_posting_rule_release(_rule())
    rule_replay = catalog.create_posting_rule_release(_rule())

    assert replay["release_id"] == release["release_id"]
    assert rule_replay["posting_rule_id"] == rule["posting_rule_id"]

    with pytest.raises(EosAccountCatalogError) as drift:
        catalog.create_catalog_release(
            AccountCatalogReleaseInput(**{**_release().__dict__, "source_hash": HASH_C})
        )
    assert drift.value.error_code == "EOS_ACCOUNT_CATALOG_CONFLICT"


def test_release_and_posting_rule_unique_semantics_fail_closed(repository) -> None:
    _engine, _factory, catalog = repository
    catalog.create_catalog_release(_release())
    with pytest.raises(EosAccountCatalogError) as source_conflict:
        catalog.create_catalog_release(
            _release(release_id=DRAFT_RELEASE_ID, status="DRAFT")
        )
    assert source_conflict.value.error_code == "EOS_ACCOUNT_CATALOG_RELEASE_CONFLICT"

    catalog.create_posting_rule_release(_rule())
    with pytest.raises(EosAccountCatalogError) as rule_conflict:
        catalog.create_posting_rule_release(
            _rule(posting_rule_id=DRAFT_RULE_ID, status="DRAFT")
        )
    assert rule_conflict.value.error_code == "EOS_ACCOUNT_CATALOG_CONFLICT"


def test_approved_account_preserves_v1_resolver_and_exposes_policy(repository) -> None:
    _engine, factory, catalog = repository
    _admit(catalog)
    created = catalog.create_approved_account(
        account=_account(), policy=_policy(allowed_currencies=("USD", "KRW", "KRW"))
    )
    replay = catalog.create_approved_account(
        account=_account(), policy=_policy(allowed_currencies=("KRW", "USD"))
    )

    assert created["policy"]["allowed_currencies"] == ["KRW", "USD"]
    assert replay["account"]["account_id"] == ACCOUNT_ID
    legacy = SqlAlchemyEosAccountRepository(factory).get_effective_account_by_code(
        tenant_id=TENANT_ID,
        account_code="TRAVEL-EXPENSE",
        effective_at=START,
    )
    assert legacy is not None and legacy["account_id"] == ACCOUNT_ID

    projection = catalog.get_effective_catalog(
        tenant_id=TENANT_ID,
        company_id=COMPANY_ID,
        effective_on=START,
    )
    assert projection is not None
    assert projection["catalog_release"]["source_hash"] == HASH_A
    assert projection["posting_rule"]["rule_hash"] == HASH_B
    assert projection["accounts"][0]["is_postable_leaf"] is True
    assert projection["accounts"][0]["is_monetary"] is False


def test_account_partial_replay_and_duplicate_code_fail_closed(repository) -> None:
    engine, _factory, catalog = repository
    _admit(catalog)
    catalog.create_approved_account(account=_account(), policy=_policy())
    with engine.begin() as connection:
        connection.execute(
            EOS_COMPANY_ACCOUNT_POLICY_TABLE.delete().where(
                EOS_COMPANY_ACCOUNT_POLICY_TABLE.c.policy_id == POLICY_ID
            )
        )
    with pytest.raises(EosAccountCatalogError) as partial:
        catalog.create_approved_account(account=_account(), policy=_policy())
    assert partial.value.error_code == "EOS_ACCOUNT_CATALOG_CONFLICT"

    with pytest.raises(EosAccountCatalogError) as duplicate:
        catalog.create_approved_account(
            account=_account(account_id=CHILD_ACCOUNT_ID),
            policy=_policy(policy_id=CHILD_POLICY_ID, account_id=CHILD_ACCOUNT_ID),
        )
    assert duplicate.value.error_code == "EOS_ACCOUNT_CATALOG_CONFLICT"


def test_draft_or_mismatched_release_and_rule_fail_closed(repository) -> None:
    _engine, _factory, catalog = repository
    catalog.create_catalog_release(_release(status="DRAFT"))
    with pytest.raises(EosAccountCatalogError) as draft_release:
        catalog.create_posting_rule_release(_rule())
    assert draft_release.value.error_code == "EOS_ACCOUNT_CATALOG_CONFLICT"

    catalog.create_catalog_release(
        _release(
            release_id=DRAFT_RELEASE_ID,
            source_version="2026.02",
            status="PUBLISHED",
        )
    )
    catalog.create_posting_rule_release(
        _rule(
            posting_rule_id=DRAFT_RULE_ID,
            catalog_release_id=DRAFT_RELEASE_ID,
            rule_version=2,
            status="DRAFT",
        )
    )
    with pytest.raises(EosAccountCatalogError) as draft_rule:
        catalog.create_approved_account(
            account=_account(),
            policy=_policy(
                catalog_release_id=DRAFT_RELEASE_ID,
                posting_rule_id=DRAFT_RULE_ID,
            ),
        )
    assert draft_rule.value.error_code == "EOS_ACCOUNT_CATALOG_CONFLICT"


def test_functional_currency_and_parent_leaf_guards(repository) -> None:
    _engine, _factory, catalog = repository
    _admit(catalog)
    with pytest.raises(EosAccountCatalogError) as currency:
        catalog.create_approved_account(
            account=_account(), policy=_policy(allowed_currencies=("USD",))
        )
    assert currency.value.error_code == "EOS_ACCOUNT_CATALOG_INVALID"

    catalog.create_approved_account(
        account=_account(
            account_id=PARENT_ACCOUNT_ID,
            account_code="OPERATING-EXPENSES",
        ),
        policy=_policy(
            policy_id=PARENT_POLICY_ID,
            account_id=PARENT_ACCOUNT_ID,
            is_postable_leaf=True,
        ),
    )
    with pytest.raises(EosAccountCatalogError) as leaf_parent:
        catalog.create_approved_account(
            account=_account(
                account_id=CHILD_ACCOUNT_ID,
                account_code="TRAVEL-CHILD",
            ),
            policy=_policy(
                policy_id=CHILD_POLICY_ID,
                account_id=CHILD_ACCOUNT_ID,
                parent_account_id=PARENT_ACCOUNT_ID,
            ),
        )
    assert leaf_parent.value.error_code == "EOS_ACCOUNT_CATALOG_CONFLICT"


def test_non_postable_parent_allows_approved_child(repository) -> None:
    _engine, _factory, catalog = repository
    _admit(catalog)
    catalog.create_approved_account(
        account=_account(
            account_id=PARENT_ACCOUNT_ID,
            account_code="OPERATING-EXPENSES",
        ),
        policy=_policy(
            policy_id=PARENT_POLICY_ID,
            account_id=PARENT_ACCOUNT_ID,
            is_postable_leaf=False,
        ),
    )
    child = catalog.create_approved_account(
        account=_account(account_id=CHILD_ACCOUNT_ID, account_code="TRAVEL-CHILD"),
        policy=_policy(
            policy_id=CHILD_POLICY_ID,
            account_id=CHILD_ACCOUNT_ID,
            parent_account_id=PARENT_ACCOUNT_ID,
        ),
    )
    assert child["policy"]["parent_account_id"] == PARENT_ACCOUNT_ID


def test_existing_account_policy_revision_allows_adjacent_not_overlapping_periods(
    repository,
) -> None:
    _engine, _factory, catalog = repository
    _admit(catalog)
    catalog.create_approved_account(
        account=_account(),
        policy=_policy(valid_until=date(2026, 7, 1)),
    )
    catalog.create_catalog_release(
        _release(
            release_id=DRAFT_RELEASE_ID,
            source_version="2026.02",
            status="PUBLISHED",
        )
    )
    catalog.create_posting_rule_release(
        _rule(
            posting_rule_id=DRAFT_RULE_ID,
            catalog_release_id=DRAFT_RELEASE_ID,
            rule_version=2,
        )
    )
    revised = catalog.create_company_account_policy(
        _policy(
            policy_id=CHILD_POLICY_ID,
            catalog_release_id=DRAFT_RELEASE_ID,
            posting_rule_id=DRAFT_RULE_ID,
            valid_from=date(2026, 7, 1),
        )
    )
    replay = catalog.create_company_account_policy(
        _policy(
            policy_id=CHILD_POLICY_ID,
            catalog_release_id=DRAFT_RELEASE_ID,
            posting_rule_id=DRAFT_RULE_ID,
            valid_from=date(2026, 7, 1),
        )
    )
    assert revised["catalog_release_id"] == DRAFT_RELEASE_ID
    assert replay["policy_id"] == CHILD_POLICY_ID

    with pytest.raises(EosAccountCatalogError) as overlap:
        catalog.create_company_account_policy(
            _policy(
                policy_id=PARENT_POLICY_ID,
                catalog_release_id=DRAFT_RELEASE_ID,
                posting_rule_id=DRAFT_RULE_ID,
                valid_from=date(2026, 6, 1),
            )
        )
    assert overlap.value.error_code == "EOS_ACCOUNT_CATALOG_CONFLICT"

    current = catalog.get_effective_catalog(
        tenant_id=TENANT_ID,
        company_id=COMPANY_ID,
        effective_on=date(2026, 7, 1),
    )
    assert current is not None
    assert current["catalog_release"]["release_id"] == DRAFT_RELEASE_ID


def test_existing_account_policy_revision_rejects_invalid_scope(repository) -> None:
    engine, _factory, catalog = repository
    _admit(catalog)
    catalog.create_approved_account(
        account=_account(),
        policy=_policy(valid_until=date(2026, 7, 1)),
    )
    catalog.create_catalog_release(
        _release(
            release_id=DRAFT_RELEASE_ID,
            source_version="2026.02",
            status="PUBLISHED",
        )
    )
    catalog.create_posting_rule_release(
        _rule(
            posting_rule_id=DRAFT_RULE_ID,
            catalog_release_id=DRAFT_RELEASE_ID,
            rule_version=2,
        )
    )

    with engine.begin() as connection:
        connection.execute(
            EOS_ACCOUNT_TABLE.update()
            .where(EOS_ACCOUNT_TABLE.c.account_id == ACCOUNT_ID)
            .values(status="INACTIVE")
        )
    with pytest.raises(EosAccountCatalogError) as inactive:
        catalog.create_company_account_policy(
            _policy(
                policy_id=CHILD_POLICY_ID,
                catalog_release_id=DRAFT_RELEASE_ID,
                posting_rule_id=DRAFT_RULE_ID,
                valid_from=date(2026, 7, 1),
            )
        )
    assert inactive.value.error_code == "EOS_ACCOUNT_CATALOG_CONFLICT"

    with engine.begin() as connection:
        connection.execute(
            EOS_ACCOUNT_TABLE.update()
            .where(EOS_ACCOUNT_TABLE.c.account_id == ACCOUNT_ID)
            .values(status="ACTIVE")
        )
    with pytest.raises(EosAccountCatalogError) as currency:
        catalog.create_company_account_policy(
            _policy(
                policy_id=CHILD_POLICY_ID,
                catalog_release_id=DRAFT_RELEASE_ID,
                posting_rule_id=DRAFT_RULE_ID,
                allowed_currencies=("USD",),
                valid_from=date(2026, 7, 1),
            )
        )
    assert currency.value.error_code == "EOS_ACCOUNT_CATALOG_INVALID"

    with pytest.raises(EosAccountCatalogError) as parent:
        catalog.create_company_account_policy(
            _policy(
                policy_id=CHILD_POLICY_ID,
                catalog_release_id=DRAFT_RELEASE_ID,
                posting_rule_id=DRAFT_RULE_ID,
                parent_account_id=ACCOUNT_ID,
                valid_from=date(2026, 7, 1),
            )
        )
    assert parent.value.error_code == "EOS_ACCOUNT_CATALOG_INVALID"


@pytest.mark.parametrize(
    ("account", "policy"),
    (
        (
            _account(),
            CompanyAccountPolicyInput(
                **{**_policy().__dict__, "tenant_id": OTHER_TENANT_ID}
            ),
        ),
        (
            _account(),
            CompanyAccountPolicyInput(
                **{**_policy().__dict__, "account_id": CHILD_ACCOUNT_ID}
            ),
        ),
        (AccountInput(**{**_account().__dict__, "status": "INACTIVE"}), _policy()),
        (
            AccountInput(**{**_account().__dict__, "effective_from": date(2026, 2, 1)}),
            _policy(),
        ),
    ),
)
def test_approved_account_identity_and_effective_guards(
    repository, account, policy
) -> None:
    _engine, _factory, catalog = repository
    _admit(catalog)
    with pytest.raises(EosAccountCatalogError) as invalid:
        catalog.create_approved_account(account=account, policy=policy)
    assert invalid.value.error_code == "EOS_ACCOUNT_CATALOG_INVALID"


def test_partial_identity_and_missing_policy_dependencies_fail_closed(
    repository,
) -> None:
    _engine, factory, catalog = repository
    _admit(catalog)
    SqlAlchemyEosAccountRepository(factory).create_account(_account())
    with pytest.raises(EosAccountCatalogError) as partial:
        catalog.create_approved_account(account=_account(), policy=_policy())
    assert partial.value.error_code == "EOS_ACCOUNT_CATALOG_CONFLICT"

    with pytest.raises(EosAccountCatalogError) as missing_account:
        catalog.create_company_account_policy(
            _policy(account_id=CHILD_ACCOUNT_ID, policy_id=CHILD_POLICY_ID)
        )
    assert missing_account.value.error_code == "EOS_ACCOUNT_NOT_FOUND"

    with pytest.raises(EosAccountCatalogError) as missing_rule:
        catalog.create_company_account_policy(_policy(posting_rule_id=DRAFT_RULE_ID))
    assert missing_rule.value.error_code == "EOS_POSTING_RULE_NOT_FOUND"


def test_posting_rule_requires_active_company_and_published_release(repository) -> None:
    engine, _factory, catalog = repository
    with pytest.raises(EosAccountCatalogError) as missing_release:
        catalog.create_posting_rule_release(_rule())
    assert missing_release.value.error_code == "EOS_ACCOUNT_CATALOG_RELEASE_NOT_FOUND"

    catalog.create_catalog_release(_release())
    with engine.begin() as connection:
        connection.execute(
            EOS_LEGAL_ENTITY_TABLE.update()
            .where(EOS_LEGAL_ENTITY_TABLE.c.company_id == COMPANY_ID)
            .values(status="INACTIVE")
        )
    with pytest.raises(EosAccountCatalogError) as inactive_company:
        catalog.create_posting_rule_release(_rule())
    assert inactive_company.value.error_code == "EOS_ACCOUNT_CATALOG_CONFLICT"


def test_posting_rule_rejects_missing_company_scope() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    EOS_METADATA.create_all(engine)
    catalog = SqlAlchemyEosAccountCatalogRepository(sessionmaker(bind=engine))
    catalog.create_catalog_release(_release())

    with pytest.raises(EosAccountCatalogError) as missing_company:
        catalog.create_posting_rule_release(_rule())
    assert missing_company.value.error_code == "EOS_LEGAL_ENTITY_NOT_FOUND"


@pytest.mark.parametrize(
    "release",
    (
        AccountCatalogReleaseInput(**{**_release().__dict__, "release_id": "bad"}),
        AccountCatalogReleaseInput(**{**_release().__dict__, "source_reference": ""}),
        AccountCatalogReleaseInput(**{**_release().__dict__, "source_hash": "bad"}),
        AccountCatalogReleaseInput(**{**_release().__dict__, "status": "ACTIVE"}),
    ),
)
def test_catalog_release_validation_fails_closed(repository, release) -> None:
    _engine, _factory, catalog = repository
    with pytest.raises(EosAccountCatalogError) as invalid:
        catalog.create_catalog_release(release)
    assert invalid.value.error_code == "EOS_ACCOUNT_CATALOG_INVALID"


@pytest.mark.parametrize(
    "rule",
    (
        PostingRuleReleaseInput(**{**_rule().__dict__, "posting_rule_id": "bad"}),
        PostingRuleReleaseInput(**{**_rule().__dict__, "rule_code": "bad code"}),
        PostingRuleReleaseInput(**{**_rule().__dict__, "rule_version": 0}),
        PostingRuleReleaseInput(**{**_rule().__dict__, "rule_hash": "bad"}),
        PostingRuleReleaseInput(**{**_rule().__dict__, "status": "ACTIVE"}),
    ),
)
def test_posting_rule_validation_fails_closed(repository, rule) -> None:
    _engine, _factory, catalog = repository
    catalog.create_catalog_release(_release())
    with pytest.raises(EosAccountCatalogError) as invalid:
        catalog.create_posting_rule_release(rule)
    assert invalid.value.error_code == "EOS_ACCOUNT_CATALOG_INVALID"


def test_catalog_projection_rejects_unpublished_release_or_rule(repository) -> None:
    engine, _factory, catalog = repository
    _admit(catalog)
    catalog.create_approved_account(account=_account(), policy=_policy())

    with engine.begin() as connection:
        connection.execute(
            EOS_ACCOUNT_CATALOG_RELEASE_TABLE.update()
            .where(EOS_ACCOUNT_CATALOG_RELEASE_TABLE.c.release_id == RELEASE_ID)
            .values(status="DRAFT")
        )
    with pytest.raises(EosAccountCatalogError) as release:
        catalog.get_effective_catalog(
            tenant_id=TENANT_ID, company_id=COMPANY_ID, effective_on=START
        )
    assert release.value.error_code == "EOS_ACCOUNT_CATALOG_INCOMPLETE"

    with engine.begin() as connection:
        connection.execute(
            EOS_ACCOUNT_CATALOG_RELEASE_TABLE.update()
            .where(EOS_ACCOUNT_CATALOG_RELEASE_TABLE.c.release_id == RELEASE_ID)
            .values(status="PUBLISHED")
        )
        connection.execute(
            EOS_POSTING_RULE_RELEASE_TABLE.update()
            .where(EOS_POSTING_RULE_RELEASE_TABLE.c.posting_rule_id == RULE_ID)
            .values(status="DRAFT")
        )
    with pytest.raises(EosAccountCatalogError) as rule:
        catalog.get_effective_catalog(
            tenant_id=TENANT_ID, company_id=COMPANY_ID, effective_on=START
        )
    assert rule.value.error_code == "EOS_ACCOUNT_CATALOG_INCOMPLETE"


def test_catalog_projection_rejects_multiple_effective_releases(repository) -> None:
    _engine, _factory, catalog = repository
    _admit(catalog)
    catalog.create_approved_account(account=_account(), policy=_policy())
    catalog.create_catalog_release(
        _release(
            release_id=DRAFT_RELEASE_ID,
            source_version="2026.02",
            status="PUBLISHED",
        )
    )
    catalog.create_posting_rule_release(
        _rule(
            posting_rule_id=DRAFT_RULE_ID,
            catalog_release_id=DRAFT_RELEASE_ID,
            rule_version=2,
        )
    )
    catalog.create_approved_account(
        account=_account(account_id=CHILD_ACCOUNT_ID, account_code="MEALS-EXPENSE"),
        policy=_policy(
            policy_id=CHILD_POLICY_ID,
            account_id=CHILD_ACCOUNT_ID,
            catalog_release_id=DRAFT_RELEASE_ID,
            posting_rule_id=DRAFT_RULE_ID,
        ),
    )

    with pytest.raises(EosAccountCatalogError) as ambiguous:
        catalog.get_effective_catalog(
            tenant_id=TENANT_ID, company_id=COMPANY_ID, effective_on=START
        )
    assert ambiguous.value.error_code == "EOS_ACCOUNT_CATALOG_AMBIGUOUS"


def test_catalog_projection_rejects_mixed_posting_rules(repository) -> None:
    _engine, _factory, catalog = repository
    _admit(catalog)
    catalog.create_posting_rule_release(
        _rule(posting_rule_id=DRAFT_RULE_ID, rule_version=2)
    )
    catalog.create_approved_account(account=_account(), policy=_policy())
    catalog.create_approved_account(
        account=_account(account_id=CHILD_ACCOUNT_ID, account_code="MEALS-EXPENSE"),
        policy=_policy(
            policy_id=CHILD_POLICY_ID,
            account_id=CHILD_ACCOUNT_ID,
            posting_rule_id=DRAFT_RULE_ID,
        ),
    )

    with pytest.raises(EosAccountCatalogError) as mixed:
        catalog.get_effective_catalog(
            tenant_id=TENANT_ID, company_id=COMPANY_ID, effective_on=START
        )
    assert mixed.value.error_code == "EOS_ACCOUNT_CATALOG_INCOMPLETE"


@pytest.mark.parametrize(
    "policy",
    (
        _policy(allowed_currencies=()),
        _policy(allowed_currencies=("K",)),
        CompanyAccountPolicyInput(
            **{**_policy().__dict__, "is_monetary": "yes"}  # type: ignore[arg-type]
        ),
        CompanyAccountPolicyInput(**{**_policy().__dict__, "valid_until": START}),
        CompanyAccountPolicyInput(**{**_policy().__dict__, "rule_revision": 0}),
        CompanyAccountPolicyInput(
            **{**_policy().__dict__, "approved_proof_ref": "bad"}
        ),
    ),
)
def test_policy_validation_fails_closed(repository, policy) -> None:
    _engine, _factory, catalog = repository
    _admit(catalog)
    with pytest.raises(EosAccountCatalogError) as invalid:
        catalog.create_approved_account(account=_account(), policy=policy)
    assert invalid.value.error_code == "EOS_ACCOUNT_CATALOG_INVALID"


def test_service_requires_fresh_oa_and_returns_catalog(repository) -> None:
    _engine, _factory, catalog = repository
    _admit(catalog)
    catalog.create_approved_account(account=_account(), policy=_policy())
    source = AuthorizationSource()
    service = EosAccountCatalogService(catalog, source)

    result = service.get_catalog(
        tenant_id=TENANT_ID,
        company_id=COMPANY_ID,
        requester_subject_id="accountant-a",
        effective_on=START,
    )
    assert result["accounts"][0]["account_code"] == "TRAVEL-EXPENSE"

    source.scopes.remove("finance:account:read")
    with pytest.raises(EosAccountCatalogError) as denied:
        service.get_catalog(
            tenant_id=TENANT_ID,
            company_id=COMPANY_ID,
            requester_subject_id="accountant-a",
            effective_on=START,
        )
    assert denied.value.error_code == "EOS_ACCOUNT_CATALOG_AUTHORIZATION_DENIED"

    source.scopes.add("finance:account:read")
    source.unavailable = True
    with pytest.raises(EosAccountCatalogError) as unavailable:
        service.get_catalog(
            tenant_id=TENANT_ID,
            company_id=COMPANY_ID,
            requester_subject_id="accountant-a",
            effective_on=START,
        )
    assert (
        unavailable.value.error_code == "EOS_ACCOUNT_CATALOG_AUTHORIZATION_UNAVAILABLE"
    )
    assert "private OA detail" not in unavailable.value.detail

    source.unavailable = False
    source.denied = True
    with pytest.raises(EosAccountCatalogError) as inactive:
        service.get_catalog(
            tenant_id=TENANT_ID,
            company_id=COMPANY_ID,
            requester_subject_id="accountant-a",
            effective_on=START,
        )
    assert inactive.value.error_code == "EOS_ACCOUNT_CATALOG_AUTHORIZATION_DENIED"


@pytest.mark.parametrize(
    ("authorization", "expected_code"),
    (
        (None, "EOS_ACCOUNT_CATALOG_AUTHORIZATION_DENIED"),
        ({"active": False}, "EOS_ACCOUNT_CATALOG_AUTHORIZATION_DENIED"),
        (
            {
                "active": True,
                "tenant_id": OTHER_TENANT_ID,
                "subject_id": "accountant-a",
                "scopes": ["finance:account:read"],
                "revision_hash": "d" * 64,
            },
            "EOS_ACCOUNT_CATALOG_AUTHORIZATION_DENIED",
        ),
        (
            {
                "active": True,
                "tenant_id": TENANT_ID,
                "subject_id": "accountant-a",
                "scopes": "finance:account:read",
                "revision_hash": "d" * 64,
            },
            "EOS_ACCOUNT_CATALOG_AUTHORIZATION_UNAVAILABLE",
        ),
        (
            {
                "active": True,
                "tenant_id": TENANT_ID,
                "subject_id": "accountant-a",
                "scopes": [""],
                "revision_hash": "d" * 64,
            },
            "EOS_ACCOUNT_CATALOG_AUTHORIZATION_UNAVAILABLE",
        ),
        (
            {
                "active": True,
                "tenant_id": TENANT_ID,
                "subject_id": "accountant-a",
                "scopes": ["finance:account:read"],
                "revision_hash": "bad",
            },
            "EOS_ACCOUNT_CATALOG_AUTHORIZATION_UNAVAILABLE",
        ),
    ),
)
def test_service_rejects_malformed_or_drifted_oa_authorization(
    repository, authorization, expected_code
) -> None:
    class RawAuthorizationSource:
        def effective_authorization(self, **_kwargs):
            return authorization

    _engine, _factory, catalog = repository
    service = EosAccountCatalogService(catalog, RawAuthorizationSource())
    with pytest.raises(EosAccountCatalogError) as rejected:
        service.get_catalog(
            tenant_id=TENANT_ID,
            company_id=COMPANY_ID,
            requester_subject_id="accountant-a",
            effective_on=START,
        )
    assert rejected.value.error_code == expected_code


def test_service_approved_create_and_missing_catalog(repository) -> None:
    _engine, _factory, catalog = repository
    _admit(catalog)
    service = EosAccountCatalogService(catalog, AuthorizationSource())
    created = service.create_approved_account(
        tenant_id=TENANT_ID,
        requester_subject_id="accountant-a",
        payload=_api_payload(),
    )
    assert created["account"]["account_id"] == ACCOUNT_ID
    assert created["policy"]["valid_from"] == "2026-01-01"

    empty_engine = create_engine("sqlite+pysqlite:///:memory:")
    EOS_METADATA.create_all(empty_engine)
    empty_service = EosAccountCatalogService(
        SqlAlchemyEosAccountCatalogRepository(sessionmaker(bind=empty_engine)),
        AuthorizationSource(),
    )
    with pytest.raises(EosAccountCatalogError) as missing:
        empty_service.get_catalog(
            tenant_id=TENANT_ID,
            company_id=COMPANY_ID,
            requester_subject_id="accountant-a",
            effective_on=START,
        )
    assert missing.value.error_code == "EOS_ACCOUNT_CATALOG_NOT_FOUND"


@pytest.mark.parametrize(
    ("tenant_id", "payload"),
    (
        ("bad tenant", _api_payload()),
        (TENANT_ID, {"account": None, "policy": {}}),
        (
            TENANT_ID,
            {
                **_api_payload(),
                "account": {
                    **_api_payload()["account"],
                    "effective_from": "not-a-date",
                },
            },
        ),
        (
            TENANT_ID,
            {
                **_api_payload(),
                "policy": {
                    **_api_payload()["policy"],
                    "allowed_currencies": "KRW",
                },
            },
        ),
    ),
)
def test_service_create_rejects_invalid_request_shapes(
    repository, tenant_id, payload
) -> None:
    _engine, _factory, catalog = repository
    service = EosAccountCatalogService(catalog, AuthorizationSource())
    with pytest.raises(EosAccountCatalogError) as invalid:
        service.create_approved_account(
            tenant_id=tenant_id,
            requester_subject_id="accountant-a",
            payload=payload,
        )
    assert invalid.value.error_code == "EOS_ACCOUNT_CATALOG_INVALID"


def test_service_accepts_native_dates_and_bounded_policy_period(repository) -> None:
    _engine, _factory, catalog = repository
    _admit(catalog)
    service = EosAccountCatalogService(catalog, AuthorizationSource())
    payload = _api_payload()
    payload["account"]["effective_from"] = START
    payload["policy"]["valid_from"] = START
    payload["policy"]["valid_until"] = date(2027, 1, 1)

    result = service.create_approved_account(
        tenant_id=TENANT_ID,
        requester_subject_id="accountant-a",
        payload=payload,
    )
    assert result["policy"]["valid_until"] == "2027-01-01"


def test_repository_persistence_failure_is_sanitized(repository) -> None:
    engine, _factory, catalog = repository
    engine.dispose()

    with pytest.raises(EosAccountCatalogError) as unavailable:
        catalog.create_catalog_release(_release())
    assert unavailable.value.error_code == "EOS_ACCOUNT_CATALOG_PERSISTENCE_FAILED"
    assert "no such table" not in unavailable.value.detail.lower()


class FakeAccountCatalogService:
    def get_catalog(self, **kwargs):
        return {"company_id": kwargs["company_id"], "accounts": []}

    def create_approved_account(self, **kwargs):
        return kwargs["payload"]


def test_v2_account_policy_routes_require_service_trust() -> None:
    app = create_eos_app(
        environ={
            "NEX_EOS_SERVICE_ID": "nex-eos",
            "NEX_PROFILE": "test",
            "NEX_VERSION": "mybee-s1-02",
            "NEX_BUILD_SHA": "test",
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
        }
    )
    app.state.eos_account_catalog_service = FakeAccountCatalogService()
    client = TestClient(app)
    headers = {
        "X-NeX-Tenant-Id": TENANT_ID,
        "X-NeX-Subject-Id": "accountant-a",
    }
    params = {"company_id": COMPANY_ID, "effective_on": "2026-01-01"}
    assert (
        client.get(
            "/internal/v2/finance/account-catalog", headers=headers, params=params
        ).status_code
        == 401
    )

    token = issue_mock_service_token(service_id="nex-ae-api", audience="nex-eos")
    headers["Authorization"] = f"Bearer {token.access_token}"
    assert (
        client.get(
            "/internal/v2/finance/account-catalog", headers=headers, params=params
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/internal/v2/finance/accounts/approved",
            headers=headers,
            json=_api_payload(),
        ).status_code
        == 201
    )

    app.state.eos_account_catalog_service = None
    assert (
        client.get(
            "/internal/v2/finance/account-catalog", headers=headers, params=params
        ).status_code
        == 503
    )


def test_v2_account_policy_route_maps_domain_error() -> None:
    class FailingService(FakeAccountCatalogService):
        def get_catalog(self, **_kwargs):
            raise EosAccountCatalogError(
                "EOS_ACCOUNT_CATALOG_NOT_FOUND",
                "No effective catalog",
                status_code=404,
            )

    app = create_eos_app(
        environ={
            "NEX_EOS_SERVICE_ID": "nex-eos",
            "NEX_PROFILE": "test",
            "NEX_VERSION": "mybee-s1-02",
            "NEX_BUILD_SHA": "test",
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
        }
    )
    app.state.eos_account_catalog_service = FailingService()
    token = issue_mock_service_token(service_id="nex-ae-api", audience="nex-eos")
    response = TestClient(app).get(
        "/internal/v2/finance/account-catalog",
        headers={
            "Authorization": f"Bearer {token.access_token}",
            "X-NeX-Tenant-Id": TENANT_ID,
            "X-NeX-Subject-Id": "accountant-a",
        },
        params={"company_id": COMPANY_ID, "effective_on": "2026-01-01"},
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "EOS_ACCOUNT_CATALOG_NOT_FOUND"


@pytest.mark.skipif(
    not DATABASE_URL or not POSTGRES_SMOKE,
    reason="Protected S1-02 EOS PostgreSQL smoke is disabled",
)
def test_s1_02_actual_postgres_migration_fk_overlap_and_zero_residue() -> None:
    schema_name = f"mybee_s102_{uuid.uuid4().hex}"
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
        assert "2517_eos_account_catalog_accounting_period" in result.applied
        runtime = build_eos_database_runtime(
            environ={"NEX_EOS_TEST_DATABASE_URL": scoped_url},
            database_env="NEX_EOS_TEST_DATABASE_URL",
        )
        legal_entities = SqlAlchemyEosLegalEntityRepository(runtime.session_factory)
        legal_entities.create_legal_entity(
            LegalEntityInput(
                TENANT_ID,
                COMPANY_ID,
                "NURI-KR-PG",
                "NURI Korea PG",
                "KRW",
                "KRW",
                "Asia/Seoul",
                START,
            )
        )
        catalog = SqlAlchemyEosAccountCatalogRepository(runtime.session_factory)
        _admit(catalog)
        approved = catalog.create_approved_account(account=_account(), policy=_policy())
        catalog.create_catalog_release(
            _release(
                release_id=DRAFT_RELEASE_ID,
                source_version="2026.02",
                status="PUBLISHED",
            )
        )
        catalog.create_posting_rule_release(
            _rule(
                posting_rule_id=DRAFT_RULE_ID,
                catalog_release_id=DRAFT_RELEASE_ID,
                rule_version=2,
            )
        )
        overlapping_policy = {
            **approved["policy"],
            "policy_id": CHILD_POLICY_ID,
            "catalog_release_id": DRAFT_RELEASE_ID,
            "posting_rule_id": DRAFT_RULE_ID,
            "created_at": datetime.now(UTC),
        }
        with (
            pytest.raises(IntegrityError),
            runtime.engine.begin() as connection,
        ):
            connection.execute(
                EOS_COMPANY_ACCOUNT_POLICY_TABLE.insert().values(**overlapping_policy)
            )

        with runtime.engine.connect() as connection:
            assert (
                connection.execute(
                    select(func.count()).select_from(EOS_ACCOUNT_CATALOG_RELEASE_TABLE)
                ).scalar_one()
                == 2
            )
            assert (
                connection.execute(
                    select(func.count()).select_from(EOS_COMPANY_ACCOUNT_POLICY_TABLE)
                ).scalar_one()
                == 1
            )
        runtime.dispose()
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

    with psycopg.connect(psycopg_url) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM information_schema.schemata WHERE schema_name = %s",
            (schema_name,),
        )
        assert cursor.fetchone() == (0,)
