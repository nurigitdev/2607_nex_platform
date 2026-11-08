from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from nex_oa.memberships import (
    InMemoryOaTenantMembershipRegistry,
    OaMembershipError,
)
from nex_oa.subject_verification import (
    OA_SUBJECT_VERIFICATION_SCHEMA_VERSION,
    OA_SUBJECT_VERIFY_SCOPE,
    OaHumanSubjectVerifier,
    OaSubjectVerificationError,
    _item,
    register_subject_verification_routes,
)
from nex_oa.subjects import InMemoryOaSubjectRegistry, SubjectRegistryError
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    SERVICE_SPECS,
    build_service_app,
    issue_mock_service_token,
)

TENANT = "tenant-p9-s14"


def _verifier() -> tuple[
    OaHumanSubjectVerifier,
    InMemoryOaSubjectRegistry,
    InMemoryOaTenantMembershipRegistry,
]:
    subjects = InMemoryOaSubjectRegistry()
    memberships = InMemoryOaTenantMembershipRegistry(subject_registry=subjects)
    return (
        OaHumanSubjectVerifier(subjects, memberships),
        subjects,
        memberships,
    )


def _seed_subject(
    subjects: InMemoryOaSubjectRegistry,
    *,
    subject_id: str,
    status: str = "ACTIVE",
) -> None:
    subjects.ensure_subject(
        {
            "tenant_id": TENANT,
            "subject_id": subject_id,
            "subject_display_name": subject_id,
            "subject_status": status,
        }
    )


def _seed_membership(
    memberships: InMemoryOaTenantMembershipRegistry,
    *,
    subject_id: str,
    status: str = "ACTIVE",
) -> None:
    memberships.ensure_membership(
        {
            "tenant_id": TENANT,
            "subject_id": subject_id,
            "subject_display_name": subject_id,
            "membership_status": status,
        }
    )


def _headers(
    *,
    caller: str = "nex-wa",
    include_scope: bool = True,
) -> dict[str, str]:
    scopes = [DEFAULT_SERVICE_SCOPE]
    if include_scope:
        scopes.append(OA_SUBJECT_VERIFY_SCOPE)
    token = issue_mock_service_token(
        service_id=caller,
        audience="nex-oa",
        scopes=scopes,
    )
    return {"Authorization": f"Bearer {token.access_token}"}


def test_subject_verification_distinguishes_all_statuses_and_is_deterministic() -> None:
    verifier, subjects, memberships = _verifier()
    _seed_subject(subjects, subject_id="active")
    _seed_membership(memberships, subject_id="active")
    _seed_subject(subjects, subject_id="inactive", status="DISABLED")
    _seed_subject(subjects, subject_id="no-membership")
    _seed_subject(subjects, subject_id="disabled-membership")
    _seed_membership(
        memberships,
        subject_id="disabled-membership",
        status="DISABLED",
    )
    request = {
        "tenant_id": TENANT,
        "subject_ids": [
            "active",
            "inactive",
            "missing",
            "no-membership",
            "disabled-membership",
        ],
    }

    first = verifier.verify_batch(request)
    second = verifier.verify_batch(request)

    assert first == second
    assert first["verification_schema_version"] == (
        OA_SUBJECT_VERIFICATION_SCHEMA_VERSION
    )
    assert first["requested_count"] == 5
    assert first["verified_count"] == 1
    assert first["rejected_count"] == 4
    assert [item["verification_status"] for item in first["results"]] == [
        "VERIFIED",
        "SUBJECT_INACTIVE",
        "SUBJECT_NOT_FOUND",
        "TENANT_MEMBERSHIP_MISSING",
        "TENANT_MEMBERSHIP_MISSING",
    ]
    assert first["results"][0] == {
        "subject_id": "active",
        "verification_status": "VERIFIED",
        "subject_revision": 1,
        "tenant_membership_revision": 1,
    }
    assert set(first["results"][2]) == {"subject_id", "verification_status"}
    assert first["verification_evidence_hash"].startswith("sha256:")


@pytest.mark.parametrize(
    ("payload", "detail"),
    [
        ([], "request must be an object"),
        ({"tenant_id": TENANT, "subject_ids": ["a"], "extra": 1}, "unsupported"),
        ({"tenant_id": "bad tenant", "subject_ids": ["a"]}, "tenant_id"),
        ({"tenant_id": TENANT, "subject_ids": "a"}, "must be an array"),
        ({"tenant_id": TENANT, "subject_ids": []}, "between 1 and 50"),
        (
            {"tenant_id": TENANT, "subject_ids": [f"s-{index}" for index in range(51)]},
            "between 1 and 50",
        ),
        ({"tenant_id": TENANT, "subject_ids": ["bad value"]}, "invalid subject"),
        ({"tenant_id": TENANT, "subject_ids": ["same", "same"]}, "unique"),
    ],
)
def test_subject_verification_rejects_invalid_batch_envelopes(
    payload: Any,
    detail: str,
) -> None:
    verifier, _subjects, _memberships = _verifier()
    with pytest.raises(OaSubjectVerificationError) as raised:
        verifier.verify_batch(payload)
    assert raised.value.status_code == 400
    assert detail in raised.value.detail


def test_subject_verification_accepts_batch_boundaries_one_and_fifty() -> None:
    verifier, _subjects, _memberships = _verifier()
    one = verifier.verify_batch({"tenant_id": TENANT, "subject_ids": ["s-0"]})
    fifty = verifier.verify_batch(
        {
            "tenant_id": TENANT,
            "subject_ids": [f"s-{index}" for index in range(50)],
        }
    )
    assert one["requested_count"] == 1
    assert fifty["requested_count"] == 50
    assert fifty["rejected_count"] == 50


