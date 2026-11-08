from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from nex_ae_api.eos_outbox_event_api import (
    EosOutboxEventAdmissionError,
    admit_eos_outbox_event,
    register_eos_outbox_event_routes,
)
from nex_eos.ae_outbox_transport import HttpAeEosOutboxTransport
from nex_eos.outbox_publication import (
    EosOutboxEvent,
    EosOutboxPublicationError,
)
from nex_oa.production_token_profiles import validate_production_token_shape
from nex_oa.service_principal_boundary import validate_service_principal_spec
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    SERVICE_SPECS,
    InMemoryOperationalEventStore,
    build_service_app,
    issue_mock_service_token,
)
from nex_runtime import demo_domain_activation as activation_module
from nex_runtime.demo_domain_activation import (
    DEMO_DOMAIN_CLAIMING_ENV,
    DemoDomainActivationError,
    demo_domain_activation_projection,
    required_demo_domain_material,
    resolve_demo_domain_activation,
)

HASH = "sha256:" + "1" * 64
EVENT = EosOutboxEvent(
    outbox_id="2dc052bd-86da-42f6-b95f-4a596b91562c",
    tenant_id="VO00",
    event_id="1b23949f-b77f-454a-a7fa-c88e6a3e2994",
    business_operation_id="81adee99-e255-4b9f-a42c-4a93a7f64158",
    event_type="VOUCHER_COMMITTED",
    event_payload={"private": "must-not-cross"},
    event_payload_hash=HASH,
)


def _enabled_environment(**changes: str) -> dict[str, str]:
    return {
        DEMO_DOMAIN_CLAIMING_ENV: "true",
        "NEX_PROFILE": "staging_live",
        "NEX_DEPLOYMENT_BOUNDARY": "P8_DEMO",
        "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "SIGNED_ONLY",
        "NEX_EOS_DATABASE_URL": "private-db-url",
        "NEX_EOS_TO_AE_SERVICE_TOKEN": "private-token",
    } | changes


def test_domain_activation_is_explicit_signed_only_and_value_free() -> None:
    disabled = resolve_demo_domain_activation({}, process_id="nex-eos-outbox-publisher")
    assert disabled.enabled is False

    enabled = resolve_demo_domain_activation(
        _enabled_environment(),
        process_id="nex-eos-outbox-publisher",
        required_secret_names=(
            "NEX_EOS_DATABASE_URL",
            "NEX_EOS_TO_AE_SERVICE_TOKEN",
        ),
    )
    projection = enabled.to_projection()
    assert projection["domain_claiming_enabled"] is True
    assert projection["trust_grant_count"] == 16
    assert "private" not in repr(projection)


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({DEMO_DOMAIN_CLAIMING_ENV: "sometimes"}, "flag"),
        ({"NEX_PROFILE": "test"}, "staging_live"),
        ({"NEX_DEPLOYMENT_BOUNDARY": "OTHER"}, "P8_DEMO"),
        ({"NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK"}, "SIGNED_ONLY"),
        ({"NEX_EOS_TO_AE_SERVICE_TOKEN": ""}, "material"),
    ),
)
def test_domain_activation_fails_closed(changes: dict[str, str], message: str) -> None:
    with pytest.raises(DemoDomainActivationError, match=message):
        resolve_demo_domain_activation(
            _enabled_environment(**changes),
            process_id="nex-eos-outbox-publisher",
            required_secret_names=(
                "NEX_EOS_DATABASE_URL",
                "NEX_EOS_TO_AE_SERVICE_TOKEN",
            ),
        )
    with pytest.raises(DemoDomainActivationError, match="not admitted"):
        resolve_demo_domain_activation({}, process_id="unknown")


