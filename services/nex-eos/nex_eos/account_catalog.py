from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from nex_runtime import build_unit_of_work
from nex_runtime.semantic_hashes import validate_hash_ref
from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Table,
    UniqueConstraint,
    Uuid,
    and_,
    or_,
    select,
    text,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .accounts import EOS_ACCOUNT_TABLE, AccountInput, build_account_record
from .authorization import AuthorizationSource, AuthorizationSubjectDenied
from .business_transactions import EOS_METADATA
from .legal_entities import EOS_LEGAL_ENTITY_TABLE

EOS_ACCOUNT_CATALOG_RELEASE_STATUSES = frozenset({"DRAFT", "PUBLISHED", "SUPERSEDED"})
EOS_COMPANY_ACCOUNT_POLICY_STATES = frozenset({"APPROVED", "REVOKED"})
EOS_POSTING_RULE_RELEASE_STATUSES = frozenset({"DRAFT", "PUBLISHED", "SUPERSEDED"})
FINANCE_ACCOUNT_CATALOG_READ_SCOPE = "finance:account:read"
FINANCE_ACCOUNT_MANAGE_SCOPE = "finance:account:manage"

_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_REVISION_HASH = re.compile(r"^[0-9a-f]{64}$")

EOS_ACCOUNT_CATALOG_RELEASE_TABLE = Table(
    "eos_account_catalog_release",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("release_id", Uuid(as_uuid=False), primary_key=True),
    Column("source_reference", String(512), nullable=False),
    Column("source_version", String(128), nullable=False),
    Column("source_hash", String(71), nullable=False),
    Column("effective_from", Date, nullable=False),
    Column("published_by", String(128), nullable=False),
    Column("approved_proof_ref", String(71), nullable=False),
    Column("status", String(16), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "tenant_id",
        "source_reference",
        "source_version",
        name="ux_eos_account_catalog_source",
    ),
    CheckConstraint(
        "status IN ('DRAFT', 'PUBLISHED', 'SUPERSEDED')",
        name="ck_eos_account_catalog_status",
    ),
)
Index(
    "ix_eos_account_catalog_effective",
    EOS_ACCOUNT_CATALOG_RELEASE_TABLE.c.tenant_id,
    EOS_ACCOUNT_CATALOG_RELEASE_TABLE.c.status,
    EOS_ACCOUNT_CATALOG_RELEASE_TABLE.c.effective_from,
)

EOS_POSTING_RULE_RELEASE_TABLE = Table(
    "eos_posting_rule_release",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("posting_rule_id", Uuid(as_uuid=False), primary_key=True),
    Column("company_id", Uuid(as_uuid=False), nullable=False),
    Column("catalog_release_id", Uuid(as_uuid=False), nullable=False),
    Column("rule_code", String(128), nullable=False),
    Column("rule_version", Integer, nullable=False),
    Column("rule_hash", String(71), nullable=False),
    Column("effective_date", Date, nullable=False),
    Column("account_mapping_hash", String(71), nullable=False),
    Column("approved_proof_ref", String(71), nullable=False),
    Column("status", String(16), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ("tenant_id", "company_id"),
        ("eos_legal_entity.tenant_id", "eos_legal_entity.company_id"),
        name="fk_eos_posting_rule_company",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "catalog_release_id"),
        (
            "eos_account_catalog_release.tenant_id",
            "eos_account_catalog_release.release_id",
        ),
        name="fk_eos_posting_rule_catalog",
    ),
    UniqueConstraint(
        "tenant_id",
        "company_id",
        "rule_code",
        "rule_version",
        name="ux_eos_posting_rule_version",
    ),
    CheckConstraint("rule_version > 0", name="ck_eos_posting_rule_version"),
    CheckConstraint(
        "status IN ('DRAFT', 'PUBLISHED', 'SUPERSEDED')",
        name="ck_eos_posting_rule_status",
    ),
)
Index(
    "ix_eos_posting_rule_effective",
    EOS_POSTING_RULE_RELEASE_TABLE.c.tenant_id,
    EOS_POSTING_RULE_RELEASE_TABLE.c.company_id,
    EOS_POSTING_RULE_RELEASE_TABLE.c.status,
    EOS_POSTING_RULE_RELEASE_TABLE.c.effective_date,
)

