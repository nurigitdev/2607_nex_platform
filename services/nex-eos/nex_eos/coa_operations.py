from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Protocol

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from .account_catalog import (
    EOS_COMPANY_ACCOUNT_POLICY_TABLE,
    EOS_POSTING_RULE_RELEASE_TABLE,
)
from .accounts import EOS_ACCOUNT_TABLE
from .authorization import AuthorizationSource, AuthorizationSubjectDenied
from .business_transactions import (
    EosBusinessOperationError,
    EosBusinessOperationRequest,
    EosBusinessTransactionCoordinator,
)
from .legal_entities import EOS_LEGAL_ENTITY_TABLE
from .unified_coa import (
    EOS_COA_ACCOUNT_BINDING_TABLE,
    EOS_COA_CODE_IDENTITY_TABLE,
    EOS_COA_COMPANY_ADOPTION_TABLE,
    EOS_COA_DEFINITION_RELEASE_TABLE,
    EOS_COA_ENTRY_TABLE,
)

FINANCE_COA_PUBLISH_SCOPE = "finance:catalog:publish"
FINANCE_COA_ADOPT_SCOPE = "finance:account:manage"
FINANCE_COA_PUBLISH_OPERATION = "FINANCE.COA.PUBLISH_APPROVED"
FINANCE_COA_EXTENSION_PUBLISH_OPERATION = "FINANCE.COA.EXTENSION_PUBLISH_APPROVED"
FINANCE_COA_ADOPT_OPERATION = "FINANCE.COA.ADOPT_APPROVED"

_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_REVISION_HASH = re.compile(r"^[0-9a-f]{64}$")
_IDENTITY_NAMESPACE = uuid.UUID("40b7598c-aa75-4afd-b35a-1da72da32dda")


class EosCoaOperationError(EosBusinessOperationError):
    pass


class CoaPublicationAdmission(Protocol):
    def admit(self, command: CoaPublicationCommand) -> None: ...


@dataclass(frozen=True)
class CoaPublicationCommand:
    definition_release_id: str
    source_reference: str
    source_hash: str
    approved_proof_ref: str
    content_hash: str
    published_by: str


@dataclass(frozen=True)
class CoaBindingCommand:
    binding_id: str
    entry_id: str
    account_id: str
    approved_proof_ref: str


@dataclass(frozen=True)
class CoaAdoptionCommand:
    tenant_id: str
    adoption_id: str
    company_id: str
    global_release_id: str
    effective_from: date
    approved_proof_ref: str
    created_by: str
    bindings: tuple[CoaBindingCommand, ...]
    extension_release_id: str | None = None
    effective_until: date | None = None


class PinnedCoaPublicationAdmission:
    def __init__(self, records: Sequence[Mapping[str, Any]]) -> None:
        self._records = tuple(_admission_record(item) for item in records)

    def admit(self, command: CoaPublicationCommand) -> None:
        candidate = {
            "source_reference": command.source_reference,
            "source_hash": command.source_hash,
            "approved_proof_ref": command.approved_proof_ref,
            "content_hash": command.content_hash,
        }
        if candidate not in self._records:
            raise EosCoaOperationError(
                "EOS_COA_SOURCE_NOT_APPROVED",
                "COA source admission does not match an immutable approved record",
                status_code=409,
            )

    @classmethod
    def from_json(cls, raw: str) -> PinnedCoaPublicationAdmission:
        try:
            value = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise EosCoaOperationError(
                "EOS_COA_ADMISSION_CONFIG_INVALID",
                "COA publication admission configuration is invalid",
                status_code=503,
                retryable=True,
            ) from exc
        if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
            raise EosCoaOperationError(
                "EOS_COA_ADMISSION_CONFIG_INVALID",
                "COA publication admission configuration must be an array",
                status_code=503,
                retryable=True,
            )
        return cls(value)


