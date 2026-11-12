from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from nex_runtime.semantic_hashes import canonical_json, semantic_sha256_hash_ref
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    or_,
    select,
    update,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .approval_policies import (
    EOS_APPROVAL_POLICY_STAGE_TABLE,
    EOS_APPROVAL_POLICY_TABLE,
)
from .authorization import AuthorizationSource, AuthorizationSubjectDenied
from .business_formal_wc import WcApprovalWorkItemClient
from .business_transactions import EOS_METADATA
from .project_applications import (
    EOS_PROJECT_APP_REVISION_TABLE,
    EOS_PROJECT_APPLICATION_TABLE,
    EosProjectApplicationError,
    SqlAlchemyEosProjectApplicationRepository,
)
from .project_lifecycle_events import append_project_lifecycle_event
from .project_memberships import (
    ProjectMembershipInput,
    SqlAlchemyEosProjectMembershipRepository,
    deterministic_project_membership_id,
)
from .projects import ProjectInput, SqlAlchemyEosProjectRepository

PROJECT_APPLICATION_APPROVAL_SCOPE = "project:application:request-approval"
PROJECT_APPLICATION_APPROVAL_OPERATION = "PROJECT.APPLICATION.REQUEST_APPROVAL"
PROJECT_APPLICATION_APPROVAL_TRANSACTION_TYPE = "PROJECT_APPLICATION"
PROJECT_APPLICATION_APPROVAL_RESUME_PREFIX = "eos.project-application:"

_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$")
_REQUEST_CODE = re.compile(r"^[A-Z0-9]{4}R[0-9]{6}$")
_HASH_REF = re.compile(r"^sha256:[0-9a-f]{64}$")
_AGENT_PREFIXES = ("agent:", "job:", "service:")


