from __future__ import annotations

import pytest
from nex_oa.demo_service_principal_provisioning import (
    DemoServicePrincipalProvisioningError,
    demo_service_principal_specs,
    provision_demo_service_principals,
)
from nex_oa.service_principal_repository import InMemoryOaServicePrincipalRepository
from nex_oa.service_principal_service import OaServicePrincipalService
from nex_runtime.demo_service_token_bootstrap import (
    DEMO_CLIENT_SECRET_ENV,
    DEMO_CREDENTIAL_ID_ENV,
)


def _service() -> OaServicePrincipalService:
    return OaServicePrincipalService(InMemoryOaServicePrincipalRepository())


def _secrets() -> dict[str, str]:
    return {
        spec.owner: f"private-{spec.owner}-client-secret-material"
        for spec in demo_service_principal_specs()
    }


def test_demo_principal_specs_cover_every_non_oa_owner_and_exact_trust() -> None:
    specs = demo_service_principal_specs()

    assert {spec.owner for spec in specs} == {
        "nex-ae-api",
        "nex-cx",
        "nex-mo",
        "nex-ag",
        "nex-wc",
        "nex-eos",
    }
    assert all("nex-oa" in spec.allowed_audiences for spec in specs)
    assert all("token:introspect" in spec.allowed_scopes for spec in specs)
    wc = next(spec for spec in specs if spec.owner == "nex-wc")
    assert wc.allowed_audiences == ("nex-ae-api", "nex-oa")
    assert wc.allowed_scopes == (
        "authorization:read",
        "service:call",
        "token:introspect",
    )


def test_demo_principal_provisioning_is_generation_bound_and_replay_safe() -> None:
    service = _service()
    secrets = _secrets()

    created = provision_demo_service_principals(
        service,
        generation="v1",
        client_secrets=secrets,
        now_epoch=1_000,
    )
    replayed = provision_demo_service_principals(
        service,
        generation="v1",
        client_secrets=secrets,
        now_epoch=1_001,
    )

    assert created.evidence() == {
        "schema_version": "p8_demo_service_principal_provisioning.v1",
        "generation": "v1",
        "owner_count": 6,
        "created_principal_count": 6,
        "updated_principal_count": 0,
        "created_credential_count": 6,
        "reused_credential_count": 0,
        "owners": [spec.owner for spec in demo_service_principal_specs()],
        "credential_values_included": False,
        "client_secret_values_included": False,
    }
    assert replayed.created_credential_count == 0
    assert replayed.reused_credential_count == 6
    assert "private-" not in repr(created)
    values = created.openbao_values_by_owner()
    assert set(values) == set(secrets)
    assert values["nex-eos"] == {
        DEMO_CREDENTIAL_ID_ENV: "p8demo-eos-v1",
        DEMO_CLIENT_SECRET_ENV: secrets["nex-eos"],
    }


def test_demo_principal_provisioning_repairs_principal_drift_without_rotating_secret() -> (
    None
):
    service = _service()
    secrets = _secrets()
    provision_demo_service_principals(
        service,
        generation="v1",
        client_secrets=secrets,
        now_epoch=1_000,
    )
    current = service.get_principal("p8demo-wc")["principal"]
    service.upsert_principal(
        {
            **current,
            "display_name": "Drifted",
            "expected_revision": current["revision"],
        }
    )

    repaired = provision_demo_service_principals(
        service,
        generation="v1",
        client_secrets=secrets,
        now_epoch=1_001,
    )

    assert repaired.updated_principal_count == 1
    assert repaired.reused_credential_count == 6
    assert service.get_principal("p8demo-wc")["principal"]["display_name"] == (
        "P8 Demo WC Runtime"
    )


def test_demo_principal_provisioning_rejects_generation_rebinding_and_bad_inputs() -> (
    None
):
    service = _service()
    secrets = _secrets()
    provision_demo_service_principals(
        service,
        generation="v1",
        client_secrets=secrets,
        now_epoch=1_000,
    )

    with pytest.raises(
        DemoServicePrincipalProvisioningError, match="different material"
    ):
        provision_demo_service_principals(
            service,
            generation="v1",
            client_secrets={**secrets, "nex-eos": "different-private-client-secret"},
            now_epoch=1_001,
        )
    with pytest.raises(DemoServicePrincipalProvisioningError, match="generation"):
        provision_demo_service_principals(
            service,
            generation="latest",
            client_secrets=secrets,
            now_epoch=1_001,
        )
    with pytest.raises(DemoServicePrincipalProvisioningError, match="coverage"):
        provision_demo_service_principals(
            service,
            generation="v2",
            client_secrets={"nex-eos": secrets["nex-eos"]},
            now_epoch=1_001,
        )
    with pytest.raises(DemoServicePrincipalProvisioningError, match="lifetime"):
        provision_demo_service_principals(
            service,
            generation="v2",
            client_secrets=secrets,
            now_epoch=1_001,
            lifetime_days=365,
        )
