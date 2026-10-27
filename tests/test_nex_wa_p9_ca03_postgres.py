from __future__ import annotations

import json
import os
import threading
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from time import time
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from nex_ae_api.agent_results import SqlAlchemyAgentResultRepository
from nex_ae_api.artifacts import (
    SqlAlchemyArtifactHandoffStore,
    SqlAlchemyArtifactRecordStore,
)
from nex_ae_api.wa_source_projections import (
    SqlAlchemyAgentResultWaProjectionSource,
    SqlAlchemyArtifactWaProjectionSource,
    register_wa_agent_result_source_routes,
    register_wa_artifact_source_routes,
)
from nex_eos import (
    NvtProjectInput,
    ProjectInput,
    ProjectMembershipInput,
    SqlAlchemyEosProjectMembershipRepository,
    SqlAlchemyEosProjectRepository,
)
from nex_eos.wa_project_verification import (
    EosWaProjectVerifier,
    register_wa_project_verification_routes,
)
from nex_oa.memberships import SqlAlchemyOaTenantMembershipRegistry
from nex_oa.subject_verification import (
    OaHumanSubjectVerifier,
    register_subject_verification_routes,
)
from nex_oa.subjects import SqlAlchemyOaSubjectRegistry
from nex_oa.token_signing import InMemoryOaRsaSigningProvider, encode_signed_jwt
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    BoundedJwksCache,
    ServiceTokenAdmissionRuntime,
    SignedServiceTokenVerifier,
    StaticJwksSource,
)
from nex_runtime.postgres_targets import resolve_postgres_test_targets
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from nex_wa import (
    WA_EVIDENCE_AUDIT_READ_SCOPE,
    WA_EVIDENCE_DETAIL_READ_SCOPE,
    WA_EVIDENCE_INGEST_SCOPE,
    WA_EVIDENCE_READ_SCOPE,
    AeAgentResultSourceAdapter,
    AeArtifactSourceAdapter,
    WaEvidenceSourceAdapterRegistry,
    WaSourceAdapterError,
    build_wa_evidence_consumer_runtime,
    normalize_evidence_intake_request,
)
from nex_wa.app import create_wa_app
from nex_wa.intake import WaEvidenceIntakeService
from nex_wa.persistence import build_wa_persistence_runtime
from nex_wa.reconciliation import WaAeReconciliationService
from nex_wc.work_result_source_projection import (
    WorkResultWaProjectionSource,
    register_wa_work_result_source_routes,
)
from nex_wc.work_results import SqlAlchemyWorkResultRepository
from run_migrations import run_service_migrations
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

pytestmark = pytest.mark.skipif(
    os.getenv("NEX_WA_P9_CA03_POSTGRES_SMOKE") != "1"
    and os.getenv("NEX_WA_P9_S29_POSTGRES_E2E") != "1",
    reason=(
        "set NEX_WA_P9_CA03_POSTGRES_SMOKE=1 or "
        "NEX_WA_P9_S29_POSTGRES_E2E=1 for the protected journey"
    ),
)

SERVICE_IDS = ("nex-ae-api", "nex-wc", "nex-oa", "nex-eos", "nex-wa")
EXPECTED_DATABASE_IDENTITIES = {
    "nex-ae-api": ("nex_ae_test", "nex_ae_user"),
    "nex-wc": ("nex_wc_test", "nex_wc_user"),
    "nex-oa": ("nex_oa_test", "nex_oa_user"),
    "nex-eos": ("nex_eos_test", "nex_eos_user"),
    "nex-wa": ("nex_wa_test", "nex_wa_user"),
}


class _VerifierIntrospector:
    def __init__(self, verifier: SignedServiceTokenVerifier, now_epoch: int) -> None:
        self._verifier = verifier
        self._now_epoch = now_epoch

    def introspect(
        self,
        token: str,
        *,
        expected_audience: str,
        required_scopes: Sequence[str],
    ) -> dict[str, object]:
        claims = self._verifier.verify(
            token,
            expected_audience=expected_audience,
            required_scopes=required_scopes,
            now_epoch=self._now_epoch,
        )
        return {
            "introspection_schema_version": "oa_token_introspection.v1",
            "active": True,
            "token_use": claims.token_use,
            "sub": claims.subject,
            "aud": claims.audience,
            "scope": " ".join(claims.scopes),
            "service_id": claims.service_id,
            "credential_id": claims.credential_id,
            "credential_revision": claims.credential_revision,
            "iat": claims.issued_at,
            "exp": claims.expires_at,
            "token_id_digest": claims.token_id_digest,
        }


class _SignedAuthority:
    def __init__(self) -> None:
        self.now_epoch = int(time())
        self.key_ref = "memory://p9-ca03-oa-key"
        self.key_id = "p9-ca03-key"
        self.signer = InMemoryOaRsaSigningProvider()
        self.signer.generate_key(self.key_ref)
        self.jwks = {
            "issuer": "urn:nex-platform:oa",
            "keys": [self.signer.public_jwk(self.key_ref, key_id=self.key_id)],
        }

    def token(self, service_id: str, audience: str, scopes: Sequence[str]) -> str:
        return encode_signed_jwt(
            headers={"alg": "RS256", "typ": "at+jwt", "kid": self.key_id},
            claims={
                "iss": "urn:nex-platform:oa",
                "sub": f"service:{service_id}",
                "aud": audience,
                "iat": self.now_epoch,
                "nbf": self.now_epoch,
                "exp": self.now_epoch + 300,
                "jti": f"sat-p9-ca03-{uuid4().hex}",
                "token_use": "service_access",
                "scope": " ".join(scopes),
                "service_id": service_id,
                "credential_id": f"p9-ca03-{service_id}",
                "credential_revision": 1,
            },
            private_key_ref=self.key_ref,
            signing_provider=self.signer,
        )

    def admission(self, audience: str) -> ServiceTokenAdmissionRuntime:
        verifier = SignedServiceTokenVerifier(
            BoundedJwksCache(
                StaticJwksSource(self.jwks),
                clock=lambda: self.now_epoch,
            ),
            clock=lambda: self.now_epoch,
        )
        return ServiceTokenAdmissionRuntime(
            expected_audience=audience,
            rollout_profile="SIGNED_ONLY",
            signed_verifier=verifier,
            introspector=_VerifierIntrospector(verifier, self.now_epoch),
            clock=lambda: self.now_epoch,
        )