EOS_PROJECT_APP_APPROVAL_TABLE = Table(
    "eos_project_app_approval",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("application_id", Uuid(as_uuid=False), primary_key=True),
    Column("approval_policy_id", Uuid(as_uuid=False), nullable=False),
    Column("policy_version", Integer, nullable=False),
    Column("policy_hash", String(71), nullable=False),
    Column("approval_hash", String(71), nullable=False),
    Column("requester_subject_id", String(128), nullable=False),
    Column("state", String(16), nullable=False),
    Column("active_stage_order", Integer, nullable=True),
    Column("stage_count", Integer, nullable=False),
    Column("target_role_ref", String(32), nullable=True),
    Column("version", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("decided_at", DateTime(timezone=True), nullable=True),
    ForeignKeyConstraint(
        ("tenant_id", "application_id"),
        (
            "eos_project_application.tenant_id",
            "eos_project_application.application_id",
        ),
        name="fk_eos_project_app_approval_application",
    ),
    ForeignKeyConstraint(
        ("tenant_id", "approval_policy_id"),
        ("eos_approval_policy.tenant_id", "eos_approval_policy.approval_policy_id"),
        name="fk_eos_project_app_approval_policy",
    ),
    CheckConstraint(
        "state IN ('PENDING', 'APPROVED', 'REJECTED')",
        name="ck_eos_project_app_approval_state",
    ),
    CheckConstraint(
        "stage_count BETWEEN 1 AND 5",
        name="ck_eos_project_app_approval_stage_count",
    ),
    CheckConstraint("version > 0", name="ck_eos_project_app_approval_version"),
)

EOS_PROJECT_APP_DECISION_TABLE = Table(
    "eos_project_app_decision",
    EOS_METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("application_id", Uuid(as_uuid=False), primary_key=True),
    Column("stage_order", Integer, primary_key=True),
    Column("wc_work_item_id", Uuid(as_uuid=False), nullable=False),
    Column("wc_decision_id", Uuid(as_uuid=False), nullable=False),
    Column("wc_event_id", Uuid(as_uuid=False), nullable=False),
    Column("wc_outbox_id", Uuid(as_uuid=False), nullable=False),
    Column("decision", String(16), nullable=False),
    Column("decision_version", Integer, nullable=False),
    Column("decided_by", String(128), nullable=False),
    Column("decision_comment", Text, nullable=True),
    Column("wc_oa_decision_ref", String(128), nullable=False),
    Column("wc_authorization_revision_hash", String(71), nullable=False),
    Column("oa_decision_ref", String(128), nullable=False),
    Column("authorization_revision_hash", String(71), nullable=False),
    Column("authorization_checked_at", DateTime(timezone=True), nullable=False),
    Column("decided_at", DateTime(timezone=True), nullable=False),
    Column("decision_hash", String(71), nullable=False),
    Column("recorded_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ("tenant_id", "application_id"),
        (
            "eos_project_app_approval.tenant_id",
            "eos_project_app_approval.application_id",
        ),
        name="fk_eos_project_app_decision_approval",
    ),
    UniqueConstraint(
        "tenant_id", "wc_work_item_id", name="ux_eos_project_app_decision_work_item"
    ),
    UniqueConstraint(
        "tenant_id", "wc_decision_id", name="ux_eos_project_app_decision_decision"
    ),
    UniqueConstraint(
        "tenant_id", "wc_event_id", name="ux_eos_project_app_decision_event"
    ),
    UniqueConstraint(
        "tenant_id", "decision_hash", name="ux_eos_project_app_decision_hash"
    ),
    CheckConstraint(
        "decision IN ('APPROVE', 'REJECT')",
        name="ck_eos_project_app_decision_action",
    ),
    CheckConstraint(
        "stage_order BETWEEN 1 AND 5",
        name="ck_eos_project_app_decision_stage",
    ),
    CheckConstraint("decision_version = 1", name="ck_eos_project_app_decision_version"),
)


class EosProjectApplicationApprovalError(RuntimeError):
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


class EosProjectApplicationApprovalService:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        authorization_source: AuthorizationSource,
        wc_client: WcApprovalWorkItemClient,
        project_agent_profile_policy_ref: str,
        clock=None,
    ) -> None:
        self._session_factory = session_factory
        self._authorization_source = authorization_source
        self._wc_client = wc_client
        self._project_agent_profile_policy_ref = _text(
            "project_agent_profile_policy_ref", project_agent_profile_policy_ref, 256
        )
        self._applications = SqlAlchemyEosProjectApplicationRepository(session_factory)
        self._projects = SqlAlchemyEosProjectRepository(session_factory)
        self._memberships = SqlAlchemyEosProjectMembershipRepository(session_factory)
        self._clock = clock or (lambda: datetime.now(UTC))

    def request_approval(
        self,
        *,
        tenant_id: str,
        project_request_code: str,
        approval_policy_id: str,
        expected_version: int,
        requester_subject_id: str,
    ) -> dict[str, Any]:
        tenant = _tenant_id(tenant_id)
        request_code = _request_code(project_request_code)
        policy_id = _uuid("approval_policy_id", approval_policy_id)
        requester = _scoped_id("requester_subject_id", requester_subject_id)
        expected = _positive_int("expected_version", expected_version)
        authorization = self._authorize(
            tenant_id=tenant,
            subject_id=requester,
            required_scope=PROJECT_APPLICATION_APPROVAL_SCOPE,
        )
        now = _aware_datetime("clock", self._clock())
        try:
            with self._session_factory.begin() as session:
                application = _load_application_by_code(
                    session,
                    tenant_id=tenant,
                    request_code=request_code,
                    for_update=True,
                )
                if application is None:
                    raise _not_found("Project application was not found")
                if application["applicant_subject_id"] != requester:
                    raise _denied("Only the Project applicant may request approval")
                if application["state"] != "SUBMITTED":
                    raise _conflict(
                        "Only a SUBMITTED Project application can request approval"
                    )
                if int(application["version"]) != expected:
                    raise _conflict("Project application version changed concurrently")
                existing = _load_approval(
                    session,
                    tenant_id=tenant,
                    application_id=str(application["application_id"]),
                    for_update=True,
                )
                if existing is not None:
                    if (
                        str(existing["approval_policy_id"]) != policy_id
                        or existing["requester_subject_id"] != requester
                    ):
                        raise _conflict(
                            "Approval request replay changed immutable semantics"
                        )
                    state = _load_state(session, application, existing)
                else:
                    policy, stages = _load_policy(session, tenant, policy_id)
                    _require_project_application_policy(policy, stages, now)
                    revision = _load_current_revision(session, application)
                    approval_hash = semantic_sha256_hash_ref(
                        {
                            "schema_version": "eos_project_application_approval.v1",
                            "tenant_id": tenant,
                            "application_id": str(application["application_id"]),
                            "project_request_code": request_code,
                            "application_revision": application["current_revision"],
                            "application_request_hash": revision["request_hash"],
                            "approval_policy_id": policy_id,
                            "policy_version": policy["version"],
                            "policy_hash": policy["policy_hash"],
                            "stages": [
                                {
                                    "stage_order": stage["stage_order"],
                                    "position_type": stage["position_type"],
                                    "quorum_count": stage["quorum_count"],
                                    "separation_policy": stage["separation_policy"],
                                }
                                for stage in stages
                            ],
                            "requester_subject_id": requester,
                            "authorization_revision_hash": _authorization_revision(
                                authorization
                            ),
                        }
                    )
                    record = {
                        "tenant_id": tenant,
                        "application_id": str(application["application_id"]),
                        "approval_policy_id": policy_id,
                        "policy_version": policy["version"],
                        "policy_hash": policy["policy_hash"],
                        "approval_hash": approval_hash,
                        "requester_subject_id": requester,
                        "state": "PENDING",
                        "active_stage_order": 1,
                        "stage_count": len(stages),
                        "target_role_ref": stages[0]["position_type"],
                        "version": 1,
                        "created_at": now,
                        "updated_at": now,
                        "decided_at": None,
                    }
                    session.execute(
                        EOS_PROJECT_APP_APPROVAL_TABLE.insert().values(**record)
                    )
                    state = _load_state(session, application, record)
        except EosProjectApplicationApprovalError:
            raise
        except IntegrityError as exc:
            raise _conflict(
                "Project application approval changed concurrently"
            ) from exc
        except SQLAlchemyError as exc:
            raise _unavailable(
                "Project application approval persistence is unavailable"
            ) from exc
        return self._receipt(state, created=existing is None)

    def ingest_wc_delivery(self, delivery: Mapping[str, Any]) -> dict[str, Any]:
        admitted = _admit_delivery(delivery)
        replay = self._load_replay(admitted)
        if replay is not None:
            return self._receipt(replay, created=False, admitted=admitted)
        authorization = self._authorize(
            tenant_id=admitted["tenant_id"],
            subject_id=admitted["decided_by"],
            required_scope="approval:decide",
        )
        recorded_at = _aware_datetime("clock", self._clock())
        try:
            with self._session_factory.begin() as session:
                application = _load_application_by_id(
                    session,
                    tenant_id=admitted["tenant_id"],
                    application_id=admitted["application_id"],
                    for_update=True,
                )
                approval = _load_approval(
                    session,
                    tenant_id=admitted["tenant_id"],
                    application_id=admitted["application_id"],
                    for_update=True,
                )
                if application is None or approval is None:
                    raise _not_found("Project application approval was not found")
                state = _load_state(session, application, approval)
                _require_delivery_boundary(state, admitted)
                _require_approver_authorization(
                    authorization,
                    tenant_id=admitted["tenant_id"],
                    decided_by=admitted["decided_by"],
                    target_role=approval["target_role_ref"],
                )
                if application["applicant_subject_id"] == admitted["decided_by"]:
                    raise _denied(
                        "Project applicant cannot approve the same application"
                    )
                if (
                    admitted["decision"] == "APPROVE"
                    and admitted["stage_order"] == int(approval["stage_count"])
                ):
                    revision = _load_current_revision(session, application)
                    self._require_active_project_parties(
                        tenant_id=admitted["tenant_id"],
                        parties=_project_parties(application, revision["payload"]),
                    )
                existing = _load_decision_by_identity(session, admitted)
                if existing is not None:
                    if existing["decision_hash"] != admitted["decision_hash"]:
                        raise _conflict(
                            "WC decision replay changed immutable semantics"
                        )
                    created = False
                else:
                    decision = _decision_record(
                        admitted, authorization=authorization, recorded_at=recorded_at
                    )
                    session.execute(
                        EOS_PROJECT_APP_DECISION_TABLE.insert().values(**decision)
                    )
                    _advance_approval(
                        session,
                        applications=self._applications,
                        projects=self._projects,
                        memberships=self._memberships,
                        application=application,
                        approval=approval,
                        admitted=admitted,
                        recorded_at=recorded_at,
                        project_agent_profile_policy_ref=(
                            self._project_agent_profile_policy_ref
                        ),
                    )
                    created = True
            state = self._load_current_state(admitted)
        except EosProjectApplicationApprovalError:
            raise
        except (EosProjectApplicationError, IntegrityError) as exc:
            raise _conflict(
                "Project application approval changed concurrently"
            ) from exc
        except SQLAlchemyError as exc:
            raise _unavailable(
                "Project application approval persistence is unavailable"
            ) from exc
        return self._receipt(state, created=created, admitted=admitted)

    def _authorize(
        self, *, tenant_id: str, subject_id: str, required_scope: str
    ) -> Mapping[str, Any]:
        try:
            value = self._authorization_source.effective_authorization(
                tenant_id=tenant_id, subject_id=subject_id
            )
        except AuthorizationSubjectDenied as exc:
            raise _denied("OA denied Project application approval authority") from exc
        except Exception as exc:
            raise _unavailable(
                "OA Project application authority is unavailable"
            ) from exc
        if not isinstance(value, Mapping):
            raise _denied("OA Project application authority is malformed")
        scopes = value.get("scopes")
        if (
            value.get("active") is not True
            or value.get("tenant_id") != tenant_id
            or value.get("subject_id") != subject_id
            or not isinstance(scopes, (list, tuple, set, frozenset))
            or required_scope not in scopes
        ):
            raise _denied("OA denied Project application approval authority")
        _authorization_revision(value)
        return dict(value)

    def _require_active_project_parties(
        self,
        *,
        tenant_id: str,
        parties: tuple[tuple[str, str], ...],
    ) -> None:
        for subject_id, _member_role in parties:
            try:
                value = self._authorization_source.effective_authorization(
                    tenant_id=tenant_id,
                    subject_id=subject_id,
                )
            except AuthorizationSubjectDenied as exc:
                raise _denied(
                    "OA denied an inactive or unknown Project party"
                ) from exc
            except Exception as exc:
                raise _unavailable(
                    "OA Project party validation is unavailable"
                ) from exc
            if (
                not isinstance(value, Mapping)
                or value.get("active") is not True
                or value.get("tenant_id") != tenant_id
                or value.get("subject_id") != subject_id
            ):
                raise _denied(
                    "OA denied an inactive, unknown, or cross-tenant Project party"
                )

    def _load_replay(self, admitted: Mapping[str, Any]) -> dict[str, Any] | None:
        try:
            with self._session_factory() as session:
                existing = _load_decision_by_identity(session, admitted)
                if existing is None:
                    return None
                if existing["decision_hash"] != admitted["decision_hash"]:
                    raise _conflict("WC decision replay changed immutable semantics")
                application = _load_application_by_id(
                    session,
                    tenant_id=admitted["tenant_id"],
                    application_id=admitted["application_id"],
                )
                approval = _load_approval(
                    session,
                    tenant_id=admitted["tenant_id"],
                    application_id=admitted["application_id"],
                )
                if application is None or approval is None:
                    raise _not_found("Project application approval was not found")
                return _load_state(session, application, approval)
        except EosProjectApplicationApprovalError:
            raise
        except SQLAlchemyError as exc:
            raise _unavailable(
                "Project application approval persistence is unavailable"
            ) from exc

    def _load_current_state(self, admitted: Mapping[str, Any]) -> dict[str, Any]:
        with self._session_factory() as session:
            application = _load_application_by_id(
                session,
                tenant_id=admitted["tenant_id"],
                application_id=admitted["application_id"],
            )
            approval = _load_approval(
                session,
                tenant_id=admitted["tenant_id"],
                application_id=admitted["application_id"],
            )
            if application is None or approval is None:
                raise _not_found("Project application approval was not found")
            return _load_state(session, application, approval)

    def _receipt(
        self,
        state: Mapping[str, Any],
        *,
        created: bool,
        admitted: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        approval = state["approval"]
        publication = None
        if approval["state"] == "PENDING":
            expected = project_application_approval_work_item(state)
            try:
                publication = self._wc_client.create_or_get(expected)
            except Exception as exc:
                raise _unavailable(
                    "WC Project committee publication is unavailable"
                ) from exc
            _require_wc_publication(publication, expected)
        application = state["application"]
        return {
            "schema_version": "eos_project_application_approval_receipt.v1",
            "created": created,
            "approval_domain": "BUSINESS_FORMAL",
            "project_request_code": application["project_request_code"],
            "application_state": application["state"],
            "approval_state": approval["state"],
            "active_stage_order": approval["active_stage_order"],
            "stage_count": approval["stage_count"],
            "approved_project_code": application["approved_project_code"],
            "wc_outbox_id": admitted["wc_outbox_id"] if admitted else None,
            "wc_event_id": admitted["wc_event_id"] if admitted else None,
            "wc_publication": publication,
        }


def is_project_application_approval_delivery(payload: Mapping[str, Any]) -> bool:
    work_item = payload.get("work_item")
    if not isinstance(work_item, Mapping):
        return False
    target = work_item.get("resume_target_ref")
    return isinstance(target, str) and target.startswith(
        PROJECT_APPLICATION_APPROVAL_RESUME_PREFIX
    )


def project_application_approval_work_item(state: Mapping[str, Any]) -> dict[str, Any]:
    application = state["application"]
    approval = state["approval"]
    stage = approval["active_stage_order"]
    if approval["state"] != "PENDING" or stage is None:
        raise _conflict("Project application approval has no publishable stage")
    source_ref = (
        f"{PROJECT_APPLICATION_APPROVAL_RESUME_PREFIX}{application['application_id']}:"
        f"stage:{stage}"
    )
    semantic = {
        "schema_version": "eos_project_application_wc_binding.v1",
        "tenant_id": application["tenant_id"],
        "application_id": str(application["application_id"]),
        "project_request_code": application["project_request_code"],
        "application_revision": application["current_revision"],
        "application_request_hash": state["revision"]["request_hash"],
        "approval_hash": approval["approval_hash"],
        "approval_policy_id": str(approval["approval_policy_id"]),
        "policy_hash": approval["policy_hash"],
        "active_stage_order": stage,
        "stage_count": approval["stage_count"],
        "target_role_ref": approval["target_role_ref"],
        "requester_subject_id": approval["requester_subject_id"],
    }
    summary = canonical_json(
        {
            "project_request_code": application["project_request_code"],
            "name": state["revision"]["payload"]["name"],
            "purpose_type": application["purpose_type"],
            "stage_order": stage,
            "stage_count": approval["stage_count"],
        }
    )
    return {
        "schema_version": "wc_approval_work_item.v1",
        "tenant_id": application["tenant_id"],
        "approval_work_item_id": str(
            uuid5(
                NAMESPACE_URL,
                "https://nex-platform.local/wc/project-application/"
                f"{application['tenant_id']}/{application['application_id']}/{stage}",
            )
        ),
        "approval_domain": "BUSINESS_FORMAL",
        "source_ref": source_ref,
        "semantic_hash": semantic_sha256_hash_ref(semantic),
        "title": f"Approve Project application: {application['project_request_code']}",
        "display_safe_summary": summary,
        "approval_provider_type": "EOS",
        "approval_target_ref": (
            f"eos.project-application:{application['project_request_code']}"
        ),
        "target_approver_ref": None,
        "target_role_ref": approval["target_role_ref"],
        "target_org_scope_ref": None,
        "target_project_scope_ref": None,
        "agent_execution_id": None,
        "executable_step_id": None,
        "nsl_execution_id": None,
        "business_operation_id": str(application["application_id"]),
        "approval_request_id": str(application["application_id"]),
        "protected_request_ref": application["project_request_code"],
        "resume_target_ref": source_ref,
        "state": "PENDING",
        "created_at": _timestamp(approval["updated_at"]),
        "expires_at": None,
        "version": approval["version"],
    }


def _advance_approval(
    session: Session,
    *,
    applications: SqlAlchemyEosProjectApplicationRepository,
    projects: SqlAlchemyEosProjectRepository,
    memberships: SqlAlchemyEosProjectMembershipRepository,
    application: Mapping[str, Any],
    approval: Mapping[str, Any],
    admitted: Mapping[str, Any],
    recorded_at: datetime,
    project_agent_profile_policy_ref: str,
) -> None:
    if admitted["decision"] == "REJECT":
        _update_approval_terminal(
            session, approval, state="REJECTED", decided_at=admitted["decided_at"]
        )
        _update_application_terminal(
            session,
            application,
            state="REJECTED",
            decided_at=admitted["decided_at"],
        )
        return
    if admitted["stage_order"] < int(approval["stage_count"]):
        next_stage = admitted["stage_order"] + 1
        next_role = session.execute(
            select(EOS_APPROVAL_POLICY_STAGE_TABLE.c.position_type).where(
                EOS_APPROVAL_POLICY_STAGE_TABLE.c.tenant_id == approval["tenant_id"],
                EOS_APPROVAL_POLICY_STAGE_TABLE.c.approval_policy_id
                == approval["approval_policy_id"],
                EOS_APPROVAL_POLICY_STAGE_TABLE.c.stage_order == next_stage,
            )
        ).scalar_one_or_none()
        if next_role is None:
            raise _conflict("Project committee next stage is unavailable")
        result = session.execute(
            update(EOS_PROJECT_APP_APPROVAL_TABLE)
            .where(
                EOS_PROJECT_APP_APPROVAL_TABLE.c.tenant_id == approval["tenant_id"],
                EOS_PROJECT_APP_APPROVAL_TABLE.c.application_id
                == approval["application_id"],
                EOS_PROJECT_APP_APPROVAL_TABLE.c.state == "PENDING",
                EOS_PROJECT_APP_APPROVAL_TABLE.c.version == approval["version"],
            )
            .values(
                active_stage_order=next_stage,
                target_role_ref=next_role,
                version=int(approval["version"]) + 1,
                updated_at=recorded_at,
            )
        )
        if result.rowcount != 1:
            raise _conflict("Project committee stage changed concurrently")
        return

    revision = _load_current_revision(session, application)
    project_parties = _project_parties(application, revision["payload"])
    project_code = applications.allocate_registration_code_in_session(
        session,
        tenant_id=application["tenant_id"],
        purpose_type=application["purpose_type"],
        issued_at=recorded_at,
    )
    project_id = str(uuid5(uuid.UUID(str(application["application_id"])), "project"))
    decision_hashes = list(
        session.execute(
            select(EOS_PROJECT_APP_DECISION_TABLE.c.decision_hash)
            .where(
                EOS_PROJECT_APP_DECISION_TABLE.c.tenant_id == application["tenant_id"],
                EOS_PROJECT_APP_DECISION_TABLE.c.application_id
                == application["application_id"],
            )
            .order_by(EOS_PROJECT_APP_DECISION_TABLE.c.stage_order)
        ).scalars()
    )
    evidence_hash = semantic_sha256_hash_ref(
        {
            "schema_version": "eos_project_application_approval_evidence.v1",
            "tenant_id": application["tenant_id"],
            "application_id": str(application["application_id"]),
            "project_request_code": application["project_request_code"],
            "approval_hash": approval["approval_hash"],
            "decision_hashes": decision_hashes,
            "approved_project_code": project_code,
        }
    )
    payload = revision["payload"]
    projects.create_project_in_session(
        session,
        ProjectInput(
            tenant_id=application["tenant_id"],
            project_id=project_id,
            project_code=project_code,
            name=payload["name"],
            parent_project_id=payload.get("parent_project_id"),
            nvt_project_id=payload.get("nvt_project_id"),
            status="ACTIVE",
            start_date=_payload_date("start_date", payload.get("start_date")),
            end_date=_payload_date("end_date", payload.get("end_date")),
            currency=payload["currency"],
            project_request_code=application["project_request_code"],
            purpose_type=application["purpose_type"],
            origin="APPROVED_APPLICATION",
            approval_evidence_ref=(
                f"eos.project-application-approval:{application['project_request_code']}"
            ),
            approval_evidence_hash=evidence_hash,
            project_owner_subject_id=application["project_owner_subject_id"],
            project_manager_subject_id=application["project_manager_subject_id"],
            agent_sync_state="PENDING",
        ),
    )
    for subject_id, member_role in project_parties:
        memberships.add_membership_in_session(
            session,
            ProjectMembershipInput(
                application["tenant_id"],
                deterministic_project_membership_id(
                    application["tenant_id"], project_id, subject_id
                ),
                project_id,
                subject_id,
                member_role,
                admitted["decided_by"],
                valid_from=recorded_at,
            ),
        )
    append_project_lifecycle_event(
        session,
        tenant_id=application["tenant_id"],
        project_id=project_id,
        project_code=project_code,
        previous_state="SUBMITTED",
        current_state="ACTIVE",
        project_version=1,
        profile_policy_ref=project_agent_profile_policy_ref,
        correlation_id=str(admitted["wc_work_item_id"]),
        causation_id=str(admitted["wc_event_id"]),
        occurred_at=recorded_at,
    )
    _update_approval_terminal(
        session, approval, state="APPROVED", decided_at=admitted["decided_at"]
    )
    _update_application_terminal(
        session,
        application,
        state="APPROVED",
        decided_at=admitted["decided_at"],
        approved_project_id=project_id,
        approved_project_code=project_code,
    )


def _project_parties(
    application: Mapping[str, Any], payload: Mapping[str, Any]
) -> tuple[tuple[str, str], ...]:
    owner = _scoped_id(
        "project_owner_subject_id", application.get("project_owner_subject_id")
    )
    manager = _scoped_id(
        "project_manager_subject_id", application.get("project_manager_subject_id")
    )
    payload_owner = payload.get("project_owner_subject_id")
    payload_manager = payload.get("project_manager_subject_id")
    members = payload.get("initial_members")

    # Historical v1 revisions predate the explicit member list. The migration
    # backfills both parties from the applicant, preserving their old meaning.
    if members is None and payload.get("schema_version") != "eos_project_application_draft.v2":
        legacy = {owner: "OWNER"}
        if manager != owner:
            legacy[manager] = "MANAGER"
        return tuple(sorted(legacy.items()))

    if payload_owner != owner or payload_manager != manager or not isinstance(members, list):
        raise _unavailable("Project application parties are malformed")
    normalized: dict[str, str] = {}
    for item in members:
        if not isinstance(item, Mapping):
            raise _unavailable("Project application parties are malformed")
        subject_id = _scoped_id("initial_members.subject_id", item.get("subject_id"))
        role = str(item.get("member_role", "")).strip().upper()
        if role not in {"OWNER", "MANAGER", "MEMBER", "VIEWER"}:
            raise _unavailable("Project application parties are malformed")
        if subject_id in normalized:
            raise _unavailable("Project application parties are malformed")
        normalized[subject_id] = role
    if normalized.get(owner) != "OWNER":
        raise _unavailable("Project application owner role is malformed")
    if manager != owner and normalized.get(manager) != "MANAGER":
        raise _unavailable("Project application manager role is malformed")
    canonical = tuple(sorted(normalized.items()))
    if [
        {"subject_id": subject_id, "member_role": role}
        for subject_id, role in canonical
    ] != members:
        raise _unavailable("Project application parties are not canonical")
    return canonical


def _update_approval_terminal(
    session: Session,
    approval: Mapping[str, Any],
    *,
    state: str,
    decided_at: datetime,
) -> None:
    result = session.execute(
        update(EOS_PROJECT_APP_APPROVAL_TABLE)
        .where(
            EOS_PROJECT_APP_APPROVAL_TABLE.c.tenant_id == approval["tenant_id"],
            EOS_PROJECT_APP_APPROVAL_TABLE.c.application_id
            == approval["application_id"],
            EOS_PROJECT_APP_APPROVAL_TABLE.c.state == "PENDING",
            EOS_PROJECT_APP_APPROVAL_TABLE.c.version == approval["version"],
        )
        .values(
            state=state,
            active_stage_order=None,
            target_role_ref=None,
            version=int(approval["version"]) + 1,
            updated_at=decided_at,
            decided_at=decided_at,
        )
    )
    if result.rowcount != 1:
        raise _conflict("Project committee decision changed concurrently")


def _update_application_terminal(
    session: Session,
    application: Mapping[str, Any],
    *,
    state: str,
    decided_at: datetime,
    approved_project_id: str | None = None,
    approved_project_code: str | None = None,
) -> None:
    result = session.execute(
        update(EOS_PROJECT_APPLICATION_TABLE)
        .where(
            EOS_PROJECT_APPLICATION_TABLE.c.tenant_id == application["tenant_id"],
            EOS_PROJECT_APPLICATION_TABLE.c.application_id
            == application["application_id"],
            EOS_PROJECT_APPLICATION_TABLE.c.state == "SUBMITTED",
            EOS_PROJECT_APPLICATION_TABLE.c.version == application["version"],
        )
        .values(
            state=state,
            approved_project_id=approved_project_id,
            approved_project_code=approved_project_code,
            version=int(application["version"]) + 1,
            updated_at=decided_at,
            decided_at=decided_at,
        )
    )
    if result.rowcount != 1:
        raise _conflict("Project application decision changed concurrently")


def _admit_delivery(value: Mapping[str, Any]) -> dict[str, Any]:
    if (
        not isinstance(value, Mapping)
        or value.get("schema_version") != "wc_approval_delivery.v1"
    ):
        raise _invalid("WC approval delivery schema is invalid")
    work_item = _mapping("work_item", value.get("work_item"))
    decision = _mapping("decision", value.get("decision"))
    event = _mapping("event", value.get("event"))
    target = _text("resume_target_ref", work_item.get("resume_target_ref"), 256)
    if (
        not target.startswith(PROJECT_APPLICATION_APPROVAL_RESUME_PREFIX)
        or ":stage:" not in target
    ):
        raise _invalid("WC delivery does not target a Project application")
    identity, _, stage_text = target.removeprefix(
        PROJECT_APPLICATION_APPROVAL_RESUME_PREFIX
    ).partition(":stage:")
    application_id = _uuid("application_id", identity)
    stage_order = _positive_int("stage_order", stage_text)
    tenant_id = _tenant_id(event.get("tenant_id"))
    work_item_id = _uuid("approval_work_item_id", event.get("approval_work_item_id"))
    decision_id = _uuid("decision_id", event.get("decision_id"))
    action = decision.get("decision")
    expected = {
        "work_item.tenant_id": (work_item.get("tenant_id"), tenant_id),
        "decision.tenant_id": (decision.get("tenant_id"), tenant_id),
        "work_item.approval_domain": (
            work_item.get("approval_domain"),
            "BUSINESS_FORMAL",
        ),
        "event.approval_domain": (event.get("approval_domain"), "BUSINESS_FORMAL"),
        "event.event_type": (
            event.get("event_type"),
            "BUSINESS_FORMAL_APPROVAL_DECIDED",
        ),
        "work_item.approval_work_item_id": (
            work_item.get("approval_work_item_id"),
            work_item_id,
        ),
        "decision.approval_work_item_id": (
            decision.get("approval_work_item_id"),
            work_item_id,
        ),
        "decision.decision_id": (decision.get("decision_id"), decision_id),
        "event.decision": (event.get("decision"), action),
    }
    for field, (actual, bound) in expected.items():
        if actual != bound:
            raise _invalid(f"{field} lineage differs")
    if action not in {"APPROVE", "REJECT"}:
        raise _invalid("WC Project committee decision is invalid")
    if work_item.get("state") != ("APPROVED" if action == "APPROVE" else "REJECTED"):
        raise _invalid("WC Project committee terminal state differs")
    if decision.get("schema_version") != "wc_approval_decision.v1":
        raise _invalid("WC decision schema is invalid")
    if event.get("schema_version") != "wc_approval_event.v1":
        raise _invalid("WC event schema is invalid")
    if decision.get("authorized_by_oa") is not True:
        raise _invalid("WC decision lacks OA authorization")
    decided_by = _scoped_id("decided_by", decision.get("decided_by"))
    if event.get("decided_by") != decided_by:
        raise _invalid("WC event decision principal differs")
    if decided_by.lower().startswith(_AGENT_PREFIXES):
        raise _denied("Only an OA Human principal may approve a Project application")
    decided_at = _datetime("decided_at", decision.get("decided_at"))
    if event.get("occurred_at") != decision.get("decided_at"):
        raise _invalid("WC decision and event timestamps differ")
    admitted = {
        "tenant_id": tenant_id,
        "application_id": application_id,
        "stage_order": stage_order,
        "wc_work_item_id": work_item_id,
        "wc_decision_id": decision_id,
        "wc_event_id": _uuid("event_id", event.get("event_id")),
        "wc_outbox_id": _uuid("outbox_id", value.get("outbox_id")),
        "work_item": work_item,
        "decision": action,
        "decision_version": _positive_int(
            "decision_version", decision.get("decision_version")
        ),
        "decided_by": decided_by,
        "decision_comment": _optional_text(
            "decision_comment", decision.get("decision_comment"), 2000
        ),
        "wc_oa_decision_ref": _scoped_id(
            "oa_decision_ref", decision.get("oa_decision_ref")
        ),
        "wc_authorization_revision_hash": _hash_ref(
            "authorization_revision_hash",
            decision.get("authorization_revision_hash"),
        ),
        "wc_authorization_checked_at": _datetime(
            "authorization_checked_at", decision.get("authorization_checked_at")
        ),
        "decided_at": decided_at,
        "correlation_id": _scoped_id("correlation_id", event.get("correlation_id")),
        "causation_id": _scoped_id("causation_id", event.get("causation_id")),
    }
    if admitted["decision_version"] != 1:
        raise _invalid("WC decision version is unsupported")
    admitted["decision_hash"] = semantic_sha256_hash_ref(
        {
            "schema_version": "eos_project_application_decision_binding.v1",
            **{
                key: admitted[key]
                for key in (
                    "tenant_id",
                    "application_id",
                    "stage_order",
                    "wc_work_item_id",
                    "wc_decision_id",
                    "wc_event_id",
                    "wc_outbox_id",
                    "decision",
                    "decision_version",
                    "decided_by",
                    "decision_comment",
                    "wc_oa_decision_ref",
                    "wc_authorization_revision_hash",
                    "correlation_id",
                    "causation_id",
                )
            },
            "work_item_semantic_hash": work_item.get("semantic_hash"),
            "decided_at": decided_at.isoformat(),
        }
    )
    return admitted


def _require_delivery_boundary(
    state: Mapping[str, Any], admitted: Mapping[str, Any]
) -> None:
    application = state["application"]
    approval = state["approval"]
    if application["state"] != "SUBMITTED" or approval["state"] != "PENDING":
        raise _conflict("Project application approval is terminal or unavailable")
    if approval["active_stage_order"] != admitted["stage_order"]:
        raise _conflict("WC Project committee decision is delayed or out of order")
    expected = project_application_approval_work_item(state)
    for field in (
        "tenant_id",
        "approval_work_item_id",
        "approval_domain",
        "source_ref",
        "semantic_hash",
        "approval_provider_type",
        "approval_target_ref",
        "target_role_ref",
        "business_operation_id",
        "approval_request_id",
        "protected_request_ref",
        "resume_target_ref",
    ):
        if admitted["work_item"].get(field) != expected.get(field):
            raise _conflict(f"WC Project committee work item {field} differs")
    if admitted["work_item"].get("version") != expected["version"] + 1:
        raise _conflict("WC Project committee work item version is out of order")


def _require_approver_authorization(
    value: Mapping[str, Any], *, tenant_id: str, decided_by: str, target_role: str
) -> None:
    if value.get("active") is not True:
        raise _denied("Active OA Human authorization is required")
    if value.get("tenant_id") != tenant_id or value.get("subject_id") != decided_by:
        raise _denied("OA tenant and Project approver identity do not match")
    roles = {item.lower() for item in _string_set("roles", value.get("roles"))}
    if target_role.lower() not in roles:
        raise _denied("Current OA role does not match the Project committee stage")


def _decision_record(
    admitted: Mapping[str, Any],
    *,
    authorization: Mapping[str, Any],
    recorded_at: datetime,
) -> dict[str, Any]:
    revision_hash = _authorization_revision(authorization)
    decision_ref = authorization.get("decision_ref") or (
        f"oa-authz:{revision_hash.removeprefix('sha256:')}"
    )
    return {
        **{
            key: admitted[key]
            for key in (
                "tenant_id",
                "application_id",
                "stage_order",
                "wc_work_item_id",
                "wc_decision_id",
                "wc_event_id",
                "wc_outbox_id",
                "decision",
                "decision_version",
                "decided_by",
                "decision_comment",
                "wc_oa_decision_ref",
                "wc_authorization_revision_hash",
                "decided_at",
                "decision_hash",
            )
        },
        "oa_decision_ref": _scoped_id("oa_decision_ref", decision_ref),
        "authorization_revision_hash": revision_hash,
        "authorization_checked_at": recorded_at,
        "recorded_at": recorded_at,
    }


def _load_state(
    session: Session, application: Mapping[str, Any], approval: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "application": dict(application),
        "approval": dict(approval),
        "revision": _load_current_revision(session, application),
    }


def _load_current_revision(
    session: Session, application: Mapping[str, Any]
) -> dict[str, Any]:
    row = (
        session.execute(
            select(EOS_PROJECT_APP_REVISION_TABLE).where(
                EOS_PROJECT_APP_REVISION_TABLE.c.tenant_id == application["tenant_id"],
                EOS_PROJECT_APP_REVISION_TABLE.c.application_id
                == application["application_id"],
                EOS_PROJECT_APP_REVISION_TABLE.c.revision
                == application["current_revision"],
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise _conflict("Project application current revision is unavailable")
    return {**dict(row), "payload": json.loads(row["payload_json"])}


def _load_application_by_code(
    session: Session, *, tenant_id: str, request_code: str, for_update: bool = False
):
    statement = select(EOS_PROJECT_APPLICATION_TABLE).where(
        EOS_PROJECT_APPLICATION_TABLE.c.tenant_id == tenant_id,
        EOS_PROJECT_APPLICATION_TABLE.c.project_request_code == request_code,
    )
    if for_update:
        statement = statement.with_for_update()
    row = session.execute(statement).mappings().one_or_none()
    return dict(row) if row is not None else None


def _load_application_by_id(
    session: Session, *, tenant_id: str, application_id: str, for_update: bool = False
):
    statement = select(EOS_PROJECT_APPLICATION_TABLE).where(
        EOS_PROJECT_APPLICATION_TABLE.c.tenant_id == tenant_id,
        EOS_PROJECT_APPLICATION_TABLE.c.application_id == application_id,
    )
    if for_update:
        statement = statement.with_for_update()
    row = session.execute(statement).mappings().one_or_none()
    return dict(row) if row is not None else None


def _load_approval(
    session: Session, *, tenant_id: str, application_id: str, for_update: bool = False
):
    statement = select(EOS_PROJECT_APP_APPROVAL_TABLE).where(
        EOS_PROJECT_APP_APPROVAL_TABLE.c.tenant_id == tenant_id,
        EOS_PROJECT_APP_APPROVAL_TABLE.c.application_id == application_id,
    )
    if for_update:
        statement = statement.with_for_update()
    row = session.execute(statement).mappings().one_or_none()
    return dict(row) if row is not None else None


def _load_policy(session: Session, tenant_id: str, policy_id: str):
    policy = (
        session.execute(
            select(EOS_APPROVAL_POLICY_TABLE).where(
                EOS_APPROVAL_POLICY_TABLE.c.tenant_id == tenant_id,
                EOS_APPROVAL_POLICY_TABLE.c.approval_policy_id == policy_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if policy is None:
        raise _not_found("Project application approval policy was not found")
    stages = list(
        session.execute(
            select(EOS_APPROVAL_POLICY_STAGE_TABLE)
            .where(
                EOS_APPROVAL_POLICY_STAGE_TABLE.c.tenant_id == tenant_id,
                EOS_APPROVAL_POLICY_STAGE_TABLE.c.approval_policy_id == policy_id,
            )
            .order_by(EOS_APPROVAL_POLICY_STAGE_TABLE.c.stage_order)
        ).mappings()
    )
    return dict(policy), [dict(stage) for stage in stages]


def _require_project_application_policy(
    policy: Mapping[str, Any], stages: list[Mapping[str, Any]], now: datetime
) -> None:
    if (
        policy["approval_domain"] != "BUSINESS_FORMAL"
        or policy["transaction_type"] != PROJECT_APPLICATION_APPROVAL_TRANSACTION_TYPE
        or policy["project_id"] is not None
        or policy["account_id"] is not None
    ):
        raise _conflict(
            "Policy is not an unscoped PROJECT_APPLICATION committee policy"
        )
    if (
        policy["status"] != "ACTIVE"
        or _as_utc(policy["effective_from"]) > now
        or (
            policy["effective_until"] is not None
            and _as_utc(policy["effective_until"]) <= now
        )
    ):
        raise _conflict("Project application approval policy is not effective")
    if not stages or [stage["stage_order"] for stage in stages] != list(
        range(1, len(stages) + 1)
    ):
        raise _conflict("Project application approval policy stages are incomplete")
    if any(
        stage["quorum_count"] != 1 or stage["separation_policy"] != "REQUESTER_EXCLUDED"
        for stage in stages
    ):
        raise _conflict(
            "Project committee requires sequential requester-excluded stages"
        )


def _load_decision_by_identity(session: Session, admitted: Mapping[str, Any]):
    rows = list(
        session.execute(
            select(EOS_PROJECT_APP_DECISION_TABLE).where(
                EOS_PROJECT_APP_DECISION_TABLE.c.tenant_id == admitted["tenant_id"],
                or_(
                    EOS_PROJECT_APP_DECISION_TABLE.c.wc_work_item_id
                    == admitted["wc_work_item_id"],
                    EOS_PROJECT_APP_DECISION_TABLE.c.wc_decision_id
                    == admitted["wc_decision_id"],
                    EOS_PROJECT_APP_DECISION_TABLE.c.wc_event_id
                    == admitted["wc_event_id"],
                ),
            )
        ).mappings()
    )
    if len(rows) > 1:
        raise _conflict("WC decision identities resolve to conflicting records")
    return dict(rows[0]) if rows else None


def _require_wc_publication(value: object, expected: Mapping[str, Any]) -> None:
    if not isinstance(value, Mapping) or not isinstance(
        value.get("work_item"), Mapping
    ):
        raise _unavailable("WC Project committee publication response is invalid")
    actual = value["work_item"]
    for field in (
        "tenant_id",
        "approval_work_item_id",
        "source_ref",
        "semantic_hash",
        "resume_target_ref",
    ):
        if actual.get(field) != expected.get(field):
            raise _unavailable("WC Project committee publication lineage differs")


def _authorization_revision(value: Mapping[str, Any]) -> str:
    revision = value.get("revision_hash")
    if not isinstance(revision, str):
        raise _denied("OA authorization revision is invalid")
    normalized = revision if revision.startswith("sha256:") else f"sha256:{revision}"
    if _HASH_REF.fullmatch(normalized) is None:
        raise _denied("OA authorization revision is invalid")
    return normalized


def _mapping(field: str, value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(f"{field} must be an object")
    return dict(value)


def _string_set(field: str, value: object) -> set[str]:
    if not isinstance(value, (list, tuple, set, frozenset)) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise _denied(f"OA {field} is invalid")
    return set(value)


def _tenant_id(value: object) -> str:
    text = str(value).strip().upper()
    if re.fullmatch(r"[A-Z0-9]{4}", text) is None:
        raise _invalid("tenant_id must be exactly four uppercase letters or digits")
    return text


def _request_code(value: object) -> str:
    text = str(value).strip().upper()
    if _REQUEST_CODE.fullmatch(text) is None:
        raise _invalid("project_request_code is invalid")
    return text


def _scoped_id(field: str, value: object) -> str:
    text = str(value).strip()
    if _SCOPED_ID.fullmatch(text) is None:
        raise _invalid(f"{field} is invalid")
    return text


def _uuid(field: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise _invalid(f"{field} must be a UUID") from exc


def _positive_int(field: str, value: object) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise _invalid(f"{field} must be a positive integer") from exc
    if isinstance(value, bool) or result < 1 or str(result) != str(value):
        raise _invalid(f"{field} must be a positive integer")
    return result


def _text(field: str, value: object, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise _invalid(f"{field} is invalid")
    return value.strip()


def _optional_text(field: str, value: object, limit: int) -> str | None:
    return None if value is None else _text(field, value, limit)


def _hash_ref(field: str, value: object) -> str:
    if not isinstance(value, str) or _HASH_REF.fullmatch(value) is None:
        raise _invalid(f"{field} must be a sha256 hash reference")
    return value


def _datetime(field: str, value: object) -> datetime:
    if not isinstance(value, str):
        raise _invalid(f"{field} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _invalid(f"{field} must be an ISO-8601 timestamp") from exc
    return _aware_datetime(field, parsed)


def _payload_date(field: str, value: object) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise _conflict(f"Project application {field} is invalid")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise _conflict(f"Project application {field} is invalid") from exc


def _aware_datetime(field: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise _invalid(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _timestamp(value: datetime) -> str:
    return _as_utc(value).isoformat()


def _invalid(detail: str) -> EosProjectApplicationApprovalError:
    return EosProjectApplicationApprovalError(
        "EOS_PROJECT_APPLICATION_APPROVAL_INVALID", detail, status_code=422
    )


def _denied(detail: str) -> EosProjectApplicationApprovalError:
    return EosProjectApplicationApprovalError(
        "EOS_PROJECT_APPLICATION_APPROVAL_DENIED", detail, status_code=403
    )


def _conflict(detail: str) -> EosProjectApplicationApprovalError:
    return EosProjectApplicationApprovalError(
        "EOS_PROJECT_APPLICATION_APPROVAL_CONFLICT", detail, status_code=409
    )


def _not_found(detail: str) -> EosProjectApplicationApprovalError:
    return EosProjectApplicationApprovalError(
        "EOS_PROJECT_APPLICATION_APPROVAL_NOT_FOUND", detail, status_code=404
    )


def _unavailable(detail: str) -> EosProjectApplicationApprovalError:
    return EosProjectApplicationApprovalError(
        "EOS_PROJECT_APPLICATION_APPROVAL_UNAVAILABLE",
        detail,
        status_code=503,
        retryable=True,
    )


__all__ = (
    "EOS_PROJECT_APP_APPROVAL_TABLE",
    "EOS_PROJECT_APP_DECISION_TABLE",
    "PROJECT_APPLICATION_APPROVAL_OPERATION",
    "PROJECT_APPLICATION_APPROVAL_RESUME_PREFIX",
    "PROJECT_APPLICATION_APPROVAL_SCOPE",
    "EosProjectApplicationApprovalError",
    "EosProjectApplicationApprovalService",
    "is_project_application_approval_delivery",
    "project_application_approval_work_item",
)