def test_activation_inventory_requires_complete_unique_trust_edges(monkeypatch) -> None:
    original = activation_module.DEMO_TRUST_GRANTS
    projection = demo_domain_activation_projection()
    assert projection["process_count"] == 3
    assert projection["required_edges_admitted"] is True
    assert projection["mock_token_fallback_allowed"] is False

    monkeypatch.setattr(
        activation_module,
        "DEMO_TRUST_GRANTS",
        tuple(
            grant
            for grant in original
            if not (grant.owner == "nex-eos" and grant.audience == "nex-wc")
        ),
    )
    with pytest.raises(DemoDomainActivationError, match="incomplete"):
        demo_domain_activation_projection()

    duplicate = original[0]
    monkeypatch.setattr(
        activation_module,
        "DEMO_TRUST_GRANTS",
        (*original, duplicate),
    )
    with pytest.raises(DemoDomainActivationError, match="ambiguous"):
        demo_domain_activation_projection()


def test_domain_material_is_derived_from_owner_trust_grants() -> None:
    assert required_demo_domain_material(
        "nex-ae-api", database_environment_name="NEX_AE_DATABASE_URL"
    ) == (
        "NEX_AE_DATABASE_URL",
        "NEX_AE_TO_OA_SERVICE_TOKEN",
        "NEX_AE_TO_CX_SERVICE_TOKEN",
        "NEX_AE_TO_MO_SERVICE_TOKEN",
        "NEX_AE_TO_AG_SERVICE_TOKEN",
        "NEX_AE_TO_WC_SERVICE_TOKEN",
        "NEX_AE_TO_EOS_SERVICE_TOKEN",
    )
    assert required_demo_domain_material(
        "nex-eos", database_environment_name="NEX_EOS_DATABASE_URL"
    ) == (
        "NEX_EOS_DATABASE_URL",
        "NEX_EOS_TO_WC_SERVICE_TOKEN",
        "NEX_EOS_TO_AE_SERVICE_TOKEN",
        "NEX_EOS_TO_OA_SERVICE_TOKEN",
    )
    with pytest.raises(DemoDomainActivationError, match="no admitted"):
        required_demo_domain_material(
            "nex-oa", database_environment_name="NEX_OA_DATABASE_URL"
        )
    with pytest.raises(DemoDomainActivationError, match="database"):
        required_demo_domain_material("nex-eos", database_environment_name="")


def test_oa_contract_accepts_wc_and_eos_without_model_specific_exceptions() -> None:
    assert (
        validate_service_principal_spec(
            {
                "principal_id": "demo-wc",
                "service_id": "nex-wc",
                "display_name": "Demo WC",
                "status": "ACTIVE",
                "allowed_audiences": ["nex-ae-api", "nex-eos"],
                "allowed_scopes": ["service:call"],
                "revision": 1,
            }
        )
        == ()
    )
    assert (
        validate_production_token_shape(
            "service_access",
            headers={"alg": "RS256", "typ": "at+jwt", "kid": "demo-key"},
            claims={
                "iss": "urn:nex-platform:oa",
                "sub": "service:nex-eos",
                "aud": "nex-wc",
                "iat": 1000,
                "nbf": 1000,
                "exp": 1300,
                "jti": "demo-jti",
                "token_use": "service_access",
                "scope": "service:call",
                "service_id": "nex-eos",
                "credential_id": "demo-eos-credential",
                "credential_revision": 1,
            },
        )
        == ()
    )


def _event_payload(**changes: str) -> dict[str, str]:
    return {
        "event_id": EVENT.event_id,
        "tenant_id": EVENT.tenant_id,
        "business_operation_id": EVENT.business_operation_id,
        "event_type": EVENT.event_type,
        "event_payload_hash": EVENT.event_payload_hash,
    } | changes