class SqlAlchemyEosCoaOperationsRepository:
    @staticmethod
    def publish_release(
        session: Session | None,
        command: CoaPublicationCommand,
    ) -> dict[str, Any]:
        session = _required_session(session)
        release = (
            session.execute(
                select(EOS_COA_DEFINITION_RELEASE_TABLE)
                .where(
                    EOS_COA_DEFINITION_RELEASE_TABLE.c.definition_release_id
                    == command.definition_release_id
                )
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        if release is None:
            raise _not_found("COA definition release was not found")
        _require_release_semantics(release, command)
        if release["scope_type"] != "GLOBAL":
            raise _conflict("Product publication requires a GLOBAL release")
        entries = (
            session.execute(
                select(EOS_COA_ENTRY_TABLE)
                .where(
                    EOS_COA_ENTRY_TABLE.c.definition_release_id
                    == command.definition_release_id
                )
                .order_by(EOS_COA_ENTRY_TABLE.c.account_code)
            )
            .mappings()
            .all()
        )
        if not entries:
            raise _conflict("COA release has no entries")
        if release["status"] == "PUBLISHED":
            return _publication_result(release, len(entries), replayed=True)
        if release["status"] != "DRAFT":
            raise _conflict("COA release cannot be published from its current state")

        for entry in entries:
            _admit_code_identity(session, release=release, entry=entry)
        published_at = datetime.now(UTC)
        session.execute(
            EOS_COA_DEFINITION_RELEASE_TABLE.update()
            .where(
                EOS_COA_DEFINITION_RELEASE_TABLE.c.definition_release_id
                == command.definition_release_id
            )
            .values(status="PUBLISHED", published_at=published_at)
        )
        published = {**dict(release), "status": "PUBLISHED", "published_at": published_at}
        return _publication_result(published, len(entries), replayed=False)

    @staticmethod
    def adopt_release(
        session: Session | None,
        command: CoaAdoptionCommand,
    ) -> dict[str, Any]:
        session = _required_session(session)
        adoption_record = _adoption_record(command)
        binding_records = _binding_records(command)
        existing = (
            session.execute(
                select(EOS_COA_COMPANY_ADOPTION_TABLE)
                .where(
                    EOS_COA_COMPANY_ADOPTION_TABLE.c.tenant_id == command.tenant_id,
                    EOS_COA_COMPANY_ADOPTION_TABLE.c.adoption_id
                    == command.adoption_id,
                )
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        if existing is not None:
            return _adoption_replay(
                session,
                existing=existing,
                expected=adoption_record,
                bindings=binding_records,
            )
        company = (
            session.execute(
                select(EOS_LEGAL_ENTITY_TABLE)
                .where(
                    EOS_LEGAL_ENTITY_TABLE.c.tenant_id == command.tenant_id,
                    EOS_LEGAL_ENTITY_TABLE.c.company_id == command.company_id,
                )
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        if company is None:
            raise _not_found("LegalEntity was not found in tenant scope")
        if (
            company["status"] != "ACTIVE"
            or company["effective_from"] > command.effective_from
        ):
            raise _conflict("LegalEntity is not active and effective")
        _published_release(
            session,
            command.global_release_id,
            effective_on=command.effective_from,
            scope_type="GLOBAL",
            owner_tenant_id=None,
        )
        if command.extension_release_id is not None:
            extension = _published_release(
                session,
                command.extension_release_id,
                effective_on=command.effective_from,
                scope_type="TENANT",
                owner_tenant_id=command.tenant_id,
            )
            if extension["base_global_release_id"] != command.global_release_id:
                raise _conflict("Tenant extension does not derive from GLOBAL release")
        session.execute(
            EOS_COA_COMPANY_ADOPTION_TABLE.insert().values(**adoption_record)
        )
        for binding in binding_records:
            _require_effective_binding(
                session,
                command=command,
                binding=binding,
            )
            session.execute(EOS_COA_ACCOUNT_BINDING_TABLE.insert().values(**binding))
        return _adoption_result(adoption_record, binding_records, replayed=False)

    @staticmethod
    def publish_extension(
        session: Session | None,
        *,
        tenant_id: str,
        command: CoaPublicationCommand,
    ) -> dict[str, Any]:
        session = _required_session(session)
        release = (
            session.execute(
                select(EOS_COA_DEFINITION_RELEASE_TABLE)
                .where(
                    EOS_COA_DEFINITION_RELEASE_TABLE.c.definition_release_id
                    == command.definition_release_id
                )
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        if release is None:
            raise _not_found("COA tenant extension release was not found")
        _require_release_semantics(release, command)
        if release["scope_type"] != "TENANT" or release["owner_tenant_id"] != tenant_id:
            raise _denied(FINANCE_COA_ADOPT_SCOPE)
        base = _published_release(
            session,
            release["base_global_release_id"],
            effective_on=release["effective_from"],
            scope_type="GLOBAL",
            owner_tenant_id=None,
        )
        if base["chart_profile"] != release["chart_profile"]:
            raise _conflict("Tenant extension chart profile differs from its GLOBAL base")
        entries = (
            session.execute(
                select(EOS_COA_ENTRY_TABLE)
                .where(
                    EOS_COA_ENTRY_TABLE.c.definition_release_id
                    == command.definition_release_id
                )
                .order_by(EOS_COA_ENTRY_TABLE.c.account_code)
            )
            .mappings()
            .all()
        )
        if not entries:
            raise _conflict("COA tenant extension release has no entries")
        if release["status"] == "PUBLISHED":
            return _publication_result(release, len(entries), replayed=True)
        if release["status"] != "DRAFT":
            raise _conflict("COA tenant extension cannot be published from its state")
        for entry in entries:
            _require_tenant_extension_entry(
                session,
                tenant_id=tenant_id,
                release=release,
                base=base,
                entry=entry,
            )
            _admit_code_identity(session, release=release, entry=entry)
        published_at = datetime.now(UTC)
        session.execute(
            EOS_COA_DEFINITION_RELEASE_TABLE.update()
            .where(
                EOS_COA_DEFINITION_RELEASE_TABLE.c.definition_release_id
                == command.definition_release_id
            )
            .values(status="PUBLISHED", published_at=published_at)
        )
        published = {**dict(release), "status": "PUBLISHED", "published_at": published_at}
        return _publication_result(published, len(entries), replayed=False)


class EosCoaOperationsService:
    def __init__(
        self,
        *,
        repository: SqlAlchemyEosCoaOperationsRepository,
        coordinator: EosBusinessTransactionCoordinator,
        authorization_source: AuthorizationSource,
        publication_admission: CoaPublicationAdmission,
    ) -> None:
        self._repository = repository
        self._coordinator = coordinator
        self._authorization_source = authorization_source
        self._publication_admission = publication_admission

    def publish_approved(
        self,
        *,
        actor_tenant_id: str,
        requester_subject_id: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        actor_tenant_id = _scoped_id("actor_tenant_id", actor_tenant_id)
        requester_subject_id = _scoped_id(
            "requester_subject_id", requester_subject_id
        )
        self._authorize(
            tenant_id=actor_tenant_id,
            subject_id=requester_subject_id,
            required_scope=FINANCE_COA_PUBLISH_SCOPE,
        )
        command = _publication_command(payload, published_by=requester_subject_id)
        self._publication_admission.admit(command)
        request = _business_request(
            tenant_id=actor_tenant_id,
            payload=payload,
            operation=FINANCE_COA_PUBLISH_OPERATION,
        )
        result = self._coordinator.execute(
            request,
            lambda session: self._repository.publish_release(session, command),
        )
        return result.to_public_projection()

    def adopt_approved(
        self,
        *,
        tenant_id: str,
        requester_subject_id: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        tenant_id = _scoped_id("tenant_id", tenant_id)
        requester_subject_id = _scoped_id(
            "requester_subject_id", requester_subject_id
        )
        self._authorize(
            tenant_id=tenant_id,
            subject_id=requester_subject_id,
            required_scope=FINANCE_COA_ADOPT_SCOPE,
        )
        command = _adoption_command(
            payload,
            tenant_id=tenant_id,
            created_by=requester_subject_id,
        )
        request = _business_request(
            tenant_id=tenant_id,
            payload=payload,
            operation=FINANCE_COA_ADOPT_OPERATION,
        )
        result = self._coordinator.execute(
            request,
            lambda session: self._repository.adopt_release(session, command),
        )
        return result.to_public_projection()

    def publish_extension_approved(
        self,
        *,
        tenant_id: str,
        requester_subject_id: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        tenant_id = _scoped_id("tenant_id", tenant_id)
        requester_subject_id = _scoped_id(
            "requester_subject_id", requester_subject_id
        )
        self._authorize(
            tenant_id=tenant_id,
            subject_id=requester_subject_id,
            required_scope=FINANCE_COA_ADOPT_SCOPE,
        )
        command = _publication_command(payload, published_by=requester_subject_id)
        request = _business_request(
            tenant_id=tenant_id,
            payload=payload,
            operation=FINANCE_COA_EXTENSION_PUBLISH_OPERATION,
        )
        result = self._coordinator.execute(
            request,
            lambda session: self._repository.publish_extension(
                session,
                tenant_id=tenant_id,
                command=command,
            ),
        )
        return result.to_public_projection()

    def _authorize(
        self, *, tenant_id: str, subject_id: str, required_scope: str
    ) -> None:
        try:
            value = self._authorization_source.effective_authorization(
                tenant_id=tenant_id,
                subject_id=subject_id,
            )
        except AuthorizationSubjectDenied as exc:
            raise _denied(required_scope) from exc
        except Exception as exc:
            raise EosCoaOperationError(
                "EOS_COA_AUTHORITY_UNAVAILABLE",
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


def _admission_record(value: Mapping[str, Any]) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise EosCoaOperationError(
            "EOS_COA_ADMISSION_CONFIG_INVALID",
            "COA admission record must be an object",
            status_code=503,
            retryable=True,
        )
    return {
        "source_reference": _text(
            "source_reference", value.get("source_reference"), 512
        ),
        "source_hash": _hash_ref("source_hash", value.get("source_hash")),
        "approved_proof_ref": _hash_ref(
            "approved_proof_ref", value.get("approved_proof_ref")
        ),
        "content_hash": _hash_ref("content_hash", value.get("content_hash")),
    }


def _publication_command(
    payload: Mapping[str, Any], *, published_by: str
) -> CoaPublicationCommand:
    return CoaPublicationCommand(
        definition_release_id=_uuid(
            "definition_release_id", payload.get("definition_release_id")
        ),
        source_reference=_text(
            "source_reference", payload.get("source_reference"), 512
        ),
        source_hash=_hash_ref("source_hash", payload.get("source_hash")),
        approved_proof_ref=_hash_ref(
            "approved_proof_ref", payload.get("approved_proof_ref")
        ),
        content_hash=_hash_ref("content_hash", payload.get("content_hash")),
        published_by=published_by,
    )


def _adoption_command(
    payload: Mapping[str, Any], *, tenant_id: str, created_by: str
) -> CoaAdoptionCommand:
    raw_bindings = payload.get("bindings")
    if isinstance(raw_bindings, (str, bytes)) or not isinstance(
        raw_bindings, Sequence
    ):
        raise _invalid("bindings", "must be a non-empty array")
    bindings = tuple(
        CoaBindingCommand(
            binding_id=_uuid("binding_id", _object(item).get("binding_id")),
            entry_id=_uuid("entry_id", _object(item).get("entry_id")),
            account_id=_uuid("account_id", _object(item).get("account_id")),
            approved_proof_ref=_hash_ref(
                "binding.approved_proof_ref",
                _object(item).get("approved_proof_ref"),
            ),
        )
        for item in raw_bindings
    )
    if not bindings:
        raise _invalid("bindings", "must be a non-empty array")
    effective_from = _date_input("effective_from", payload.get("effective_from"))
    effective_until = _optional_date_input(
        "effective_until", payload.get("effective_until")
    )
    if effective_until is not None and effective_until <= effective_from:
        raise _invalid("effective_until", "must follow effective_from")
    return CoaAdoptionCommand(
        tenant_id=tenant_id,
        adoption_id=_uuid("adoption_id", payload.get("adoption_id")),
        company_id=_uuid("company_id", payload.get("company_id")),
        global_release_id=_uuid(
            "global_release_id", payload.get("global_release_id")
        ),
        extension_release_id=_optional_uuid(
            "extension_release_id", payload.get("extension_release_id")
        ),
        effective_from=effective_from,
        effective_until=effective_until,
        approved_proof_ref=_hash_ref(
            "approved_proof_ref", payload.get("approved_proof_ref")
        ),
        created_by=created_by,
        bindings=bindings,
    )


def _business_request(
    *, tenant_id: str, payload: Mapping[str, Any], operation: str
) -> EosBusinessOperationRequest:
    business_operation_id = _uuid(
        "business_operation_id", payload.get("business_operation_id")
    )
    idempotency_key = _text(
        "idempotency_key", payload.get("idempotency_key"), 256
    )
    business_payload = {
        key: value
        for key, value in payload.items()
        if key not in {"business_operation_id", "idempotency_key"}
    }
    return EosBusinessOperationRequest(
        tenant_id=tenant_id,
        business_operation_id=business_operation_id,
        idempotency_key=idempotency_key,
        operation=operation,
        payload_hash=semantic_sha256_hash_ref(business_payload),
    )


def _required_session(session: Session | None) -> Session:
    if session is None:
        raise EosCoaOperationError(
            "EOS_COA_TRANSACTION_REQUIRED",
            "COA mutation requires the durable EOS transaction coordinator",
            status_code=503,
            retryable=True,
        )
    return session


def _require_release_semantics(
    release: Mapping[str, Any], command: CoaPublicationCommand
) -> None:
    expected = {
        "source_reference": command.source_reference,
        "source_hash": command.source_hash,
        "approved_proof_ref": command.approved_proof_ref,
        "content_hash": command.content_hash,
    }
    if any(release[key] != value for key, value in expected.items()):
        raise EosCoaOperationError(
            "EOS_COA_CATALOG_HASH_MISMATCH",
            "COA release differs from the approved publication command",
            status_code=409,
        )


def _admit_code_identity(
    session: Session,
    *,
    release: Mapping[str, Any],
    entry: Mapping[str, Any],
) -> None:
    table = EOS_COA_CODE_IDENTITY_TABLE
    owner_predicate = (
        table.c.owner_tenant_id.is_(None)
        if release["owner_tenant_id"] is None
        else table.c.owner_tenant_id == release["owner_tenant_id"]
    )
    identities = (
        session.execute(
            select(table)
            .where(
                table.c.scope_type == release["scope_type"],
                owner_predicate,
                table.c.chart_profile == release["chart_profile"],
                or_(
                    table.c.account_code == entry["account_code"],
                    table.c.semantic_key == entry["semantic_key"],
                ),
            )
            .with_for_update()
        )
        .mappings()
        .all()
    )
    if identities:
        if len(identities) != 1 or any(
            identities[0][key] != entry[key]
            for key in ("account_code", "semantic_key")
        ):
            raise EosCoaOperationError(
                "EOS_COA_CODE_SEMANTIC_CONFLICT",
                "COA code or semantic identity was previously assigned differently",
                status_code=409,
            )
        return
    identity_key = ":".join(
        (
            release["scope_type"],
            release["owner_tenant_id"] or "GLOBAL",
            release["chart_profile"],
            entry["account_code"],
        )
    )
    session.execute(
        table.insert().values(
            identity_id=str(uuid.uuid5(_IDENTITY_NAMESPACE, identity_key)),
            scope_type=release["scope_type"],
            owner_tenant_id=release["owner_tenant_id"],
            chart_profile=release["chart_profile"],
            account_code=entry["account_code"],
            semantic_key=entry["semantic_key"],
            first_release_id=release["definition_release_id"],
            state="ACTIVE",
            created_at=datetime.now(UTC),
        )
    )


def _published_release(
    session: Session,
    release_id: str,
    *,
    effective_on: date,
    scope_type: str,
    owner_tenant_id: str | None,
) -> Mapping[str, Any]:
    release = (
        session.execute(
            select(EOS_COA_DEFINITION_RELEASE_TABLE)
            .where(
                EOS_COA_DEFINITION_RELEASE_TABLE.c.definition_release_id
                == release_id
            )
            .with_for_update()
        )
        .mappings()
        .one_or_none()
    )
    if release is None:
        raise _not_found("COA definition release was not found")
    if (
        release["status"] != "PUBLISHED"
        or release["effective_from"] > effective_on
        or release["scope_type"] != scope_type
        or release["owner_tenant_id"] != owner_tenant_id
    ):
        raise _conflict("COA release is not published and effective in scope")
    return release


def _require_tenant_extension_entry(
    session: Session,
    *,
    tenant_id: str,
    release: Mapping[str, Any],
    base: Mapping[str, Any],
    entry: Mapping[str, Any],
) -> None:
    suffix = int(entry["account_code"][-3:])
    if (
        entry["scope_type"] != "TENANT"
        or entry["owner_tenant_id"] != tenant_id
        or entry["hierarchy_level"] != 4
        or not 800 <= suffix <= 999
    ):
        raise _conflict("COA tenant extension entry is outside its governed namespace")
    parent = (
        session.execute(
            select(EOS_COA_ENTRY_TABLE).where(
                EOS_COA_ENTRY_TABLE.c.entry_id == entry["parent_entry_id"]
            )
        )
        .mappings()
        .one_or_none()
    )
    if (
        parent is None
        or parent["definition_release_id"] != base["definition_release_id"]
        or parent["hierarchy_level"] != 3
        or parent["category"] != entry["category"]
        or parent["account_code"] != entry["account_code"][:5] + "000"
        or parent["is_postable"]
    ):
        raise _conflict("COA tenant extension requires a valid GLOBAL family parent")
    collision = session.execute(
        select(EOS_ACCOUNT_TABLE.c.account_id)
        .where(
            EOS_ACCOUNT_TABLE.c.tenant_id == tenant_id,
            EOS_ACCOUNT_TABLE.c.account_code == entry["account_code"],
        )
        .limit(1)
    ).scalar_one_or_none()
    if collision is not None:
        raise _conflict("COA tenant extension collides with an existing Account code")


def _require_effective_binding(
    session: Session,
    *,
    command: CoaAdoptionCommand,
    binding: Mapping[str, Any],
) -> None:
    entry = (
        session.execute(
            select(EOS_COA_ENTRY_TABLE).where(
                EOS_COA_ENTRY_TABLE.c.entry_id == binding["entry_id"]
            )
        )
        .mappings()
        .one_or_none()
    )
    allowed_releases = {command.global_release_id, command.extension_release_id}
    if entry is None or entry["definition_release_id"] not in allowed_releases:
        raise _conflict("COA binding entry is outside the adopted releases")
    if entry["scope_type"] == "TENANT" and entry["owner_tenant_id"] != command.tenant_id:
        raise _denied(FINANCE_COA_ADOPT_SCOPE)
    account = (
        session.execute(
            select(EOS_ACCOUNT_TABLE).where(
                EOS_ACCOUNT_TABLE.c.tenant_id == command.tenant_id,
                EOS_ACCOUNT_TABLE.c.account_id == binding["account_id"],
            )
        )
        .mappings()
        .one_or_none()
    )
    if account is None:
        raise _not_found("Tenant Account was not found for COA binding")
    if (
        account["status"] != "ACTIVE"
        or account["effective_from"] > command.effective_from
        or (
            account["effective_until"] is not None
            and account["effective_until"] <= command.effective_from
        )
    ):
        raise _conflict("Tenant Account is not active and effective")
    policy = EOS_COMPANY_ACCOUNT_POLICY_TABLE
    rule = EOS_POSTING_RULE_RELEASE_TABLE
    effective_policy = session.execute(
        select(policy.c.policy_id)
        .select_from(
            policy.join(
                rule,
                and_(
                    policy.c.tenant_id == rule.c.tenant_id,
                    policy.c.posting_rule_id == rule.c.posting_rule_id,
                ),
            )
        )
        .where(
            policy.c.tenant_id == command.tenant_id,
            policy.c.company_id == command.company_id,
            policy.c.account_id == binding["account_id"],
            policy.c.state == "APPROVED",
            policy.c.valid_from <= command.effective_from,
            or_(
                policy.c.valid_until.is_(None),
                policy.c.valid_until > command.effective_from,
            ),
            rule.c.company_id == command.company_id,
            rule.c.status == "PUBLISHED",
            rule.c.effective_date <= command.effective_from,
        )
        .limit(1)
    ).scalar_one_or_none()
    if effective_policy is None:
        raise _conflict("COA binding requires effective Account policy and PostingRule")


def _adoption_record(command: CoaAdoptionCommand) -> dict[str, Any]:
    return {
        "tenant_id": command.tenant_id,
        "adoption_id": command.adoption_id,
        "company_id": command.company_id,
        "global_release_id": command.global_release_id,
        "extension_release_id": command.extension_release_id,
        "effective_from": command.effective_from,
        "effective_until": command.effective_until,
        "approved_proof_ref": command.approved_proof_ref,
        "state": "APPROVED",
        "created_by": command.created_by,
        "created_at": datetime.now(UTC),
    }


def _binding_records(command: CoaAdoptionCommand) -> list[dict[str, Any]]:
    records = [
        {
            "tenant_id": command.tenant_id,
            "binding_id": item.binding_id,
            "adoption_id": command.adoption_id,
            "entry_id": item.entry_id,
            "account_id": item.account_id,
            "approved_proof_ref": item.approved_proof_ref,
            "created_at": datetime.now(UTC),
        }
        for item in command.bindings
    ]
    if len({item["entry_id"] for item in records}) != len(records) or len(
        {item["account_id"] for item in records}
    ) != len(records):
        raise _conflict("COA adoption bindings contain duplicate identities")
    return records


def _adoption_replay(
    session: Session,
    *,
    existing: Mapping[str, Any],
    expected: Mapping[str, Any],
    bindings: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    _same_semantics(existing, expected, ignored={"created_at"})
    existing_bindings = (
        session.execute(
            select(EOS_COA_ACCOUNT_BINDING_TABLE)
            .where(
                EOS_COA_ACCOUNT_BINDING_TABLE.c.tenant_id == existing["tenant_id"],
                EOS_COA_ACCOUNT_BINDING_TABLE.c.adoption_id == existing["adoption_id"],
            )
            .order_by(EOS_COA_ACCOUNT_BINDING_TABLE.c.entry_id)
        )
        .mappings()
        .all()
    )
    expected_bindings = sorted(bindings, key=lambda item: item["entry_id"])
    if len(existing_bindings) != len(expected_bindings):
        raise _conflict("COA adoption replay has a different binding count")
    for current, target in zip(existing_bindings, expected_bindings, strict=True):
        _same_semantics(current, target, ignored={"created_at"})
    return _adoption_result(existing, existing_bindings, replayed=True)


def _publication_result(
    release: Mapping[str, Any], entry_count: int, *, replayed: bool
) -> dict[str, Any]:
    return {
        "definition_release_id": release["definition_release_id"],
        "scope_type": release["scope_type"],
        "status": release["status"],
        "entry_count": entry_count,
        "content_hash": release["content_hash"],
        "published_at": _wire(release["published_at"]),
        "replayed": replayed,
    }


def _adoption_result(
    adoption: Mapping[str, Any],
    bindings: Sequence[Mapping[str, Any]],
    *,
    replayed: bool,
) -> dict[str, Any]:
    return {
        "tenant_id": adoption["tenant_id"],
        "adoption_id": adoption["adoption_id"],
        "company_id": adoption["company_id"],
        "global_release_id": adoption["global_release_id"],
        "extension_release_id": adoption["extension_release_id"],
        "effective_from": _wire(adoption["effective_from"]),
        "effective_until": _wire(adoption["effective_until"]),
        "state": adoption["state"],
        "binding_count": len(bindings),
        "replayed": replayed,
    }


def _same_semantics(
    existing: Mapping[str, Any], expected: Mapping[str, Any], *, ignored: set[str]
) -> None:
    if any(
        existing[key] != value
        for key, value in expected.items()
        if key not in ignored
    ):
        raise _conflict("COA operation identity has different semantics")


def _admit_authorization(
    value: object, *, tenant_id: str, subject_id: str, required_scope: str
) -> None:
    if not isinstance(value, Mapping) or value.get("active") is not True:
        raise _denied(required_scope)
    if value.get("tenant_id") != tenant_id or value.get("subject_id") != subject_id:
        raise _denied(required_scope)
    scopes = value.get("scopes")
    if isinstance(scopes, (str, bytes)) or not isinstance(scopes, Sequence):
        raise _authority_unavailable()
    if any(not isinstance(item, str) or not item for item in scopes):
        raise _authority_unavailable()
    if required_scope not in scopes:
        raise _denied(required_scope)
    revision_hash = value.get("revision_hash")
    if not isinstance(revision_hash, str) or _REVISION_HASH.fullmatch(revision_hash) is None:
        raise _authority_unavailable()


def _wire(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _object(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid("binding", "must be an object")
    return value


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


def _text(field: str, value: object, maximum: int) -> str:
    normalized = str(value).strip() if value is not None else ""
    if not normalized or len(normalized) > maximum:
        raise _invalid(field, f"must contain 1..{maximum} characters")
    return normalized


def _hash_ref(field: str, value: object) -> str:
    try:
        return validate_hash_ref(value)
    except (TypeError, ValueError) as exc:
        raise _invalid(field, "must be a SHA-256 hash reference") from exc


def _date_input(field: str, value: object) -> date:
    try:
        parsed = date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise _invalid(field, "must be an ISO date") from exc
    return parsed


def _optional_date_input(field: str, value: object) -> date | None:
    return None if value is None else _date_input(field, value)


def _invalid(field: str, detail: str) -> EosCoaOperationError:
    return EosCoaOperationError(
        "EOS_COA_INVALID", f"{field} {detail}", status_code=422
    )


def _conflict(detail: str) -> EosCoaOperationError:
    return EosCoaOperationError("EOS_COA_CONFLICT", detail, status_code=409)


def _not_found(detail: str) -> EosCoaOperationError:
    return EosCoaOperationError("EOS_COA_NOT_FOUND", detail, status_code=404)


def _denied(required_scope: str) -> EosCoaOperationError:
    return EosCoaOperationError(
        "EOS_COA_AUTHORIZATION_DENIED",
        f"Fresh OA authority is required for {required_scope}",
        status_code=403,
    )


def _authority_unavailable() -> EosCoaOperationError:
    return EosCoaOperationError(
        "EOS_COA_AUTHORITY_UNAVAILABLE",
        "OA effective authorization evidence is malformed or unavailable",
        status_code=503,
        retryable=True,
    )
