from __future__ import annotations

from nex_oa.service_principal_boundary import (
    PROPOSED_TABLES,
    S126_SERVICE_PRINCIPAL_HANDOFF,
    validate_service_credential_record,
    validate_service_principal_spec,
)


def _principal(**changes: object) -> dict[str, object]:
    return {
        "principal_id": "principal-1",
        "service_id": "nex-ae-api",
        "display_name": "NeX AE API",
        "status": "ACTIVE",
        "allowed_audiences": ["nex-oa", "nex-cx"],
        "allowed_scopes": ["service:call", "document:read"],
        "revision": 1,
    } | changes


def _credential(**changes: object) -> dict[str, object]:
    return {
        "credential_id": "credential-1",
        "principal_id": "principal-1",
        "secret_hash": "$argon2id$v=19$m=65536,t=3,p=4$hash",
        "secret_hint": "a1b2",
        "status": "ACTIVE",
        "issued_at": 1_000,
        "expires_at": 1_000 + 90 * 86_400,
        "grace_until": 1_000 + 86_400,
        "revision": 1,
    } | changes


def test_s126_handoff_freezes_credential_and_storage_boundaries() -> None:
    handoff = S126_SERVICE_PRINCIPAL_HANDOFF

    assert handoff.owner == "nex-oa"
    assert handoff.implementation_requirement == "S126"
    assert handoff.proposed_tables == PROPOSED_TABLES
    assert max(map(len, PROPOSED_TABLES)) < 30
    assert handoff.credential_hash_algorithm == "argon2id"
    assert handoff.maximum_credential_lifetime_days == 90
    assert handoff.maximum_rotation_grace_seconds == 86_400
    assert handoff.maximum_simultaneous_active_credentials == 2
    assert handoff.database_plaintext_secret_allowed is False
    assert handoff.silent_default_audience_or_scope_allowed is False
    assert handoff.to_wire()["token_ttl_seconds"] == 300


def test_valid_principal_and_credential_shapes_pass() -> None:
    assert validate_service_principal_spec(_principal()) == ()
    assert validate_service_credential_record(_credential()) == ()


def test_missing_fields_fail_closed() -> None:
    principal_errors = validate_service_principal_spec({})
    credential_errors = validate_service_credential_record({})

    assert "field_missing:principal_id" in principal_errors
    assert "field_missing:allowed_scopes" in principal_errors
    assert "field_missing:credential_id" in credential_errors
    assert "field_missing:secret_hash" in credential_errors


def test_principal_scalar_allowlist_and_revision_errors_are_explicit() -> None:
    errors = validate_service_principal_spec(
        _principal(
            principal_id=" principal ",
            display_name=1,
            service_id="unknown",
            status="UNKNOWN",
            allowed_audiences=["nex-cx", "nex-cx", "outside"],
            allowed_scopes=["service:call", ""],
            revision=True,
        )
    )

    assert "principal_invalid:principal_id" in errors
    assert "principal_invalid:display_name" in errors
    assert "principal_service_id_unknown" in errors
    assert "principal_status_invalid" in errors
    assert "principal_audiences_duplicate" in errors
    assert "principal_audiences_unknown" in errors
    assert "principal_scopes_invalid" in errors
    assert "principal_revision_invalid" in errors


def test_empty_and_wrong_allowlists_are_rejected() -> None:
    assert "principal_audiences_invalid" in validate_service_principal_spec(
        _principal(allowed_audiences=[])
    )
    assert "principal_scopes_invalid" in validate_service_principal_spec(
        _principal(allowed_scopes="service:call")
    )


def test_credential_scalar_hash_status_and_forbidden_fields_are_rejected() -> None:
    errors = validate_service_credential_record(
        _credential(
            credential_id=" credential ",
            principal_id=1,
            secret_hash="$pbkdf2$hash",
            secret_hint="too-long-hint",
            status="UNKNOWN",
            revision=0,
            client_secret="plaintext",
            access_token="token",
        )
    )

    assert "credential_invalid:credential_id" in errors
    assert "credential_invalid:principal_id" in errors
    assert "credential_hash_algorithm_invalid" in errors
    assert "credential_secret_hint_too_long" in errors
    assert "credential_status_invalid" in errors
    assert "credential_revision_invalid" in errors
    assert "credential_field_forbidden:client_secret" in errors
    assert "credential_field_forbidden:access_token" in errors


def test_credential_time_types_lifetime_and_rotation_are_bounded() -> None:
    assert "credential_invalid:issued_at" in validate_service_credential_record(
        _credential(issued_at=True)
    )
    errors = validate_service_credential_record(
        _credential(expires_at=1_000, grace_until=999)
    )
    assert "credential_expiry_invalid" in errors
    assert "credential_rotation_grace_invalid" in errors

    errors = validate_service_credential_record(
        _credential(
            expires_at=1_000 + 91 * 86_400,
            grace_until=1_000 + 86_401,
        )
    )
    assert "credential_lifetime_exceeded" in errors
    assert "credential_rotation_grace_exceeded" in errors
