from __future__ import annotations

from datetime import UTC, datetime

import pytest

from nex_oa.federated_identities import (
    OaFederationError,
    build_external_identity_link,
    build_federation_provider,
    external_identity_projection,
    external_subject_digest,
    federation_provider_projection,
    resolve_federated_identity,
)
import run_oa_federated_identity_domain as runner


NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _provider(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "provider_id": "company-oidc",
        "issuer": "https://id.example.test",
        "client_id": "nex-platform",
        "discovery_url": "https://id.example.test/.well-known/openid-configuration",
        "display_name": "Company OIDC",
    }
    payload.update(overrides)
    return build_federation_provider(payload, now=NOW)


def _identity(provider: dict[str, object], **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "provider_id": "company-oidc",
        "external_subject": "opaque-subject",
        "tenant_id": "company",
        "subject_id": "employee-1001",
    }
    payload.update(overrides)
    return build_external_identity_link(payload, provider=provider, now=NOW)


def test_provider_and_identity_are_privacy_safe() -> None:
    provider = _provider()
    identity = _identity(provider)

    assert provider["provider_schema_version"] == "oa_fed_provider.v1"
    assert provider["id_token_algorithms"] == ("RS256",)
    assert provider["revision"] == 1
    assert identity["identity_schema_version"] == "oa_fed_identity.v1"
    assert identity["external_subject_digest"] == external_subject_digest(
        "https://id.example.test", "opaque-subject"
    )
    assert "external_subject" not in identity
    assert federation_provider_projection(provider) == provider
    assert external_identity_projection(identity) == identity

    naive_provider = build_federation_provider(
        {
            "provider_id": "company-naive",
            "issuer": "https://naive.example.test",
            "client_id": "nex-platform",
            "discovery_url": "https://naive.example.test/.well-known/openid-configuration",
            "display_name": "Naive Clock Provider",
        },
        now=datetime(2026, 1, 1),
    )
    assert naive_provider["created_at"] == "2026-01-01T00:00:00Z"


def test_resolution_returns_only_internal_identity() -> None:
    provider = _provider()
    identity = _identity(provider)
    resolved = resolve_federated_identity(
        {
            "issuer": provider["issuer"],
            "audience": provider["client_id"],
            "subject": "opaque-subject",
        },
        provider=provider,
        identity_link=identity,
    )

    assert resolved["resolution_status"] == "RESOLVED"
    assert resolved["auth_method"] == "federated_oidc"
    assert resolved["tenant_id"] == "company"
    assert resolved["subject_id"] == "employee-1001"
    assert resolved["raw_external_subject_included"] is False


@pytest.mark.parametrize(
    ("payload", "error_code"),
    (
        ({"provider_id": "Company"}, "oa.federation_provider_id_invalid"),
        ({"issuer": "http://id.example.test"}, "oa.federation_issuer_invalid"),
        ({"issuer": "https://user:pass@id.example.test"}, "oa.federation_issuer_invalid"),
        ({"issuer": "https://id.example.test/#fragment"}, "oa.federation_issuer_invalid"),
        ({"discovery_url": "https://other.example.test/.well-known/openid-configuration"}, "oa.federation_provider_discovery_host_mismatch"),
        ({"client_secret": "private"}, "oa.federated_provider_private_payload_rejected"),
        ({"unknown": "value"}, "oa.federated_provider_field_unsupported"),
        ({"status": "BROKEN"}, "oa.federation_status_invalid"),
    ),
)
def test_provider_rejects_invalid_or_private_input(
    payload: dict[str, object], error_code: str
) -> None:
    base: dict[str, object] = {
        "provider_id": "company-oidc",
        "issuer": "https://id.example.test",
        "client_id": "nex-platform",
        "discovery_url": "https://id.example.test/.well-known/openid-configuration",
        "display_name": "Company OIDC",
    }
    base.update(payload)
    with pytest.raises(OaFederationError) as exc_info:
        build_federation_provider(base, now=NOW)
    assert exc_info.value.error_code == error_code
    assert str(exc_info.value) == exc_info.value.detail


