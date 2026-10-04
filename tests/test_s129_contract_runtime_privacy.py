from __future__ import annotations

from fastapi import FastAPI, Header, Request
from fastapi.testclient import TestClient
import pytest

from nex_ag.federated_operator_authorization import (
    AgFederatedAuthorizationTelemetry,
)
from nex_ag.federated_operator_context import (
    AG_FEDERATED_OPERATOR_CONTEXT_HEADER,
    encode_ag_federated_operator_context_header,
)
from nex_ag.federated_operator_operations import (
    AG_FEDERATED_AUTH_RUNTIME_PATH,
    attach_ag_federated_authorization_telemetry,
    register_ag_federated_operator_runtime_routes,
)
from nex_ag.service_auth import authorize_ag_service_or_admin_request
from nex_runtime import issue_mock_service_token
import run_s129_contract_runtime_privacy as runner


def _context(*, roles=None, scopes=None):
    return {
        "tenant_id": "company",
        "subject_id": "employee-1001",
        "roles": roles if roles is not None else ["admin"],
        "scopes": scopes if scopes is not None else ["workspace:use"],
        "auth_method": "federated_oidc",
        "session_id_digest": "a" * 64,
    }


def _token(service_id: str = "nex-ae-api") -> str:
    return issue_mock_service_token(
        service_id=service_id,
        audience="nex-ag",
    ).access_token


def _headers(context, *, service_id: str = "nex-ae-api"):
    return {
        "Authorization": f"Bearer {_token(service_id)}",
        AG_FEDERATED_OPERATOR_CONTEXT_HEADER: (
            encode_ag_federated_operator_context_header(context)
        ),
    }


def _app() -> tuple[FastAPI, AgFederatedAuthorizationTelemetry]:
    app = FastAPI()
    telemetry = attach_ag_federated_authorization_telemetry(app)

    @app.post("/action")
    def action(
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        denied = authorize_ag_service_or_admin_request(
            request,
            authorization,
            admin_error_code="AG_ADMIN_REQUIRED",
            admin_error_detail="Admin role is required.",
        )
        return denied or {"accepted": True}

    register_ag_federated_operator_runtime_routes(app, telemetry=telemetry)
    return app, telemetry


def test_runtime_telemetry_counts_each_bounded_outcome() -> None:
    app, telemetry = _app()
    client = TestClient(app)
    assert client.post("/action", headers=_headers(_context())).status_code == 200
    assert client.post(
        "/action", headers=_headers(_context(), service_id="nex-cx")
    ).status_code == 403
    malformed = {
        "Authorization": f"Bearer {_token()}",
        AG_FEDERATED_OPERATOR_CONTEXT_HEADER: "invalid",
    }
    assert client.post("/action", headers=malformed).status_code == 401
    assert client.post(
        "/action", headers=_headers(_context(scopes=["documents:read"]))
    ).status_code == 403
    assert client.post(
        "/action", headers=_headers(_context(roles=["viewer"]))
    ).status_code == 403

    runtime = client.get(
        AG_FEDERATED_AUTH_RUNTIME_PATH,
        headers={"Authorization": f"Bearer {_token()}"},
    )
    assert runtime.status_code == 200
    assert runtime.json()["counts"] == {
        "authorized": 1,
        "denied_caller": 1,
        "denied_context": 1,
        "denied_scope": 1,
        "denied_role": 1,
    }
    assert runtime.json()["subject_identifiers_included"] is False
    assert telemetry.public_snapshot()["counts"] == runtime.json()["counts"]


def test_runtime_route_is_protected_and_telemetry_rejects_unknown_outcome() -> None:
    app, telemetry = _app()
    assert TestClient(app).get(AG_FEDERATED_AUTH_RUNTIME_PATH).status_code == 401
    with pytest.raises(ValueError):
        telemetry.record("private-subject")


def test_attach_replaces_stale_runtime_state() -> None:
    app = FastAPI()
    first = attach_ag_federated_authorization_telemetry(app)
    second = attach_ag_federated_authorization_telemetry(app)
    assert second is not first


def test_contract_runtime_privacy_runner_and_cli(monkeypatch, capsys, tmp_path) -> None:
    assert runner._contains_key(
        {"safe": [{"subject_id": "private"}]}, {"subject_id"}
    )
    assert not runner._contains_key(
        {"subject_identifiers_included": False}, {"subject_id"}
    )
    evidence = runner.run_s129_contract_runtime_privacy()
    assert evidence["status"] == "PASS"
    assert all(evidence["checks"].values())
    assert evidence["oa_drift"]["drift_count"] == 21
    assert runner.summary_line(evidence).startswith(
        "s129_contract_runtime_privacy=pass checks=8/8"
    )

    blocked = runner.run_s129_contract_runtime_privacy(tmp_path)
    assert blocked["status"] == "FAIL"
    monkeypatch.setattr(runner, "run_s129_contract_runtime_privacy", lambda: evidence)
    assert runner.main(["--summary"]) == 0
    assert "next=1290" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        runner, "run_s129_contract_runtime_privacy", lambda: {"status": "FAIL"}
    )
    assert runner.main([]) == 1
