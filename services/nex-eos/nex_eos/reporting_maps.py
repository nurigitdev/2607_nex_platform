from __future__ import annotations

import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref
from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    Table,
    UniqueConstraint,
    Uuid,
    select,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .authorization import AuthorizationSource, AuthorizationSubjectDenied
from .business_transactions import EOS_METADATA

FINANCE_REPORT_READ_SCOPE = "finance:report:read"
EOS_COA_REPORTING_RELEASE_STATUSES = frozenset(
    {"DRAFT", "PUBLISHED", "SUPERSEDED"}
)
EOS_COA_REPORTING_MAPPING_STATUSES = frozenset(
    {"MAPPING_PENDING", "RESOLVED", "NOT_APPLICABLE"}
)
EOS_COA_REPORTING_STATEMENT_KINDS = frozenset(
    {"BALANCE_SHEET", "INCOME_STATEMENT", "CASH_FLOW", "EQUITY", "NOTES"}
)

_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_CODE = re.compile(r"^[A-Z][A-Z0-9_.:-]{0,127}$")
_CONCEPT_ID = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:-]{0,255}$")
_REVISION_HASH = re.compile(r"^[0-9a-f]{64}$")

EOS_COA_REPORTING_RELEASE_TABLE = Table(
    "eos_coa_reporting_release",
    EOS_METADATA,
    Column("mapping_release_id", Uuid(as_uuid=False), primary_key=True),
    Column("jurisdiction", String(32), nullable=False),
    Column("taxonomy_name", String(128), nullable=False),
    Column("taxonomy_version", String(64), nullable=False),
    Column("effective_from", Date, nullable=False),
    Column("effective_until", Date, nullable=True),
    Column("source_reference", String(512), nullable=False),
    Column("source_hash", String(71), nullable=False),
    Column("approved_proof_ref", String(71), nullable=False),
    Column("content_hash", String(71), nullable=False),
    Column("status", String(16), nullable=False),
    Column("created_by", String(128), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("published_at", DateTime(timezone=True), nullable=True),
    UniqueConstraint(
        "jurisdiction",
        "taxonomy_name",
        "taxonomy_version",
        name="ux_eos_coa_reporting_release_version",
    ),
    CheckConstraint(
        "status IN ('DRAFT', 'PUBLISHED', 'SUPERSEDED')",
        name="ck_eos_coa_reporting_release_status",
    ),
)
Index(
    "ix_eos_coa_reporting_release_effective",
    EOS_COA_REPORTING_RELEASE_TABLE.c.jurisdiction,
    EOS_COA_REPORTING_RELEASE_TABLE.c.taxonomy_name,
    EOS_COA_REPORTING_RELEASE_TABLE.c.status,
    EOS_COA_REPORTING_RELEASE_TABLE.c.effective_from,
    EOS_COA_REPORTING_RELEASE_TABLE.c.effective_until,
)

EOS_COA_REPORTING_MAP_TABLE = Table(
    "eos_coa_reporting_map",
    EOS_METADATA,
    Column("mapping_release_id", Uuid(as_uuid=False), primary_key=True),
    Column("mapping_rule_id", Uuid(as_uuid=False), primary_key=True),
    Column("entry_id", Uuid(as_uuid=False), nullable=False),
    Column("statement_kind", String(32), nullable=False),
    Column("mapping_status", String(32), nullable=False),
    Column("taxonomy_concept_id", String(256), nullable=True),
    Column("context_json", JSON, nullable=False),
    Column("source_row_hash", String(71), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ("mapping_release_id",),
        ("eos_coa_reporting_release.mapping_release_id",),
        name="fk_eos_coa_reporting_map_release",
    ),
    ForeignKeyConstraint(
        ("entry_id",),
        ("eos_coa_entry.entry_id",),
        name="fk_eos_coa_reporting_map_entry",
    ),
    CheckConstraint(
        "mapping_status IN ('MAPPING_PENDING', 'RESOLVED', 'NOT_APPLICABLE')",
        name="ck_eos_coa_reporting_map_status",
    ),
)
Index(
    "ix_eos_coa_reporting_map_entry",
    EOS_COA_REPORTING_MAP_TABLE.c.entry_id,
    EOS_COA_REPORTING_MAP_TABLE.c.mapping_release_id,
    EOS_COA_REPORTING_MAP_TABLE.c.statement_kind,
)


class EosReportingMapError(RuntimeError):
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
class ReportingMapReleaseInput:
    mapping_release_id: str
    jurisdiction: str
    taxonomy_name: str
    taxonomy_version: str
    effective_from: date
    source_reference: str
    source_hash: str
    approved_proof_ref: str
    content_hash: str
    created_by: str
    effective_until: date | None = None


@dataclass(frozen=True)
class ReportingMapRuleInput:
    mapping_rule_id: str
    entry_id: str
    statement_kind: str
    mapping_status: str
    source_row_hash: str
    taxonomy_concept_id: str | None = None
    context: Mapping[str, Any] | None = None


class SqlAlchemyEosReportingMapRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create_draft(
        self,
        *,
        release: ReportingMapReleaseInput,
        rules: Sequence[ReportingMapRuleInput],
    ) -> dict[str, Any]:
        release_record = _release_record(release)
        rule_records = _rule_records(release_record["mapping_release_id"], rules)
        try:
            with self._session_factory.begin() as session:
                session.execute(
                    EOS_COA_REPORTING_RELEASE_TABLE.insert().values(**release_record)
                )
                session.execute(EOS_COA_REPORTING_MAP_TABLE.insert(), rule_records)
        except IntegrityError as exc:
            raise _conflict("Reporting mapping release conflicts with durable state") from exc
        except SQLAlchemyError as exc:
            raise _unavailable() from exc
        return _release_projection(release_record, rule_records)

    def publish_approved(
        self,
        *,
        mapping_release_id: str,
        source_hash: str,
        approved_proof_ref: str,
        content_hash: str,
    ) -> dict[str, Any]:
        mapping_release_id = _uuid("mapping_release_id", mapping_release_id)
        expected = {
            "source_hash": _hash_ref("source_hash", source_hash),
            "approved_proof_ref": _hash_ref(
                "approved_proof_ref", approved_proof_ref
            ),
            "content_hash": _hash_ref("content_hash", content_hash),
        }
        try:
            with self._session_factory.begin() as session:
                release = (
                    session.execute(
                        select(EOS_COA_REPORTING_RELEASE_TABLE)
                        .where(
                            EOS_COA_REPORTING_RELEASE_TABLE.c.mapping_release_id
                            == mapping_release_id
                        )
                        .with_for_update()
                    )
                    .mappings()
                    .one_or_none()
                )
                if release is None:
                    raise _not_found("Reporting mapping release was not found")
                if any(release[key] != value for key, value in expected.items()):
                    raise _conflict(
                        "Reporting mapping source differs from approved evidence"
                    )
                if release["status"] == "PUBLISHED":
                    return self._read_projection(session, release)
                if release["status"] != "DRAFT":
                    raise _conflict("Reporting mapping release cannot be published")
                published_at = datetime.now(UTC)
                session.execute(
                    EOS_COA_REPORTING_RELEASE_TABLE.update()
                    .where(
                        EOS_COA_REPORTING_RELEASE_TABLE.c.mapping_release_id
                        == mapping_release_id
                    )
                    .values(status="PUBLISHED", published_at=published_at)
                )
                return self._read_projection(
                    session,
                    {**dict(release), "status": "PUBLISHED", "published_at": published_at},
                )
        except EosReportingMapError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def get_mapping(
        self,
        *,
        mapping_release_id: str,
        entry_id: str,
        effective_on: date,
        regulated_export: bool,
    ) -> dict[str, Any]:
        mapping_release_id = _uuid("mapping_release_id", mapping_release_id)
        entry_id = _uuid("entry_id", entry_id)
        effective_on = _date_value("effective_on", effective_on)
        if not isinstance(regulated_export, bool):
            raise _invalid("regulated_export", "must be a boolean")
        try:
            with self._session_factory() as session:
                release = session.execute(
                    select(EOS_COA_REPORTING_RELEASE_TABLE).where(
                        EOS_COA_REPORTING_RELEASE_TABLE.c.mapping_release_id
                        == mapping_release_id,
                        EOS_COA_REPORTING_RELEASE_TABLE.c.status == "PUBLISHED",
                        EOS_COA_REPORTING_RELEASE_TABLE.c.effective_from
                        <= effective_on,
                    )
                ).mappings().one_or_none()
                if (
                    release is None
                    or (
                        release["effective_until"] is not None
                        and release["effective_until"] <= effective_on
                    )
                ):
                    raise _not_found(
                        "Published reporting mapping release is not effective"
                    )
                rules = (
                    session.execute(
                        select(EOS_COA_REPORTING_MAP_TABLE)
                        .where(
                            EOS_COA_REPORTING_MAP_TABLE.c.mapping_release_id
                            == mapping_release_id,
                            EOS_COA_REPORTING_MAP_TABLE.c.entry_id == entry_id,
                        )
                        .order_by(EOS_COA_REPORTING_MAP_TABLE.c.mapping_rule_id)
                    )
                    .mappings()
                    .all()
                )
                if not rules:
                    raise _not_found("Reporting mapping entry was not found")
                if regulated_export and any(
                    rule["mapping_status"] == "MAPPING_PENDING" for rule in rules
                ):
                    raise EosReportingMapError(
                        "EOS_COA_REPORTING_MAPPING_PENDING",
                        "Regulated export requires resolved reporting mappings",
                        status_code=409,
                    )
                projection = _release_projection(release, rules)
                projection.update(
                    {
                        "entry_id": entry_id,
                        "regulated_export_eligible": all(
                            rule["mapping_status"] != "MAPPING_PENDING"
                            for rule in rules
                        ),
                        "evidence_hash": semantic_sha256_hash_ref(
                            {
                                "mapping_release_id": mapping_release_id,
                                "entry_id": entry_id,
                                "content_hash": release["content_hash"],
                                "rules": [_rule_projection(rule) for rule in rules],
                            }
                        ),
                    }
                )
                return projection
        except EosReportingMapError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    @staticmethod
    def _read_projection(
        session: Session, release: Mapping[str, Any]
    ) -> dict[str, Any]:
        rules = (
            session.execute(
                select(EOS_COA_REPORTING_MAP_TABLE)
                .where(
                    EOS_COA_REPORTING_MAP_TABLE.c.mapping_release_id
                    == release["mapping_release_id"]
                )
                .order_by(EOS_COA_REPORTING_MAP_TABLE.c.mapping_rule_id)
            )
            .mappings()
            .all()
        )
        return _release_projection(release, rules)


class EosReportingMapService:
    def __init__(
        self,
        repository: SqlAlchemyEosReportingMapRepository,
        authorization_source: AuthorizationSource,
    ) -> None:
        self._repository = repository
        self._authorization_source = authorization_source

    def get_mapping(
        self,
        *,
        tenant_id: str,
        requester_subject_id: str,
        mapping_release_id: str,
        entry_id: str,
        effective_on: date,
        regulated_export: bool,
    ) -> dict[str, Any]:
        tenant_id = _scoped_id("tenant_id", tenant_id)
        requester_subject_id = _scoped_id(
            "requester_subject_id", requester_subject_id
        )
        self._authorize(tenant_id, requester_subject_id)
        return self._repository.get_mapping(
            mapping_release_id=mapping_release_id,
            entry_id=entry_id,
            effective_on=effective_on,
            regulated_export=regulated_export,
        )

    def _authorize(self, tenant_id: str, subject_id: str) -> None:
        try:
            value = self._authorization_source.effective_authorization(
                tenant_id=tenant_id,
                subject_id=subject_id,
            )
        except AuthorizationSubjectDenied as exc:
            raise _denied() from exc
        except Exception as exc:
            raise EosReportingMapError(
                "EOS_COA_REPORTING_AUTHORITY_UNAVAILABLE",
                "OA reporting authority is unavailable",
                status_code=503,
                retryable=True,
            ) from exc
        if not isinstance(value, Mapping) or value.get("active") is not True:
            raise _denied()
        if value.get("tenant_id") != tenant_id or value.get("subject_id") != subject_id:
            raise _denied()
        scopes = value.get("scopes")
        if isinstance(scopes, (str, bytes)) or not isinstance(scopes, Sequence):
            raise _authority_unavailable()
        if FINANCE_REPORT_READ_SCOPE not in scopes:
            raise _denied()
        revision_hash = value.get("revision_hash")
        if (
            not isinstance(revision_hash, str)
            or _REVISION_HASH.fullmatch(revision_hash) is None
        ):
            raise _authority_unavailable()


def _release_record(value: ReportingMapReleaseInput) -> dict[str, Any]:
    effective_from = _date_value("effective_from", value.effective_from)
    effective_until = (
        None
        if value.effective_until is None
        else _date_value("effective_until", value.effective_until)
    )
    if effective_until is not None and effective_until <= effective_from:
        raise _invalid("effective_until", "must follow effective_from")
    return {
        "mapping_release_id": _uuid(
            "mapping_release_id", value.mapping_release_id
        ),
        "jurisdiction": _code("jurisdiction", value.jurisdiction, 32),
        "taxonomy_name": _text("taxonomy_name", value.taxonomy_name, 128),
        "taxonomy_version": _text(
            "taxonomy_version", value.taxonomy_version, 64
        ),
        "effective_from": effective_from,
        "effective_until": effective_until,
        "source_reference": _text(
            "source_reference", value.source_reference, 512
        ),
        "source_hash": _hash_ref("source_hash", value.source_hash),
        "approved_proof_ref": _hash_ref(
            "approved_proof_ref", value.approved_proof_ref
        ),
        "content_hash": _hash_ref("content_hash", value.content_hash),
        "status": "DRAFT",
        "created_by": _scoped_id("created_by", value.created_by),
        "created_at": datetime.now(UTC),
        "published_at": None,
    }


def _rule_records(
    mapping_release_id: str, values: Sequence[ReportingMapRuleInput]
) -> list[dict[str, Any]]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence) or not values:
        raise _invalid("rules", "must be a non-empty sequence")
    records = [_rule_record(mapping_release_id, value) for value in values]
    identities = [item["mapping_rule_id"] for item in records]
    if len(set(identities)) != len(identities):
        raise _conflict("Reporting mapping rules contain duplicate identities")
    return records


