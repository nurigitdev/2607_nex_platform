from __future__ import annotations

import pytest

from nex_oa.service_principals import (
    OaServicePrincipalError,
    normalize_audiences,
    normalize_credential_status,
    normalize_scopes,
    normalize_service_id,
    normalize_service_principal_id,
    plan_credential_issue,
    plan_credential_status_transition,
    plan_service_principal_upsert,
)


def _principal(**overrides: object) -> dict[str, object]:
    return {
        "principal_id": "ae-runtime",
        "service_id": "nex-ae-api",
        "display_name": "AE Runtime",
        "status": "ACTIVE",
        "allowed_audiences": ["nex-cx", "nex-oa"],
        "allowed_scopes": ["document:read", "generation:create"],
        "revision": 1,
        **overrides,
    }


def _credential(**overrides: object) -> dict[str, object]:
    return {
        "credential_id": "cred-1",
        "principal_id": "ae-runtime",
        "status": "ACTIVE",
        "revision": 2,
        "grace_until": None,
        **overrides,
    }


def test_plan_service_principal_create_and_update() -> None:
    created = plan_service_principal_upsert(
        {**_principal(), "expected_revision": 0}
    )
    updated = plan_service_principal_upsert(
        {
            **created,
            "display_name": " AE Runtime Updated ",
            "allowed_audiences": ["nex-oa", "nex-cx", "nex-cx"],
            "expected_revision": 1,
        },
        current=created,
    )

    assert created["revision"] == 1
    assert created["allowed_audiences"] == ("nex-cx", "nex-oa")
    assert updated["display_name"] == "AE Runtime Updated"
    assert updated["previous_revision"] == 1
    assert updated["revision"] == 2


def test_principal_identity_and_revision_are_guarded() -> None:
    with pytest.raises(OaServicePrincipalError) as identity:
        plan_service_principal_upsert(
            {**_principal(principal_id="changed"), "expected_revision": 1},
            current=_principal(),
        )
    with pytest.raises(OaServicePrincipalError) as revision:
        plan_service_principal_upsert(
            {**_principal(), "expected_revision": 0}, current=_principal()
        )

    assert identity.value.error_code == "oa.service_principal_identity_immutable"
    assert revision.value.status_code == 409
    assert revision.value.error_code == "oa.service_principal_revision_conflict"


@pytest.mark.parametrize(
    "payload",
    [
        {"principal_id": None},
        {"principal_id": "A"},
        {"service_id": "unknown"},
        {"display_name": " "},
        {"display_name": "x" * 129},
        {"status": "deleted"},
        {"allowed_audiences": "nex-cx"},
        {"allowed_audiences": []},
        {"allowed_scopes": "document:read"},
        {"allowed_scopes": []},
        {"allowed_scopes": ["invalid"]},
        {"expected_revision": True},
        {"expected_revision": " 0"},
    ],
)
def test_principal_contract_rejects_invalid_fields(payload: dict[str, object]) -> None:
    with pytest.raises(OaServicePrincipalError) as caught:
        plan_service_principal_upsert(
            {**_principal(), **payload, "expected_revision": payload.get("expected_revision", 0)}
        )

    assert caught.value.status_code == 400
    assert str(caught.value)


def test_normalizers_are_canonical_and_fail_closed() -> None:
    assert normalize_service_principal_id(" AE.Runtime ") == "ae.runtime"
    assert normalize_service_id(" NEX-CX ") == "nex-cx"
    assert normalize_audiences(["nex-oa", " NEX-CX "]) == ("nex-cx", "nex-oa")
    assert normalize_scopes([" Document:Read ", "document:read"]) == (
        "document:read",
    )
    assert normalize_credential_status(" rotating ") == "ROTATING"

    with pytest.raises(OaServicePrincipalError):
        normalize_service_id(42)
    with pytest.raises(OaServicePrincipalError):
        normalize_credential_status(None)
    with pytest.raises(OaServicePrincipalError):
        normalize_audiences([42])


def test_credential_issue_contract() -> None:
    issued = plan_credential_issue(
        {"credential_id": "cred-1", "lifetime_days": 30},
        principal=_principal(),
        active_credential_count=1,
        now_epoch=1_000,
    )

    assert issued["status"] == "ACTIVE"
    assert issued["issued_at"] == 1_000
    assert issued["expires_at"] == 1_000 + 30 * 86_400
    assert issued["revision"] == 1


@pytest.mark.parametrize(
    ("principal", "count", "lifetime", "error_code"),
    [
        (_principal(status="DISABLED"), 0, 30, "oa.service_principal_disabled"),
        (_principal(), 2, 30, "oa.service_credential_active_limit"),
        (_principal(), -1, 30, "oa.service_principal_active_credential_count_invalid"),
        (_principal(), 0, 0, "oa.service_principal_lifetime_days_invalid"),
        (_principal(), 0, 91, "oa.service_principal_lifetime_days_invalid"),
    ],
)
def test_credential_issue_fails_closed(
    principal: dict[str, object], count: object, lifetime: object, error_code: str
) -> None:
    with pytest.raises(OaServicePrincipalError) as caught:
        plan_credential_issue(
            {"credential_id": "cred-1", "lifetime_days": lifetime},
            principal=principal,
            active_credential_count=count,
            now_epoch=1_000,
        )

    assert caught.value.error_code == error_code


def test_credential_transition_rotation_revocation_and_idempotency() -> None:
    rotating = plan_credential_status_transition(
        _credential(),
        target_status="ROTATING",
        expected_revision=2,
        now_epoch=2_000,
        grace_seconds=3_600,
    )
    revoked = plan_credential_status_transition(
        _credential(status="ROTATING", revision=3, grace_until=5_600),
        target_status="REVOKED",
        expected_revision=3,
        now_epoch=3_000,
    )
    unchanged = plan_credential_status_transition(
        _credential(),
        target_status="ACTIVE",
        expected_revision=2,
        now_epoch=3_000,
    )

    assert rotating["grace_until"] == 5_600
    assert rotating["revision"] == 3
    assert revoked["grace_until"] is None
    assert revoked["status"] == "REVOKED"
    assert unchanged["changed"] is False
    assert unchanged["changed_at"] is None
    assert unchanged["revision"] == 2


@pytest.mark.parametrize(
    ("credential", "target", "expected", "grace", "error_code"),
    [
        (_credential(), "ROTATING", 1, 1, "oa.service_credential_revision_conflict"),
        (_credential(status="REVOKED"), "ACTIVE", 2, None, "oa.service_credential_transition_invalid"),
        (_credential(), "ROTATING", 2, None, "oa.service_principal_grace_seconds_invalid"),
        (_credential(), "ROTATING", 2, 86_401, "oa.service_principal_grace_seconds_invalid"),
        (_credential(), "REVOKED", 2, 1, "oa.service_principal_grace_seconds_invalid"),
    ],
)
def test_credential_transition_fails_closed(
    credential: dict[str, object],
    target: object,
    expected: object,
    grace: object,
    error_code: str,
) -> None:
    with pytest.raises(OaServicePrincipalError) as caught:
        plan_credential_status_transition(
            credential,
            target_status=target,
            expected_revision=expected,
            now_epoch=2_000,
            grace_seconds=grace,
        )

    assert caught.value.error_code == error_code