class _BrokenSubjectRegistry:
    def get_subject(self, **_kwargs: Any) -> dict[str, Any] | None:
        raise SubjectRegistryError(503, "broken", "broken", True)


class _BrokenMembershipRegistry:
    def get_membership(self, **_kwargs: Any) -> dict[str, Any] | None:
        raise OaMembershipError(503, "broken", "broken", True)


class _StaticSubjectRegistry:
    def __init__(self, snapshot: dict[str, Any]) -> None:
        self.snapshot = snapshot

    def get_subject(self, **_kwargs: Any) -> dict[str, Any] | None:
        return self.snapshot


class _StaticMembershipRegistry:
    def __init__(self, snapshot: dict[str, Any] | None) -> None:
        self.snapshot = snapshot

    def get_membership(self, **_kwargs: Any) -> dict[str, Any] | None:
        return self.snapshot


def test_subject_verification_fails_closed_on_dependency_and_projection_errors() -> None:
    with pytest.raises(OaSubjectVerificationError, match="SubjectRegistryError"):
        OaHumanSubjectVerifier(
            _BrokenSubjectRegistry(),  # type: ignore[arg-type]
            _StaticMembershipRegistry(None),  # type: ignore[arg-type]
        ).verify_batch({"tenant_id": TENANT, "subject_ids": ["subject"]})

    subject = {
        "subject": {"status": "ACTIVE", "revision": 1},
    }
    with pytest.raises(OaSubjectVerificationError, match="OaMembershipError"):
        OaHumanSubjectVerifier(
            _StaticSubjectRegistry(subject),  # type: ignore[arg-type]
            _BrokenMembershipRegistry(),  # type: ignore[arg-type]
        ).verify_batch({"tenant_id": TENANT, "subject_ids": ["subject"]})

    malformed_cases = [
        ({"subject": "bad"}, None),
        ({"subject": {"status": "ACTIVE", "revision": 0}}, None),
        (subject, {"membership": "bad"}),
        (subject, {"membership": {"status": "ACTIVE", "revision": False}}),
    ]
    for subject_snapshot, membership_snapshot in malformed_cases:
        with pytest.raises(OaSubjectVerificationError) as raised:
            OaHumanSubjectVerifier(
                _StaticSubjectRegistry(subject_snapshot),  # type: ignore[arg-type]
                _StaticMembershipRegistry(membership_snapshot),  # type: ignore[arg-type]
            ).verify_batch({"tenant_id": TENANT, "subject_ids": ["subject"]})
        assert raised.value.status_code == 503
        assert raised.value.retryable is True

    with pytest.raises(ValueError, match="unknown subject verification status"):
        _item("subject", "UNKNOWN")


def test_protected_subject_verification_route_enforces_scope_caller_and_errors() -> None:
    verifier, subjects, memberships = _verifier()
    _seed_subject(subjects, subject_id="active")
    _seed_membership(memberships, subject_id="active")
    app = build_service_app(SERVICE_SPECS["nex-oa"])
    register_subject_verification_routes(app, verifier=verifier)
    client = TestClient(app)
    path = "/internal/v1/identity/subjects:verify-batch"
    payload = {"tenant_id": TENANT, "subject_ids": ["active"]}

    missing = client.post(path, json=payload)
    wrong_scope = client.post(path, headers=_headers(include_scope=False), json=payload)
    wrong_caller = client.post(path, headers=_headers(caller="nex-ae-api"), json=payload)
    invalid = client.post(path, headers=_headers(), json={"tenant_id": TENANT, "subject_ids": []})
    accepted = client.post(path, headers=_headers(), json=payload)

    assert missing.status_code == 401
    assert wrong_scope.status_code == 401
    assert wrong_scope.json()["error_code"] == "TOKEN_SCOPE_MISSING"
    assert wrong_caller.status_code == 403
    assert wrong_caller.json()["error_code"] == "OA_SUBJECT_VERIFY_CALLER_FORBIDDEN"
    assert invalid.status_code == 400
    assert invalid.json()["error_code"] == "oa.subject_verification_request_invalid"
    assert accepted.status_code == 200
    assert accepted.json()["verified_count"] == 1
    assert accepted.json()["request_id"]
    assert accepted.json()["trace_id"]


def test_protected_subject_verification_route_maps_dependency_unavailable() -> None:
    verifier = OaHumanSubjectVerifier(
        _BrokenSubjectRegistry(),  # type: ignore[arg-type]
        _StaticMembershipRegistry(None),  # type: ignore[arg-type]
    )
    app = build_service_app(SERVICE_SPECS["nex-oa"])
    register_subject_verification_routes(app, verifier=verifier)
    response = TestClient(app).post(
        "/internal/v1/identity/subjects:verify-batch",
        headers=_headers(),
        json={"tenant_id": TENANT, "subject_ids": ["subject"]},
    )
    assert response.status_code == 503
    assert response.json()["error_code"] == "oa.subject_verification_unavailable"
    assert response.json()["retryable"] is True


def test_oa_entrypoint_registers_subject_verification_route() -> None:
    from nex_oa import main

    paths = {getattr(route, "path", "") for route in main.app.routes}
    assert "/internal/v1/identity/subjects:verify-batch" in paths