def test_loopback_http_requires_explicit_test_flag() -> None:
    payload = {
        "provider_id": "loopback",
        "issuer": "http://127.0.0.1:19090",
        "client_id": "nex-platform",
        "discovery_url": "http://127.0.0.1:19090/.well-known/openid-configuration",
        "display_name": "Loopback",
    }
    with pytest.raises(OaFederationError):
        build_federation_provider(payload, now=NOW)
    assert build_federation_provider(
        payload, now=NOW, allow_loopback_http=True
    )["provider_id"] == "loopback"


@pytest.mark.parametrize(
    ("overrides", "provider_overrides", "error_code"),
    (
        ({"provider_id": "other"}, {}, "oa.federated_identity_provider_mismatch"),
        ({"email": "private@example.test"}, {}, "oa.federated_identity_private_payload_rejected"),
        ({"unknown": "value"}, {}, "oa.federated_identity_field_unsupported"),
        ({"status": "BROKEN"}, {}, "oa.federation_status_invalid"),
        ({}, {"status": "DISABLED"}, "oa.federation_provider_inactive"),
    ),
)
def test_identity_link_rejects_invalid_input(
    overrides: dict[str, object],
    provider_overrides: dict[str, object],
    error_code: str,
) -> None:
    provider = _provider(**provider_overrides)
    with pytest.raises(OaFederationError) as exc_info:
        _identity(provider, **overrides)
    assert exc_info.value.error_code == error_code


@pytest.mark.parametrize(
    ("assertion_overrides", "identity_overrides", "provider_overrides", "error_code"),
    (
        ({"issuer": "https://wrong.example.test"}, {}, {}, "oa.federated_assertion_issuer_invalid"),
        ({"audience": "wrong-client"}, {}, {}, "oa.federated_assertion_audience_invalid"),
        ({"audience": []}, {}, {}, "oa.federated_assertion_audience_invalid"),
        ({"audience": 123}, {}, {}, "oa.federated_assertion_audience_invalid"),
        ({"audience": b"bytes"}, {}, {}, "oa.federated_assertion_audience_invalid"),
        ({"subject": "wrong-subject"}, {}, {}, "oa.federated_identity_not_linked"),
        ({}, {"status": "DISABLED"}, {}, "oa.federated_identity_not_linked"),
        ({}, {}, {"status": "DISABLED"}, "oa.federation_provider_inactive"),
    ),
)
def test_resolution_fails_closed(
    assertion_overrides: dict[str, object],
    identity_overrides: dict[str, object],
    provider_overrides: dict[str, object],
    error_code: str,
) -> None:
    active_provider = _provider()
    identity = _identity(active_provider)
    identity.update(identity_overrides)
    provider = {**active_provider, **provider_overrides}
    assertion: dict[str, object] = {
        "issuer": active_provider["issuer"],
        "audience": [active_provider["client_id"]],
        "subject": "opaque-subject",
    }
    assertion.update(assertion_overrides)
    with pytest.raises(OaFederationError) as exc_info:
        resolve_federated_identity(assertion, provider=provider, identity_link=identity)
    assert exc_info.value.error_code == error_code


def test_payload_and_scalar_validation_edges() -> None:
    with pytest.raises(OaFederationError) as exc_info:
        build_federation_provider([])  # type: ignore[arg-type]
    assert exc_info.value.error_code == "oa.federation_provider_payload_invalid"
    with pytest.raises(OaFederationError):
        external_subject_digest("", "subject")
    with pytest.raises(OaFederationError):
        external_subject_digest("https://id.example.test", " spaced ")


def test_domain_smoke_and_cli(monkeypatch, capsys) -> None:
    evidence = runner.run_oa_federated_identity_domain()
    assert evidence["status"] == "PASS"
    assert all(evidence["checks"].values())
    assert runner.summary_line(evidence) == (
        "oa_federated_identity_domain=pass checks=7/7 digest=64 next=1284"
    )
    monkeypatch.setattr(runner, "run_oa_federated_identity_domain", lambda: evidence)
    assert runner.main(["--summary"]) == 0
    assert "next=1284" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        runner, "run_oa_federated_identity_domain", lambda: {"status": "FAIL"}
    )
    assert runner.main([]) == 1
