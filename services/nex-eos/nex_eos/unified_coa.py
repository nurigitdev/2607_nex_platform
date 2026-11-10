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
    select,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .business_transactions import EOS_METADATA

EOS_COA_RELEASE_SCOPES = frozenset({"GLOBAL", "TENANT"})
EOS_COA_RELEASE_STATUSES = frozenset({"DRAFT", "PUBLISHED", "SUPERSEDED"})
EOS_COA_CATEGORIES = frozenset(
    {"ASSET", "LIABILITY", "EQUITY", "REVENUE", "EXPENSE"}
)
EOS_COA_NORMAL_BALANCES = frozenset({"DR", "CR"})
EOS_COA_MAPPING_STATUSES = frozenset(
    {"MAPPING_PENDING", "RESOLVED", "NOT_APPLICABLE"}
)

_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_ACCOUNT_CODE = re.compile(r"^[1-9][0-9]{7}$")
_SEMANTIC_KEY = re.compile(r"^MB-COA-[A-Z0-9]+(?:-[A-Z0-9]+)*$")

EOS_COA_DEFINITION_RELEASE_TABLE = Table(
    "eos_coa_definition_release",
    EOS_METADATA,
    Column("definition_release_id", Uuid(as_uuid=False), primary_key=True),
    Column("scope_type", String(8), nullable=False),
    Column("owner_tenant_id", String(128), nullable=True),
    Column("base_global_release_id", Uuid(as_uuid=False), nullable=True),
    Column("chart_profile", String(64), nullable=False),
    Column("release_version", String(64), nullable=False),
    Column("effective_from", Date, nullable=False),
    Column("source_reference", String(512), nullable=False),
    Column("source_hash", String(71), nullable=False),
    Column("approved_proof_ref", String(71), nullable=False),
    Column("content_hash", String(71), nullable=False),
    Column("status", String(16), nullable=False),
    Column("created_by", String(128), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("published_at", DateTime(timezone=True), nullable=True),
    ForeignKeyConstraint(
        ("base_global_release_id",),
        ("eos_coa_definition_release.definition_release_id",),
        name="fk_eos_coa_release_base",
    ),
    CheckConstraint(
        "status IN ('DRAFT', 'PUBLISHED', 'SUPERSEDED')",
        name="ck_eos_coa_release_status",
    ),
)
Index(
    "ix_eos_coa_release_effective",
    EOS_COA_DEFINITION_RELEASE_TABLE.c.scope_type,
    EOS_COA_DEFINITION_RELEASE_TABLE.c.owner_tenant_id,
    EOS_COA_DEFINITION_RELEASE_TABLE.c.status,
    EOS_COA_DEFINITION_RELEASE_TABLE.c.effective_from,
)

EOS_COA_ENTRY_TABLE = Table(
    "eos_coa_entry",
    EOS_METADATA,
    Column("entry_id", Uuid(as_uuid=False), primary_key=True),
    Column("definition_release_id", Uuid(as_uuid=False), nullable=False),
    Column("scope_type", String(8), nullable=False),
    Column("owner_tenant_id", String(128), nullable=True),
    Column("account_code", String(8), nullable=False),
    Column("semantic_key", String(128), nullable=False),
    Column("account_name", String(256), nullable=False),
    Column("parent_entry_id", Uuid(as_uuid=False), nullable=True),
    Column("hierarchy_level", Integer, nullable=False),
    Column("category", String(16), nullable=False),
    Column("account_type", String(32), nullable=False),
    Column("normal_balance", String(2), nullable=False),
    Column("is_contra", Boolean, nullable=False),
    Column("is_postable", Boolean, nullable=False),
    Column("is_monetary_default", Boolean, nullable=False),
    Column("reporting_mapping_status", String(32), nullable=False),
    Column("source_lineage", String(128), nullable=False),
    Column("source_row_hash", String(71), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ("definition_release_id",),
        ("eos_coa_definition_release.definition_release_id",),
        name="fk_eos_coa_entry_release",
    ),
    ForeignKeyConstraint(
        ("parent_entry_id",),
        ("eos_coa_entry.entry_id",),
        name="fk_eos_coa_entry_parent",
    ),
    UniqueConstraint(
        "definition_release_id",
        "account_code",
        name="ux_eos_coa_entry_code",
    ),
    UniqueConstraint(
        "definition_release_id",
        "semantic_key",
        name="ux_eos_coa_entry_semantic",
    ),
    CheckConstraint(
        "hierarchy_level BETWEEN 1 AND 4", name="ck_eos_coa_entry_level"
    ),
)
Index(
    "ix_eos_coa_entry_release",
    EOS_COA_ENTRY_TABLE.c.definition_release_id,
    EOS_COA_ENTRY_TABLE.c.hierarchy_level,
    EOS_COA_ENTRY_TABLE.c.account_code,
)
Index(
    "ix_eos_coa_entry_semantic",
    EOS_COA_ENTRY_TABLE.c.semantic_key,
    EOS_COA_ENTRY_TABLE.c.scope_type,
    EOS_COA_ENTRY_TABLE.c.owner_tenant_id,
)

EOS_COA_CODE_IDENTITY_TABLE = Table(
    "eos_coa_code_identity",
    EOS_METADATA,
    Column("identity_id", Uuid(as_uuid=False), primary_key=True),
    Column("scope_type", String(8), nullable=False),
    Column("owner_tenant_id", String(128), nullable=True),
    Column("chart_profile", String(64), nullable=False),
    Column("account_code", String(8), nullable=False),
    Column("semantic_key", String(128), nullable=False),
    Column("first_release_id", Uuid(as_uuid=False), nullable=False),
    Column("state", String(16), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ("first_release_id",),
        ("eos_coa_definition_release.definition_release_id",),
        name="fk_eos_coa_identity_release",
    ),
)

EOS_COA_COMPANY_ADOPTION_TABLE = Table(
    "eos_coa_company_adoption",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("adoption_id", Uuid(as_uuid=False), primary_key=True),
    Column("company_id", Uuid(as_uuid=False), nullable=False),
    Column("global_release_id", Uuid(as_uuid=False), nullable=False),
    Column("extension_release_id", Uuid(as_uuid=False), nullable=True),
    Column("effective_from", Date, nullable=False),
    Column("effective_until", Date, nullable=True),
    Column("approved_proof_ref", String(71), nullable=False),
    Column("state", String(16), nullable=False),
    Column("created_by", String(128), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ("tenant_id", "company_id"),
        ("eos_legal_entity.tenant_id", "eos_legal_entity.company_id"),
        name="fk_eos_coa_adoption_company",
    ),
    ForeignKeyConstraint(
        ("global_release_id",),
        ("eos_coa_definition_release.definition_release_id",),
        name="fk_eos_coa_adoption_global",
    ),
    ForeignKeyConstraint(
        ("extension_release_id",),
        ("eos_coa_definition_release.definition_release_id",),
        name="fk_eos_coa_adoption_extension",
    ),
)
Index(
    "ix_eos_coa_adoption_effective",
    EOS_COA_COMPANY_ADOPTION_TABLE.c.tenant_id,
    EOS_COA_COMPANY_ADOPTION_TABLE.c.company_id,
    EOS_COA_COMPANY_ADOPTION_TABLE.c.state,
    EOS_COA_COMPANY_ADOPTION_TABLE.c.effective_from,
    EOS_COA_COMPANY_ADOPTION_TABLE.c.effective_until,
)

EOS_COA_ACCOUNT_BINDING_TABLE = Table(
    "eos_coa_account_binding",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("binding_id", Uuid(as_uuid=False), primary_key=True),
    Column("adoption_id", Uuid(as_uuid=False), nullable=False),
    Column("entry_id", Uuid(as_uuid=False), nullable=False),
    Column("account_id", Uuid(as_uuid=False), nullable=False),
    Column("approved_proof_ref", String(71), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ("tenant_id", "adoption_id"),
        (
            "eos_coa_company_adoption.tenant_id",
            "eos_coa_company_adoption.adoption_id",
        ),
        name="fk_eos_coa_binding_adoption",
    ),
    ForeignKeyConstraint(
        ("entry_id",),
        ("eos_coa_entry.entry_id",),
        name="fk_eos_coa_binding_entry",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "account_id"),
        ("eos_account.tenant_id", "eos_account.account_id"),
        name="fk_eos_coa_binding_account",
    ),
    UniqueConstraint(
        "tenant_id",
        "adoption_id",
        "entry_id",
        name="ux_eos_coa_binding_entry",
    ),
    UniqueConstraint(
        "tenant_id",
        "adoption_id",
        "account_id",
        name="ux_eos_coa_binding_account",
    ),
)
Index(
    "ix_eos_coa_binding_account",
    EOS_COA_ACCOUNT_BINDING_TABLE.c.tenant_id,
    EOS_COA_ACCOUNT_BINDING_TABLE.c.account_id,
)


