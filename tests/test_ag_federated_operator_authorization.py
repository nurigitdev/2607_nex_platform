from __future__ import annotations

import base64
import json

from fastapi import FastAPI, Header, Request
from fastapi.testclient import TestClient
import pytest

from nex_ag.federated_operator_authorization import (
    AG_FEDERATED_AUTHORIZATION_AUDIT_STATE_KEY,
    ag_federated_authorization_audit_from_request,
)
from nex_ag.federated_operator_context import (
    AG_FEDERATED_OPERATOR_CONTEXT_HEADER,
    AgFederatedOperatorContextError,
    ag_federated_operator_context_from_request,
    decode_ag_federated_operator_context_header,
    encode_ag_federated_operator_context_header,
)
from nex_ag.service_auth import authorize_ag_service_or_admin_request
from nex_runtime import issue_mock_service_token, issue_mock_user_token
import run_ag_federated_authorization_hardening as runner


def _context(**overrides: object) -> dict[str, object]:
    return {
        "tenant_id": "company",
        "subject_id": "employee-1001",
        "roles": ["admin"],
        "scopes": ["workspace:use"],
        "auth_method": "federated_oidc",
        "session_id_digest": "a" * 64,
        **overrides,
    }


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/admin")
    def admin(
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        denied = authorize_ag_service_or_admin_request(
            request,
            authorization,
            admin_error_code="AG_ADMIN_REQUIRED",
            admin_error_detail="Admin role is required.",
        )
        audit = ag_federated_authorization_audit_from_request(request)
        if denied is not None:
            return denied
        context = ag_federated_operator_context_from_request(request)
        return {
            "authorized": True,
            "context": context.to_wire() if context else None,
            "audit": audit.to_wire() if audit else None,
        }

    return app


def _service_headers(
    *,
    service_id: str = "nex-ae-api",
    context: dict[str, object] | None = None,
) -> dict[str, str]:
    token = issue_mock_service_token(service_id=service_id, audience="nex-ag")
    headers = {"Authorization": f"Bearer {token.access_token}"}
    if context is not None:
        headers[AG_FEDERATED_OPERATOR_CONTEXT_HEADER] = (
            encode_ag_federated_operator_context_header(context)
        )
    return headers


def test_header_round_trip_and_fail_closed_decoding() -> None:
    encoded = encode_ag_federated_operator_context_header(_context())
    assert "=" not in encoded
    assert decode_ag_federated_operator_context_header(encoded).to_wire() == _context()

    too_large_json = base64.urlsafe_b64encode(b'"' + b"x" * 2_100 + b'"').decode().rstrip("=")
    invalid_values = (
        None,
        "",
        " spaced ",
        "not+base64",
        "a" * 4_097,
        base64.urlsafe_b64encode(b"not-json").decode().rstrip("="),
        too_large_json,
    )
    for value in invalid_values:
        with pytest.raises(AgFederatedOperatorContextError):
            decode_ag_federated_operator_context_header(value)


def test_ae_admin_context_is_authorized_and_audited() -> None:
    response = TestClient(_app()).get(
        "/admin", headers=_service_headers(context=_context())
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["context"] == _context()
    assert payload["audit"]["outcome"] == "AUTHORIZED"
    assert payload["audit"]["caller_service_id"] == "nex-ae-api"
    assert payload["audit"]["raw_context_included"] is False
    assert payload["audit"]["external_identity_included"] is False
    serialized = json.dumps(payload).lower()
    assert "authorization" not in serialized
    assert "provider_id" not in serialized


@pytest.mark.parametrize(
    ("headers", "status", "error_code"),
    (
        (
            _service_headers(service_id="nex-cx", context=_context()),
            403,
            "AG_FEDERATED_OPERATOR_CALLER_FORBIDDEN",
        ),
        (
            _service_headers(context=_context(roles=["viewer"])),
            403,
            "AG_ADMIN_REQUIRED",
        ),
        (
            _service_headers(context=_context(scopes=["documents:read"])),
            403,
            "AG_FEDERATED_OPERATOR_SCOPE_REQUIRED",
        ),
    ),
)
def test_federated_authorization_denials(headers, status, error_code) -> None:
    response = TestClient(_app()).get("/admin", headers=headers)
    assert response.status_code == status
    assert response.json()["error_code"] == error_code


def test_malformed_context_and_missing_service_auth_fail_closed() -> None:
    headers = _service_headers()
    headers[AG_FEDERATED_OPERATOR_CONTEXT_HEADER] = "invalid"
    malformed = TestClient(_app()).get("/admin", headers=headers)
    missing = TestClient(_app()).get(
        "/admin",
        headers={AG_FEDERATED_OPERATOR_CONTEXT_HEADER: "invalid"},
    )
    assert malformed.status_code == 401
    assert malformed.json()["error_code"] == "AG_FEDERATED_OPERATOR_CONTEXT_INVALID"
    assert missing.status_code == 401


def test_existing_service_and_admin_user_paths_remain_compatible() -> None:
    service = TestClient(_app()).get("/admin", headers=_service_headers())
    admin = issue_mock_user_token(
        tenant_id="company",
        user_id="employee-1001",
        audience="nex-ag",
        roles=["admin"],
    )
    user = TestClient(_app()).get(
        "/admin", headers={"Authorization": f"Bearer {admin.access_token}"}
    )
    assert service.status_code == 200
    assert service.json()["context"] is None
    assert user.status_code == 200
    assert user.json()["audit"] is None


def test_corrupt_audit_state_is_not_exposed() -> None:
    class State:
        pass

    class FakeRequest:
        state = State()

    setattr(FakeRequest.state, AG_FEDERATED_AUTHORIZATION_AUDIT_STATE_KEY, {})
    assert ag_federated_authorization_audit_from_request(FakeRequest()) is None


def test_runner_and_cli(monkeypatch, capsys) -> None:
    unauthenticated = runner._client().get("/admin")
    assert unauthenticated.status_code == 401
    assert "X-NEX-Audit-Outcome" not in unauthenticated.headers

    evidence = runner.run_ag_federated_authorization_hardening()
    assert evidence["status"] == "PASS"
    assert all(evidence["checks"].values())
    assert runner.summary_line(evidence) == (
        "ag_federated_authorization=pass checks=7/7 next=1289"
    )
    monkeypatch.setattr(
        runner, "run_ag_federated_authorization_hardening", lambda: evidence
    )
    assert runner.main(["--summary"]) == 0
    assert "next=1289" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        runner,
        "run_ag_federated_authorization_hardening",
        lambda: {"status": "FAIL"},
    )
    assert runner.main([]) == 1