def test_eos_outbox_admission_is_idempotent_hash_bound_and_payload_free() -> None:
    store = InMemoryOperationalEventStore()
    created, is_created = admit_eos_outbox_event(store, _event_payload())
    replayed, is_replayed_created = admit_eos_outbox_event(store, _event_payload())

    assert is_created is True
    assert is_replayed_created is False
    assert replayed == created
    persisted = store.get_event(EVENT.event_id)
    assert persisted is not None
    assert persisted["details"]["event_payload_hash"] == HASH
    assert "private" not in repr(persisted)
    assert persisted["details"]["payload_bytes_included"] is False

    with pytest.raises(EosOutboxEventAdmissionError, match="different lineage"):
        admit_eos_outbox_event(
            store, _event_payload(event_payload_hash="sha256:" + "2" * 64)
        )
    with pytest.raises(EosOutboxEventAdmissionError, match="metadata"):
        admit_eos_outbox_event(store, {"event_id": EVENT.event_id})
    with pytest.raises(EosOutboxEventAdmissionError, match="hash"):
        admit_eos_outbox_event(store, _event_payload(event_payload_hash="bad"))
    with pytest.raises(EosOutboxEventAdmissionError, match="event_id"):
        admit_eos_outbox_event(store, _event_payload(event_id="not-a-uuid"))
    with pytest.raises(EosOutboxEventAdmissionError, match="business_operation_id"):
        admit_eos_outbox_event(
            store, _event_payload(business_operation_id="not-a-uuid")
        )


def test_eos_outbox_route_requires_eos_caller_and_replays_safely() -> None:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    store = InMemoryOperationalEventStore()
    register_eos_outbox_event_routes(app, store=store)
    client = TestClient(app)

    eos_token = issue_mock_service_token(
        service_id="nex-eos",
        audience="nex-ae-api",
        scopes=[DEFAULT_SERVICE_SCOPE],
    ).access_token
    response = client.post(
        "/internal/v1/eos-outbox-events",
        json=_event_payload(),
        headers={"Authorization": f"Bearer {eos_token}"},
    )
    assert response.status_code == 201
    assert response.json()["event_payload_hash"] == HASH
    assert (
        client.post(
            "/internal/v1/eos-outbox-events",
            json=_event_payload(),
            headers={"Authorization": f"Bearer {eos_token}"},
        ).status_code
        == 200
    )

    wc_token = issue_mock_service_token(
        service_id="nex-wc",
        audience="nex-ae-api",
        scopes=[DEFAULT_SERVICE_SCOPE],
    ).access_token
    denied = client.post(
        "/internal/v1/eos-outbox-events",
        json=_event_payload(),
        headers={"Authorization": f"Bearer {wc_token}"},
    )
    assert denied.status_code == 403
    assert denied.json()["error_code"] == "AE_EOS_OUTBOX_CALLER_DENIED"


class _Response:
    def __init__(self, payload: object) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self) -> bytes:
        return self._body


def test_http_eos_transport_sends_metadata_only_and_validates_receipt() -> None:
    observed: dict[str, object] = {}

    def opener(request, *, timeout):
        observed["body"] = json.loads(request.data)
        observed["authorization"] = request.headers["Authorization"]
        observed["timeout"] = timeout
        return _Response(
            {
                "event_id": EVENT.event_id,
                "event_payload_hash": HASH,
                "receipt_ref": f"AE:OPERATIONAL_EVENT:{EVENT.event_id}",
            }
        )

    transport = HttpAeEosOutboxTransport(
        base_url="https://ae.example",
        service_token="private-token",
        timeout_seconds=12,
        opener=opener,
    )
    receipt = transport.publish(EVENT)

    assert receipt.event_id == EVENT.event_id
    assert observed["body"] == _event_payload()
    assert "private" not in repr(observed["body"])
    assert observed["authorization"] == "Bearer private-token"
    assert observed["timeout"] == 12

    broken = HttpAeEosOutboxTransport(
        base_url="https://ae.example",
        service_token="token",
        opener=lambda *_args, **_kwargs: _Response(
            {
                "event_id": "wrong",
                "event_payload_hash": HASH,
                "receipt_ref": "receipt",
            }
        ),
    )
    with pytest.raises(EosOutboxPublicationError, match="binding"):
        broken.publish(EVENT)


@pytest.mark.parametrize(
    "kwargs",
    (
        {"base_url": "", "service_token": "token"},
        {"base_url": "https://ae", "service_token": ""},
        {"base_url": "https://ae", "service_token": "token", "timeout_seconds": 0},
    ),
)
def test_http_eos_transport_configuration_fails_closed(kwargs) -> None:
    with pytest.raises(EosOutboxPublicationError):
        HttpAeEosOutboxTransport(**kwargs)