class _GetClient:
    def __init__(self, client: TestClient, token: str) -> None:
        self._client = client
        self._token = token

    def get(self, path: str, tenant_id: str) -> Mapping[str, object]:
        response = self._client.get(
            path,
            headers={
                "Authorization": f"Bearer {self._token}",
                "X-NeX-Tenant-Id": tenant_id,
            },
        )
        assert response.status_code == 200, response.text
        return response.json()


class _AeAgentResultClient(_GetClient):
    def fetch_result(self, *, tenant_id: str, result_id: str):
        return self.get(f"/internal/v1/wa-sources/agent-results/{result_id}", tenant_id)


class _AeArtifactClient(_GetClient):
    def fetch_version(
        self, *, tenant_id: str, artifact_id: str, artifact_version_id: str
    ):
        return self.get(
            f"/internal/v1/wa-sources/artifacts/{artifact_id}/versions/"
            f"{artifact_version_id}",
            tenant_id,
        )


class _WcWorkResultClient(_GetClient):
    def fetch_by_execution(self, *, tenant_id: str, agent_execution_id: str):
        return self.get(
            f"/internal/v1/wa-sources/work-results/by-execution/{agent_execution_id}",
            tenant_id,
        )


class _AeReconciliationClient:
    _PATHS = {
        "AE_AGENT_RESULT": "/internal/v1/wa-sources/agent-results",
        "AE_ARTIFACT": "/internal/v1/wa-sources/artifacts",
    }

    def __init__(self, client: TestClient, token: str) -> None:
        self._client = client
        self._token = token

    def list_sources(self, **kwargs):
        source_type = str(kwargs["source_type"])
        params = {
            "created_after": kwargs["created_after"],
            "created_before": kwargs["created_before"],
            "limit": kwargs["limit"],
        }
        if kwargs["cursor"] is not None:
            params["cursor"] = kwargs["cursor"]
        response = self._client.get(
            self._PATHS[source_type],
            params=params,
            headers={
                "Authorization": f"Bearer {self._token}",
                "X-NeX-Tenant-Id": kwargs["tenant_id"],
            },
        )
        assert response.status_code == 200, response.text
        return response.json()


class _PostClient:
    def __init__(self, client: TestClient, token: str) -> None:
        self._client = client
        self._token = token

    def post(self, path: str, tenant_id: str, payload: Mapping[str, object]):
        response = self._client.post(
            path,
            json=dict(payload),
            headers={
                "Authorization": f"Bearer {self._token}",
                "X-NeX-Tenant-Id": tenant_id,
            },
        )
        assert response.status_code == 200, response.text
        return response.json()


class _OaSubjectClient(_PostClient):
    def verify_subject(self, *, tenant_id: str, subject_id: str):
        return self.post(
            "/internal/v1/identity/subjects:verify-batch",
            tenant_id,
            {"tenant_id": tenant_id, "subject_ids": [subject_id]},
        )


class _EosProjectClient(_PostClient):
    def verify_project(self, *, tenant_id: str, project_id: str):
        return self.post(
            "/internal/v1/projects:verify-batch",
            tenant_id,
            {"tenant_id": tenant_id, "project_ids": [project_id]},
        )


class _EosMembershipClient(_PostClient):
    def verify_membership(
        self,
        *,
        tenant_id: str,
        project_id: str,
        subject_id: str,
        occurred_at: str,
    ):
        return self.post(
            "/internal/v1/project-memberships:verify-at",
            tenant_id,
            {
                "tenant_id": tenant_id,
                "project_id": project_id,
                "subject_id": subject_id,
                "occurred_at": occurred_at,
            },
        )


def _install_signed_admission(
    app: FastAPI, authority: _SignedAuthority, audience: str
) -> None:
    app.state.service_token_admission = authority.admission(audience)