def _rule_record(
    mapping_release_id: str, value: ReportingMapRuleInput
) -> dict[str, Any]:
    if not isinstance(value, ReportingMapRuleInput):
        raise _invalid("rule", "must be a ReportingMapRuleInput")
    status = _choice(
        "mapping_status", value.mapping_status, EOS_COA_REPORTING_MAPPING_STATUSES
    )
    concept = value.taxonomy_concept_id
    if status == "RESOLVED":
        concept = _concept_id(concept)
    elif concept is not None:
        raise _invalid(
            "taxonomy_concept_id", "must be absent unless mapping is RESOLVED"
        )
    context = {} if value.context is None else value.context
    if not isinstance(context, Mapping):
        raise _invalid("context", "must be an object")
    try:
        context_hash = semantic_sha256_hash_ref(dict(context))
    except (TypeError, ValueError) as exc:
        raise _invalid("context", "must be canonical JSON") from exc
    return {
        "mapping_release_id": mapping_release_id,
        "mapping_rule_id": _uuid("mapping_rule_id", value.mapping_rule_id),
        "entry_id": _uuid("entry_id", value.entry_id),
        "statement_kind": _choice(
            "statement_kind", value.statement_kind, EOS_COA_REPORTING_STATEMENT_KINDS
        ),
        "mapping_status": status,
        "taxonomy_concept_id": concept,
        "context_json": {**dict(context), "context_hash": context_hash},
        "source_row_hash": _hash_ref("source_row_hash", value.source_row_hash),
        "created_at": datetime.now(UTC),
    }


