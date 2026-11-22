#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from time import sleep, time
from typing import Any
from urllib.error import HTTPError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "domains/mybee",
    ROOT / "services/_shared",
    ROOT / "services/nex-ae-api",
    ROOT / "services/nex-eos",
    ROOT / "services/nex-oa",
    ROOT / "scripts/db",
):
    sys.path.insert(0, str(path))

import httpx
import psycopg
import uvicorn
from mybee_ax.integrations import (
    HttpVoucherCandidateProviderTransport,
    NexVoucherCandidateClient,
    VoucherCandidateConsumerError,
    VoucherCandidateLine,
    build_voucher_candidate_draft,
)
from nex_ae_api.mybee_product_consumer import MYBEE_CONSUMER_OPERATIONS
from nex_eos.account_catalog import (
    AccountCatalogReleaseInput,
    CompanyAccountPolicyInput,
    PostingRuleReleaseInput,
    SqlAlchemyEosAccountCatalogRepository,
)
from nex_eos.accounting_periods import (
    AccountingPeriodInput,
    SqlAlchemyEosAccountingPeriodRepository,
)
from nex_eos.accounts import AccountInput
from nex_eos.app import create_eos_app
from nex_eos.approval_policies import EOS_APPROVAL_POLICY_TABLE
from nex_eos.approved_documents import EOS_APPROVED_DOCUMENT_TABLE
from nex_eos.authorization import HttpOaAuthorizationSource
from nex_eos.business_transactions import (
    EOS_BUSINESS_OPERATION_TABLE,
)
from nex_eos.document_signoff import EOS_DOCUMENT_SIGNOFF_EVIDENCE_TABLE
from nex_eos.legal_entities import (
    LegalEntityInput,
    SqlAlchemyEosLegalEntityRepository,
)
from nex_eos.oa_outbox_transport import HttpOaProjectEntitlementTransport
from nex_eos.outbox_publication import (
    EosOutboxEvent,
    EosOutboxPublicationError,
    SqlAlchemyEosOutboxPublisher,
)
from nex_eos.project_entitlement_events import append_project_entitlement_snapshot
from nex_eos.projects import NvtProjectInput, ProjectInput
from nex_eos.scoped_approvals import EOS_SCOPED_APPROVAL_CASE_TABLE
from nex_oa.authorization_repository import build_authorization_repository_for_runtime
from nex_oa.authorization_resolver import OaEffectiveAuthorizationResolver
from nex_oa.authorization_service import (
    OaAuthorizationService,
    register_authorization_routes,
)
from nex_oa.memberships import build_tenant_membership_registry_for_runtime
from nex_oa.project_entitlement_sync import (
    build_project_entitlement_inbox_for_runtime,
    register_project_entitlement_sync_routes,
)
from nex_oa.project_entitlements import (
    OaProjectAuthorizationDecisionService,
    build_project_grant_repository_for_runtime,
    register_project_entitlement_routes,
)
from nex_oa.subjects import build_subject_registry_for_runtime
from nex_oa.token_signing import InMemoryOaRsaSigningProvider, encode_signed_jwt
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    SERVICE_SPECS,
    attach_service_persistence_runtime,
    build_service_app,
    psycopg_database_url,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from nex_runtime.service_token_admission import ServiceTokenAdmissionRuntime
from nex_runtime.signed_token_verifier import (
    BoundedJwksCache,
    SignedServiceTokenVerifier,
    StaticJwksSource,
)
from run_migrations import run_service_migrations
from sqlalchemy import text
from sqlalchemy.engine import make_url

DEFAULT_REPORT = Path("reports/quality/mybee-w40-ca02-s04-protected-acceptance.json")
SCHEMA_VERSION = "mybee.w40_ca02_s04_protected_acceptance.v1"

TENANT = "VO00"
SUBJECT = "employee-w40-s04"
NO_SCOPE_SUBJECT = "employee-w40-s04-no-scope"
NON_MEMBER_SUBJECT = "employee-w40-s04-non-member"
COMPANY_ID = "40000000-0000-4000-8000-000000000001"
NVT_PROJECT_ID = "40000000-0000-4000-8000-000000000002"
PROJECT_ID = "40000000-0000-4000-8000-000000000003"
PROJECT_CODE = "VO00D260001"
ENVELOPE_ID = "40000000-0000-4000-8000-000000000004"
DOCUMENT_OPERATION_ID = "40000000-0000-4000-8000-000000000005"
POLICY_ID = "40000000-0000-4000-8000-000000000006"
CASE_ID = "40000000-0000-4000-8000-000000000007"
EVIDENCE_ID = "40000000-0000-4000-8000-000000000008"
DEBIT_ID = "40000000-0000-4000-8000-000000000009"
CREDIT_ID = "40000000-0000-4000-8000-000000000010"
CATALOG_RELEASE_ID = "40000000-0000-4000-8000-000000000011"
POSTING_RULE_ID = "40000000-0000-4000-8000-000000000012"
PERIOD_ID = "40000000-0000-4000-8000-000000000013"
CREATE_OPERATION_ID = "40000000-0000-4000-8000-000000000014"
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64
HASH_D = "sha256:" + "d" * 64