EOS_COMPANY_ACCOUNT_POLICY_TABLE = Table(
    "eos_company_account_policy",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("policy_id", Uuid(as_uuid=False), primary_key=True),
    Column("company_id", Uuid(as_uuid=False), nullable=False),
    Column("account_id", Uuid(as_uuid=False), nullable=False),
    Column("catalog_release_id", Uuid(as_uuid=False), nullable=False),
    Column("posting_rule_id", Uuid(as_uuid=False), nullable=False),
    Column("parent_account_id", Uuid(as_uuid=False), nullable=True),
    Column("is_postable_leaf", Boolean, nullable=False),
    Column("is_monetary", Boolean, nullable=False),
    Column("statement_line_ref", String(128), nullable=False),
    Column("allowed_currencies", JSON, nullable=False),
    Column("valid_from", Date, nullable=False),
    Column("valid_until", Date, nullable=True),
    Column("rule_revision", Integer, nullable=False),
    Column("approved_proof_ref", String(71), nullable=False),
    Column("state", String(16), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ("tenant_id", "company_id"),
        ("eos_legal_entity.tenant_id", "eos_legal_entity.company_id"),
        name="fk_eos_company_account_company",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "account_id"),
        ("eos_account.tenant_id", "eos_account.account_id"),
        name="fk_eos_company_account_account",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "catalog_release_id"),
        (
            "eos_account_catalog_release.tenant_id",
            "eos_account_catalog_release.release_id",
        ),
        name="fk_eos_company_account_catalog",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "posting_rule_id"),
        (
            "eos_posting_rule_release.tenant_id",
            "eos_posting_rule_release.posting_rule_id",
        ),
        name="fk_eos_company_account_rule",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "parent_account_id"),
        ("eos_account.tenant_id", "eos_account.account_id"),
        name="fk_eos_company_account_parent",
    ),
    UniqueConstraint(
        "tenant_id",
        "company_id",
        "account_id",
        "catalog_release_id",
        name="ux_eos_company_account_release",
    ),
    CheckConstraint(
        "valid_until IS NULL OR valid_until > valid_from",
        name="ck_eos_company_account_period",
    ),
    CheckConstraint("rule_revision > 0", name="ck_eos_company_account_revision"),
    CheckConstraint(
        "state IN ('APPROVED', 'REVOKED')", name="ck_eos_company_account_state"
    ),
)
Index(
    "ix_eos_company_account_effective",
    EOS_COMPANY_ACCOUNT_POLICY_TABLE.c.tenant_id,
    EOS_COMPANY_ACCOUNT_POLICY_TABLE.c.company_id,
    EOS_COMPANY_ACCOUNT_POLICY_TABLE.c.state,
    EOS_COMPANY_ACCOUNT_POLICY_TABLE.c.valid_from,
    EOS_COMPANY_ACCOUNT_POLICY_TABLE.c.valid_until,
)


class EosAccountCatalogError(RuntimeError):
    def __init__(
        self,
        error_code: str,
        detail: str,
        *,
        status_code: int,
        retryable: bool = False,
    ) -> None:
        self.error_code = error_code
        self.detail = detail
        self.status_code = status_code
        self.retryable = retryable
        super().__init__(detail)


@dataclass(frozen=True)
class AccountCatalogReleaseInput:
    tenant_id: str
    release_id: str
    source_reference: str
    source_version: str
    source_hash: str
    effective_from: date
    published_by: str
    approved_proof_ref: str
    status: str = "PUBLISHED"


@dataclass(frozen=True)
class PostingRuleReleaseInput:
    tenant_id: str
    posting_rule_id: str
    company_id: str
    catalog_release_id: str
    rule_code: str
    rule_version: int
    rule_hash: str
    effective_date: date
    account_mapping_hash: str
    approved_proof_ref: str
    status: str = "PUBLISHED"


@dataclass(frozen=True)
class CompanyAccountPolicyInput:
    tenant_id: str
    policy_id: str
    company_id: str
    account_id: str
    catalog_release_id: str
    posting_rule_id: str
    is_postable_leaf: bool
    is_monetary: bool
    statement_line_ref: str
    allowed_currencies: Sequence[str]
    valid_from: date
    approved_proof_ref: str
    parent_account_id: str | None = None
    valid_until: date | None = None
    rule_revision: int = 1
    state: str = "APPROVED"


class SqlAlchemyEosAccountCatalogRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create_catalog_release(
        self, value: AccountCatalogReleaseInput
    ) -> dict[str, Any]:
        record = _catalog_release_record(value)
        return self._insert_replayable(
            table=EOS_ACCOUNT_CATALOG_RELEASE_TABLE,
            identity_column="release_id",
            record=record,
            conflict_code="EOS_ACCOUNT_CATALOG_RELEASE_CONFLICT",
        )

    def create_posting_rule_release(
        self, value: PostingRuleReleaseInput
    ) -> dict[str, Any]:
        record = _posting_rule_record(value)
        try:
            with build_unit_of_work(self._session_factory) as transaction:
                session = transaction.db
                existing = _row_by_identity(
                    session,
                    EOS_POSTING_RULE_RELEASE_TABLE,
                    record["tenant_id"],
                    "posting_rule_id",
                    record["posting_rule_id"],
                )
                if existing is not None:
                    return _exact_replay(existing, record, "posting rule release")
                self._require_company_and_release(
                    session,
                    tenant_id=record["tenant_id"],
                    company_id=record["company_id"],
                    release_id=record["catalog_release_id"],
                    effective_on=record["effective_date"],
                )
                session.execute(
                    EOS_POSTING_RULE_RELEASE_TABLE.insert().values(**record)
                )
        except EosAccountCatalogError:
            raise
        except IntegrityError as exc:
            raise _conflict("posting rule release violates identity or scope") from exc
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc
        return dict(record)

    def create_approved_account(
        self,
        *,
        account: AccountInput,
        policy: CompanyAccountPolicyInput,
    ) -> dict[str, Any]:
        account_record = build_account_record(account)
        policy_record = _policy_record(policy)
        if account_record["tenant_id"] != policy_record["tenant_id"]:
            raise _invalid("tenant_id", "must match Account and policy")
        if account_record["account_id"] != policy_record["account_id"]:
            raise _invalid("account_id", "must match Account and policy")
        if account_record["status"] != "ACTIVE":
            raise _invalid("account.status", "must be ACTIVE at approved creation")
        if account_record["effective_from"] > policy_record["valid_from"]:
            raise _invalid(
                "account.effective_from", "must not follow policy valid_from"
            )

        try:
            with build_unit_of_work(self._session_factory) as transaction:
                session = transaction.db
                self._lock_company_scope(
                    session,
                    tenant_id=policy_record["tenant_id"],
                    company_id=policy_record["company_id"],
                )
                existing_account = _row_by_identity(
                    session,
                    EOS_ACCOUNT_TABLE,
                    account_record["tenant_id"],
                    "account_id",
                    account_record["account_id"],
                )
                existing_policy = _row_by_identity(
                    session,
                    EOS_COMPANY_ACCOUNT_POLICY_TABLE,
                    policy_record["tenant_id"],
                    "policy_id",
                    policy_record["policy_id"],
                )
                if existing_account is not None or existing_policy is not None:
                    if existing_account is None or existing_policy is None:
                        raise _conflict(
                            "partial Account/policy identity already exists"
                        )
                    _exact_replay(existing_account, account_record, "Account")
                    _exact_replay(existing_policy, policy_record, "account policy")
                    return _approved_result(existing_account, existing_policy)

                company = self._require_company_and_release(
                    session,
                    tenant_id=policy_record["tenant_id"],
                    company_id=policy_record["company_id"],
                    release_id=policy_record["catalog_release_id"],
                    effective_on=policy_record["valid_from"],
                )
                self._require_posting_rule(session, policy_record)
                if (
                    company["functional_currency"]
                    not in policy_record["allowed_currencies"]
                ):
                    raise _invalid(
                        "allowed_currencies",
                        "must include the LegalEntity functional currency",
                    )
                self._require_parent_policy(session, policy_record)
                session.execute(EOS_ACCOUNT_TABLE.insert().values(**account_record))
                session.execute(
                    EOS_COMPANY_ACCOUNT_POLICY_TABLE.insert().values(**policy_record)
                )
        except EosAccountCatalogError:
            raise
        except IntegrityError as exc:
            raise _conflict(
                "approved Account violates identity or policy scope"
            ) from exc
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc
        return _approved_result(account_record, policy_record)

    def create_company_account_policy(
        self, value: CompanyAccountPolicyInput
    ) -> dict[str, Any]:
        """Attach an approved policy revision to an existing stable Account."""

        record = _policy_record(value)
        try:
            with build_unit_of_work(self._session_factory) as transaction:
                session = transaction.db
                self._lock_company_scope(
                    session,
                    tenant_id=record["tenant_id"],
                    company_id=record["company_id"],
                )
                existing = _row_by_identity(
                    session,
                    EOS_COMPANY_ACCOUNT_POLICY_TABLE,
                    record["tenant_id"],
                    "policy_id",
                    record["policy_id"],
                )
                if existing is not None:
                    return _exact_replay(existing, record, "account policy")
                account = _row_by_identity(
                    session,
                    EOS_ACCOUNT_TABLE,
                    record["tenant_id"],
                    "account_id",
                    record["account_id"],
                )
                if account is None:
                    raise EosAccountCatalogError(
                        "EOS_ACCOUNT_NOT_FOUND",
                        "Stable Account identity was not found in tenant scope",
                        status_code=404,
                    )
                if (
                    account["status"] != "ACTIVE"
                    or account["effective_from"] > record["valid_from"]
                    or (
                        account["effective_until"] is not None
                        and account["effective_until"] <= record["valid_from"]
                    )
                ):
                    raise _conflict("Account is not active and effective")
                company = self._require_company_and_release(
                    session,
                    tenant_id=record["tenant_id"],
                    company_id=record["company_id"],
                    release_id=record["catalog_release_id"],
                    effective_on=record["valid_from"],
                )
                self._require_posting_rule(session, record)
                if company["functional_currency"] not in record["allowed_currencies"]:
                    raise _invalid(
                        "allowed_currencies",
                        "must include the LegalEntity functional currency",
                    )
                self._require_parent_policy(session, record)
                overlap = session.execute(
                    _policy_overlap_statement(record)
                ).scalar_one_or_none()
                if overlap is not None:
                    raise _conflict("account policy effective period overlaps")
                session.execute(
                    EOS_COMPANY_ACCOUNT_POLICY_TABLE.insert().values(**record)
                )
        except EosAccountCatalogError:
            raise
        except IntegrityError as exc:
            raise _conflict("account policy violates identity or scope") from exc
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc
        return dict(record)

    def get_effective_catalog(
        self, *, tenant_id: str, company_id: str, effective_on: date
    ) -> dict[str, Any] | None:
        tenant_id = _scoped_id("tenant_id", tenant_id)
        company_id = _uuid("company_id", company_id)
        effective_on = _date("effective_on", effective_on)
        policy = EOS_COMPANY_ACCOUNT_POLICY_TABLE
        account = EOS_ACCOUNT_TABLE
        statement = (
            select(
                policy.c.policy_id,
                policy.c.catalog_release_id,
                policy.c.posting_rule_id,
                policy.c.parent_account_id,
                policy.c.is_postable_leaf,
                policy.c.is_monetary,
                policy.c.statement_line_ref,
                policy.c.allowed_currencies,
                policy.c.valid_from,
                policy.c.valid_until,
                policy.c.rule_revision,
                policy.c.approved_proof_ref,
                account.c.account_id,
                account.c.account_code,
                account.c.name,
                account.c.category,
                account.c.account_type,
            )
            .select_from(
                policy.join(
                    account,
                    and_(
                        policy.c.tenant_id == account.c.tenant_id,
                        policy.c.account_id == account.c.account_id,
                    ),
                )
            )
            .where(
                policy.c.tenant_id == tenant_id,
                policy.c.company_id == company_id,
                policy.c.state == "APPROVED",
                policy.c.valid_from <= effective_on,
                or_(
                    policy.c.valid_until.is_(None), policy.c.valid_until > effective_on
                ),
                account.c.status == "ACTIVE",
                account.c.effective_from <= effective_on,
                or_(
                    account.c.effective_until.is_(None),
                    account.c.effective_until > effective_on,
                ),
            )
            .order_by(account.c.account_code, account.c.account_id)
        )
        try:
            with self._session_factory() as session:
                rows = [dict(row) for row in session.execute(statement).mappings()]
                if not rows:
                    return None
                release_ids = {row["catalog_release_id"] for row in rows}
                if len(release_ids) != 1:
                    raise EosAccountCatalogError(
                        "EOS_ACCOUNT_CATALOG_AMBIGUOUS",
                        "Multiple catalog releases are effective for one company",
                        status_code=409,
                    )
                release_id = next(iter(release_ids))
                release = _row_by_identity(
                    session,
                    EOS_ACCOUNT_CATALOG_RELEASE_TABLE,
                    tenant_id,
                    "release_id",
                    release_id,
                )
                if (
                    release is None
                    or release["status"] != "PUBLISHED"
                    or release["effective_from"] > effective_on
                ):
                    raise _incomplete("effective catalog release is not published")
                rule_ids = {row["posting_rule_id"] for row in rows}
                if len(rule_ids) != 1:
                    raise _incomplete("effective policies do not share one PostingRule")
                posting_rule = _row_by_identity(
                    session,
                    EOS_POSTING_RULE_RELEASE_TABLE,
                    tenant_id,
                    "posting_rule_id",
                    next(iter(rule_ids)),
                )
                if (
                    posting_rule is None
                    or posting_rule["status"] != "PUBLISHED"
                    or posting_rule["company_id"] != company_id
                    or posting_rule["catalog_release_id"] != release_id
                    or posting_rule["effective_date"] > effective_on
                ):
                    raise _incomplete("effective PostingRule release is unavailable")
        except EosAccountCatalogError:
            raise
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc
        return {
            "tenant_id": tenant_id,
            "company_id": company_id,
            "effective_on": effective_on,
            "catalog_release": release,
            "posting_rule": posting_rule,
            "accounts": rows,
        }

    def _insert_replayable(
        self,
        *,
        table: Table,
        identity_column: str,
        record: Mapping[str, Any],
        conflict_code: str,
    ) -> dict[str, Any]:
        try:
            with build_unit_of_work(self._session_factory) as transaction:
                existing = _row_by_identity(
                    transaction.db,
                    table,
                    record["tenant_id"],
                    identity_column,
                    record[identity_column],
                )
                if existing is not None:
                    return _exact_replay(existing, record, "catalog release")
                transaction.db.execute(table.insert().values(**record))
        except EosAccountCatalogError:
            raise
        except IntegrityError as exc:
            raise EosAccountCatalogError(
                conflict_code,
                "Catalog release identity or source version conflicts",
                status_code=409,
            ) from exc
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc
        return dict(record)

    @staticmethod
    def _lock_company_scope(
        session: Session, *, tenant_id: str, company_id: str
    ) -> None:
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
                {"scope": f"account-policy:{tenant_id}:{company_id}"},
            )

    @staticmethod
    def _require_company_and_release(
        session: Session,
        *,
        tenant_id: str,
        company_id: str,
        release_id: str,
        effective_on: date,
    ) -> Mapping[str, Any]:
        company = (
            session.execute(
                select(EOS_LEGAL_ENTITY_TABLE)
                .where(
                    EOS_LEGAL_ENTITY_TABLE.c.tenant_id == tenant_id,
                    EOS_LEGAL_ENTITY_TABLE.c.company_id == company_id,
                )
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        if company is None:
            raise EosAccountCatalogError(
                "EOS_LEGAL_ENTITY_NOT_FOUND",
                "LegalEntity was not found in tenant scope",
                status_code=404,
            )
        if company["status"] != "ACTIVE" or company["effective_from"] > effective_on:
            raise _conflict("LegalEntity is not active and effective")
        release = _row_by_identity(
            session,
            EOS_ACCOUNT_CATALOG_RELEASE_TABLE,
            tenant_id,
            "release_id",
            release_id,
        )
        if release is None:
            raise EosAccountCatalogError(
                "EOS_ACCOUNT_CATALOG_RELEASE_NOT_FOUND",
                "Account catalog release was not found",
                status_code=404,
            )
        if release["status"] != "PUBLISHED" or release["effective_from"] > effective_on:
            raise _conflict("Account catalog release is not published and effective")
        return company

    @staticmethod
    def _require_posting_rule(session: Session, policy: Mapping[str, Any]) -> None:
        rule = _row_by_identity(
            session,
            EOS_POSTING_RULE_RELEASE_TABLE,
            policy["tenant_id"],
            "posting_rule_id",
            policy["posting_rule_id"],
        )
        if rule is None:
            raise EosAccountCatalogError(
                "EOS_POSTING_RULE_NOT_FOUND",
                "PostingRule release was not found",
                status_code=404,
            )
        if (
            rule["status"] != "PUBLISHED"
            or rule["company_id"] != policy["company_id"]
            or rule["catalog_release_id"] != policy["catalog_release_id"]
            or rule["effective_date"] > policy["valid_from"]
        ):
            raise _conflict("PostingRule is not published for this company and catalog")

    @staticmethod
    def _require_parent_policy(session: Session, policy: Mapping[str, Any]) -> None:
        parent_account_id = policy["parent_account_id"]
        if parent_account_id is None:
            return
        if parent_account_id == policy["account_id"]:
            raise _invalid("parent_account_id", "must differ from account_id")
        parent = (
            session.execute(
                select(EOS_COMPANY_ACCOUNT_POLICY_TABLE).where(
                    EOS_COMPANY_ACCOUNT_POLICY_TABLE.c.tenant_id == policy["tenant_id"],
                    EOS_COMPANY_ACCOUNT_POLICY_TABLE.c.company_id
                    == policy["company_id"],
                    EOS_COMPANY_ACCOUNT_POLICY_TABLE.c.account_id == parent_account_id,
                    EOS_COMPANY_ACCOUNT_POLICY_TABLE.c.catalog_release_id
                    == policy["catalog_release_id"],
                    EOS_COMPANY_ACCOUNT_POLICY_TABLE.c.state == "APPROVED",
                    EOS_COMPANY_ACCOUNT_POLICY_TABLE.c.is_postable_leaf.is_(False),
                )
            )
            .mappings()
            .one_or_none()
        )
        if parent is None:
            raise _conflict(
                "Parent account must be an approved non-postable account in the release"
            )


class EosAccountCatalogService:
    def __init__(
        self,
        repository: SqlAlchemyEosAccountCatalogRepository,
        authorization_source: AuthorizationSource,
    ) -> None:
        self._repository = repository
        self._authorization_source = authorization_source

    def get_catalog(
        self,
        *,
        tenant_id: str,
        company_id: str,
        requester_subject_id: str,
        effective_on: date,
    ) -> dict[str, Any]:
        tenant_id = _scoped_id("tenant_id", tenant_id)
        requester_subject_id = _scoped_id("requester_subject_id", requester_subject_id)
        self._authorize(
            tenant_id=tenant_id,
            subject_id=requester_subject_id,
            required_scope=FINANCE_ACCOUNT_CATALOG_READ_SCOPE,
        )
        result = self._repository.get_effective_catalog(
            tenant_id=tenant_id,
            company_id=company_id,
            effective_on=effective_on,
        )
        if result is None:
            raise EosAccountCatalogError(
                "EOS_ACCOUNT_CATALOG_NOT_FOUND",
                "No approved account catalog is effective for the company",
                status_code=404,
            )
        return _wire(result)

    def create_approved_account(
        self,
        *,
        tenant_id: str,
        requester_subject_id: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        tenant_id = _scoped_id("tenant_id", tenant_id)
        requester_subject_id = _scoped_id("requester_subject_id", requester_subject_id)
        self._authorize(
            tenant_id=tenant_id,
            subject_id=requester_subject_id,
            required_scope=FINANCE_ACCOUNT_MANAGE_SCOPE,
        )
        account_payload = _object("account", payload.get("account"))
        policy_payload = _object("policy", payload.get("policy"))
        account = AccountInput(
            tenant_id=tenant_id,
            account_id=_uuid("account.account_id", account_payload.get("account_id")),
            account_code=_text(
                "account.account_code", account_payload.get("account_code"), 64
            ),
            name=_text("account.name", account_payload.get("name"), 256),
            category=_text("account.category", account_payload.get("category"), 16),
            account_type=_text(
                "account.account_type", account_payload.get("account_type"), 32
            ),
            effective_from=_date_input(
                "account.effective_from", account_payload.get("effective_from")
            ),
            effective_until=_optional_date_input(
                "account.effective_until", account_payload.get("effective_until")
            ),
        )
        policy = CompanyAccountPolicyInput(
            tenant_id=tenant_id,
            policy_id=_uuid("policy.policy_id", policy_payload.get("policy_id")),
            company_id=_uuid("policy.company_id", policy_payload.get("company_id")),
            account_id=account.account_id,
            catalog_release_id=_uuid(
                "policy.catalog_release_id", policy_payload.get("catalog_release_id")
            ),
            posting_rule_id=_uuid(
                "policy.posting_rule_id", policy_payload.get("posting_rule_id")
            ),
            parent_account_id=_optional_uuid(
                "policy.parent_account_id", policy_payload.get("parent_account_id")
            ),
            is_postable_leaf=_boolean(
                "policy.is_postable_leaf", policy_payload.get("is_postable_leaf")
            ),
            is_monetary=_boolean(
                "policy.is_monetary", policy_payload.get("is_monetary")
            ),
            statement_line_ref=_text(
                "policy.statement_line_ref",
                policy_payload.get("statement_line_ref"),
                128,
            ),
            allowed_currencies=_currencies(policy_payload.get("allowed_currencies")),
            valid_from=_date_input(
                "policy.valid_from", policy_payload.get("valid_from")
            ),
            valid_until=_optional_date_input(
                "policy.valid_until", policy_payload.get("valid_until")
            ),
            rule_revision=_positive_int(
                "policy.rule_revision", policy_payload.get("rule_revision", 1)
            ),
            approved_proof_ref=_hash_ref(
                "policy.approved_proof_ref", policy_payload.get("approved_proof_ref")
            ),
        )
        return _wire(
            self._repository.create_approved_account(account=account, policy=policy)
        )

    def _authorize(
        self, *, tenant_id: str, subject_id: str, required_scope: str
    ) -> None:
        try:
            value = self._authorization_source.effective_authorization(
                tenant_id=tenant_id,
                subject_id=subject_id,
            )
        except AuthorizationSubjectDenied as exc:
            raise _authorization_denied(required_scope) from exc
        except Exception as exc:
            raise EosAccountCatalogError(
                "EOS_ACCOUNT_CATALOG_AUTHORIZATION_UNAVAILABLE",
                "OA effective authorization is unavailable",
                status_code=503,
                retryable=True,
            ) from exc
        _admit_authorization(
            value,
            tenant_id=tenant_id,
            subject_id=subject_id,
            required_scope=required_scope,
        )


def _catalog_release_record(value: AccountCatalogReleaseInput) -> dict[str, Any]:
    return {
        "tenant_id": _scoped_id("tenant_id", value.tenant_id),
        "release_id": _uuid("release_id", value.release_id),
        "source_reference": _text("source_reference", value.source_reference, 512),
        "source_version": _text("source_version", value.source_version, 128),
        "source_hash": _hash_ref("source_hash", value.source_hash),
        "effective_from": _date("effective_from", value.effective_from),
        "published_by": _scoped_id("published_by", value.published_by),
        "approved_proof_ref": _hash_ref("approved_proof_ref", value.approved_proof_ref),
        "status": _choice("status", value.status, EOS_ACCOUNT_CATALOG_RELEASE_STATUSES),
        "created_at": datetime.now(UTC),
    }


def _posting_rule_record(value: PostingRuleReleaseInput) -> dict[str, Any]:
    return {
        "tenant_id": _scoped_id("tenant_id", value.tenant_id),
        "posting_rule_id": _uuid("posting_rule_id", value.posting_rule_id),
        "company_id": _uuid("company_id", value.company_id),
        "catalog_release_id": _uuid("catalog_release_id", value.catalog_release_id),
        "rule_code": _code("rule_code", value.rule_code),
        "rule_version": _positive_int("rule_version", value.rule_version),
        "rule_hash": _hash_ref("rule_hash", value.rule_hash),
        "effective_date": _date("effective_date", value.effective_date),
        "account_mapping_hash": _hash_ref(
            "account_mapping_hash", value.account_mapping_hash
        ),
        "approved_proof_ref": _hash_ref("approved_proof_ref", value.approved_proof_ref),
        "status": _choice("status", value.status, EOS_POSTING_RULE_RELEASE_STATUSES),
        "created_at": datetime.now(UTC),
    }


def _policy_record(value: CompanyAccountPolicyInput) -> dict[str, Any]:
    valid_from = _date("valid_from", value.valid_from)
    valid_until = _optional_date("valid_until", value.valid_until)
    if valid_until is not None and valid_until <= valid_from:
        raise _invalid("valid_until", "must follow valid_from")
    return {
        "tenant_id": _scoped_id("tenant_id", value.tenant_id),
        "policy_id": _uuid("policy_id", value.policy_id),
        "company_id": _uuid("company_id", value.company_id),
        "account_id": _uuid("account_id", value.account_id),
        "catalog_release_id": _uuid("catalog_release_id", value.catalog_release_id),
        "posting_rule_id": _uuid("posting_rule_id", value.posting_rule_id),
        "parent_account_id": _optional_uuid(
            "parent_account_id", value.parent_account_id
        ),
        "is_postable_leaf": _boolean("is_postable_leaf", value.is_postable_leaf),
        "is_monetary": _boolean("is_monetary", value.is_monetary),
        "statement_line_ref": _code("statement_line_ref", value.statement_line_ref),
        "allowed_currencies": list(_currencies(value.allowed_currencies)),
        "valid_from": valid_from,
        "valid_until": valid_until,
        "rule_revision": _positive_int("rule_revision", value.rule_revision),
        "approved_proof_ref": _hash_ref("approved_proof_ref", value.approved_proof_ref),
        "state": _choice("state", value.state, EOS_COMPANY_ACCOUNT_POLICY_STATES),
        "created_at": datetime.now(UTC),
    }


def _row_by_identity(
    session: Session,
    table: Table,
    tenant_id: str,
    identity_column: str,
    identity: str,
) -> Mapping[str, Any] | None:
    return (
        session.execute(
            select(table).where(
                table.c.tenant_id == tenant_id,
                getattr(table.c, identity_column) == identity,
            )
        )
        .mappings()
        .one_or_none()
    )


def _exact_replay(
    existing: Mapping[str, Any], record: Mapping[str, Any], label: str
) -> dict[str, Any]:
    keys = tuple(key for key in record if key not in {"created_at", "updated_at"})
    if any(existing[key] != record[key] for key in keys):
        raise _conflict(f"{label} identity has different semantics")
    return dict(existing)


def _approved_result(
    account: Mapping[str, Any], policy: Mapping[str, Any]
) -> dict[str, Any]:
    return {"account": dict(account), "policy": dict(policy)}


def _policy_overlap_statement(record: Mapping[str, Any]):
    table = EOS_COMPANY_ACCOUNT_POLICY_TABLE
    predicates = [
        table.c.tenant_id == record["tenant_id"],
        table.c.company_id == record["company_id"],
        table.c.account_id == record["account_id"],
        table.c.state == "APPROVED",
        or_(table.c.valid_until.is_(None), table.c.valid_until > record["valid_from"]),
    ]
    if record["valid_until"] is not None:
        predicates.append(table.c.valid_from < record["valid_until"])
    return select(table.c.policy_id).where(*predicates).limit(1)


def _admit_authorization(
    value: object, *, tenant_id: str, subject_id: str, required_scope: str
) -> None:
    if not isinstance(value, Mapping) or value.get("active") is not True:
        raise _authorization_denied(required_scope)
    if value.get("tenant_id") != tenant_id or value.get("subject_id") != subject_id:
        raise _authorization_denied(required_scope)
    scopes = value.get("scopes")
    if isinstance(scopes, (str, bytes)) or not isinstance(scopes, Sequence):
        raise _authorization_unavailable()
    if any(not isinstance(item, str) or not item for item in scopes):
        raise _authorization_unavailable()
    if required_scope not in scopes:
        raise _authorization_denied(required_scope)
    revision_hash = value.get("revision_hash")
    if (
        not isinstance(revision_hash, str)
        or _REVISION_HASH.fullmatch(revision_hash) is None
    ):
        raise _authorization_unavailable()


def _wire(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _wire(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_wire(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _object(field_name: str, value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(field_name, "must be an object")
    return value


def _uuid(field_name: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise _invalid(field_name, "must be a UUID") from exc


def _optional_uuid(field_name: str, value: object) -> str | None:
    return None if value is None else _uuid(field_name, value)


def _scoped_id(field_name: str, value: object) -> str:
    normalized = str(value).strip() if value is not None else ""
    if _SCOPED_ID.fullmatch(normalized) is None:
        raise _invalid(field_name, "has invalid stable-reference syntax")
    return normalized


def _code(field_name: str, value: object) -> str:
    normalized = str(value).strip() if value is not None else ""
    if _CODE.fullmatch(normalized) is None:
        raise _invalid(field_name, "has invalid code syntax")
    return normalized


def _text(field_name: str, value: object, maximum: int) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not normalized or len(normalized) > maximum:
        raise _invalid(field_name, f"must contain 1..{maximum} characters")
    return normalized


def _choice(field_name: str, value: object, choices: frozenset[str]) -> str:
    normalized = str(value).strip().upper() if value is not None else ""
    if normalized not in choices:
        raise _invalid(field_name, f"must be one of {sorted(choices)}")
    return normalized


def _date(field_name: str, value: object) -> date:
    if isinstance(value, datetime) or not isinstance(value, date):
        raise _invalid(field_name, "must be a date")
    return value


def _date_input(field_name: str, value: object) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise _invalid(field_name, "must be an ISO date") from exc
    raise _invalid(field_name, "must be an ISO date")


def _optional_date(field_name: str, value: object) -> date | None:
    return None if value is None else _date(field_name, value)


def _optional_date_input(field_name: str, value: object) -> date | None:
    return None if value is None else _date_input(field_name, value)


def _positive_int(field_name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _invalid(field_name, "must be a positive integer")
    return value


def _boolean(field_name: str, value: object) -> bool:
    if not isinstance(value, bool):
        raise _invalid(field_name, "must be boolean")
    return value


def _currencies(value: object) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise _invalid("allowed_currencies", "must be an array")
    result: list[str] = []
    for item in value:
        normalized = str(item).strip().upper() if item is not None else ""
        if _CURRENCY.fullmatch(normalized) is None:
            raise _invalid("allowed_currencies", "contains an invalid currency")
        if normalized not in result:
            result.append(normalized)
    if not result:
        raise _invalid("allowed_currencies", "must not be empty")
    return tuple(sorted(result))


def _hash_ref(field_name: str, value: object) -> str:
    try:
        return validate_hash_ref(value)
    except (TypeError, ValueError) as exc:
        raise _invalid(field_name, "must be a SHA-256 hash reference") from exc


def _invalid(field_name: str, detail: str) -> EosAccountCatalogError:
    return EosAccountCatalogError(
        "EOS_ACCOUNT_CATALOG_INVALID",
        f"{field_name} {detail}",
        status_code=422,
    )


def _conflict(detail: str) -> EosAccountCatalogError:
    return EosAccountCatalogError(
        "EOS_ACCOUNT_CATALOG_CONFLICT", detail, status_code=409
    )


def _incomplete(detail: str) -> EosAccountCatalogError:
    return EosAccountCatalogError(
        "EOS_ACCOUNT_CATALOG_INCOMPLETE", detail, status_code=409
    )


def _authorization_denied(required_scope: str) -> EosAccountCatalogError:
    return EosAccountCatalogError(
        "EOS_ACCOUNT_CATALOG_AUTHORIZATION_DENIED",
        f"Fresh OA authority for {required_scope} is required",
        status_code=403,
    )


def _authorization_unavailable() -> EosAccountCatalogError:
    return EosAccountCatalogError(
        "EOS_ACCOUNT_CATALOG_AUTHORIZATION_UNAVAILABLE",
        "OA effective authorization response is malformed",
        status_code=503,
        retryable=True,
    )


def _persistence_error() -> EosAccountCatalogError:
    return EosAccountCatalogError(
        "EOS_ACCOUNT_CATALOG_PERSISTENCE_FAILED",
        "Account catalog persistence is unavailable",
        status_code=503,
        retryable=True,
    )