def _release_projection(
    release: Mapping[str, Any], rules: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    return {
        "schema_version": "eos_coa_reporting_map.v1",
        "mapping_release_id": release["mapping_release_id"],
        "jurisdiction": release["jurisdiction"],
        "taxonomy_name": release["taxonomy_name"],
        "taxonomy_version": release["taxonomy_version"],
        "effective_from": _wire(release["effective_from"]),
        "effective_until": _wire(release["effective_until"]),
        "status": release["status"],
        "source_reference": release["source_reference"],
        "source_hash": release["source_hash"],
        "approved_proof_ref": release["approved_proof_ref"],
        "content_hash": release["content_hash"],
        "published_at": _wire(release["published_at"]),
        "rules": [_rule_projection(rule) for rule in rules],
    }


def _rule_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "mapping_rule_id": value["mapping_rule_id"],
        "entry_id": value["entry_id"],
        "statement_kind": value["statement_kind"],
        "mapping_status": value["mapping_status"],
        "taxonomy_concept_id": value["taxonomy_concept_id"],
        "context": dict(value["context_json"]),
        "source_row_hash": value["source_row_hash"],
    }


def _wire(value: Any) -> Any:
    if isinstance(value, datetime):
        normalized = value.replace(tzinfo=UTC) if value.tzinfo is None else value
        return normalized.astimezone(UTC).isoformat()
    return value.isoformat() if isinstance(value, date) else value


