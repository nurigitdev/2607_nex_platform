from __future__ import annotations

import re
import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .authorization import AuthorizationSource, AuthorizationSubjectDenied
from .reporting_maps import EOS_COA_REPORTING_MAP_TABLE
from .unified_coa import (
    EOS_COA_COMPANY_ADOPTION_TABLE,
    EOS_COA_DEFINITION_RELEASE_TABLE,
    EOS_COA_ENTRY_TABLE,
)

FINANCE_COA_ADMIN_SCOPE = "finance:catalog:publish"
_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_REVISION_HASH = re.compile(r"^[0-9a-f]{64}$")
_DIFF_FIELDS = (
    "semantic_key",
    "account_name",
    "parent_account_code",
    "hierarchy_level",
    "category",
    "account_type",
    "normal_balance",
    "is_contra",
    "is_postable",
    "is_monetary_default",
    "reporting_mapping_status",
    "source_lineage",
    "source_row_hash",
)


class EosCoaReleaseAdminError(RuntimeError):
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


class SqlAlchemyEosCoaReleaseAdminRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def preview_diff(
        self, *, base_release_id: str, target_release_id: str
    ) -> dict[str, Any]:
        base_release_id = _uuid("base_release_id", base_release_id)
        target_release_id = _uuid("target_release_id", target_release_id)
        if base_release_id == target_release_id:
            raise _invalid("Release diff requires two distinct releases")
        try:
            with self._session_factory() as session:
                releases = (
                    session.execute(
                        select(EOS_COA_DEFINITION_RELEASE_TABLE).where(
                            EOS_COA_DEFINITION_RELEASE_TABLE.c.definition_release_id.in_(
                                (base_release_id, target_release_id)
                            )
                        )
                    )
                    .mappings()
                    .all()
                )
                by_id = {
                    item["definition_release_id"]: item for item in releases
                }
                if base_release_id not in by_id or target_release_id not in by_id:
                    raise _not_found()
                base = by_id[base_release_id]
                target = by_id[target_release_id]
                _require_compatible(base, target)
                base_entries = _entries(session, base_release_id)
                target_entries = _entries(session, target_release_id)
                return _diff_projection(base, target, base_entries, target_entries)
        except EosCoaReleaseAdminError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable() from exc

    def operations_snapshot(self) -> dict[str, Any]:
        try:
            with self._session_factory() as session:
                releases = session.execute(
                    select(EOS_COA_DEFINITION_RELEASE_TABLE.c.status)
                ).scalars().all()
                entries = session.execute(
                    select(EOS_COA_ENTRY_TABLE.c.entry_id)
                ).scalars().all()
                adoptions = session.execute(
                    select(EOS_COA_COMPANY_ADOPTION_TABLE.c.state)
                ).scalars().all()
                mappings = session.execute(
                    select(EOS_COA_REPORTING_MAP_TABLE.c.mapping_status)
                ).scalars().all()
        except SQLAlchemyError as exc:
            raise _unavailable() from exc
        counts = {
            "releases": _counts(releases),
            "entries": len(entries),
            "adoptions": _counts(adoptions),
            "reporting_mappings": _counts(mappings),
        }
        return {
            "schema_version": "eos_coa_release_operations.v1",
            "generated_at": datetime.now(UTC).isoformat(),
            "counts": counts,
            "readiness": {
                "regulated_reporting": (
                    "BLOCKED_MAPPING_PENDING"
                    if counts["reporting_mappings"].get("MAPPING_PENDING", 0)
                    else "NO_PENDING_MAPPINGS"
                )
            },
            "evidence_hash": semantic_sha256_hash_ref(counts),
        }


class EosCoaReleaseAdminService:
    def __init__(
        self,
        repository: SqlAlchemyEosCoaReleaseAdminRepository,
        authorization_source: AuthorizationSource,
    ) -> None:
        self._repository = repository
        self._authorization_source = authorization_source

    def preview_diff(
        self,
        *,
        actor_tenant_id: str,
        requester_subject_id: str,
        base_release_id: str,
        target_release_id: str,
    ) -> dict[str, Any]:
        self._authorize(actor_tenant_id, requester_subject_id)
        return self._repository.preview_diff(
            base_release_id=base_release_id,
            target_release_id=target_release_id,
        )

    def operations_snapshot(
        self, *, actor_tenant_id: str, requester_subject_id: str
    ) -> dict[str, Any]:
        self._authorize(actor_tenant_id, requester_subject_id)
        return self._repository.operations_snapshot()

    def _authorize(self, tenant_id: str, subject_id: str) -> None:
        tenant_id = _scoped_id("actor_tenant_id", tenant_id)
        subject_id = _scoped_id("requester_subject_id", subject_id)
        try:
            value = self._authorization_source.effective_authorization(
                tenant_id=tenant_id,
                subject_id=subject_id,
            )
        except AuthorizationSubjectDenied as exc:
            raise _denied() from exc
        except Exception as exc:
            raise _authority_unavailable() from exc
        if not isinstance(value, Mapping) or value.get("active") is not True:
            raise _denied()
        if value.get("tenant_id") != tenant_id or value.get("subject_id") != subject_id:
            raise _denied()
        scopes = value.get("scopes")
        if isinstance(scopes, (str, bytes)) or not isinstance(scopes, Sequence):
            raise _authority_unavailable()
        if FINANCE_COA_ADMIN_SCOPE not in scopes:
            raise _denied()
        revision_hash = value.get("revision_hash")
        if (
            not isinstance(revision_hash, str)
            or _REVISION_HASH.fullmatch(revision_hash) is None
        ):
            raise _authority_unavailable()