class W40Ca02S04AcceptanceError(RuntimeError):
    pass


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
    ) -> dict[str, Any]:
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
            "token_id_digest": claims.token_id_digest,
            "iat": claims.issued_at,
            "exp": claims.expires_at,
        }


class _SignedAuthority:
    def __init__(self) -> None:
        self.now_epoch = int(time())
        self.key_ref = "memory://mybee-w40-ca02-s04-key"
        self.key_id = "mybee-w40-ca02-s04-key"
        self.signer = InMemoryOaRsaSigningProvider()
        self.signer.generate_key(self.key_ref)
        self.jwks = {
            "issuer": "urn:nex-platform:oa",
            "keys": [self.signer.public_jwk(self.key_ref, key_id=self.key_id)],
        }

    def token(self, service_id: str, audience: str, *, scopes: Sequence[str]) -> str:
        now = self.now_epoch
        return encode_signed_jwt(
            headers={"alg": "RS256", "typ": "at+jwt", "kid": self.key_id},
            claims={
                "iss": "urn:nex-platform:oa",
                "sub": f"service:{service_id}",
                "aud": audience,
                "iat": now,
                "nbf": now,
                "exp": now + 300,
                "jti": f"sat-w40-ca02-s04-{uuid.uuid4().hex}",
                "token_use": "service_access",
                "scope": " ".join(sorted(set(scopes))),
                "service_id": service_id,
                "credential_id": f"w40-ca02-s04-{service_id}",
                "credential_revision": 1,
            },
            private_key_ref=self.key_ref,
            signing_provider=self.signer,
        )

    def admission(self, audience: str) -> ServiceTokenAdmissionRuntime:
        verifier = SignedServiceTokenVerifier(
            BoundedJwksCache(StaticJwksSource(self.jwks), clock=lambda: self.now_epoch),
            clock=lambda: self.now_epoch,
        )
        return ServiceTokenAdmissionRuntime(
            expected_audience=audience,
            rollout_profile="SIGNED_ONLY",
            signed_verifier=verifier,
            introspector=_VerifierIntrospector(verifier, self.now_epoch),
            clock=lambda: self.now_epoch,
        )


@dataclass
class _StartedServer:
    url: str
    server: uvicorn.Server
    thread: threading.Thread

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=5)


class _FailingTransport:
    @staticmethod
    def publish(_event: EosOutboxEvent):
        raise EosOutboxPublicationError(
            "EOS_OUTBOX_TRANSPORT_UNAVAILABLE",
            "bounded failure",
            retryable=True,
        )


class _RecordingTransport:
    def __init__(self, delegate: HttpOaProjectEntitlementTransport) -> None:
        self.delegate = delegate
        self.last_event: EosOutboxEvent | None = None

    def publish(self, event: EosOutboxEvent):
        self.last_event = event
        return self.delegate.publish(event)