def _uuid(field: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise _invalid(field, "must be a UUID") from exc


def _scoped_id(field: str, value: object) -> str:
    normalized = str(value).strip() if value is not None else ""
    if _SCOPED_ID.fullmatch(normalized) is None:
        raise _invalid(field, "must be a stable reference")
    return normalized


def _code(field: str, value: object, maximum: int) -> str:
    normalized = str(value).strip().upper() if value is not None else ""
    if len(normalized) > maximum or _CODE.fullmatch(normalized) is None:
        raise _invalid(field, "has invalid code syntax")
    return normalized


def _text(field: str, value: object, maximum: int) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not normalized or len(normalized) > maximum:
        raise _invalid(field, f"must contain 1..{maximum} characters")
    return normalized


def _choice(field: str, value: object, choices: frozenset[str]) -> str:
    normalized = str(value).strip().upper() if value is not None else ""
    if normalized not in choices:
        raise _invalid(field, "has an unsupported value")
    return normalized


def _concept_id(value: object) -> str:
    normalized = str(value).strip() if value is not None else ""
    if _CONCEPT_ID.fullmatch(normalized) is None:
        raise _invalid("taxonomy_concept_id", "has invalid concept syntax")
    return normalized


def _date_value(field: str, value: object) -> date:
    if isinstance(value, datetime) or not isinstance(value, date):
        raise _invalid(field, "must be a date")
    return value


def _hash_ref(field: str, value: object) -> str:
    try:
        return validate_hash_ref(value)
    except (TypeError, ValueError) as exc:
        raise _invalid(field, "must be a SHA-256 hash reference") from exc


def _invalid(field: str, detail: str) -> EosReportingMapError:
    return EosReportingMapError(
        "EOS_COA_REPORTING_INPUT_INVALID",
        f"{field} {detail}",
        status_code=422,
    )


def _not_found(detail: str) -> EosReportingMapError:
    return EosReportingMapError(
        "EOS_COA_REPORTING_NOT_FOUND", detail, status_code=404
    )


def _conflict(detail: str) -> EosReportingMapError:
    return EosReportingMapError(
        "EOS_COA_REPORTING_CONFLICT", detail, status_code=409
    )


def _denied() -> EosReportingMapError:
    return EosReportingMapError(
        "EOS_COA_REPORTING_AUTHORIZATION_DENIED",
        "Fresh finance:report:read authority is required",
        status_code=403,
    )


def _authority_unavailable() -> EosReportingMapError:
    return EosReportingMapError(
        "EOS_COA_REPORTING_AUTHORITY_UNAVAILABLE",
        "OA reporting authority evidence is invalid",
        status_code=503,
        retryable=True,
    )


def _unavailable() -> EosReportingMapError:
    return EosReportingMapError(
        "EOS_COA_REPORTING_PERSISTENCE_UNAVAILABLE",
        "Reporting mapping persistence is unavailable",
        status_code=503,
        retryable=True,
    )