def _seed_ae(
    engine,
    *,
    tenant_id: str,
    project_id: str,
    subject_id: str,
    ids: Mapping[str, str],
    result_hash: str,
    artifact_hash: str,
    occurred_at: datetime,
) -> None:
    result_envelope = {
        "schema_version": "2.1",
        "tenant_id": tenant_id,
        "result_id": ids["agent_result"],
        "agent_execution_id": ids["execution"],
        "agent_id": ids["agent"],
        "agent_type": "PA",
        "project_id": project_id,
        "status": "PARTIAL",
        "quality": "PARTIAL",
        "structured_result": {"result_ref": "wa://bounded/p9-ca03"},
        "artifact_refs": [],
        "evidence_refs": [],
        "business_refs": [],
        "citation_refs": [],
        "source_work_item_ref": ids["work_item"],
        "source_claim_ref": ids["claim"],
        "source_claim_generation": 1,
        "source_claimant_agent_id": ids["agent"],
        "source_assignment_ref": ids["assignment"],
        "created_at": occurred_at.isoformat(),
        "result_hash": result_hash,
    }
    owner = {"actor_type": "user", "actor_id": subject_id, "tenant_id": tenant_id}
    workspace = {"workspace_id": ids["workspace"], "tenant_id": tenant_id}
    handoff_ref = {
        "artifact_handoff_id": ids["handoff"],
        "artifact_request_id": ids["artifact_request"],
    }
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO ae_agent_identity "
                "(tenant_id, agent_id, agent_type, profile_ref, status, project_id) "
                "VALUES (:tenant, :agent, 'PA', 'profile:p9-ca03', 'ACTIVE', :project)"
            ),
            {"tenant": tenant_id, "agent": ids["agent"], "project": project_id},
        )
        connection.execute(
            text(
                "INSERT INTO ae_agent_execution "
                "(tenant_id, agent_execution_id, agent_id, agent_type, principal_id, "
                "trigger_id, source_type, source_ref, project_id, state, phase, version, "
                "result_id, correlation_id, received_at, created_at, updated_at, "
                "work_item_ref, claim_ref, claim_generation, assignment_ref, requester_ref) "
                "VALUES (:tenant, :execution, :agent, 'PA', :subject, :trigger, "
                "'CLAIMED_WORKITEM', :work_item, :project, 'RUNNING', 'RESULT_PUBLISH', "
                "1, :result, :correlation, :occurred, :occurred, :occurred, "
                ":work_item, :claim, 1, :assignment, :subject)"
            ),
            {
                "tenant": tenant_id,
                "execution": ids["execution"],
                "agent": ids["agent"],
                "subject": subject_id,
                "trigger": ids["trigger"],
                "work_item": ids["work_item"],
                "project": project_id,
                "result": ids["agent_result"],
                "correlation": f"corr-{ids['execution']}",
                "occurred": occurred_at,
                "claim": ids["claim"],
                "assignment": ids["assignment"],
            },
        )
        connection.execute(
            text(
                "INSERT INTO ae_agent_result "
                "(tenant_id, result_id, agent_execution_id, agent_type, agent_id, "
                "project_id, status, quality, structured_result_json, result_envelope_json, "
                "result_hash, source_work_item_ref, source_claim_ref, "
                "source_claim_generation, source_claimant_agent_id, "
                "source_assignment_ref, created_at) VALUES "
                "(:tenant, :result, :execution, 'PA', :agent, :project, 'PARTIAL', "
                "'PARTIAL', CAST(:structured AS JSONB), CAST(:envelope AS JSONB), :hash, "
                ":work_item, :claim, 1, :claimant_agent, :assignment, :occurred)"
            ),
            {
                "tenant": tenant_id,
                "result": ids["agent_result"],
                "execution": ids["execution"],
                "agent": ids["agent"],
                "project": project_id,
                "structured": json.dumps(result_envelope["structured_result"]),
                "envelope": json.dumps(result_envelope),
                "hash": result_hash,
                "work_item": ids["work_item"],
                "claim": ids["claim"],
                "claimant_agent": ids["agent"],
                "assignment": ids["assignment"],
                "occurred": occurred_at,
            },
        )
        connection.execute(
            text(
                "INSERT INTO ae_result_delivery "
                "(tenant_id, delivery_id, result_id, agent_execution_id, target_type, "
                "target_ref, required, state, publication_operation_id, "
                "idempotency_key_ref, attempt_no, correlation_id, created_at, updated_at) "
                "VALUES (:tenant, :delivery, :result, :execution, 'WC_WORK_RESULT', "
                ":target, true, 'PENDING', :operation, :idempotency, 0, :correlation, "
                ":occurred, :occurred)"
            ),
            {
                "tenant": tenant_id,
                "delivery": ids["delivery"],
                "result": ids["agent_result"],
                "execution": ids["execution"],
                "target": ids["work_result"],
                "operation": f"PUBOP:{uuid4().hex}",
                "idempotency": f"PUBIDEMP:{uuid4().hex}",
                "correlation": f"corr-{ids['execution']}",
                "occurred": occurred_at,
            },
        )
        connection.execute(
            text(
                "INSERT INTO ae_artifact_handoffs "
                "(artifact_handoff_id, artifact_request_id, handoff_status, tenant_id, "
                "workspace_id, owner_user_id, trace_id, request_id, chat_document_id, "
                "interaction_id, cx_generation_id, structured_draft_id, draft_schema_version, "
                "structured_draft_content_hash, citation_claims_hash, validation_result_hash, "
                "artifact_intent, target_formats, artifact_title, language, "
                "retention_policy_ref, actor_claims_ref, workspace_ref, quality_summary, "
                "created_at, updated_at) VALUES "
                "(:handoff, :request, 'READY_FOR_RENDERING', :tenant, :workspace, :subject, "
                ":trace, :request_id, :chat, :interaction, :generation, :draft, "
                "'cx_structured_draft.v1', :source_hash, :citation_hash, :validation_hash, "
                "'create_artifact', CAST('[\"MD\"]' AS JSONB), 'P9 CA03 evidence', 'ko', "
                "'retain:p9-ca03', CAST(:owner AS JSONB), CAST(:workspace_ref AS JSONB), "
                "CAST('{}' AS JSONB), :occurred, :occurred)"
            ),
            {
                "handoff": ids["handoff"],
                "request": ids["artifact_request"],
                "tenant": tenant_id,
                "workspace": ids["workspace"],
                "subject": subject_id,
                "trace": uuid4().hex,
                "request_id": f"request-{uuid4().hex}",
                "chat": f"chat-{uuid4().hex}",
                "interaction": f"interaction-{uuid4().hex}",
                "generation": f"generation-{uuid4().hex}",
                "draft": f"draft-{uuid4().hex}",
                "source_hash": "a" * 64,
                "citation_hash": "c" * 64,
                "validation_hash": "d" * 64,
                "owner": json.dumps(owner),
                "workspace_ref": json.dumps(workspace),
                "occurred": occurred_at,
            },
        )
        connection.execute(
            text(
                "INSERT INTO ae_artifacts "
                "(artifact_id, artifact_type, artifact_status, current_version_id, "
                "artifact_handoff_id, artifact_request_id, tenant_id, workspace_id, "
                "owner_user_id, chat_document_id, interaction_id, trace_id, request_id, "
                "display_title, language, artifact_intent, target_formats, "
                "retention_policy_ref, owner_actor_ref, workspace_ref, template_ref, "
                "handoff_ref, created_at, updated_at) VALUES "
                "(:artifact, 'generated_document', 'READY', :version, :handoff, :request, "
                ":tenant, :workspace, :subject, :chat, :interaction, :trace, :request_id, "
                "'P9 CA03 evidence', 'ko', 'create_artifact', CAST('[\"MD\"]' AS JSONB), "
                "'retain:p9-ca03', CAST(:owner AS JSONB), CAST(:workspace_ref AS JSONB), "
                "CAST('{}' AS JSONB), CAST(:handoff_ref AS JSONB), :occurred, :occurred)"
            ),
            {
                "artifact": ids["artifact"],
                "version": ids["artifact_version"],
                "handoff": ids["handoff"],
                "request": ids["artifact_request"],
                "tenant": tenant_id,
                "workspace": ids["workspace"],
                "subject": subject_id,
                "chat": f"chat-{ids['artifact']}",
                "interaction": f"interaction-{ids['artifact']}",
                "trace": uuid4().hex,
                "request_id": f"request-{uuid4().hex}",
                "owner": json.dumps(owner),
                "workspace_ref": json.dumps(workspace),
                "handoff_ref": json.dumps(handoff_ref),
                "occurred": occurred_at,
            },
        )
        connection.execute(
            text(
                "INSERT INTO ae_artifact_source_refs "
                "(source_ref_id, artifact_id, cx_generation_id, structured_draft_id, "
                "draft_schema_version, structured_draft_content_hash, citation_claims_hash, "
                "validation_result_hash, quality_summary, created_at) VALUES "
                "(:source_ref, :artifact, :generation, :draft, 'cx_structured_draft.v1', "
                ":source_hash, :citation_hash, :validation_hash, CAST('{}' AS JSONB), :occurred)"
            ),
            {
                "source_ref": f"source-{ids['artifact']}",
                "artifact": ids["artifact"],
                "generation": f"generation-{ids['artifact']}",
                "draft": f"draft-{ids['artifact']}",
                "source_hash": "a" * 64,
                "citation_hash": "c" * 64,
                "validation_hash": "d" * 64,
                "occurred": occurred_at,
            },
        )
        connection.execute(
            text(
                "INSERT INTO ae_artifact_versions "
                "(artifact_version_id, artifact_id, version_no, version_reason, "
                "source_generation_id, source_structured_draft_id, source_content_hash, "
                "source_citation_claims_hash, render_policy_hash, artifact_content_hash, "
                "rendered_formats, validation_snapshot, created_at) VALUES "
                "(:version, :artifact, 1, 'initial', :generation, :draft, :source_hash, "
                ":citation_hash, :render_hash, :artifact_hash, CAST('[\"MD\"]' AS JSONB), "
                "CAST('{}' AS JSONB), :occurred)"
            ),
            {
                "version": ids["artifact_version"],
                "artifact": ids["artifact"],
                "generation": f"generation-{ids['artifact']}",
                "draft": f"draft-{ids['artifact']}",
                "source_hash": "a" * 64,
                "citation_hash": "c" * 64,
                "render_hash": "e" * 64,
                "artifact_hash": artifact_hash.removeprefix("sha256:"),
                "occurred": occurred_at,
            },
        )


