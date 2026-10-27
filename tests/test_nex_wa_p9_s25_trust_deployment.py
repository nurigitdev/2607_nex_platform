from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from nex_runtime.demo_trust import demo_secret_bindings_for_owner
from nex_runtime.p9_wa_trust import (
    P9_WA_SECRET_TARGETS_BY_OWNER,
    P9WaTrustError,
    materialize_p9_wa_owner_secrets,
    p9_wa_trust_projection,
)
from nex_runtime.production_container_bootstrap import (
    prepare_production_container_environment,
)
from nex_runtime.production_secret_materialization import ResolvedSecret
from nex_runtime.runtime_profiles import (
    CURRENT_SERVICE_ENDPOINT_ENV_NAMES,
    CURRENT_SIGNED_TRUST_ENV_NAMES,
    CURRENT_TEST_DATABASE_ENV_NAMES,
    RuntimeProfileError,
    resolve_current_runtime_profile,
)

ROOT = Path(__file__).resolve().parents[1]


class Resolver:
    def __init__(self, change=None, *, raises: bool = False) -> None:
        self.change = change
        self.raises = raises
        self.revoked = False

    def resolve(self, reference, *, context):
        if self.raises:
            raise RuntimeError("private provider detail")
        secret = ResolvedSecret(
            owner=context.owner,
            target_environment_name=context.target_environment_name,
            secret_generation=context.secret_generation,
            reference_version=context.reference_version,
            provider_id="openbao",
            value=f"private-{context.target_environment_name}",
        )
        return self.change(secret) if self.change else secret

    def revoke(self):
        self.revoked = True


def _trust_environment(owner: str) -> dict[str, str]:
    result = {
        "NEX_PROFILE": "staging_live",
        "NEX_DEPLOYMENT_BOUNDARY": "P9_WA",
        "NEX_SECRET_GENERATION": "secret:p9-wa.1",
        "NEX_OPENBAO_ROLE_ID_FILE": "/run/secrets/role",
        "NEX_OPENBAO_SECRET_ID_FILE": "/run/secrets/secret",
    }
    inherited_targets = (
        tuple(
            binding.target_environment_name
            for binding in demo_secret_bindings_for_owner(owner)
        )
        if owner == "nex-ae-api"
        else ()
    )
    for target in (*inherited_targets, *P9_WA_SECRET_TARGETS_BY_OWNER[owner]):
        result[f"{target}_REF"] = (
            f"secret://openbao/nex-platform/staging/{owner}/{target}@v1"
        )
    return result


def _yaml(path: str) -> dict:
    return yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))


def test_current_signed_trust_inventory_closes_wa_inbound_and_outbound_edges() -> None:
    assert CURRENT_SIGNED_TRUST_ENV_NAMES[-5:] == (
        "NEX_AE_TO_WA_SERVICE_TOKEN",
        "NEX_WA_TO_AE_SERVICE_TOKEN",
        "NEX_WA_TO_WC_SERVICE_TOKEN",
        "NEX_WA_TO_OA_SERVICE_TOKEN",
        "NEX_WA_TO_EOS_SERVICE_TOKEN",
    )
    assert len(CURRENT_SIGNED_TRUST_ENV_NAMES) == len(
        set(CURRENT_SIGNED_TRUST_ENV_NAMES)
    )


def test_current_protected_profile_fails_closed_without_each_wa_trust_edge() -> None:
    required = (
        *CURRENT_TEST_DATABASE_ENV_NAMES,
        *CURRENT_SERVICE_ENDPOINT_ENV_NAMES,
        *CURRENT_SIGNED_TRUST_ENV_NAMES,
    )
    baseline = {name: f"configured-{index}" for index, name in enumerate(required)}

    for name in CURRENT_SIGNED_TRUST_ENV_NAMES[-5:]:
        environment = dict(baseline)
        environment.pop(name)
        with pytest.raises(RuntimeProfileError, match=name):
            resolve_current_runtime_profile("test", environ=environment)


def test_p9_wa_trust_projection_and_owner_materialization_are_scoped() -> None:
    assert p9_wa_trust_projection() == {
        "schema_version": "p9_wa_trust.v1",
        "deployment_boundary": "P9_WA",
        "owners": ["nex-ae-api", "nex-wa"],
        "owner_extension_secret_counts": {"nex-ae-api": 1, "nex-wa": 5},
        "ae_inherits_p8_demo_secrets": True,
        "raw_secret_values_included": False,
    }

    wa = materialize_p9_wa_owner_secrets(
        _trust_environment("nex-wa"),
        Resolver(),
        owner="nex-wa",
        profile="staging_live",
    )
    ae = materialize_p9_wa_owner_secrets(
        _trust_environment("nex-ae-api"),
        Resolver(),
        owner="nex-ae-api",
        profile="staging_live",
    )

    assert set(wa.owner_environment.process_environment()) == set(
        P9_WA_SECRET_TARGETS_BY_OWNER["nex-wa"]
    )
    assert set(ae.owner_environment.process_environment()) == {
        *(
            binding.target_environment_name
            for binding in demo_secret_bindings_for_owner("nex-ae-api")
        ),
        "NEX_AE_TO_WA_SERVICE_TOKEN",
    }
    assert "private-" not in repr(wa)
    assert "private-" not in repr(ae)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda env: env.update(NEX_DEPLOYMENT_BOUNDARY="P8_DEMO"), "boundary"),
        (lambda env: env.update(NEX_SECRET_GENERATION="bad"), "generation"),
        (lambda env: env.update(NEX_WA_DATABASE_URL="raw"), "raw P9 WA"),
        (lambda env: env.pop("NEX_WA_DATABASE_URL_REF"), "reference"),
        (
            lambda env: env.update(
                NEX_WA_DATABASE_URL_REF=(
                    "secret://openbao/nex-platform/staging/nex-eos/"
                    "NEX_WA_DATABASE_URL@v1"
                )
            ),
            "reference",
        ),
    ],
)
def test_p9_wa_materialization_fails_closed(mutate, message) -> None:
    environment = _trust_environment("nex-wa")
    mutate(environment)
    with pytest.raises(P9WaTrustError, match=message):
        materialize_p9_wa_owner_secrets(
            environment,
            Resolver(),
            owner="nex-wa",
            profile="staging_live",
        )


