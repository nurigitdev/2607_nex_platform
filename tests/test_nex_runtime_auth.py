from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta

import pytest

from nex_runtime.auth import (
    DEFAULT_SERVICE_SCOPE,
    DEFAULT_USER_SCOPE,
    MOCK_SERVICE_TOKEN_PREFIX,
    MOCK_USER_TOKEN_PREFIX,
    issue_mock_service_token,
    issue_mock_user_token,
    validate_authorization_header,
    validate_mock_service_token,
    validate_mock_user_token,
    validate_user_authorization_header,
)

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)


def test_issue_mock_service_token_returns_wire_claims() -> None:
    issued = issue_mock_service_token(
        service_id="nex-ae-api",
        audience="nex-cx",
        issued_at=NOW,
    )

    assert issued.access_token.startswith(MOCK_SERVICE_TOKEN_PREFIX)
    assert issued.claims.to_wire()["subject"] == "service:nex-ae-api"
    assert issued.claims.to_wire()["scopes"] == [DEFAULT_SERVICE_SCOPE]


def test_issue_mock_user_token_returns_wire_claims() -> None:
    issued = issue_mock_user_token(
        tenant_id="tenant-local",
        user_id="user-local",
        roles=["employee"],
        issued_at=NOW,
    )

    assert issued.access_token.startswith(MOCK_USER_TOKEN_PREFIX)
    assert issued.claims.to_wire()["subject"] == "user:tenant-local:user-local"
    assert issued.claims.to_wire()["audience"] == "nex-ae-api"
    assert issued.claims.to_wire()["scopes"] == [DEFAULT_USER_SCOPE]
    assert issued.claims.to_wire()["roles"] == ["employee"]
    assert issued.claims.to_wire()["token_use"] == "user"


def test_validate_authorization_header_accepts_service_claim() -> None:
    issued = issue_mock_service_token(
        service_id="nex-ae-api",
        audience="nex-cx",
        scopes=[DEFAULT_SERVICE_SCOPE, "generation:request"],
        issued_at=NOW,
    )

    result = validate_authorization_header(
        f"Bearer {issued.access_token}",
        expected_audience="nex-cx",
        required_scopes=[DEFAULT_SERVICE_SCOPE],
        now=NOW + timedelta(seconds=1),
    )

    assert result.ok
    assert result.claims is not None
    assert result.claims.service_id == "nex-ae-api"


def test_validate_user_authorization_header_accepts_user_claim() -> None:
    issued = issue_mock_user_token(
        tenant_id="tenant-local",
        user_id="user-local",
        scopes=[DEFAULT_USER_SCOPE, "documents:upload"],
        roles=["employee"],
        issued_at=NOW,
    )

    result = validate_user_authorization_header(
        f"Bearer {issued.access_token}",
        expected_audience="nex-ae-api",
        required_scopes=[DEFAULT_USER_SCOPE],
        now=NOW + timedelta(seconds=1),
    )

    assert result.ok
    assert result.claims is not None
    assert result.claims.tenant_id == "tenant-local"
    assert result.claims.user_id == "user-local"
    assert result.claims.roles == ("employee",)


def test_validate_authorization_header_rejects_missing_header() -> None:
    result = validate_authorization_header(None)

    assert not result.ok
    assert result.error_code == "AUTHORIZATION_HEADER_MISSING"


def test_validate_user_authorization_header_rejects_missing_header() -> None:
    result = validate_user_authorization_header(None)

    assert not result.ok
    assert result.error_code == "AUTHORIZATION_HEADER_MISSING"


def test_validate_authorization_header_rejects_non_bearer_scheme() -> None:
    result = validate_authorization_header("Basic abc")

    assert not result.ok
    assert result.error_code == "AUTHORIZATION_HEADER_INVALID"


def test_validate_user_authorization_header_rejects_non_bearer_scheme() -> None:
    result = validate_user_authorization_header("Basic abc")

    assert not result.ok
    assert result.error_code == "AUTHORIZATION_HEADER_INVALID"