def _entries(session: Session, release_id: str) -> list[Mapping[str, Any]]:
    return list(
        session.execute(
            select(EOS_COA_ENTRY_TABLE)
            .where(EOS_COA_ENTRY_TABLE.c.definition_release_id == release_id)
            .order_by(EOS_COA_ENTRY_TABLE.c.account_code)
        )
        .mappings()
        .all()
    )


def _require_compatible(base: Mapping[str, Any], target: Mapping[str, Any]) -> None:
    identity = ("scope_type", "owner_tenant_id", "chart_profile")
    if any(base[field] != target[field] for field in identity):
        raise _conflict("COA releases do not share a comparable scope and profile")
    if target["effective_from"] <= base["effective_from"]:
        raise _conflict("Target COA release must become effective after the base")


def _entry_map(entries: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    parent_codes = {
        item["entry_id"]: item["account_code"] for item in entries
    }
    return {
        item["account_code"]: {
            **dict(item),
            "parent_account_code": parent_codes.get(item["parent_entry_id"]),
        }
        for item in entries
    }


def _diff_projection(
    base: Mapping[str, Any],
    target: Mapping[str, Any],
    base_entries: Sequence[Mapping[str, Any]],
    target_entries: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    base_map = _entry_map(base_entries)
    target_map = _entry_map(target_entries)
    added = sorted(set(target_map) - set(base_map))
    removed = sorted(set(base_map) - set(target_map))
    changed = []
    for account_code in sorted(set(base_map) & set(target_map)):
        changed_fields = [
            field
            for field in _DIFF_FIELDS
            if base_map[account_code][field] != target_map[account_code][field]
        ]
        if changed_fields:
            changed.append(
                {
                    "account_code": account_code,
                    "base_semantic_key": base_map[account_code]["semantic_key"],
                    "target_semantic_key": target_map[account_code]["semantic_key"],
                    "changed_fields": changed_fields,
                }
            )
    summary = {
        "added": len(added),
        "removed": len(removed),
        "changed": len(changed),
        "unchanged": len(set(base_map) & set(target_map)) - len(changed),
    }
    evidence = {
        "base_release_id": base["definition_release_id"],
        "base_content_hash": base["content_hash"],
        "target_release_id": target["definition_release_id"],
        "target_content_hash": target["content_hash"],
        "summary": summary,
        "added_account_codes": added,
        "removed_account_codes": removed,
        "changed": changed,
    }
    return {
        "schema_version": "eos_coa_release_diff.v1",
        **evidence,
        "base_release_version": base["release_version"],
        "target_release_version": target["release_version"],
        "evidence_hash": semantic_sha256_hash_ref(evidence),
    }


def _counts(values: Sequence[str]) -> dict[str, int]:
    return dict(sorted(Counter(values).items()))


def _uuid(field: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise _invalid(f"{field} must be a UUID") from exc


def _scoped_id(field: str, value: object) -> str:
    normalized = str(value).strip() if value is not None else ""
    if _SCOPED_ID.fullmatch(normalized) is None:
        raise _invalid(f"{field} must be a stable reference")
    return normalized


def _invalid(detail: str) -> EosCoaReleaseAdminError:
    return EosCoaReleaseAdminError(
        "EOS_COA_ADMIN_INPUT_INVALID", detail, status_code=422
    )


def _not_found() -> EosCoaReleaseAdminError:
    return EosCoaReleaseAdminError(
        "EOS_COA_ADMIN_RELEASE_NOT_FOUND",
        "COA release was not found",
        status_code=404,
    )


def _conflict(detail: str) -> EosCoaReleaseAdminError:
    return EosCoaReleaseAdminError(
        "EOS_COA_ADMIN_RELEASE_CONFLICT", detail, status_code=409
    )


def _denied() -> EosCoaReleaseAdminError:
    return EosCoaReleaseAdminError(
        "EOS_COA_ADMIN_AUTHORIZATION_DENIED",
        "Fresh finance:catalog:publish authority is required",
        status_code=403,
    )


def _authority_unavailable() -> EosCoaReleaseAdminError:
    return EosCoaReleaseAdminError(
        "EOS_COA_ADMIN_AUTHORITY_UNAVAILABLE",
        "OA administrative authority is unavailable or invalid",
        status_code=503,
        retryable=True,
    )


def _unavailable() -> EosCoaReleaseAdminError:
    return EosCoaReleaseAdminError(
        "EOS_COA_ADMIN_PERSISTENCE_UNAVAILABLE",
        "COA release administration persistence is unavailable",
        status_code=503,
        retryable=True,
    )