def run_protected_acceptance(
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    eos_database_url = env.get(
        "NEX_EOS_TEST_DATABASE_URL",
        "postgresql+psycopg://nex_eos_user:nuri1004@127.0.0.1:5432/nex_eos_test",
    )
    oa_database_url = env.get(
        "NEX_OA_TEST_DATABASE_URL",
        "postgresql+psycopg://nex_oa_user:nuri1004@127.0.0.1:5432/nex_oa_test",
    )
    run_id = uuid.uuid4().hex
    schema_names = {
        "nex-eos": f"mybee_w40ca02s04_eos_{run_id}",
        "nex-oa": f"mybee_w40ca02s04_oa_{run_id}",
    }
    base_urls = {"nex-eos": eos_database_url, "nex-oa": oa_database_url}
    scoped_urls: dict[str, str] = {}
    servers: list[_StartedServer] = []
    resources: list[Any] = []
    authority = _SignedAuthority()
    ae_to_eos = authority.token(
        "nex-ae-api", "nex-eos", scopes=(DEFAULT_SERVICE_SCOPE,)
    )
    eos_to_oa = authority.token(
        "nex-eos",
        "nex-oa",
        scopes=(
            DEFAULT_SERVICE_SCOPE,
            "authorization:read",
            "project-entitlement:write",
        ),
    )
    try:
        for service_id, database_url in base_urls.items():
            _create_schema(
                database_url,
                expected_identity=(
                    f"{service_id.replace('-', '_')}_test",
                    f"{service_id.replace('-', '_')}_user",
                ),
                schema_name=schema_names[service_id],
            )
            scoped_urls[service_id] = _scoped_database_url(
                database_url, schema_names[service_id]
            )
            migration = run_service_migrations(
                service_id, database_url=scoped_urls[service_id], profile="test"
            )
            if len(migration.planned) != len(migration.applied) + len(
                migration.skipped
            ):
                raise W40Ca02S04AcceptanceError(
                    f"{service_id} migrations did not converge"
                )

        oa_app, oa_runtime, memberships = _build_oa_app(
            scoped_urls["nex-oa"], authority.admission("nex-oa")
        )
        resources.append(oa_runtime)
        _seed_memberships(memberships)
        oa_server = _start_api_server(oa_app)
        servers.append(oa_server)

        eos_app = create_eos_app(
            environ={
                "NEX_PROFILE": "test",
                "NEX_EOS_DATABASE_URL": scoped_urls["nex-eos"],
                "NEX_OA_BASE_URL": oa_server.url,
                "NEX_EOS_TO_OA_SERVICE_TOKEN": eos_to_oa,
                "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
            }
        )
        eos_app.state.service_token_admission = authority.admission("nex-eos")
        eos_runtime = eos_app.state.eos_database_runtime
        resources.append(eos_runtime)
        _seed_eos(eos_app)

        sessions = eos_runtime.session_factory
        failed = SqlAlchemyEosOutboxPublisher(sessions).publish_next(
            _FailingTransport(), tenant_id=TENANT
        )
        if failed is None or failed.delivery_state != "PENDING":
            raise W40Ca02S04AcceptanceError(
                "entitlement failure did not remain pending"
            )
        _assert_project_sync(sessions, "PENDING")

        entitlement_transport = _RecordingTransport(
            HttpOaProjectEntitlementTransport(
                base_url=oa_server.url,
                service_token=eos_to_oa,
            )
        )
        published = SqlAlchemyEosOutboxPublisher(sessions).publish_next(
            entitlement_transport, tenant_id=TENANT
        )
        if published is None or published.delivery_state != "PUBLISHED":
            raise W40Ca02S04AcceptanceError(
                "restarted entitlement delivery did not publish"
            )
        _assert_project_sync(sessions, "IN_SYNC")
        if (
            SqlAlchemyEosOutboxPublisher(sessions).publish_next(
                entitlement_transport, tenant_id=TENANT
            )
            is not None
        ):
            raise W40Ca02S04AcceptanceError("published event was claimed twice")
        if entitlement_transport.last_event is None:
            raise W40Ca02S04AcceptanceError("published event was not observed")
        replay_receipt = entitlement_transport.delegate.publish(
            entitlement_transport.last_event
        )
        if replay_receipt.event_id != entitlement_transport.last_event.event_id:
            raise W40Ca02S04AcceptanceError("exact replay receipt drifted")
        _assert_oa_grant_count(oa_runtime, expected=2)
        _assert_tampered_entitlement_rejected(
            entitlement_transport.delegate,
            entitlement_transport.last_event,
            oa_runtime,
        )
        _assert_oa_authorization_http(oa_server.url, eos_to_oa)

        eos_server = _start_api_server(eos_app)
        servers.append(eos_server)
        client = _client(eos_server.url, ae_to_eos)
        draft = _draft(SUBJECT)
        try:
            created = client.create(
                draft,
                business_operation_id=CREATE_OPERATION_ID,
                idempotency_key="w40-ca02-s04-candidate",
                trace_id="trace-w40-ca02-s04",
                correlation_id="correlation-w40-ca02-s04",
                causation_id="causation-w40-ca02-s04",
            )
        except VoucherCandidateConsumerError as exc:
            raise W40Ca02S04AcceptanceError(
                f"authorized VoucherCandidate create failed: {exc.code}"
            ) from exc
        validation = client.validate(draft, created, as_of=_now())
        if validation.get("status") != "PASS":
            raise W40Ca02S04AcceptanceError("candidate validation did not pass")

        eos_server.stop()
        servers.remove(eos_server)
        eos_runtime.dispose()
        resources.remove(eos_runtime)
        restarted_app = create_eos_app(
            environ={
                "NEX_PROFILE": "test",
                "NEX_EOS_DATABASE_URL": scoped_urls["nex-eos"],
                "NEX_OA_BASE_URL": oa_server.url,
                "NEX_EOS_TO_OA_SERVICE_TOKEN": eos_to_oa,
                "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
            }
        )
        restarted_app.state.service_token_admission = authority.admission("nex-eos")
        restarted_runtime = restarted_app.state.eos_database_runtime
        resources.append(restarted_runtime)
        restarted_server = _start_api_server(restarted_app)
        servers.append(restarted_server)
        restarted_client = _client(restarted_server.url, ae_to_eos)
        replayed = restarted_client.create(
            draft,
            business_operation_id=CREATE_OPERATION_ID,
            idempotency_key="w40-ca02-s04-candidate",
            trace_id="trace-w40-ca02-s04",
            correlation_id="correlation-w40-ca02-s04",
            causation_id="causation-w40-ca02-s04",
        )
        if replayed["candidate_ref"] != created["candidate_ref"]:
            raise W40Ca02S04AcceptanceError("restart replay duplicated candidate")

        _assert_changed_replay_rejected(restarted_client, draft)
        candidate_count = _candidate_count(restarted_runtime.session_factory)
        _assert_denied_matrix(
            restarted_client,
            draft,
            restarted_runtime.session_factory,
            base_url=restarted_server.url,
            expected_count=candidate_count,
        )

        report = {
            "schema_version": SCHEMA_VERSION,
            "status": "PASS",
            "actual_postgresql": True,
            "actual_loopback_http": True,
            "signed_service_tokens": True,
            "service_token_profile": "SIGNED_ONLY",
            "entitlement_failure_pending": True,
            "entitlement_restart_recovered": True,
            "entitlement_exact_replay": True,
            "entitlement_tamper_rejected": True,
            "oa_project_grant_count": 2,
            "mybee_operations": list(MYBEE_CONSUMER_OPERATIONS),
            "voucher_candidate_created": True,
            "voucher_candidate_validated": True,
            "service_restart_replay": True,
            "changed_replay_conflict": True,
            "fail_closed_matrix": [
                "MEMBER_WITHOUT_FINANCE_SCOPE",
                "FINANCE_SCOPED_NON_MEMBER",
                "STALE_PROJECT_PROJECTION",
                "MALFORMED_SERVICE_TOKEN",
            ],
            "voucher_candidate_count": candidate_count,
            "zero_residue": True,
            "content_included": False,
            "secret_included": False,
            "remote_provider_required": False,
            "next_slice": "W40-S4-01",
        }
        return report
    finally:
        for server in reversed(servers):
            server.stop()
        for resource in reversed(resources):
            dispose = getattr(resource, "dispose", None)
            if callable(dispose):
                dispose()
        for service_id, database_url in base_urls.items():
            _drop_schema(database_url, schema_names[service_id])


def _build_oa_app(database_url: str, admission: ServiceTokenAdmissionRuntime):
    spec = SERVICE_SPECS["nex-oa"]
    app = build_service_app(spec, service_token_admission=admission)
    runtime = attach_service_persistence_runtime(
        app,
        spec,
        environ={
            spec.database_env: database_url,
            "NEX_OA_PERSISTENCE_MODE": "postgres",
        },
    )
    subjects = build_subject_registry_for_runtime(runtime)
    memberships = build_tenant_membership_registry_for_runtime(
        runtime, subject_registry=subjects
    )
    authorization_repository = build_authorization_repository_for_runtime(runtime)
    authorization_service = OaAuthorizationService(
        repository=authorization_repository,
        resolver=OaEffectiveAuthorizationResolver(authorization_repository),
        membership_registry=memberships,
    )
    grant_repository = build_project_grant_repository_for_runtime(runtime)
    register_authorization_routes(app, service=authorization_service)
    register_project_entitlement_routes(
        app,
        service=OaProjectAuthorizationDecisionService(
            repository=grant_repository,
            authorization_source=authorization_service,
        ),
    )
    register_project_entitlement_sync_routes(
        app,
        inbox=build_project_entitlement_inbox_for_runtime(runtime),
        repository=grant_repository,
    )
    return app, runtime, memberships


def _seed_memberships(memberships: Any) -> None:
    for subject_id, scopes in (
        (SUBJECT, ["finance:voucher-candidate:create"]),
        (NO_SCOPE_SUBJECT, ["workspace:read"]),
        (NON_MEMBER_SUBJECT, ["finance:voucher-candidate:create"]),
    ):
        memberships.ensure_membership(
            {
                "tenant_id": TENANT,
                "subject_id": subject_id,
                "tenant_display_name": "W40 CA02 S04 Tenant",
                "subject_display_name": subject_id,
                "roles": ["employee"],
                "scopes": scopes,
                "membership_metadata": {"smoke_marker": "w40-ca02-s04"},
            }
        )


def _seed_eos(app: Any) -> None:
    dependencies = app.state.eos_dependencies
    sessions = dependencies.database_runtime.session_factory
    now = _now()
    SqlAlchemyEosLegalEntityRepository(sessions).create_legal_entity(
        LegalEntityInput(
            TENANT,
            COMPANY_ID,
            "W40S04",
            "W40 CA02 S04 Company",
            "KRW",
            "KRW",
            "Asia/Seoul",
            date(2026, 1, 1),
        )
    )
    projects = dependencies.projects
    projects.create_nvt_project(
        NvtProjectInput(TENANT, NVT_PROJECT_ID, "NVT-W40-S04", "W40 S04")
    )
    projects.create_project(
        ProjectInput(
            TENANT,
            PROJECT_ID,
            PROJECT_CODE,
            "W40 CA02 S04 Project",
            nvt_project_id=NVT_PROJECT_ID,
            status="ACTIVE",
            start_date=date(2026, 1, 1),
            currency="KRW",
            project_request_code="VO00R260001",
            purpose_type="D",
            origin="APPROVED_APPLICATION",
            approval_evidence_ref="wc-approval:w40-ca02-s04",
            approval_evidence_hash=HASH_A,
            project_owner_subject_id=SUBJECT,
            project_manager_subject_id=SUBJECT,
            authorization_sync_state="PENDING",
            authorization_version=1,
        )
    )
    with sessions.begin() as session:
        append_project_entitlement_snapshot(
            session,
            tenant_id=TENANT,
            project_id=PROJECT_ID,
            project_code=PROJECT_CODE,
            project_status="ACTIVE",
            source_version=1,
            members=[
                {"subject_id": SUBJECT, "project_role": "OWNER"},
                {"subject_id": NO_SCOPE_SUBJECT, "project_role": "MEMBER"},
            ],
            correlation_id="w40-ca02-s04-entitlement",
            causation_id="w40-ca02-s04-project",
            occurred_at=now,
        )
    _seed_accounting_sources(dependencies, now)
    _seed_approved_document(sessions, now)


def _seed_accounting_sources(dependencies: Any, now: datetime) -> None:
    sessions = dependencies.database_runtime.session_factory
    periods = SqlAlchemyEosAccountingPeriodRepository(sessions)
    periods.create_open_period(
        AccountingPeriodInput(
            TENANT,
            COMPANY_ID,
            PERIOD_ID,
            now.year,
            now.month,
            date(now.year, now.month, 1),
            date(now.year, now.month, 28),
        )
    )
    catalog = SqlAlchemyEosAccountCatalogRepository(sessions)
    catalog.create_catalog_release(
        AccountCatalogReleaseInput(
            TENANT,
            CATALOG_RELEASE_ID,
            "urn:mybee:w40-ca02-s04:coa",
            "2026.11",
            HASH_A,
            date(2026, 1, 1),
            "accounting-controller",
            HASH_B,
        )
    )
    catalog.create_posting_rule_release(
        PostingRuleReleaseInput(
            TENANT,
            POSTING_RULE_ID,
            COMPANY_ID,
            CATALOG_RELEASE_ID,
            "KIFRS-W40-S04",
            1,
            HASH_B,
            date(2026, 1, 1),
            HASH_C,
            HASH_A,
        )
    )
    for index, account_id in enumerate((DEBIT_ID, CREDIT_ID), start=1):
        catalog.create_approved_account(
            account=AccountInput(
                TENANT,
                account_id,
                f"W40S04-{index}",
                f"W40 S04 Account {index}",
                "EXPENSE" if index == 1 else "ASSET",
                "GENERAL",
                date(2026, 1, 1),
            ),
            policy=CompanyAccountPolicyInput(
                TENANT,
                f"40000000-0000-4000-8000-{100 + index:012d}",
                COMPANY_ID,
                account_id,
                CATALOG_RELEASE_ID,
                POSTING_RULE_ID,
                True,
                False,
                "PL-W40-S04" if index == 1 else "BS-W40-S04",
                ("KRW",),
                date(2026, 1, 1),
                HASH_C,
            ),
        )


def _seed_approved_document(sessions: Any, now: datetime) -> None:
    with sessions.begin() as session:
        session.execute(
            EOS_BUSINESS_OPERATION_TABLE.insert().values(
                tenant_id=TENANT,
                business_operation_id=DOCUMENT_OPERATION_ID,
                idempotency_key="w40-ca02-s04-approved-document",
                operation="APPROVE_BUSINESS_DOCUMENT",
                payload_hash=HASH_D,
                commit_state="COMMITTED",
                result_json={"envelope_id": ENVELOPE_ID},
                created_at=now - timedelta(hours=2),
                committed_at=now - timedelta(hours=1),
            )
        )
        session.execute(
            EOS_APPROVAL_POLICY_TABLE.insert().values(
                tenant_id=TENANT,
                approval_policy_id=POLICY_ID,
                policy_key="mybee.w40.ca02.s04.document",
                version=1,
                name="W40 CA02 S04 document approval",
                approval_domain="BUSINESS_FORMAL",
                risk_level="MEDIUM",
                minimum_amount=None,
                maximum_amount=None,
                project_id=PROJECT_ID,
                account_id=None,
                transaction_type="DOCUMENT_SIGNOFF",
                status="ACTIVE",
                effective_from=now - timedelta(days=2),
                effective_until=None,
                policy_hash=HASH_C,
                created_at=now - timedelta(days=2),
                updated_at=now - timedelta(days=2),
            )
        )
        session.execute(
            EOS_SCOPED_APPROVAL_CASE_TABLE.insert().values(
                tenant_id=TENANT,
                case_id=CASE_ID,
                idempotency_key="w40-ca02-s04-scoped-case",
                company_id=COMPANY_ID,
                purpose="DOCUMENT_SIGNOFF",
                scope_type="PROJECT",
                project_set_hash=HASH_A,
                subject_ref="mybee.proposal:w40-ca02-s04",
                subject_revision=1,
                subject_hash=HASH_A,
                requester_ref_type="oa.user",
                requester_id=SUBJECT,
                approval_policy_id=POLICY_ID,
                approval_policy_version=1,
                approval_policy_hash=HASH_C,
                oa_decision_ref="oa.authorization:w40-ca02-s04",
                authorization_revision_hash=HASH_B,
                authorization_checked_at=now - timedelta(hours=2),
                state="APPROVED",
                active_stage_order=None,
                stage_count=1,
                target_role_ref="TEAM_LEAD",
                version=2,
                case_hash=HASH_B,
                created_business_operation_id=DOCUMENT_OPERATION_ID,
                correlation_id="correlation-w40-ca02-s04-document",
                causation_id="causation-w40-ca02-s04-document",
                expires_at=now + timedelta(days=30),
                created_at=now - timedelta(hours=2),
                updated_at=now - timedelta(hours=1),
                decided_at=now - timedelta(hours=1),
            )
        )
        session.execute(
            EOS_DOCUMENT_SIGNOFF_EVIDENCE_TABLE.insert().values(
                tenant_id=TENANT,
                case_id=CASE_ID,
                evidence_id=EVIDENCE_ID,
                company_id=COMPANY_ID,
                envelope_id=ENVELOPE_ID,
                context_hash=HASH_A,
                document_payload_hash=HASH_D,
                approver_subject_id="approver-w40-s04",
                approval_policy_hash=HASH_C,
                wc_work_item_id="40000000-0000-4000-8000-000000000021",
                wc_final_decision_id="40000000-0000-4000-8000-000000000022",
                oa_authorization_revision_hash=HASH_B,
                decided_at=now - timedelta(hours=1),
                proof_hash=HASH_B,
                created_at=now - timedelta(hours=1),
            )
        )
        session.execute(
            EOS_APPROVED_DOCUMENT_TABLE.insert().values(
                tenant_id=TENANT,
                envelope_id=ENVELOPE_ID,
                company_id=COMPANY_ID,
                approved_document_id="proposal-w40-ca02-s04",
                document_revision=1,
                document_type="BUSINESS_PROPOSAL",
                work_code="FL0004011",
                document_content_hash=HASH_A,
                attachment_manifest_hash=HASH_B,
                business_approval_proof_id=None,
                scoped_document_evidence_id=EVIDENCE_ID,
                business_proof_hash=HASH_B,
                approval_policy_id=POLICY_ID,
                approval_policy_version=1,
                approval_policy_hash=HASH_C,
                scope_type="PROJECT",
                project_set_hash=HASH_A,
                allowed_project_ids=[PROJECT_ID],
                allowed_project_codes=[PROJECT_CODE],
                approved_amount=Decimal("10000.0000"),
                approved_currency="KRW",
                tolerance_policy_hash=None,
                valid_from=now - timedelta(hours=1),
                valid_until=now + timedelta(days=30),
                state="ACTIVE",
                approved_at=now - timedelta(hours=1),
                approved_by_ref_type="oa.user",
                approved_by_id="approver-w40-s04",
                source_work_item_ref="wc.approval:w40-ca02-s04",
                payload_hash=HASH_D,
                created_business_operation_id=DOCUMENT_OPERATION_ID,
                created_at=now - timedelta(hours=1),
            )
        )


def _document_projection(now: datetime) -> dict[str, Any]:
    return {
        "schema_version": "eos_approved_document_envelope.v2",
        "tenant_id": TENANT,
        "envelope_id": ENVELOPE_ID,
        "company_id": COMPANY_ID,
        "approved_document_id": "proposal-w40-ca02-s04",
        "document_revision": 1,
        "document_type": "BUSINESS_PROPOSAL",
        "work_code": "FL0004011",
        "document_content_hash": HASH_A,
        "attachment_manifest_hash": HASH_B,
        "business_approval_proof_id": "40000000-0000-4000-8000-000000000023",
        "business_proof_hash": HASH_B,
        "approval_policy_id": POLICY_ID,
        "approval_policy_version": 1,
        "approval_policy_hash": HASH_C,
        "scope_type": "PROJECT",
        "project_set_hash": HASH_A,
        "allowed_project_ids": [PROJECT_ID],
        "allowed_project_codes": [PROJECT_CODE],
        "approved_amount": "10000.0000",
        "approved_currency": "KRW",
        "remaining_amount": "10000.0000",
        "tolerance_policy_hash": None,
        "valid_from": (now - timedelta(hours=1)).isoformat(),
        "valid_until": (now + timedelta(days=30)).isoformat(),
        "state": "ACTIVE",
        "usable": True,
        "approved_at": (now - timedelta(hours=1)).isoformat(),
        "approved_by_principal_ref": {
            "type": "oa.user",
            "id": "approver-w40-s04",
        },
        "source_work_item_ref": "wc.approval:w40-ca02-s04",
        "payload_hash": HASH_D,
        "created_business_operation_id": DOCUMENT_OPERATION_ID,
        "created_at": (now - timedelta(hours=1)).isoformat(),
    }


def _draft(subject_id: str):
    now = _now()
    return build_voucher_candidate_draft(
        tenant_id=TENANT,
        company_id=COMPANY_ID,
        preparer_subject_id=subject_id,
        project_id=PROJECT_ID,
        project_code=PROJECT_CODE,
        approved_document=_document_projection(now),
        source_kind="EXPENSE_CLAIM",
        source_record_ref=f"mybee.expense:{subject_id}:w40-ca02-s04",
        business_work_code="FL0004011",
        transaction_currency="KRW",
        recognition_date=now.date(),
        lines=(
            VoucherCandidateLine(
                account_id=DEBIT_ID,
                debit_original=Decimal(10000),
                credit_original=Decimal(0),
                source_record_line_ref="expense-line-1",
                description="Protected acceptance expense",
                evidence_hash=HASH_A,
            ),
            VoucherCandidateLine(
                account_id=CREDIT_ID,
                debit_original=Decimal(0),
                credit_original=Decimal(10000),
                source_record_line_ref="expense-line-2",
                description="Protected acceptance offset",
                evidence_hash=HASH_B,
            ),
        ),
    )


def _client(base_url: str, token: str) -> NexVoucherCandidateClient:
    return NexVoucherCandidateClient(
        HttpVoucherCandidateProviderTransport(
            eos_base_url=base_url,
            service_token=token,
            timeout_seconds=15,
        )
    )


def _assert_changed_replay_rejected(client: NexVoucherCandidateClient, draft: Any):
    changed = replace(draft, source_record_ref="mybee.expense:changed-w40-ca02-s04")
    try:
        client.create(
            changed,
            business_operation_id=CREATE_OPERATION_ID,
            idempotency_key="w40-ca02-s04-candidate",
            trace_id="trace-w40-ca02-s04",
            correlation_id="correlation-w40-ca02-s04",
            causation_id="causation-w40-ca02-s04",
        )
    except VoucherCandidateConsumerError as exc:
        if exc.status_code != 409:
            raise
    else:
        raise W40Ca02S04AcceptanceError("changed replay was accepted")


def _assert_denied_matrix(
    client: NexVoucherCandidateClient,
    draft: Any,
    sessions: Any,
    *,
    base_url: str,
    expected_count: int,
) -> None:
    for subject_id, suffix in (
        (NO_SCOPE_SUBJECT, "no-scope"),
        (NON_MEMBER_SUBJECT, "non-member"),
    ):
        denied = replace(draft, preparer_subject_id=subject_id)
        _expect_denied_create(client, denied, suffix)
        if _candidate_count(sessions) != expected_count:
            raise W40Ca02S04AcceptanceError("denied request mutated candidate state")
    with sessions.begin() as session:
        session.execute(
            text(
                "UPDATE eos_project SET authorization_sync_state = 'PENDING' "
                "WHERE tenant_id = :tenant_id AND project_id = :project_id"
            ),
            {"tenant_id": TENANT, "project_id": PROJECT_ID},
        )
    _expect_denied_create(client, draft, "stale")
    with sessions.begin() as session:
        session.execute(
            text(
                "UPDATE eos_project SET authorization_sync_state = 'IN_SYNC' "
                "WHERE tenant_id = :tenant_id AND project_id = :project_id"
            ),
            {"tenant_id": TENANT, "project_id": PROJECT_ID},
        )
    malformed = _client(base_url, "not-a-signed-token")
    _expect_denied_create(malformed, draft, "malformed-token")
    if _candidate_count(sessions) != expected_count:
        raise W40Ca02S04AcceptanceError("fail-closed matrix mutated candidate state")


def _expect_denied_create(client: NexVoucherCandidateClient, draft: Any, suffix: str):
    try:
        client.create(
            draft,
            business_operation_id=str(uuid.uuid4()),
            idempotency_key=f"w40-ca02-s04-{suffix}",
            trace_id=f"trace-w40-ca02-s04-{suffix}",
            correlation_id=f"correlation-w40-ca02-s04-{suffix}",
            causation_id=f"causation-w40-ca02-s04-{suffix}",
        )
    except VoucherCandidateConsumerError as exc:
        if exc.status_code not in {401, 403, 503}:
            raise
    else:
        raise W40Ca02S04AcceptanceError(f"{suffix} request was accepted")


def _assert_tampered_entitlement_rejected(
    transport: HttpOaProjectEntitlementTransport,
    event: EosOutboxEvent,
    oa_runtime: Any,
) -> None:
    changed_payload = dict(event.event_payload)
    changed_payload["correlation_id"] = "tampered-w40-ca02-s04"
    tampered = EosOutboxEvent(
        outbox_id=event.outbox_id,
        tenant_id=event.tenant_id,
        event_id=event.event_id,
        business_operation_id=event.business_operation_id,
        event_type=event.event_type,
        event_payload=changed_payload,
        event_payload_hash=semantic_sha256_hash_ref(changed_payload),
    )
    try:
        transport.publish(tampered)
    except EosOutboxPublicationError as exc:
        if exc.retryable:
            raise W40Ca02S04AcceptanceError(
                "tampered entitlement was treated as retryable"
            ) from exc
    else:
        raise W40Ca02S04AcceptanceError("tampered entitlement was accepted")
    _assert_oa_grant_count(oa_runtime, expected=2)


def _assert_oa_authorization_http(base_url: str, service_token: str) -> None:
    authorization = HttpOaAuthorizationSource(
        base_url=base_url,
        service_token=service_token,
    ).effective_authorization(tenant_id=TENANT, subject_id=SUBJECT)
    request = {
        "tenant_id": TENANT,
        "subject_id": SUBJECT,
        "project_code": PROJECT_CODE,
        "action": "finance:voucher-candidate:create",
        "correlation_id": "w40-ca02-s04-authorization",
        "minimum_source_version": 1,
    }
    response = httpx.post(
        f"{base_url}/internal/v1/auth/project-decisions",
        json=request,
        headers={"Authorization": f"Bearer {service_token}"},
        timeout=10,
    )
    if response.status_code != 200:
        problem = response.json()
        raise W40Ca02S04AcceptanceError(
            "OA Project decision failed: "
            f"{problem.get('error_code', response.status_code)}"
        )
    decision = response.json()["decision"]
    if authorization.get("revision_hash") != decision.get(
        "authorization_revision_hash"
    ):
        raise W40Ca02S04AcceptanceError("OA authorization revision drifted")
    if decision.get("allowed") is not True:
        raise W40Ca02S04AcceptanceError("OA denied the admitted Project member")


def _assert_project_sync(sessions: Any, expected: str) -> None:
    with sessions() as session:
        value = session.execute(
            text(
                "SELECT authorization_sync_state FROM eos_project "
                "WHERE tenant_id = :tenant_id AND project_id = :project_id"
            ),
            {"tenant_id": TENANT, "project_id": PROJECT_ID},
        ).scalar_one()
    if value != expected:
        raise W40Ca02S04AcceptanceError(
            f"Project authorization sync state is {value}, expected {expected}"
        )


def _assert_oa_grant_count(runtime: Any, *, expected: int) -> None:
    with runtime.api_session_factory() as session:
        count = session.execute(
            text("SELECT count(*) FROM oa_project_grant")
        ).scalar_one()
    if count != expected:
        raise W40Ca02S04AcceptanceError(
            f"OA Project grant count is {count}, expected {expected}"
        )


def _candidate_count(sessions: Any) -> int:
    with sessions() as session:
        return int(
            session.execute(
                text(
                    "SELECT count(*) FROM eos_voucher_candidate "
                    "WHERE tenant_id = :tenant_id"
                ),
                {"tenant_id": TENANT},
            ).scalar_one()
        )


def _start_api_server(app: Any) -> _StartedServer:
    port = _free_port()
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        lifespan="off",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    _wait_for_url(f"{url}/health")
    return _StartedServer(url, server, thread)


def _wait_for_url(url: str, *, attempts: int = 100) -> None:
    for _ in range(attempts):
        try:
            with urlopen(url, timeout=0.5) as response:
                if response.status < 500:
                    return
        except (OSError, HTTPError):
            sleep(0.05)
    raise W40Ca02S04AcceptanceError("loopback service did not become ready")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        return int(server.getsockname()[1])


def _create_schema(
    database_url: str,
    *,
    expected_identity: tuple[str, str],
    schema_name: str,
) -> None:
    with (
        psycopg.connect(psycopg_database_url(database_url), autocommit=True) as conn,
        conn.cursor() as cursor,
    ):
        cursor.execute("SELECT current_database(), current_user")
        if cursor.fetchone() != expected_identity:
            raise W40Ca02S04AcceptanceError("database identity admission failed")
        cursor.execute(f'CREATE SCHEMA "{schema_name}"')


def _drop_schema(database_url: str, schema_name: str) -> None:
    with (
        psycopg.connect(psycopg_database_url(database_url), autocommit=True) as conn,
        conn.cursor() as cursor,
    ):
        cursor.execute(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
        cursor.execute("SELECT to_regnamespace(%s)", (schema_name,))
        if cursor.fetchone() != (None,):
            raise W40Ca02S04AcceptanceError("protected schema residue remains")


def _scoped_database_url(database_url: str, schema_name: str) -> str:
    return (
        make_url(database_url)
        .update_query_dict({"options": f"-csearch_path={schema_name}"})
        .render_as_string(hide_password=False)
    )


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _write_report(path: Path, report: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(dict(report), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--summary", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run_protected_acceptance()
    _write_report(args.report, report)
    if args.summary:
        print(
            "mybee_w40_ca02_s04_protected_acceptance=pass "
            f"grants={report['oa_project_grant_count']} "
            f"candidates={report['voucher_candidate_count']} "
            f"next={report['next_slice']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