class EosUnifiedCoaError(RuntimeError):
    def __init__(self, error_code: str, detail: str, *, status_code: int) -> None:
        self.error_code = error_code
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


@dataclass(frozen=True)
class CoaDefinitionReleaseInput:
    definition_release_id: str
    scope_type: str
    chart_profile: str
    release_version: str
    effective_from: date
    source_reference: str
    source_hash: str
    approved_proof_ref: str
    content_hash: str
    created_by: str
    owner_tenant_id: str | None = None
    base_global_release_id: str | None = None
    status: str = "DRAFT"


@dataclass(frozen=True)
class CoaEntryInput:
    entry_id: str
    account_code: str
    semantic_key: str
    account_name: str
    hierarchy_level: int
    category: str
    account_type: str
    normal_balance: str
    is_contra: bool
    is_postable: bool
    is_monetary_default: bool
    source_lineage: str
    source_row_hash: str
    parent_entry_id: str | None = None
    reporting_mapping_status: str = "MAPPING_PENDING"


class SqlAlchemyEosUnifiedCoaRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create_draft_release(
        self,
        *,
        release: CoaDefinitionReleaseInput,
        entries: Sequence[CoaEntryInput],
    ) -> dict[str, Any]:
        release_record = _release_record(release)
        if release_record["status"] != "DRAFT":
            raise _invalid("status", "COA-02 persistence only admits DRAFT releases")
        entry_records = _entry_records(release_record, entries)
        try:
            with build_unit_of_work(self._session_factory) as transaction:
                session = transaction.db
                existing = _release_by_id(
                    session, release_record["definition_release_id"]
                )
                if existing is not None:
                    return self._exact_replay(
                        session=session,
                        existing_release=existing,
                        release_record=release_record,
                        entry_records=entry_records,
                    )
                session.execute(
                    EOS_COA_DEFINITION_RELEASE_TABLE.insert().values(**release_record)
                )
                for record in entry_records:
                    session.execute(EOS_COA_ENTRY_TABLE.insert().values(**record))
        except EosUnifiedCoaError:
            raise
        except IntegrityError as exc:
            raise _conflict("COA release or entry identity already exists") from exc
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc
        return {"release": dict(release_record), "entries": entry_records}

    def get_release(
        self, *, definition_release_id: str
    ) -> dict[str, Any] | None:
        release_id = _uuid("definition_release_id", definition_release_id)
        try:
            with self._session_factory() as session:
                release = _release_by_id(session, release_id)
                if release is None:
                    return None
                entries = (
                    session.execute(
                        select(EOS_COA_ENTRY_TABLE)
                        .where(
                            EOS_COA_ENTRY_TABLE.c.definition_release_id == release_id
                        )
                        .order_by(
                            EOS_COA_ENTRY_TABLE.c.hierarchy_level,
                            EOS_COA_ENTRY_TABLE.c.account_code,
                        )
                    )
                    .mappings()
                    .all()
                )
        except SQLAlchemyError as exc:
            raise _persistence_error() from exc
        return {
            "release": dict(release),
            "entries": [dict(item) for item in entries],
        }

    @staticmethod
    def _exact_replay(
        *,
        session: Session,
        existing_release: Mapping[str, Any],
        release_record: Mapping[str, Any],
        entry_records: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        _same_record(existing_release, release_record, ignored={"created_at"})
        existing_entries = (
            session.execute(
                select(EOS_COA_ENTRY_TABLE)
                .where(
                    EOS_COA_ENTRY_TABLE.c.definition_release_id
                    == release_record["definition_release_id"]
                )
                .order_by(
                    EOS_COA_ENTRY_TABLE.c.hierarchy_level,
                    EOS_COA_ENTRY_TABLE.c.account_code,
                )
            )
            .mappings()
            .all()
        )
        if len(existing_entries) != len(entry_records):
            raise _conflict("COA release replay has a different entry count")
        for existing, expected in zip(existing_entries, entry_records, strict=True):
            _same_record(existing, expected, ignored={"created_at"})
        return {
            "release": dict(existing_release),
            "entries": [dict(item) for item in existing_entries],
        }


def _release_record(value: CoaDefinitionReleaseInput) -> dict[str, Any]:
    scope_type = _choice("scope_type", value.scope_type, EOS_COA_RELEASE_SCOPES)
    owner_tenant_id = _optional_scoped_id("owner_tenant_id", value.owner_tenant_id)
    base_global_release_id = _optional_uuid(
        "base_global_release_id", value.base_global_release_id
    )
    if scope_type == "GLOBAL" and (
        owner_tenant_id is not None or base_global_release_id is not None
    ):
        raise _invalid("scope_type", "GLOBAL release cannot have tenant/base owner")
    if scope_type == "TENANT" and (
        owner_tenant_id is None or base_global_release_id is None
    ):
        raise _invalid("scope_type", "TENANT release requires owner and GLOBAL base")
    return {
        "definition_release_id": _uuid(
            "definition_release_id", value.definition_release_id
        ),
        "scope_type": scope_type,
        "owner_tenant_id": owner_tenant_id,
        "base_global_release_id": base_global_release_id,
        "chart_profile": _text("chart_profile", value.chart_profile, 64),
        "release_version": _text("release_version", value.release_version, 64),
        "effective_from": _date("effective_from", value.effective_from),
        "source_reference": _text("source_reference", value.source_reference, 512),
        "source_hash": _hash_ref("source_hash", value.source_hash),
        "approved_proof_ref": _hash_ref(
            "approved_proof_ref", value.approved_proof_ref
        ),
        "content_hash": _hash_ref("content_hash", value.content_hash),
        "status": _choice("status", value.status, EOS_COA_RELEASE_STATUSES),
        "created_by": _scoped_id("created_by", value.created_by),
        "created_at": datetime.now(UTC),
        "published_at": None,
    }


def _entry_records(
    release: Mapping[str, Any], entries: Sequence[CoaEntryInput]
) -> list[dict[str, Any]]:
    if not entries:
        raise _invalid("entries", "must not be empty")
    records = [_entry_record(release, item) for item in entries]
    records.sort(key=lambda item: (item["hierarchy_level"], item["account_code"]))
    by_id: dict[str, Mapping[str, Any]] = {}
    by_code: set[str] = set()
    by_semantic: set[str] = set()
    for record in records:
        if record["entry_id"] in by_id or record["account_code"] in by_code:
            raise _conflict("COA entry identity or code is duplicated")
        if record["semantic_key"] in by_semantic:
            raise _conflict("COA semantic key is duplicated")
        _validate_entry_parent(record, release=release, by_id=by_id)
        by_id[record["entry_id"]] = record
        by_code.add(record["account_code"])
        by_semantic.add(record["semantic_key"])
    return records


def _entry_record(
    release: Mapping[str, Any], value: CoaEntryInput
) -> dict[str, Any]:
    code = str(value.account_code).strip()
    if _ACCOUNT_CODE.fullmatch(code) is None:
        raise _invalid("account_code", "must contain exactly eight governed digits")
    semantic_key = str(value.semantic_key).strip()
    if _SEMANTIC_KEY.fullmatch(semantic_key) is None:
        raise _invalid("semantic_key", "has invalid MyBee semantic-key syntax")
    hierarchy_level = _positive_int("hierarchy_level", value.hierarchy_level)
    if hierarchy_level > 4 or _hierarchy_level(code) != hierarchy_level:
        raise _invalid("hierarchy_level", "does not match account_code")
    category = _choice("category", value.category, EOS_COA_CATEGORIES)
    normal_balance = _choice(
        "normal_balance", value.normal_balance, EOS_COA_NORMAL_BALANCES
    )
    is_contra = _boolean("is_contra", value.is_contra)
    expected_balance = _normal_balance(category, is_contra)
    if normal_balance != expected_balance:
        raise _invalid("normal_balance", f"must be {expected_balance}")
    is_postable = _boolean("is_postable", value.is_postable)
    if is_postable != (hierarchy_level == 4):
        raise _invalid("is_postable", "must be true only for a leaf")
    account_type = _text("account_type", value.account_type, 32)
    if (account_type == "ACCOUNT_GROUP") == (hierarchy_level == 4):
        raise _invalid("account_type", "must distinguish group and leaf")
    suffix = int(code[-3:])
    if (
        release["scope_type"] == "GLOBAL"
        and hierarchy_level == 4
        and not 1 <= suffix <= 699
    ):
        raise _invalid("account_code", "GLOBAL leaf suffix must be 001..699")
    if release["scope_type"] == "TENANT" and (
        hierarchy_level != 4 or not 800 <= suffix <= 999
    ):
        raise _invalid("account_code", "TENANT entry must be an 800..999 leaf")
    return {
        "entry_id": _uuid("entry_id", value.entry_id),
        "definition_release_id": release["definition_release_id"],
        "scope_type": release["scope_type"],
        "owner_tenant_id": release["owner_tenant_id"],
        "account_code": code,
        "semantic_key": semantic_key,
        "account_name": _text("account_name", value.account_name, 256),
        "parent_entry_id": _optional_uuid("parent_entry_id", value.parent_entry_id),
        "hierarchy_level": hierarchy_level,
        "category": category,
        "account_type": account_type,
        "normal_balance": normal_balance,
        "is_contra": is_contra,
        "is_postable": is_postable,
        "is_monetary_default": _boolean(
            "is_monetary_default", value.is_monetary_default
        ),
        "reporting_mapping_status": _choice(
            "reporting_mapping_status",
            value.reporting_mapping_status,
            EOS_COA_MAPPING_STATUSES,
        ),
        "source_lineage": _text("source_lineage", value.source_lineage, 128),
        "source_row_hash": _hash_ref("source_row_hash", value.source_row_hash),
        "created_at": datetime.now(UTC),
    }


def _validate_entry_parent(
    record: Mapping[str, Any],
    *,
    release: Mapping[str, Any],
    by_id: Mapping[str, Mapping[str, Any]],
) -> None:
    level = record["hierarchy_level"]
    parent_id = record["parent_entry_id"]
    if level == 1:
        if parent_id is not None:
            raise _invalid("parent_entry_id", "root must not have a parent")
        return
    if release["scope_type"] == "TENANT":
        if parent_id is None:
            raise _invalid("parent_entry_id", "TENANT leaf requires GLOBAL family")
        return
    parent = by_id.get(parent_id)
    if parent is None:
        raise _invalid("parent_entry_id", "must precede child in the same release")
    if (
        parent["hierarchy_level"] != level - 1
        or parent["category"] != record["category"]
        or _expected_parent_code(record["account_code"], level)
        != parent["account_code"]
    ):
        raise _invalid("parent_entry_id", "does not match the governed hierarchy")


def _release_by_id(
    session: Session, definition_release_id: str
) -> Mapping[str, Any] | None:
    return (
        session.execute(
            select(EOS_COA_DEFINITION_RELEASE_TABLE).where(
                EOS_COA_DEFINITION_RELEASE_TABLE.c.definition_release_id
                == definition_release_id
            )
        )
        .mappings()
        .one_or_none()
    )


def _same_record(
    existing: Mapping[str, Any],
    expected: Mapping[str, Any],
    *,
    ignored: set[str],
) -> None:
    if any(
        existing[key] != value
        for key, value in expected.items()
        if key not in ignored
    ):
        raise _conflict("COA release identity has different semantics")


def _hierarchy_level(code: str) -> int | None:
    if code[1:] == "0000000":
        return 1
    if code[1:3] != "00" and code[3:] == "00000":
        return 2
    if code[1:3] != "00" and code[3:5] != "00" and code[5:] == "000":
        return 3
    if code[1:3] != "00" and code[3:5] != "00" and code[5:] != "000":
        return 4
    return None


def _expected_parent_code(code: str, level: int) -> str:
    if level == 2:
        return code[0] + "0000000"
    if level == 3:
        return code[:3] + "00000"
    return code[:5] + "000"


def _normal_balance(category: str, is_contra: bool) -> str:
    normal = "DR" if category in {"ASSET", "EXPENSE"} else "CR"
    if not is_contra:
        return normal
    return "CR" if normal == "DR" else "DR"


def _uuid(field: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise _invalid(field, "must be a UUID") from exc


def _optional_uuid(field: str, value: object) -> str | None:
    return None if value is None else _uuid(field, value)


def _scoped_id(field: str, value: object) -> str:
    normalized = str(value).strip() if value is not None else ""
    if _SCOPED_ID.fullmatch(normalized) is None:
        raise _invalid(field, "has invalid stable-reference syntax")
    return normalized


def _optional_scoped_id(field: str, value: object) -> str | None:
    return None if value is None else _scoped_id(field, value)


def _text(field: str, value: object, maximum: int) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not normalized or len(normalized) > maximum:
        raise _invalid(field, f"must contain 1..{maximum} characters")
    return normalized


def _choice(field: str, value: object, choices: frozenset[str]) -> str:
    normalized = str(value).strip().upper() if value is not None else ""
    if normalized not in choices:
        raise _invalid(field, f"must be one of {sorted(choices)}")
    return normalized


def _date(field: str, value: object) -> date:
    if isinstance(value, datetime) or not isinstance(value, date):
        raise _invalid(field, "must be a date")
    return value


def _positive_int(field: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _invalid(field, "must be a positive integer")
    return value


def _boolean(field: str, value: object) -> bool:
    if not isinstance(value, bool):
        raise _invalid(field, "must be boolean")
    return value


def _hash_ref(field: str, value: object) -> str:
    try:
        return validate_hash_ref(value)
    except (TypeError, ValueError) as exc:
        raise _invalid(field, "must be a SHA-256 hash reference") from exc


def _invalid(field: str, detail: str) -> EosUnifiedCoaError:
    return EosUnifiedCoaError(
        "EOS_COA_INVALID", f"{field} {detail}", status_code=422
    )


def _conflict(detail: str) -> EosUnifiedCoaError:
    return EosUnifiedCoaError("EOS_COA_CONFLICT", detail, status_code=409)


def _persistence_error() -> EosUnifiedCoaError:
    return EosUnifiedCoaError(
        "EOS_COA_PERSISTENCE_FAILED",
        "Unified COA persistence is unavailable",
        status_code=503,
    )