def test_validate_mock_service_token_rejects_wrong_audience() -> None:
    issued = issue_mock_service_token(
        service_id="nex-ae-api",
        audience="nex-cx",
        issued_at=NOW,
    )

    result = validate_mock_service_token(
        issued.access_token,
        expected_audience="nex-mo",
        now=NOW + timedelta(seconds=1),
    )

    assert not result.ok
    assert result.error_code == "TOKEN_AUDIENCE_INVALID"


def test_validate_mock_user_token_rejects_wrong_audience() -> None:
    issued = issue_mock_user_token(
        tenant_id="tenant-local",
        user_id="user-local",
        issued_at=NOW,
    )

    result = validate_mock_user_token(
        issued.access_token,
        expected_audience="nex-cx",
        now=NOW + timedelta(seconds=1),
    )

    assert not result.ok
    assert result.error_code == "TOKEN_AUDIENCE_INVALID"


def test_validate_mock_service_token_rejects_missing_scope() -> None:
    issued = issue_mock_service_token(
        service_id="nex-ae-api",
        audience="nex-cx",
        scopes=["generation:request"],
        issued_at=NOW,
    )

    result = validate_mock_service_token(
        issued.access_token,
        required_scopes=[DEFAULT_SERVICE_SCOPE],
        now=NOW + timedelta(seconds=1),
    )

    assert not result.ok
    assert result.error_code == "TOKEN_SCOPE_MISSING"


def test_validate_mock_user_token_rejects_missing_scope() -> None:
    issued = issue_mock_user_token(
        tenant_id="tenant-local",
        user_id="user-local",
        scopes=["documents:upload"],
        issued_at=NOW,
    )

    result = validate_mock_user_token(
        issued.access_token,
        required_scopes=[DEFAULT_USER_SCOPE],
        now=NOW + timedelta(seconds=1),
    )

    assert not result.ok
    assert result.error_code == "TOKEN_SCOPE_MISSING"


def test_validate_mock_service_token_rejects_expired_token() -> None:
    issued = issue_mock_service_token(
        service_id="nex-ae-api",
        audience="nex-cx",
        issued_at=NOW,
        ttl_seconds=1,
    )

    result = validate_mock_service_token(issued.access_token, now=NOW + timedelta(seconds=2))

    assert not result.ok
    assert result.error_code == "TOKEN_EXPIRED"


def test_validate_mock_user_token_rejects_expired_token() -> None:
    issued = issue_mock_user_token(
        tenant_id="tenant-local",
        user_id="user-local",
        issued_at=NOW,
        ttl_seconds=1,
    )

    result = validate_mock_user_token(issued.access_token, now=NOW + timedelta(seconds=2))

    assert not result.ok
    assert result.error_code == "TOKEN_EXPIRED"


def test_validate_mock_service_token_rejects_future_token() -> None:
    issued = issue_mock_service_token(
        service_id="nex-ae-api",
        audience="nex-cx",
        issued_at=NOW + timedelta(seconds=10),
    )

    result = validate_mock_service_token(issued.access_token, now=NOW)

    assert not result.ok
    assert result.error_code == "TOKEN_NOT_YET_VALID"


def test_validate_mock_user_token_rejects_future_token() -> None:
    issued = issue_mock_user_token(
        tenant_id="tenant-local",
        user_id="user-local",
        issued_at=NOW + timedelta(seconds=10),
    )

    result = validate_mock_user_token(issued.access_token, now=NOW)

    assert not result.ok
    assert result.error_code == "TOKEN_NOT_YET_VALID"


def test_validate_mock_service_token_rejects_bad_prefix() -> None:
    result = validate_mock_service_token("not-a-token")

    assert not result.ok
    assert result.error_code == "TOKEN_FORMAT_INVALID"


def test_validate_mock_user_token_rejects_bad_prefix_and_service_token() -> None:
    service = issue_mock_service_token(
        service_id="nex-ae-api",
        audience="nex-cx",
        issued_at=NOW,
    )

    assert validate_mock_user_token("not-a-token").error_code == "TOKEN_FORMAT_INVALID"
    result = validate_mock_user_token(service.access_token)

    assert not result.ok
    assert result.error_code == "TOKEN_FORMAT_INVALID"