def _clone_ready_artifact(
    session_factory,
    *,
    ids: Mapping[str, str],
    artifact_hash: str,
    occurred_at: datetime,
) -> None:
    handoffs = SqlAlchemyArtifactHandoffStore(session_factory)
    artifacts = SqlAlchemyArtifactRecordStore(session_factory)
    source_handoff = handoffs.get(ids["handoff"])
    source_artifact = artifacts.get(ids["artifact"])
    assert source_handoff is not None
    assert source_artifact is not None

    clone_at = (occurred_at + timedelta(seconds=1)).isoformat()
    cloned_handoff = deepcopy(source_handoff)
    cloned_handoff.update(
        {
            "artifact_handoff_id": ids["missed_handoff"],
            "artifact_request_id": ids["missed_artifact_request"],
            "trace_id": uuid4().hex,
            "request_id": f"request-{uuid4().hex}",
            "chat_document_id": f"chat-{ids['missed_artifact']}",
            "interaction_id": f"interaction-{ids['missed_artifact']}",
            "cx_generation_id": f"generation-{ids['missed_artifact']}",
            "structured_draft_id": f"draft-{ids['missed_artifact']}",
            "artifact_title": "P9 S29 reconciliation evidence",
            "created_at": clone_at,
            "updated_at": clone_at,
        }
    )
    handoffs.save(cloned_handoff)

    cloned_artifact = deepcopy(source_artifact)
    cloned_artifact.update(
        {
            "artifact_id": ids["missed_artifact"],
            "current_version_id": ids["missed_artifact_version"],
            "trace_id": uuid4().hex,
            "request_id": f"request-{uuid4().hex}",
            "chat_document_id": f"chat-{ids['missed_artifact']}",
            "interaction_id": f"interaction-{ids['missed_artifact']}",
            "display_title": "P9 S29 reconciliation evidence",
            "handoff_ref": {
                "artifact_handoff_id": ids["missed_handoff"],
                "artifact_request_id": ids["missed_artifact_request"],
            },
            "created_at": clone_at,
            "updated_at": clone_at,
        }
    )
    cloned_artifact["source_refs"] = [
        {
            **source_ref,
            "source_ref_id": f"source-{ids['missed_artifact']}",
            "cx_generation_id": f"generation-{ids['missed_artifact']}",
            "structured_draft_id": f"draft-{ids['missed_artifact']}",
            "created_at": clone_at,
        }
        for source_ref in source_artifact["source_refs"]
    ]
    cloned_artifact["versions"] = [
        {
            **version,
            "artifact_version_id": ids["missed_artifact_version"],
            "artifact_id": ids["missed_artifact"],
            "source_generation_id": f"generation-{ids['missed_artifact']}",
            "source_structured_draft_id": f"draft-{ids['missed_artifact']}",
            "artifact_content_hash": artifact_hash.removeprefix("sha256:"),
            "created_at": clone_at,
        }
        for version in source_artifact["versions"]
    ]
    cloned_artifact["render_jobs"] = []
    cloned_artifact["files"] = []
    cloned_artifact["links"] = []
    artifacts.save(cloned_artifact)


