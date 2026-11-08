from __future__ import annotations

import json
from datetime import UTC, datetime
from io import BytesIO
from urllib.error import HTTPError, URLError

import pytest
from nex_eos import (
    AuthorizationSubjectDenied,
    EosAuthorizationError,
    EosAuthorizationTarget,
    EosVoucherAuthorizationClient,
    HttpOaAuthorizationSource,
)
from nex_eos import authorization as module

NOW = datetime(2026, 10, 21, 1, 2, 3, tzinfo=UTC)


class Source:
    def __init__(self, value=None, error=None):
        self.value = value or {
            "active": True,
            "tenant_id": "tenant-a",
            "subject_id": "employee-1001",
            "scopes": ["finance:voucher-draft:create"],
            "revision_hash": "a" * 64,
        }
        self.error = error
        self.calls = []

    def effective_authorization(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.value


def _target(**overrides):
    values = {
        "tenant_id": "tenant-a",
        "subject_id": "employee-1001",
        "service_subject": "nex-ae-api",
        "service_audience": "nex-eos",
        "service_scopes": ("service:call",),
        "project_id": "project-1001",
        "org_unit_id": "finance-team",
        "resource_type": "voucher_draft",
        "resource_id": "operation-1001",
    }
    values.update(overrides)
    return EosAuthorizationTarget(**values)


def test_authorize_create_preserves_metadata_safe_fresh_evidence():
    source = Source()
    evidence = EosVoucherAuthorizationClient(source, clock=lambda: NOW).authorize_create(
        _target()
    )
    assert source.calls == [
        {"tenant_id": "tenant-a", "subject_id": "employee-1001"}
    ]
    assert evidence.authorization_revision_hash == "a" * 64
    assert evidence.authorization_checked_at == NOW
    assert evidence.to_metadata()["project_id"] == "project-1001"
    assert "token" not in evidence.to_metadata()


def test_explicit_project_org_and_resource_constraints_must_match():
    value = {
        **Source().value,
        "project_ids": ["project-1001"],
        "org_unit_ids": ["finance-team"],
        "resource_refs": ["voucher_draft:operation-1001"],
    }
    assert EosVoucherAuthorizationClient(Source(value)).authorize_create(_target())
    for field, denied_value in (
        ("project_ids", ["other"]),
        ("org_unit_ids", ["other"]),
        ("resource_refs", ["voucher_draft:other"]),
    ):
        with pytest.raises(EosAuthorizationError) as denied:
            EosVoucherAuthorizationClient(
                Source({**value, field: denied_value})
            ).authorize_create(_target())
        assert denied.value.error_code == "EOS_AUTHORIZATION_DENIED"

    no_org = {key: item for key, item in value.items() if key != "org_unit_ids"}
    evidence = EosVoucherAuthorizationClient(Source(no_org)).authorize_create(
        _target(org_unit_id=None)
    )
    assert evidence.org_unit_id is None


@pytest.mark.parametrize(
    "value",
    (
        None,
        {"active": False},
        {**Source().value, "tenant_id": "tenant-b"},
        {**Source().value, "subject_id": "other"},
        {**Source().value, "scopes": []},
        {**Source().value, "scopes": "finance:voucher-draft:create"},
        {**Source().value, "revision_hash": "bad"},
        {**Source().value, "project_ids": [""]},
    ),
)
def test_inactive_malformed_and_scope_mismatch_fail_closed(value):
    source = Source()
    source.value = value
    with pytest.raises(EosAuthorizationError) as denied:
        EosVoucherAuthorizationClient(source).authorize_create(_target())
    assert denied.value.error_code == "EOS_AUTHORIZATION_DENIED"
    assert denied.value.status_code == 403


@pytest.mark.parametrize(
    "overrides",
    (
        {"service_audience": "nex-cx"},
        {"service_scopes": ()},
        {"service_scopes": "service:call"},
        {"service_scopes": ("service:call", " bad")},
        {"subject_id": "bad value"},
        {"org_unit_id": "bad value"},
    ),
)
def test_service_trust_and_target_validation_precede_oa(overrides):
    source = Source()
    with pytest.raises(EosAuthorizationError):
        EosVoucherAuthorizationClient(source).authorize_create(_target(**overrides))
    assert source.calls == []


def test_typed_denial_and_dependency_failure_are_distinct():
    with pytest.raises(EosAuthorizationError) as denied:
        EosVoucherAuthorizationClient(
            Source(error=AuthorizationSubjectDenied("inactive"))
        ).authorize_create(_target())
    assert denied.value.status_code == 403
    assert denied.value.retryable is False

    with pytest.raises(EosAuthorizationError) as unavailable:
        EosVoucherAuthorizationClient(
            Source(error=RuntimeError("private endpoint"))
        ).authorize_create(_target())
    assert unavailable.value.status_code == 503
    assert unavailable.value.retryable is True
    assert "private endpoint" not in unavailable.value.detail


def test_clock_and_target_type_fail_closed():
    with pytest.raises(EosAuthorizationError) as invalid:
        EosVoucherAuthorizationClient(Source()).authorize_create({})
    assert invalid.value.status_code == 422
    with pytest.raises(EosAuthorizationError) as bad_clock:
        EosVoucherAuthorizationClient(
            Source(), clock=lambda: datetime(2026, 1, 1)
        ).authorize_create(_target())
    assert bad_clock.value.error_code == "EOS_AUTHORIZATION_CLOCK_INVALID"


class Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return json.dumps(self.payload).encode()


def test_http_source_calls_oa_with_service_token(monkeypatch):
    calls = []

    def open_request(request, timeout):
        calls.append((request, timeout))
        return Response({"authorization": Source().value})

    monkeypatch.setattr(module, "urlopen", open_request)
    result = HttpOaAuthorizationSource(
        base_url="http://oa/", service_token="service-token", timeout_seconds=7
    ).effective_authorization(tenant_id="tenant a", subject_id="employee/1")
    assert result["active"] is True
    assert calls[0][1] == 7
    assert "tenant%20a" in calls[0][0].full_url
    assert "employee%2F1" in calls[0][0].full_url
    assert calls[0][0].headers["Authorization"] == "Bearer service-token"
    assert calls[0][0].headers["Cache-control"] == "no-store, max-age=0"
    assert calls[0][0].headers["Pragma"] == "no-cache"


@pytest.mark.parametrize(
    "error_code",
    ("oa.authorization_membership_inactive", "oa.authorization_membership_not_found"),
)
def test_http_source_preserves_oa_subject_denial(monkeypatch, error_code):
    error = HTTPError(
        "http://oa",
        403,
        "denied",
        {},
        BytesIO(json.dumps({"error_code": error_code}).encode()),
    )
    monkeypatch.setattr(module, "urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(error))
    with pytest.raises(AuthorizationSubjectDenied):
        HttpOaAuthorizationSource(
            base_url="http://oa", service_token="token"
        ).effective_authorization(tenant_id="tenant", subject_id="subject")


@pytest.mark.parametrize(
    "effect",
    (
        HTTPError("http://oa", 500, "error", {}, BytesIO(b"not-json")),
        URLError("offline"),
        TimeoutError(),
    ),
)
def test_http_source_transport_failures_are_unavailable(monkeypatch, effect):
    monkeypatch.setattr(module, "urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(effect))
    with pytest.raises(RuntimeError):
        HttpOaAuthorizationSource(
            base_url="http://oa", service_token="token"
        ).effective_authorization(tenant_id="tenant", subject_id="subject")


def test_http_error_with_non_object_problem_is_generic_failure(monkeypatch):
    error = HTTPError(
        "http://oa", 500, "error", {}, BytesIO(json.dumps([]).encode())
    )
    monkeypatch.setattr(
        module,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(error),
    )
    with pytest.raises(RuntimeError, match="HTTP 500"):
        HttpOaAuthorizationSource(
            base_url="http://oa", service_token="token"
        ).effective_authorization(tenant_id="tenant", subject_id="subject")


def test_http_source_rejects_missing_token_and_malformed_payload(monkeypatch):
    with pytest.raises(RuntimeError):
        HttpOaAuthorizationSource(
            base_url="http://oa", service_token=" "
        ).effective_authorization(tenant_id="tenant", subject_id="subject")
    monkeypatch.setattr(module, "urlopen", lambda *_args, **_kwargs: Response([]))
    with pytest.raises(AuthorizationSubjectDenied):
        HttpOaAuthorizationSource(
            base_url="http://oa", service_token="token"
        ).effective_authorization(tenant_id="tenant", subject_id="subject")
