from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker


@dataclass(frozen=True)
class AgentIdentityRepositoryError(Exception):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class ResolvedIaIdentity:
    identity: dict[str, Any]
    assignment: dict[str, Any]


class SqlAlchemyAgentIdentityRegistry:
    """Resolve one server-managed, persistent IA for a trusted principal."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        id_factory: Callable[[], str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._id_factory = id_factory or (lambda: str(uuid4()))
        self._clock = clock or (lambda: datetime.now(UTC))

    def resolve_or_provision_ia(
        self,
        *,
        tenant_id: str,
        principal_id: str,
        profile_ref: str,
    ) -> ResolvedIaIdentity:
        _require_text("tenant_id", tenant_id)
        _require_text("principal_id", principal_id)
        _require_text("profile_ref", profile_ref)
        try:
            with self._session_factory() as session:
                existing = _load_resolution(session, tenant_id, principal_id)
                if existing is not None:
                    return _require_active_ia(existing)

                now = self._clock().astimezone(UTC).isoformat().replace("+00:00", "Z")
                candidate_agent_id = self._id_factory()
                assignment_id = self._id_factory()
                session.execute(
                    text(_IDENTITY_INSERT_SQL),
                    {
                        "tenant_id": tenant_id,
                        "agent_id": candidate_agent_id,
                        "profile_ref": profile_ref,
                        "created_at": now,
                    },
                )
                inserted = session.execute(
                    text(_ASSIGNMENT_INSERT_SQL),
                    {
                        "assignment_id": assignment_id,
                        "tenant_id": tenant_id,
                        "principal_id": principal_id,
                        "agent_id": candidate_agent_id,
                        "created_at": now,
                    },
                )
                if int(inserted.rowcount or 0) == 0:
                    session.execute(
                        text(
                            """
                            DELETE FROM ae_agent_identity
                            WHERE tenant_id = :tenant_id AND agent_id = :agent_id
                            """
                        ),
                        {"tenant_id": tenant_id, "agent_id": candidate_agent_id},
                    )

                resolved = _load_resolution(session, tenant_id, principal_id)
                if resolved is None:
                    raise AgentIdentityRepositoryError(
                        "ae.ia_assignment_write_conflict",
                        "IA assignment could not be reloaded after provisioning.",
                        True,
                    )
                session.commit()
                return _require_active_ia(resolved)
        except AgentIdentityRepositoryError:
            raise
        except SQLAlchemyError as exc:
            raise AgentIdentityRepositoryError(
                "ae.agent_identity_store_unavailable",
                "AE agent identity store is unavailable.",
                True,
            ) from exc

    def resolve_ia(
        self,
        *,
        tenant_id: str,
        principal_id: str,
    ) -> ResolvedIaIdentity | None:
        _require_text("tenant_id", tenant_id)
        _require_text("principal_id", principal_id)
        try:
            with self._session_factory() as session:
                resolved = _load_resolution(session, tenant_id, principal_id)
                return None if resolved is None else _require_active_ia(resolved)
        except AgentIdentityRepositoryError:
            raise
        except SQLAlchemyError as exc:
            raise AgentIdentityRepositoryError(
                "ae.agent_identity_store_unavailable",
                "AE agent identity store is unavailable.",
                True,
            ) from exc

    def register_agent(
        self,
        *,
        tenant_id: str,
        agent_type: str,
        profile_ref: str,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        _require_text("tenant_id", tenant_id)
        _require_text("profile_ref", profile_ref)
        if agent_type not in {"CA", "PA", "EA"}:
            raise AgentIdentityRepositoryError(
                "ae.agent_identity_input_invalid",
                "Background agent_type must be CA, PA, or EA.",
            )
        if agent_type == "PA":
            _require_text("project_id", project_id or "")
        elif project_id is not None:
            _require_text("project_id", project_id)
        agent_id = self._id_factory()
        now = self._clock().astimezone(UTC).isoformat().replace("+00:00", "Z")
        try:
            with self._session_factory() as session:
                session.execute(
                    text(_BACKGROUND_IDENTITY_INSERT_SQL),
                    {
                        "tenant_id": tenant_id,
                        "agent_id": agent_id,
                        "agent_type": agent_type,
                        "profile_ref": profile_ref,
                        "project_id": project_id,
                        "created_at": now,
                    },
                )
                saved = _load_identity(session, tenant_id, agent_id)
                if saved is None:
                    raise AgentIdentityRepositoryError(
                        "ae.agent_identity_write_conflict",
                        "AgentIdentity could not be reloaded after registration.",
                        True,
                    )
                session.commit()
                return saved
        except AgentIdentityRepositoryError:
            raise
        except IntegrityError as exc:
            raise AgentIdentityRepositoryError(
                "ae.active_pa_conflict",
                "An active PA already exists for the tenant and project.",
            ) from exc
        except SQLAlchemyError as exc:
            raise AgentIdentityRepositoryError(
                "ae.agent_identity_store_unavailable",
                "AE agent identity store is unavailable.",
                True,
            ) from exc

    def get_agent(self, *, tenant_id: str, agent_id: str) -> dict[str, Any] | None:
        _require_text("tenant_id", tenant_id)
        _require_text("agent_id", agent_id)
        try:
            with self._session_factory() as session:
                return _load_identity(session, tenant_id, agent_id)
        except SQLAlchemyError as exc:
            raise AgentIdentityRepositoryError(
                "ae.agent_identity_store_unavailable",
                "AE agent identity store is unavailable.",
                True,
            ) from exc

    def list_eligible_agents(
        self,
        *,
        tenant_id: str,
        agent_type: str | None = None,
        status: str | None = "ACTIVE",
        project_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        _require_text("tenant_id", tenant_id)
        if agent_type is not None and agent_type not in {"CA", "PA", "EA"}:
            raise AgentIdentityRepositoryError(
                "ae.agent_identity_input_invalid", "agent_type filter is invalid."
            )
        if status is not None and status not in {"ACTIVE", "SUSPENDED", "RETIRED"}:
            raise AgentIdentityRepositoryError(
                "ae.agent_identity_input_invalid", "status filter is invalid."
            )
        if project_id is not None:
            _require_text("project_id", project_id)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise AgentIdentityRepositoryError(
                "ae.agent_identity_input_invalid", "limit must be between 1 and 500."
            )
        clauses = ["tenant_id = :tenant_id", "agent_type IN ('CA', 'PA', 'EA')"]
        params: dict[str, Any] = {"tenant_id": tenant_id, "limit": limit}
        if agent_type is not None:
            clauses.append("agent_type = :agent_type")
            params["agent_type"] = agent_type
        if status is not None:
            clauses.append("status = :status")
            params["status"] = status
        if project_id is not None:
            clauses.append("project_id = :project_id")
            params["project_id"] = project_id
        query = f"""
            SELECT {_IDENTITY_COLUMNS}
            FROM ae_agent_identity
            WHERE {' AND '.join(clauses)}
            ORDER BY created_at ASC, agent_id ASC
            LIMIT :limit
        """
        try:
            with self._session_factory() as session:
                rows = session.execute(text(query), params).mappings().all()
                return [_identity_from_row(row) for row in rows]
        except SQLAlchemyError as exc:
            raise AgentIdentityRepositoryError(
                "ae.agent_identity_store_unavailable",
                "AE agent identity store is unavailable.",
                True,
            ) from exc

    def set_agent_status(
        self,
        *,
        tenant_id: str,
        agent_id: str,
        status: str,
        expected_version: int,
    ) -> dict[str, Any]:
        _require_text("tenant_id", tenant_id)
        _require_text("agent_id", agent_id)
        if status not in {"ACTIVE", "SUSPENDED", "RETIRED"}:
            raise AgentIdentityRepositoryError(
                "ae.agent_identity_input_invalid", "AgentIdentity status is invalid."
            )
        if (
            isinstance(expected_version, bool)
            or not isinstance(expected_version, int)
            or expected_version < 1
        ):
            raise AgentIdentityRepositoryError(
                "ae.agent_identity_input_invalid", "expected_version is invalid."
            )
        try:
            with self._session_factory() as session:
                current = _load_identity(session, tenant_id, agent_id)
                if current is None:
                    raise AgentIdentityRepositoryError(
                        "ae.agent_identity_not_found", "AgentIdentity was not found."
                    )
                if current["agent_type"] == "IA":
                    raise AgentIdentityRepositoryError(
                        "ae.agent_identity_managed_by_assignment",
                        "IA status is managed through the principal assignment lifecycle.",
                    )
                updated = session.execute(
                    text(
                        """
                        UPDATE ae_agent_identity
                        SET status = :status, version = version + 1
                        WHERE tenant_id = :tenant_id AND agent_id = :agent_id
                          AND version = :expected_version
                        """
                    ),
                    {
                        "tenant_id": tenant_id,
                        "agent_id": agent_id,
                        "status": status,
                        "expected_version": expected_version,
                    },
                )
                if int(updated.rowcount or 0) != 1:
                    raise AgentIdentityRepositoryError(
                        "ae.agent_identity_version_conflict",
                        "AgentIdentity version does not match expected_version.",
                    )
                saved = _load_identity(session, tenant_id, agent_id)
                assert saved is not None
                session.commit()
                return saved
        except AgentIdentityRepositoryError:
            raise
        except IntegrityError as exc:
            raise AgentIdentityRepositoryError(
                "ae.active_pa_conflict",
                "An active PA already exists for the tenant and project.",
            ) from exc
        except SQLAlchemyError as exc:
            raise AgentIdentityRepositoryError(
                "ae.agent_identity_store_unavailable",
                "AE agent identity store is unavailable.",
                True,
            ) from exc

    def resolve_active_pa(
        self, *, tenant_id: str, project_id: str
    ) -> dict[str, Any] | None:
        matches = self.list_eligible_agents(
            tenant_id=tenant_id,
            agent_type="PA",
            status="ACTIVE",
            project_id=project_id,
            limit=2,
        )
        if len(matches) > 1:
            raise AgentIdentityRepositoryError(
                "ae.active_pa_invariant_broken",
                "More than one active PA exists for the tenant and project.",
            )
        return matches[0] if matches else None


_IDENTITY_INSERT_SQL = """
    INSERT INTO ae_agent_identity (
        tenant_id, agent_id, schema_version, agent_type, profile_ref,
        status, project_id, created_at, version
    ) VALUES (
        :tenant_id, :agent_id, '2.1', 'IA', :profile_ref,
        'ACTIVE', NULL, :created_at, 1
    )