def _seed_wc(
    engine,
    *,
    tenant_id: str,
    project_id: str,
    ids: Mapping[str, str],
    occurred_at: datetime,
) -> str:
    payload = {
        "schema_version": "2.1",
        "tenant_id": tenant_id,
        "result_id": ids["work_result"],
        "work_item_id": ids["work_item"],
        "revision_no": 1,
        "result_type": "REPORT",
        "schema_ref": "schema:p9-ca03:report:v1",
        "technical_outcome": "SUCCEEDED",
        "business_outcome": "VERIFIED",
        "source_execution_ref": ids["execution"],
        "claim_ref": ids["claim"],
        "claim_generation": 1,
        "assignment_ref": ids["assignment"],
        "submitted_by": {"entity_type": "AGENT", "entity_id": ids["agent"]},
        "trace": {"correlation_id": f"corr-{ids['execution']}"},
        "submitted_at": occurred_at.isoformat().replace("+00:00", "Z"),
        "payload": {"private_ref": "wc-private://p9-ca03"},
        "summary": "bounded supporting result",
    }
    result_hash = semantic_sha256_hash_ref(payload)
    delegation_spec = {"result_contract_ref": payload["schema_ref"]}
    work_item = {"requester": {"entity_type": "HUMAN", "entity_id": "employee-p9-ca03"}}
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO wc_work_item "
                "(tenant_id, work_item_id, idempotency_key, delegation_semantic_hash, "
                "delegation_spec, work_item, state, source_type, parent_execution_id, "
                "parent_plan_id, parent_step_id, delegation_revision, project_id, "
                "required_agent_type, version, created_at, updated_at) VALUES "
                "(:tenant, :work, :idempotency, :semantic, CAST(:delegation AS JSONB), "
                "CAST(:work_item AS JSONB), 'RESULT_SUBMITTED', 'AGENT_PLAN_STEP', "
                ":parent_execution, :parent_plan, :parent_step, 1, :project, 'PA', 4, "
                ":occurred, :occurred)"
            ),
            {
                "tenant": tenant_id,
                "work": ids["work_item"],
                "idempotency": "sha256:" + "1" * 64,
                "semantic": "sha256:" + "2" * 64,
                "delegation": json.dumps(delegation_spec),
                "work_item": json.dumps(work_item),
                "parent_execution": f"parent-{ids['execution']}",
                "parent_plan": f"plan-{ids['execution']}",
                "parent_step": f"step-{ids['execution']}",
                "project": project_id,
                "occurred": occurred_at,
            },
        )
        connection.execute(
            text(
                "INSERT INTO wc_routing_decision "
                "(tenant_id, routing_decision_id, work_item_id, decision_version, "
                "policy_version, status, selected_agent_id, decision, created_at) VALUES "
                "(:tenant, :routing, :work, 1, 'p9-ca03', 'SELECTED', :agent, "
                "CAST('{}' AS JSONB), :occurred)"
            ),
            {
                "tenant": tenant_id,
                "routing": ids["routing"],
                "work": ids["work_item"],
                "agent": ids["agent"],
                "occurred": occurred_at,
            },
        )
        connection.execute(
            text(
                "INSERT INTO wc_assignment "
                "(tenant_id, assignment_id, work_item_id, routing_decision_id, agent_id, "
                "agent_type, project_id, claim_generation, status, created_at, updated_at, "
                "agent_execution_id) VALUES "
                "(:tenant, :assignment, :work, :routing, :agent, 'PA', :project, 1, "
                "'COMPLETED', :occurred, :occurred, :execution)"
            ),
            {
                "tenant": tenant_id,
                "assignment": ids["assignment"],
                "work": ids["work_item"],
                "routing": ids["routing"],
                "agent": ids["agent"],
                "project": project_id,
                "occurred": occurred_at,
                "execution": ids["execution"],
            },
        )
        connection.execute(
            text(
                "INSERT INTO wc_claim "
                "(tenant_id, claim_id, work_item_id, assignment_id, claim_generation, "
                "state, lease_verifier, lease_expires_at, authorization_revision_hash, "
                "authorized_subject_id, authorization_checked_at, created_at, updated_at) "
                "VALUES (:tenant, :claim, :work, :assignment, 1, 'COMPLETED', :verifier, "
                ":expires, :authorization, :agent, :occurred, :occurred, :occurred)"
            ),
            {
                "tenant": tenant_id,
                "claim": ids["claim"],
                "work": ids["work_item"],
                "assignment": ids["assignment"],
                "verifier": "sha256:" + "3" * 64,
                "expires": occurred_at + timedelta(hours=1),
                "authorization": "sha256:" + "4" * 64,
                "agent": ids["agent"],
                "occurred": occurred_at,
            },
        )
        connection.execute(
            text(
                "INSERT INTO wc_work_result "
                "(tenant_id, result_id, work_item_id, revision_no, result_type, "
                "result_schema_ref, result_hash, result_payload, source_execution_ref, "
                "claim_id, claim_generation, assignment_id, submitted_agent_id, "
                "authorization_revision_hash, authorization_checked_at, submitted_at) "
                "VALUES (:tenant, :result, :work, 1, 'REPORT', :schema, :hash, "
                "CAST(:payload AS JSONB), :execution, :claim, 1, :assignment, :agent, "
                ":authorization, :occurred, :occurred)"
            ),
            {
                "tenant": tenant_id,
                "result": ids["work_result"],
                "work": ids["work_item"],
                "schema": payload["schema_ref"],
                "hash": result_hash,
                "payload": json.dumps(payload),
                "execution": ids["execution"],
                "claim": ids["claim"],
                "assignment": ids["assignment"],
                "agent": ids["agent"],
                "authorization": "sha256:" + "4" * 64,
                "occurred": occurred_at,
            },
        )
    return result_hash


def _cleanup(
    engines: Mapping[str, object], tenant_id: str, ids: Mapping[str, str]
) -> None:
    with engines["nex-wa"].begin() as connection:
        connection.execute(
            text("DELETE FROM wa_work_asset_evidence WHERE tenant_id=:tenant"),
            {"tenant": tenant_id},
        )
        connection.execute(
            text("DELETE FROM wa_work_asset WHERE tenant_id=:tenant"),
            {"tenant": tenant_id},
        )
        connection.execute(
            text("DELETE FROM wa_work_evidence WHERE tenant_id=:tenant"),
            {"tenant": tenant_id},
        )
        connection.execute(
            text(
                "DELETE FROM service_log_entries WHERE trace_id IN "
                "(SELECT trace_id FROM service_jobs "
                " WHERE payload->>'tenant_id'=:tenant)"
            ),
            {"tenant": tenant_id},
        )
        connection.execute(
            text(
                "DELETE FROM service_operational_events WHERE trace_id IN "
                "(SELECT trace_id FROM service_jobs "
                " WHERE payload->>'tenant_id'=:tenant)"
            ),
            {"tenant": tenant_id},
        )
        connection.execute(
            text("DELETE FROM service_jobs WHERE payload->>'tenant_id'=:tenant"),
            {"tenant": tenant_id},
        )
        connection.execute(
            text(
                "DELETE FROM service_worker_heartbeats "
                "WHERE service_id='nex-wa' AND worker_id LIKE :worker_prefix"
            ),
            {"worker_prefix": ids["worker_prefix"] + "%"},
        )
    with engines["nex-ae-api"].begin() as connection:
        for artifact_id in (ids["artifact"], ids["missed_artifact"]):
            connection.execute(
                text("DELETE FROM ae_artifact_versions WHERE artifact_id=:artifact"),
                {"artifact": artifact_id},
            )
            connection.execute(
                text("DELETE FROM ae_artifact_source_refs WHERE artifact_id=:artifact"),
                {"artifact": artifact_id},
            )
            connection.execute(
                text("DELETE FROM ae_artifacts WHERE artifact_id=:artifact"),
                {"artifact": artifact_id},
            )
        for handoff_id in (ids["handoff"], ids["missed_handoff"]):
            connection.execute(
                text(
                    "DELETE FROM ae_artifact_handoffs "
                    "WHERE artifact_handoff_id=:handoff"
                ),
                {"handoff": handoff_id},
            )
        connection.execute(
            text("DELETE FROM ae_result_delivery WHERE tenant_id=:tenant"),
            {"tenant": tenant_id},
        )
        connection.execute(
            text("DELETE FROM ae_agent_result WHERE tenant_id=:tenant"),
            {"tenant": tenant_id},
        )
        connection.execute(
            text("DELETE FROM ae_agent_execution WHERE tenant_id=:tenant"),
            {"tenant": tenant_id},
        )
        connection.execute(
            text("DELETE FROM ae_agent_identity WHERE tenant_id=:tenant"),
            {"tenant": tenant_id},
        )
    with engines["nex-wc"].begin() as connection:
        for table in (
            "wc_work_result",
            "wc_claim",
            "wc_assignment",
            "wc_routing_decision",
            "wc_work_item",
        ):
            connection.execute(
                text(f"DELETE FROM {table} WHERE tenant_id=:tenant"),
                {"tenant": tenant_id},
            )
    with engines["nex-eos"].begin() as connection:
        for table in ("eos_project_member", "eos_project", "eos_nvt_project"):
            connection.execute(
                text(f"DELETE FROM {table} WHERE tenant_id=:tenant"),
                {"tenant": tenant_id},
            )
    with engines["nex-oa"].begin() as connection:
        for table in ("oa_tenant_memberships", "oa_subjects", "oa_tenants"):
            connection.execute(
                text(f"DELETE FROM {table} WHERE tenant_id=:tenant"),
                {"tenant": tenant_id},
            )