@pytest.mark.parametrize(
    "resolver",
    [
        Resolver(raises=True),
        Resolver(lambda secret: object()),
        Resolver(lambda secret: replace(secret, owner="nex-eos")),
        Resolver(lambda secret: replace(secret, value="bad\nvalue")),
    ],
)
def test_p9_wa_materialization_sanitizes_provider_failures(resolver) -> None:
    with pytest.raises(P9WaTrustError) as raised:
        materialize_p9_wa_owner_secrets(
            _trust_environment("nex-wa"),
            resolver,
            owner="nex-wa",
            profile="staging_live",
        )
    assert "private provider detail" not in str(raised.value)


def test_production_bootstrap_materializes_wa_and_scrubs_private_inputs() -> None:
    resolver = Resolver()
    process_environment, result = prepare_production_container_environment(
        "nex-wa",
        _trust_environment("nex-wa"),
        root=ROOT,
        resolver_factory=lambda _: resolver,
    )

    assert resolver.revoked is True
    assert result.owner_environment.owner == "nex-wa"
    assert set(result.owner_environment.process_environment()) == set(
        P9_WA_SECRET_TARGETS_BY_OWNER["nex-wa"]
    )
    assert not any(name.endswith("_REF") for name in process_environment)
    assert "NEX_OPENBAO_SECRET_ID_FILE" not in process_environment


def test_p9_compose_adds_hardened_wa_api_and_active_consumer() -> None:
    compose = _yaml("deployment/compose/p9-wa.override.yaml")
    services = compose["services"]
    wa = services["nex-wa"]
    consumer = services["nex-wa-evidence-consumer"]

    assert wa["image"].startswith("${NEX_WA_RUNTIME_IMAGE:")
    assert wa["command"][-1] == "8108"
    assert wa["read_only"] is True
    assert wa["tmpfs"] == ["/tmp"]
    assert wa["cap_drop"] == ["ALL"]
    assert wa["security_opt"] == ["no-new-privileges:true"]
    assert "ports" not in wa
    assert wa["environment"]["NEX_SERVICE_TOKEN_ROLLOUT_PROFILE"] == "SIGNED_ONLY"
    assert wa["environment"]["NEX_WA_BASE_URL"].startswith("https://")
    assert all(
        name.endswith("_REF")
        for name in wa["environment"]
        if name.endswith("DATABASE_URL_REF") or "SERVICE_TOKEN_REF" in name
    )

    assert "profiles" not in consumer
    assert consumer["command"] == ["python", "-m", "nex_wa.consumer_main"]
    assert consumer["restart"] == "unless-stopped"
    assert "ports" not in consumer


def test_p9_compose_routes_wa_through_tls_and_binds_ae_token_by_reference() -> None:
    compose = _yaml("deployment/compose/p9-wa.override.yaml")
    dynamic = _yaml("deployment/compose/traefik/p9-wa-dynamic.yaml")

    ae_environment = compose["services"]["nex-ae-api"]["environment"]
    assert ae_environment["NEX_WA_BASE_URL"] == (
        "https://wa.nex-staging.test:8443"
    )
    assert ae_environment["NEX_AE_TO_WA_SERVICE_TOKEN_REF"].startswith(
        "secret://openbao/"
    )
    assert dynamic["http"]["routers"]["wa"]["tls"] == {}
    assert dynamic["http"]["services"]["wa"] == {
        "loadBalancer": {"servers": [{"url": "http://nex-wa:8108"}]}
    }
    assert compose["services"]["traefik"]["networks"]["service"]["aliases"] == [
        "wa.nex-staging.test"
    ]


def test_p9_compose_uses_owner_scoped_wa_approle_inputs_only() -> None:
    compose = _yaml("deployment/compose/p9-wa.override.yaml")
    assert set(compose["secrets"]) == {"wa_role_id", "wa_secret_id"}
    serialized = str(compose)
    assert "nuri1004" not in serialized
    assert "api-key" not in serialized.lower()
    assert "host.docker.internal:5432" not in serialized
