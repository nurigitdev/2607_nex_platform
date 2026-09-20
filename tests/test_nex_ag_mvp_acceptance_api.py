from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from nex_ag.mvp_acceptance_api import (
    AG_MVP_ACCEPTANCE_OPERATIONS_PATH,
    RepositoryAgMvpAcceptanceEvidenceProvider,
    register_ag_mvp_acceptance_routes,
)
from nex_runtime import (
    SERVICE_SPECS,
    build_service_app,
    issue_mock_service_token,
    issue_mock_user_token,
)


NOW = datetime(2026, 9, 20, 3, 0, tzinfo=UTC)
TRACE_ID = "a" * 32


def _passing_evidence() -> dict:
    common = {"status": "PASS", "observed_at": "2026-09-20T03:00:00Z"}
    return {
        "ag_requirement_closures": {
            **common,
            "requirement_count": 33,
            "issue_count": 0,
        },
        "contract_validation": {
            **common,
            "schema_count": 81,
            "openapi_count": 7,
            "negative_fixture_count": 95,
        },
        "unit_regression": {
            **common,
            "passed_tests": 6209,
            "failed_tests": 0,
        },
        "statement_coverage": {**common, "percent": 98.83},
        "branch_coverage": {**common, "percent": 96.43},
        "postgres_smoke": {
            **common,
            "backend": "postgresql",
            "database": "nex_ag_test",
            "zero_residue": True,
        },
        "privacy_failure_runbooks": {**common, "runbook_count": 27},
        "cx_transition_handoff": {
            **common,
            "target_service": "nex-cx",
            "manifest_status": "SEALED",
        },
    }


class StaticProvider:
    def __init__(self, evidence: dict) -> None:
        self.evidence = evidence

    def collect(self, *, observed_at: datetime) -> dict:
        assert observed_at == NOW
        return self.evidence


class FailingProvider:
    def collect(self, *, observed_at: datetime) -> dict:
        raise RuntimeError("private provider failure")


def _client(provider=None) -> TestClient:
    app = build_service_app(SERVICE_SPECS["nex-ag"])
    register_ag_mvp_acceptance_routes(
        app,
        evidence_provider=provider,
        clock=lambda: NOW,
    )
    return TestClient(app)


def _admin_headers() -> dict[str, str]:
    token = issue_mock_user_token(
        tenant_id="local-tenant",
        user_id="employee-0001",
        audience="nex-ag",
        roles=["admin"],
    ).access_token
    return {
        "Authorization": f"Bearer {token}",
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def test_admin_reads_server_selected_accepted_projection() -> None:
    response = _client(StaticProvider(_passing_evidence())).get(
        AG_MVP_ACCEPTANCE_OPERATIONS_PATH,
        headers=_admin_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ACCEPTED"
    assert payload["transition_status"] == "READY_FOR_CX"
    assert payload["evidence_source_status"] == "COLLECTED"
    assert payload["server_selected"] is True
    assert payload["request_trace_id"] == TRACE_ID
    assert "passed_tests" not in str(payload)


def test_repository_provider_is_partial_and_fail_closed() -> None:
    provider = RepositoryAgMvpAcceptanceEvidenceProvider()
    evidence = provider.collect(observed_at=NOW)

    assert evidence == {
        "ag_requirement_closures": {
            "status": "PASS",
            "observed_at": "2026-09-20T03:00:00Z",
            "requirement_count": 33,
            "issue_count": 0,
        }
    }
    payload = _client().get(
        AG_MVP_ACCEPTANCE_OPERATIONS_PATH,
        headers=_admin_headers(),
    ).json()
    assert payload["status"] == "BLOCKED"
    assert payload["summary"]["passed_gate_count"] == 1
    assert payload["summary"]["blocked_gate_count"] == 7


def test_service_principal_can_read_acceptance() -> None:
    token = issue_mock_service_token(
        service_id="nex-oa", audience="nex-ag"
    ).access_token

    response = _client(StaticProvider(_passing_evidence())).get(
        AG_MVP_ACCEPTANCE_OPERATIONS_PATH,
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ACCEPTED"


def test_viewer_and_missing_credentials_are_rejected() -> None:
    viewer = issue_mock_user_token(
        tenant_id="local-tenant",
        user_id="employee-0002",
        audience="nex-ag",
        roles=["viewer"],
    ).access_token
    client = _client(StaticProvider(_passing_evidence()))

    forbidden = client.get(
        AG_MVP_ACCEPTANCE_OPERATIONS_PATH,
        headers={"Authorization": f"Bearer {viewer}"},
    )
    unauthorized = client.get(AG_MVP_ACCEPTANCE_OPERATIONS_PATH)

    assert forbidden.status_code == 403
    assert forbidden.json()["error_code"] == (
        "AG_MVP_ACCEPTANCE_ADMIN_ROLE_REQUIRED"
    )
    assert unauthorized.status_code == 401


def test_provider_failure_is_redacted_and_blocks_all_gates() -> None:
    response = _client(FailingProvider()).get(
        AG_MVP_ACCEPTANCE_OPERATIONS_PATH,
        headers=_admin_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "BLOCKED"
    assert payload["evidence_source_status"] == "UNAVAILABLE"
    assert payload["summary"]["blocked_gate_count"] == 8
    assert "private provider failure" not in str(payload)


def test_route_is_read_only_and_rejects_posted_evidence() -> None:
    response = _client(StaticProvider(_passing_evidence())).post(
        AG_MVP_ACCEPTANCE_OPERATIONS_PATH,
        headers=_admin_headers(),
        json=_passing_evidence(),
    )

    assert response.status_code == 405


def test_repository_provider_rejects_naive_observation_time() -> None:
    provider = RepositoryAgMvpAcceptanceEvidenceProvider()

    try:
        provider.collect(observed_at=datetime(2026, 9, 20, 3, 0))
    except ValueError as exc:
        assert "timezone-aware" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("naive time must be rejected")