def test_p9_ca03_and_s29_actual_postgres_signed_canonical_foundation_e2e() -> None:
    targets = {
        target.target.service_id: target
        for target in resolve_postgres_test_targets(os.environ, service_ids=SERVICE_IDS)
    }
    for service_id in SERVICE_IDS:
        run_service_migrations(
            service_id,
            database_url=targets[service_id].database_url,
            profile="test",
        )
    engines = {
        service_id: create_engine(target.database_url)
        for service_id, target in targets.items()
    }
    for service_id, engine in engines.items():
        with engine.connect() as connection:
            assert (
                tuple(
                    connection.execute(
                        text("SELECT current_database(), current_user")
                    ).one()
                )
                == EXPECTED_DATABASE_IDENTITIES[service_id]
            )

    suffix = uuid4().hex
    tenant_id = f"P9S29-{suffix}"
    subject_id = f"employee-{suffix}"
    ids = {
        name: str(uuid4())
        for name in (
            "agent",
            "execution",
            "trigger",
            "agent_result",
            "delivery",
            "work_item",
            "routing",
            "assignment",
            "claim",
            "nvt_project",
            "project",
            "project_membership",
            "missed_handoff",
        )
    }
    ids.update(
        {
            "work_result": f"work-result-{suffix}",
            "artifact": f"artifact-{suffix}",
            "artifact_version": f"artifact-version-{suffix}",
            "artifact_request": f"artifact-request-{suffix}",
            "handoff": f"handoff-{suffix}",
            "workspace": f"workspace-{suffix}",
            "missed_artifact": f"artifact-missed-{suffix}",
            "missed_artifact_version": f"artifact-version-missed-{suffix}",
            "missed_artifact_request": f"artifact-request-missed-{suffix}",
            "worker_prefix": f"p9-s29-worker-{suffix}-",
        }
    )
    occurred_at = datetime.now(UTC).replace(microsecond=0)
    agent_result_hash = "sha256:" + "8" * 64
    artifact_hash = "sha256:" + "9" * 64
    missed_artifact_hash = "sha256:" + "a" * 64
    authority = _SignedAuthority()
    factories = {
        service_id: sessionmaker(
            bind=engine,
            autoflush=False,
            expire_on_commit=False,
        )
        for service_id, engine in engines.items()
    }
    wa_runtime = None

    try:
        subjects = SqlAlchemyOaSubjectRegistry(factories["nex-oa"])
        memberships = SqlAlchemyOaTenantMembershipRegistry(
            factories["nex-oa"], subject_registry=subjects
        )
        subjects.ensure_subject(
            {
                "tenant_id": tenant_id,
                "tenant_display_name": "P9 CA03 Tenant",
                "subject_id": subject_id,
                "subject_display_name": "P9 CA03 User",
            }
        )
        memberships.ensure_membership(
            {
                "tenant_id": tenant_id,
                "subject_id": subject_id,
                "membership_status": "ACTIVE",
                "roles": ["employee"],
                "scopes": ["user:access"],
            }
        )

        projects = SqlAlchemyEosProjectRepository(factories["nex-eos"])
        project_memberships = SqlAlchemyEosProjectMembershipRepository(
            factories["nex-eos"]
        )
        projects.create_nvt_project(
            NvtProjectInput(
                tenant_id,
                ids["nvt_project"],
                f"NVT-{suffix[:8]}",
                "P9 CA03 NVT",
            )
        )
        projects.create_project(
            ProjectInput(
                tenant_id,
                ids["project"],
                f"PROJECT-{suffix[:8]}",
                "P9 CA03 Project",
                nvt_project_id=ids["nvt_project"],
            )
        )
        project_memberships.create_membership(
            ProjectMembershipInput(
                tenant_id,
                ids["project_membership"],
                ids["project"],
                subject_id,
                "MEMBER",
                subject_id,
                valid_from=occurred_at - timedelta(minutes=1),
            )
        )

        _seed_wc(
            engines["nex-wc"],
            tenant_id=tenant_id,
            project_id=ids["project"],
            ids=ids,
            occurred_at=occurred_at,
        )
        _seed_ae(
            engines["nex-ae-api"],
            tenant_id=tenant_id,
            project_id=ids["project"],
            subject_id=subject_id,
            ids=ids,
            result_hash=agent_result_hash,
            artifact_hash=artifact_hash,
            occurred_at=occurred_at,
        )
        _clone_ready_artifact(
            factories["nex-ae-api"],
            ids=ids,
            artifact_hash=missed_artifact_hash,
            occurred_at=occurred_at,
        )

        ae_app = FastAPI()
        _install_signed_admission(ae_app, authority, "nex-ae-api")
        agent_results = SqlAlchemyAgentResultRepository(factories["nex-ae-api"])
        register_wa_agent_result_source_routes(
            ae_app,
            source=SqlAlchemyAgentResultWaProjectionSource(agent_results),
        )
        register_wa_artifact_source_routes(
            ae_app,
            source=SqlAlchemyArtifactWaProjectionSource(
                SqlAlchemyArtifactRecordStore(factories["nex-ae-api"])
            ),
        )

        wc_app = FastAPI()
        _install_signed_admission(wc_app, authority, "nex-wc")
        register_wa_work_result_source_routes(
            wc_app,
            source=WorkResultWaProjectionSource(
                SqlAlchemyWorkResultRepository(factories["nex-wc"])
            ),
        )

        oa_app = FastAPI()
        _install_signed_admission(oa_app, authority, "nex-oa")
        register_subject_verification_routes(
            oa_app,
            verifier=OaHumanSubjectVerifier(subjects, memberships),
        )

        eos_app = FastAPI()
        _install_signed_admission(eos_app, authority, "nex-eos")
        register_wa_project_verification_routes(
            eos_app,
            verifier=EosWaProjectVerifier(projects, project_memberships),
        )

        source_scopes = (DEFAULT_SERVICE_SCOPE, "work:source:read")
        project_scopes = (DEFAULT_SERVICE_SCOPE, "project:verify")
        subject_scopes = (DEFAULT_SERVICE_SCOPE, "identity:subject:verify")
        ae_client = TestClient(ae_app)
        agent_source = _AeAgentResultClient(
            ae_client,
            authority.token("nex-wa", "nex-ae-api", source_scopes),
        )
        artifact_source = _AeArtifactClient(
            ae_client,
            authority.token("nex-wa", "nex-ae-api", source_scopes),
        )
        wc_source = _WcWorkResultClient(
            TestClient(wc_app),
            authority.token("nex-wa", "nex-wc", source_scopes),
        )
        project_source = _EosProjectClient(
            TestClient(eos_app),
            authority.token("nex-wa", "nex-eos", project_scopes),
        )
        membership_source = _EosMembershipClient(
            TestClient(eos_app),
            authority.token("nex-wa", "nex-eos", project_scopes),
        )
        subject_source = _OaSubjectClient(
            TestClient(oa_app),
            authority.token("nex-wa", "nex-oa", subject_scopes),
        )

        wa_environ = {
            "NEX_PROFILE": "test",
            "NEX_VERSION": "2.1.0-p9-s29",
            "NEX_BUILD_SHA": "p9s29postgres",
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
            "NEX_WA_DATABASE_URL": targets["nex-wa"].database_url,
        }
        wa_runtime = build_wa_persistence_runtime(environ=wa_environ)
        agent_adapter = AeAgentResultSourceAdapter(
            source=agent_source,
            admission=wa_runtime.evidence_admission_service,
            projects=project_source,
            work_results=wc_source,
            clock=lambda: occurred_at,
        )
        agent_request = normalize_evidence_intake_request(
            {
                "schema_version": "wa_evidence_intake_request.v1",
                "tenant_id": tenant_id,
                "source_type": "AE_AGENT_RESULT",
                "source_ref": ids["execution"],
                "source_revision_ref": ids["agent_result"],
                "source_hash": agent_result_hash,
                "occurred_at": occurred_at.isoformat(),
                "correlation_id": f"corr-{ids['execution']}",
            }
        )
        with pytest.raises(WaSourceAdapterError) as pre_ack:
            agent_adapter.fetch(agent_request)
        assert pre_ack.value.error_code == "WA_AGENT_RESULT_NOT_COMPLETE"

        with engines["nex-ae-api"].begin() as connection:
            connection.execute(
                text(
                    "UPDATE ae_agent_execution SET state='SUCCEEDED', completed_at=:now, "
                    "updated_at=:now WHERE tenant_id=:tenant AND agent_execution_id=:execution"
                ),
                {
                    "now": occurred_at,
                    "tenant": tenant_id,
                    "execution": ids["execution"],
                },
            )
            connection.execute(
                text(
                    "UPDATE ae_result_delivery SET state='ACKNOWLEDGED', attempt_no=1, "
                    "latest_preflight_ref='preflight:p9-s29', acknowledged_at=:now, "
                    "updated_at=:now WHERE tenant_id=:tenant AND delivery_id=:delivery"
                ),
                {"now": occurred_at, "tenant": tenant_id, "delivery": ids["delivery"]},
            )

        artifact_adapter = AeArtifactSourceAdapter(
            source=artifact_source,
            subjects=subject_source,
            memberships=membership_source,
            admission=wa_runtime.evidence_admission_service,
            clock=lambda: occurred_at,
        )
        artifact_request = normalize_evidence_intake_request(
            {
                "schema_version": "wa_evidence_intake_request.v1",
                "tenant_id": tenant_id,
                "source_type": "AE_ARTIFACT",
                "source_ref": ids["artifact"],
                "source_revision_ref": ids["artifact_version"],
                "source_hash": artifact_hash,
                "occurred_at": occurred_at.isoformat(),
                "correlation_id": f"corr-{ids['artifact']}",
            }
        )
        wa_app = create_wa_app(
            environ=wa_environ,
            persistence_builder=lambda **_kwargs: wa_runtime,
        )
        _install_signed_admission(wa_app, authority, "nex-wa")
        registry = WaEvidenceSourceAdapterRegistry(
            {
                "AE_AGENT_RESULT": agent_adapter,
                "AE_ARTIFACT": artifact_adapter,
            }
        )
        intake_token = authority.token(
            "nex-ae-api",
            "nex-wa",
            (DEFAULT_SERVICE_SCOPE, WA_EVIDENCE_INGEST_SCOPE),
        )
        read_token = authority.token(
            "nex-ae-api",
            "nex-wa",
            (
                DEFAULT_SERVICE_SCOPE,
                WA_EVIDENCE_READ_SCOPE,
                WA_EVIDENCE_DETAIL_READ_SCOPE,
                WA_EVIDENCE_AUDIT_READ_SCOPE,
            ),
        )
        basic_token = authority.token(
            "nex-ae-api",
            "nex-wa",
            (DEFAULT_SERVICE_SCOPE, WA_EVIDENCE_READ_SCOPE),
        )
        wrong_audience = authority.token(
            "nex-ae-api",
            "nex-ae-api",
            (DEFAULT_SERVICE_SCOPE, WA_EVIDENCE_READ_SCOPE),
        )
        with TestClient(wa_app) as wa_client:
            def notify(payload, request_suffix: str):
                return wa_client.post(
                    "/internal/v1/evidence-intake",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {intake_token}",
                        "X-Request-ID": f"p9-s29-{request_suffix}-{suffix}",
                    },
                )

            agent_payload = agent_request.to_job_payload()
            artifact_payload = artifact_request.to_job_payload()
            agent_notification = notify(agent_payload, "agent")
            artifact_notification = notify(artifact_payload, "artifact")
            assert agent_notification.status_code == 202
            assert artifact_notification.status_code == 202

            replay = notify(agent_payload, "agent-replay")
            conflict = notify(
                {**agent_payload, "source_hash": "sha256:" + "f" * 64},
                "agent-conflict",
            )
            assert replay.status_code == 202
            assert replay.json()["job_id"] == agent_notification.json()["job_id"]
            assert replay.json()["idempotent_reuse"] is True
            assert conflict.status_code == 409
            assert conflict.json()["error_code"] == "WA_SOURCE_IDEMPOTENCY_CONFLICT"

            barrier = threading.Barrier(2)

            def consume(index: int):
                consumer = build_wa_evidence_consumer_runtime(
                    persistence=wa_runtime,
                    registry=registry,
                    worker_id=f"{ids['worker_prefix']}{index}",
                )
                barrier.wait()
                execution = consumer.run_once()
                consumer.stop()
                return execution

            with ThreadPoolExecutor(max_workers=2) as executor:
                first_batch = tuple(executor.map(consume, (1, 2)))
            assert {item.status for item in first_batch} == {"SUCCEEDED"}
            assert len(
                {
                    str(item.job["job_id"])
                    for item in first_batch
                    if item.job is not None
                }
            ) == 2

            reconciliation = WaAeReconciliationService(
                source=_AeReconciliationClient(
                    ae_client,
                    authority.token("nex-wa", "nex-ae-api", source_scopes),
                ),
                intake=WaEvidenceIntakeService(wa_runtime.intake_job_queue),
            ).run(
                tenant_id=tenant_id,
                created_after=(occurred_at - timedelta(minutes=1))
                .isoformat()
                .replace("+00:00", "Z"),
                created_before=(occurred_at + timedelta(minutes=1))
                .isoformat()
                .replace("+00:00", "Z"),
                mode="operator",
                page_size=10,
                max_pages_per_source=1,
            )
            assert sum(item.jobs_reused for item in reconciliation.sources) == 2
            assert sum(item.jobs_admitted for item in reconciliation.sources) == 1

            missed_payload = {
                "schema_version": "wa_evidence_intake_request.v1",
                "tenant_id": tenant_id,
                "source_type": "AE_ARTIFACT",
                "source_ref": ids["missed_artifact"],
                "source_revision_ref": ids["missed_artifact_version"],
                "source_hash": missed_artifact_hash,
                "occurred_at": (occurred_at + timedelta(seconds=1)).isoformat(),
                "correlation_id": f"corr-{ids['missed_artifact']}",
            }
            delayed_notification = notify(missed_payload, "artifact-delayed")
            assert delayed_notification.status_code == 202
            assert delayed_notification.json()["idempotent_reuse"] is True

            recovery_consumer = build_wa_evidence_consumer_runtime(
                persistence=wa_runtime,
                registry=registry,
                worker_id=f"{ids['worker_prefix']}reconciliation",
            )
            recovered = recovery_consumer.run_once()
            recovery_consumer.stop()
            assert recovered.status == "SUCCEEDED"

            with wa_runtime.api_engine.connect() as connection:
                counts = connection.execute(
                    text(
                        "SELECT "
                        "(SELECT count(*) FROM wa_work_evidence WHERE tenant_id=:tenant), "
                        "(SELECT count(*) FROM wa_work_asset WHERE tenant_id=:tenant), "
                        "(SELECT count(*) FROM service_jobs "
                        " WHERE payload->>'tenant_id'=:tenant AND status='SUCCEEDED')"
                    ),
                    {"tenant": tenant_id},
                ).one()
                roles = (
                    connection.execute(
                        text(
                            "SELECT binding_role FROM wa_work_asset_evidence "
                            "WHERE tenant_id=:tenant ORDER BY binding_role"
                        ),
                        {"tenant": tenant_id},
                    )
                    .scalars()
                    .all()
                )
                forbidden_tables = connection.execute(
                    text(
                        "SELECT count(*) FROM information_schema.tables "
                        "WHERE table_schema=current_schema() AND table_name LIKE 'wa_%' "
                        "AND (table_name ILIKE '%approval%' "
                        "OR table_name ILIKE '%delegation%' "
                        "OR table_name ILIKE '%salary%' "
                        "OR table_name ILIKE '%cost%' "
                        "OR table_name ILIKE '%profit%')"
                    )
                ).scalar_one()
                evidence_id = str(
                    connection.execute(
                        text(
                            "SELECT work_evidence_id FROM wa_work_evidence "
                            "WHERE tenant_id=:tenant AND source_type='AE_ARTIFACT' "
                            "AND source_ref=:source_ref"
                        ),
                        {"tenant": tenant_id, "source_ref": ids["artifact"]},
                    ).scalar_one()
                )
            assert tuple(counts) == (4, 3, 3)
            assert roles == ["PRIMARY", "PRIMARY", "PRIMARY", "SUPPORTING"]
            assert forbidden_tables == 0

            detail_path = f"/internal/v1/work-evidence/{evidence_id}"
            assert (
                wa_client.get(
                    detail_path,
                    headers={
                        "Authorization": f"Bearer {read_token}",
                        "X-NeX-Tenant-Id": tenant_id,
                    },
                ).status_code
                == 200
            )
            assert (
                wa_client.get(
                    detail_path,
                    headers={
                        "Authorization": f"Bearer {basic_token}",
                        "X-NeX-Tenant-Id": tenant_id,
                    },
                ).status_code
                == 403
            )
            assert (
                wa_client.get(
                    detail_path,
                    headers={
                        "Authorization": f"Bearer {wrong_audience}",
                        "X-NeX-Tenant-Id": tenant_id,
                    },
                ).status_code
                == 403
            )
            assert (
                wa_client.get(
                    detail_path,
                    headers={
                        "Authorization": f"Bearer {read_token}",
                        "X-NeX-Tenant-Id": f"OTHER-{suffix}",
                    },
                ).status_code
                == 404
            )
            print(
                "p9_s29_canonical_e2e=pass services=5 signed_trust=pass "
                "concurrent_claims=2 reconciliation_admitted=1 "
                "evidence=4 assets=3 privacy=pass"
            )
    finally:
        _cleanup(engines, tenant_id, ids)
        with engines["nex-wa"].connect() as connection:
            assert (
                connection.execute(
                    text(
                        "SELECT "
                        "(SELECT count(*) FROM wa_work_evidence WHERE tenant_id=:tenant) + "
                        "(SELECT count(*) FROM wa_work_asset WHERE tenant_id=:tenant) + "
                        "(SELECT count(*) FROM wa_work_asset_evidence WHERE tenant_id=:tenant) + "
                        "(SELECT count(*) FROM service_jobs "
                        " WHERE payload->>'tenant_id'=:tenant) + "
                        "(SELECT count(*) FROM service_worker_heartbeats "
                        " WHERE worker_id LIKE :worker_prefix)"
                    ),
                    {
                        "tenant": tenant_id,
                        "worker_prefix": ids["worker_prefix"] + "%",
                    },
                ).scalar_one()
                == 0
            )
        if wa_runtime is not None:
            wa_runtime.dispose()
        for engine in engines.values():
            engine.dispose()