def test_validate_mock_service_token_rejects_bad_payload() -> None:
    encoded = base64.urlsafe_b64encode(json.dumps(["bad"]).encode("utf-8")).decode("ascii")

    result = validate_mock_service_token(f"{MOCK_SERVICE_TOKEN_PREFIX}{encoded}")

    assert not result.ok
    assert result.error_code == "TOKEN_FORMAT_INVALID"


def test_validate_mock_user_token_rejects_bad_payload_and_roles() -> None:
    encoded = base64.urlsafe_b64encode(json.dumps(["bad"]).encode("utf-8")).decode("ascii")
    bad_roles = base64.urlsafe_b64encode(
        json.dumps(
            {
                "issuer": "nex-oa",
                "subject": "user:tenant-local:user-local",
                "audience": "nex-ae-api",
                "tenant_id": "tenant-local",
                "user_id": "user-local",
                "scopes": [DEFAULT_USER_SCOPE],
                "roles": "employee",
                "issued_at": "2026-08-02T12:00:00Z",
                "expires_at": "2026-08-02T13:00:00Z",
                "token_use": "user",
            }
        ).encode("utf-8")
    ).decode("ascii")

    assert (
        validate_mock_user_token(f"{MOCK_USER_TOKEN_PREFIX}{encoded}").error_code
        == "TOKEN_FORMAT_INVALID"
    )
    assert (
        validate_mock_user_token(f"{MOCK_USER_TOKEN_PREFIX}{bad_roles}").error_code
        == "TOKEN_FORMAT_INVALID"
    )


def test_validate_mock_user_token_rejects_static_claim_mismatches() -> None:
    def token_with(overrides: dict[str, object]) -> str:
        payload = issue_mock_user_token(
            tenant_id="tenant-local",
            user_id="user-local",
            issued_at=NOW,
        ).claims.to_wire()
        payload.update(overrides)
        encoded = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode(
            "ascii"
        )
        return f"{MOCK_USER_TOKEN_PREFIX}{encoded}"

    assert validate_mock_user_token(token_with({"issuer": "other"})).error_code == (
        "TOKEN_ISSUER_INVALID"
    )
    assert validate_mock_user_token(token_with({"token_use": "service"})).error_code == (
        "TOKEN_USE_INVALID"
    )
    assert validate_mock_user_token(token_with({"audience": "unknown"})).error_code == (
        "TOKEN_AUDIENCE_INVALID"
    )
    assert validate_mock_user_token(token_with({"subject": "user:other"})).error_code == (
        "TOKEN_SUBJECT_INVALID"
    )


@pytest.mark.parametrize(
    ("service_id", "audience"),
    [
        ("unknown-service", "nex-cx"),
        ("nex-ae-api", "unknown-service"),
    ],
)
def test_issue_mock_service_token_rejects_unknown_services(
    service_id: str,
    audience: str,
) -> None:
    with pytest.raises(ValueError):
        issue_mock_service_token(service_id=service_id, audience=audience)


def test_issue_mock_service_token_rejects_non_positive_ttl() -> None:
    with pytest.raises(ValueError):
        issue_mock_service_token(
            service_id="nex-ae-api",
            audience="nex-cx",
            ttl_seconds=0,
        )


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"tenant_id": "", "user_id": "user-local"}, "tenant_id"),
        ({"tenant_id": "tenant-local", "user_id": ""}, "user_id"),
        ({"tenant_id": "tenant-local", "user_id": "user-local", "audience": "unknown"}, "audience"),
        ({"tenant_id": "tenant-local", "user_id": "user-local", "ttl_seconds": 0}, "ttl_seconds"),
    ],
)
def test_issue_mock_user_token_rejects_invalid_inputs(
    kwargs: dict[str, object],
    match: str,
) -> None:
    with pytest.raises(ValueError, match=match):
        issue_mock_user_token(**kwargs)