"""


_BACKGROUND_IDENTITY_INSERT_SQL = """
    INSERT INTO ae_agent_identity (
        tenant_id, agent_id, schema_version, agent_type, profile_ref,
        status, project_id, created_at, version
    ) VALUES (
        :tenant_id, :agent_id, '2.1', :agent_type, :profile_ref,
        'ACTIVE', :project_id, :created_at, 1
    )
"""


_IDENTITY_COLUMNS = """
    schema_version, tenant_id, agent_id, agent_type, profile_ref,
    status, project_id, created_at, version
"""


_ASSIGNMENT_INSERT_SQL = """
    INSERT INTO ae_ia_principal_assignment (
        assignment_id, tenant_id, principal_id, agent_id,
        status, created_at, updated_at, version
    ) VALUES (
        :assignment_id, :tenant_id, :principal_id, :agent_id,
        'ACTIVE', :created_at, :created_at, 1
    ) ON CONFLICT (tenant_id, principal_id) DO NOTHING
"""


def _load_resolution(
    session: Session,
    tenant_id: str,
    principal_id: str,
) -> ResolvedIaIdentity | None:
    row = (
        session.execute(
            text(
                """
                SELECT i.schema_version, i.tenant_id, i.agent_id,
                       i.agent_type, i.profile_ref, i.status AS identity_status,
                       i.project_id, i.created_at AS identity_created_at,
                       i.version AS identity_version,
                       a.assignment_id, a.principal_id,
                       a.status AS assignment_status,
                       a.created_at AS assignment_created_at,
                       a.updated_at AS assignment_updated_at,
                       a.version AS assignment_version
                FROM ae_ia_principal_assignment AS a
                JOIN ae_agent_identity AS i
                  ON i.tenant_id = a.tenant_id AND i.agent_id = a.agent_id
                WHERE a.tenant_id = :tenant_id
                  AND a.principal_id = :principal_id
                """
            ),
            {"tenant_id": tenant_id, "principal_id": principal_id},
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    return ResolvedIaIdentity(
        identity={
            "schema_version": row["schema_version"],
            "tenant_id": row["tenant_id"],
            "agent_id": str(row["agent_id"]),
            "agent_type": row["agent_type"],
            "profile_ref": row["profile_ref"],
            "status": row["identity_status"],
            "project_id": row["project_id"],
            "created_at": _datetime_value(row["identity_created_at"]),
            "version": int(row["identity_version"]),
        },
        assignment={
            "assignment_id": str(row["assignment_id"]),
            "tenant_id": row["tenant_id"],
            "principal_id": row["principal_id"],
            "agent_id": str(row["agent_id"]),
            "status": row["assignment_status"],
            "created_at": _datetime_value(row["assignment_created_at"]),
            "updated_at": _datetime_value(row["assignment_updated_at"]),
            "version": int(row["assignment_version"]),
        },
    )


def _load_identity(
    session: Session, tenant_id: str, agent_id: str
) -> dict[str, Any] | None:
    row = (
        session.execute(
            text(
                f"""
                SELECT {_IDENTITY_COLUMNS}
                FROM ae_agent_identity
                WHERE tenant_id = :tenant_id AND agent_id = :agent_id
                """
            ),
            {"tenant_id": tenant_id, "agent_id": agent_id},
        )
        .mappings()
        .first()
    )
    return None if row is None else _identity_from_row(row)


def _identity_from_row(row: Any) -> dict[str, Any]:
    return {
        "schema_version": row["schema_version"],
        "tenant_id": row["tenant_id"],
        "agent_id": str(row["agent_id"]),
        "agent_type": row["agent_type"],
        "profile_ref": row["profile_ref"],
        "status": row["status"],
        "project_id": row["project_id"],
        "created_at": _datetime_value(row["created_at"]),
        "version": int(row["version"]),
    }


def _require_active_ia(resolved: ResolvedIaIdentity) -> ResolvedIaIdentity:
    identity = resolved.identity
    assignment = resolved.assignment
    if assignment["status"] != "ACTIVE":
        raise AgentIdentityRepositoryError(
            "ae.ia_assignment_inactive",
            "The principal IA assignment is not active.",
        )
    if (
        identity["agent_type"] != "IA"
        or identity["status"] != "ACTIVE"
        or identity["project_id"] is not None
    ):
        raise AgentIdentityRepositoryError(
            "ae.ia_identity_ineligible",
            "The assigned agent is not an active project-neutral IA.",
        )
    return resolved


def _require_text(field: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise AgentIdentityRepositoryError(
            "ae.agent_identity_input_invalid",
            f"{field} must be a non-empty string.",
        )


def _datetime_value(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat().replace("+00:00", "Z")
    return str(value)
