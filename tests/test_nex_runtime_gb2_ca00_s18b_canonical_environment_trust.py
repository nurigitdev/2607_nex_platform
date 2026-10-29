from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
import pytest
from nex_oa.canonical_service_principal_provisioning import (
    CanonicalServicePrincipalProvisioningError,
    canonical_service_principal_specs,
    provision_canonical_service_principals,
)
from nex_oa.service_auth import build_oa_local_service_token_admission
from nex_oa.service_principal_repository import InMemoryOaServicePrincipalRepository
from nex_oa.service_principal_service import OaServicePrincipalService
from nex_oa.service_principals import OaServicePrincipalError
from nex_oa.token_exchange_service import service_token_exchange_profile_for_environment
from nex_oa.token_signing import InMemoryOaRsaSigningProvider, encode_signed_jwt
from nex_runtime import canonical_platform_trust as trust
from nex_runtime.canonical_platform_trust import (
    CANONICAL_PLATFORM_OWNERS,
    CANONICAL_PLATFORM_SECRET_BINDINGS,
    SERVICE_CLIENT_SECRET_ENV,
    SERVICE_CREDENTIAL_ID_ENV,
    CanonicalPlatformTrustError,
    canonical_platform_trust_projection,
    canonical_secret_bindings_for_owner,
    canonical_startup_credential_bindings_for_owner,
    configure_canonical_runtime_approles,
    materialize_canonical_owner_secrets,
)
from nex_runtime.current_platform_installation import (
    CURRENT_COMPOSE_PATHS,
    admit_current_platform_installation,
)
from nex_runtime.production_container_bootstrap import (
    prepare_production_container_environment,
)
from nex_runtime.production_secret_materialization import ResolvedSecret
from nex_runtime.startup_service_token_bootstrap import (
    StartupServiceTokenBootstrapError,
    issue_startup_service_tokens,
    startup_service_token_grants_for_owner,
)
from run_canonical_platform_trust_admission import _source_admission

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = "memory://canonical-startup-token"
KEY_ID = "canonical-startup-token"


class Resolver:
    def __init__(self, change=None, *, raises: bool = False) -> None:
        self.change = change
        self.raises = raises
        self.revoked = False

    def resolve(self, reference: str, *, context: Any) -> ResolvedSecret:
        if self.raises:
            raise RuntimeError("private provider detail")
        value = ResolvedSecret(
            owner=context.owner,
            target_environment_name=context.target_environment_name,
            secret_generation=context.secret_generation,
            reference_version=context.reference_version,
            provider_id="openbao",
            value=f"private-{context.target_environment_name}",
        )
        return self.change(value) if self.change else value

    def revoke(self) -> None:
        self.revoked = True


def _environment(
    owner: str = "nex-eos",
    *,
    profile: str = "staging_live",
    bootstrap: bool = True,
) -> dict[str, str]:
    namespace = "staging" if profile == "staging_live" else "production"
    result = {
        "NEX_PROFILE": profile,
        "NEX_DEPLOYMENT_BOUNDARY": "CANONICAL_PLATFORM",
        "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "SIGNED_ONLY",
        "NEX_SERVICE_TOKEN_BOOTSTRAP_PROFILE": "STARTUP_24H",
        "NEX_STARTUP_SERVICE_TOKEN_BOOTSTRAP": "true" if bootstrap else "false",
        "NEX_OA_BASE_URL": "https://oa.nex-staging.test:8443",
        "NEX_OPENBAO_TIMEOUT_SECONDS": "10",
        "NEX_SECRET_GENERATION": "secret:canonical-platform.1",
        "NEX_OPENBAO_ROLE_ID_FILE": "/run/secrets/role",
        "NEX_OPENBAO_SECRET_ID_FILE": "/run/secrets/secret",
    }
    bindings = list(canonical_secret_bindings_for_owner(owner))
    if bootstrap:
        bindings.extend(canonical_startup_credential_bindings_for_owner(owner))
    for binding in bindings:
        result[binding.source_environment_name] = (
            f"secret://openbao/nex-platform/{namespace}/{owner}/"
            f"{binding.target_environment_name}@v1"
        )
    return result


class TokenEndpoint:
    def __init__(self, owner: str = "nex-eos") -> None:
        self.signer = InMemoryOaRsaSigningProvider()
        self.signer.generate_key(REFERENCE)
        self.jwk = self.signer.public_jwk(REFERENCE, key_id=KEY_ID)
        self.owner = owner
        self.requests: list[dict[str, Any]] = []

    def __call__(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        if method == "GET" and url.endswith("/.well-known/jwks.json"):
            return httpx.Response(
                200,
                json={"issuer": "urn:nex-platform:oa", "keys": [self.jwk]},
            )
        assert method == "POST"
        payload = dict(kwargs["json"])
        self.requests.append(payload)
        token = encode_signed_jwt(
            headers={"alg": "RS256", "typ": "at+jwt", "kid": KEY_ID},
            claims={
                "iss": "urn:nex-platform:oa",
                "sub": f"service:{self.owner}",
                "aud": payload["audience"],
                "iat": 500,
                "nbf": 500,
                "exp": 86_900,
                "jti": f"canonical-{len(self.requests)}",
                "token_use": "startup_service_access",
                "scope": " ".join(sorted(payload["scope"].split(" "))),
                "service_id": self.owner,
                "credential_id": payload["credential_id"],
                "credential_revision": 1,
                "deployment_boundary": "CANONICAL_PLATFORM",
                "deployment_profile": "staging_live",
            },
            private_key_ref=REFERENCE,
            signing_provider=self.signer,
        )
        return httpx.Response(
            200,
            json={
                "access_token": token,
                "token_type": "Bearer",
                "expires_in": 86_400,
                "scope": payload["scope"],
            },
        )


def test_canonical_inventory_covers_all_current_service_owners() -> None:
    projection = canonical_platform_trust_projection()

    assert projection["deployment_boundary"] == "CANONICAL_PLATFORM"
    assert projection["owner_count"] == 8
    assert projection["secret_binding_count"] == 37
    assert projection["trust_grant_count"] == 21
    assert projection["tls_host_count"] == 14
    assert projection["owner_secret_counts"]["nex-wa"] == 5
    assert len(CANONICAL_PLATFORM_SECRET_BINDINGS) == 37
    assert canonical_startup_credential_bindings_for_owner("nex-oa") == ()
    assert len(canonical_startup_credential_bindings_for_owner("nex-wa")) == 2
    with pytest.raises(CanonicalPlatformTrustError, match="owner"):
        canonical_secret_bindings_for_owner("unknown")
    with pytest.raises(CanonicalPlatformTrustError, match="owner"):
        canonical_startup_credential_bindings_for_owner("unknown")


def test_canonical_owner_materialization_is_scoped_deterministic_and_scrubbed() -> None:
    environment = _environment()
    result = materialize_canonical_owner_secrets(
        environment, Resolver(), owner="nex-eos", profile="staging_live"
    )
    repeated = materialize_canonical_owner_secrets(
        environment, Resolver(), owner="nex-eos", profile="staging_live"
    )

    assert result.configuration_digest == repeated.configuration_digest
    assert result.materialization_digest == repeated.materialization_digest
    assert len(result.owner_environment.secrets) == 6
    assert set(result.owner_environment.process_environment()) == {
        "NEX_EOS_DATABASE_URL",
        "NEX_EOS_TO_WC_SERVICE_TOKEN",
        "NEX_EOS_TO_AE_SERVICE_TOKEN",
        "NEX_EOS_TO_OA_SERVICE_TOKEN",
        SERVICE_CREDENTIAL_ID_ENV,
        SERVICE_CLIENT_SECRET_ENV,
    }
    assert "private-" not in repr(result)

    production = materialize_canonical_owner_secrets(
        _environment(profile="production"),
        Resolver(),
        owner="nex-eos",
        profile="production",
    )
    assert production.profile == "production"
    without_bootstrap = materialize_canonical_owner_secrets(
        _environment(bootstrap=False),
        Resolver(),
        owner="nex-eos",
        profile="staging_live",
    )
    assert len(without_bootstrap.owner_environment.secrets) == 4
    with pytest.raises(CanonicalPlatformTrustError, match="profile"):
        materialize_canonical_owner_secrets(
            _environment(), Resolver(), owner="nex-eos", profile="development"
        )


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda env: env.update(NEX_DEPLOYMENT_BOUNDARY="OTHER"), "boundary"),
        (lambda env: env.update(NEX_SECRET_GENERATION="bad"), "generation"),
        (lambda env: env.pop("NEX_EOS_DATABASE_URL_REF"), "reference"),
        (
            lambda env: env.update(
                NEX_EOS_DATABASE_URL_REF=(
                    "secret://openbao/nex-platform/staging/nex-wc/"
                    "NEX_EOS_DATABASE_URL@v1"
                )
            ),
            "reference",
        ),
        (lambda env: env.update(NEX_EOS_DATABASE_URL="raw"), "raw canonical"),
        (
            lambda env: env.update(
                NEX_EOS_DATABASE_URL_REF=(
                    "secret://openbao/nex-platform/staging/nex-eos/"
                    "NEX_EOS_DATABASE_URL@latest"
                )
            ),
            "reference",
        ),
    ],
)
def test_canonical_materialization_fails_closed(mutate, message) -> None:
    environment = _environment()
    mutate(environment)
    with pytest.raises(CanonicalPlatformTrustError, match=message):
        materialize_canonical_owner_secrets(
            environment, Resolver(), owner="nex-eos", profile="staging_live"
        )


@pytest.mark.parametrize(
    ("resolver", "message"),
    [
        (Resolver(raises=True), "resolution failed"),
        (Resolver(lambda value: object()), "result is invalid"),
        (Resolver(lambda value: replace(value, owner="nex-wc")), "metadata mismatch"),
        (
            Resolver(lambda value: replace(value, provider_id="other")),
            "metadata mismatch",
        ),
        (
            Resolver(lambda value: replace(value, value="bad\nvalue")),
            "value is invalid",
        ),
    ],
)
def test_canonical_materialization_sanitizes_resolver_failures(
    resolver, message
) -> None:
    with pytest.raises(CanonicalPlatformTrustError, match=message) as raised:
        materialize_canonical_owner_secrets(
            _environment(), resolver, owner="nex-eos", profile="staging_live"
        )
    assert "private provider detail" not in str(raised.value)


def test_canonical_runtime_approle_is_restart_safe_and_owner_scoped() -> None:
    class Admin:
        def __init__(self) -> None:
            self.calls = []

        def request(self, method, path, **kwargs):
            self.calls.append((method, path, kwargs))
            if method == "GET":
                return {"data": {"secret_id_ttl": 86_400, "secret_id_num_uses": 0}}
            return {}

    admin = Admin()
    result = configure_canonical_runtime_approles(
        admin, root_token="root", owners=("nex-oa", "nex-wa")
    )
    assert result["deployment_boundary"] == "CANONICAL_PLATFORM"
    assert result["owner_count"] == 2
    assert len(admin.calls) == 4
    with pytest.raises(CanonicalPlatformTrustError, match="owner"):
        configure_canonical_runtime_approles(admin, root_token="root", owners=("bad",))
    with pytest.raises(CanonicalPlatformTrustError, match="root token"):
        configure_canonical_runtime_approles(admin, root_token="")


@pytest.mark.parametrize("invalid_ttl", [None, "not-an-integer"])
def test_canonical_runtime_approle_rejects_readback_drift(invalid_ttl) -> None:
    class DriftedAdmin:
        def request(self, method, path, **kwargs):
            if method == "GET":
                return {
                    "data": {
                        "secret_id_ttl": invalid_ttl,
                        "secret_id_num_uses": 0,
                    }
                }
            return {}

    with pytest.raises(CanonicalPlatformTrustError, match="policy drift"):
        configure_canonical_runtime_approles(
            DriftedAdmin(), root_token="root", owners=("nex-wa",)
        )


def test_startup_token_bootstrap_issues_scoped_tokens_and_scrubs_credentials() -> None:
    endpoint = TokenEndpoint()
    environment = _environment()
    environment[SERVICE_CREDENTIAL_ID_ENV] = "credential-nex-eos"
    environment[SERVICE_CLIENT_SECRET_ENV] = "private-client-secret"

    result, evidence = issue_startup_service_tokens(
        "nex-eos", environment, requester=endpoint, clock=lambda: 500
    )

    assert evidence.issued_token_count == 4
    assert evidence.token_ttl_seconds == 86_400
    assert SERVICE_CREDENTIAL_ID_ENV not in result
    assert SERVICE_CLIENT_SECRET_ENV not in result
    assert endpoint.requests[-1]["scope"] == "token:introspect"
    assert "private-client-secret" not in json.dumps(evidence.to_wire())
    oa_environment, oa_evidence = issue_startup_service_tokens(
        "nex-oa", _environment("nex-oa"), requester=endpoint, clock=lambda: 500
    )
    assert oa_evidence.issued_token_count == 0
    assert oa_environment["NEX_PROFILE"] == "staging_live"
    assert len(startup_service_token_grants_for_owner("nex-wa")) == 5
    with pytest.raises(StartupServiceTokenBootstrapError, match="owner"):
        startup_service_token_grants_for_owner("unknown")


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"NEX_PROFILE": "production"}, "NEX_PROFILE"),
        ({"NEX_DEPLOYMENT_BOUNDARY": "P8_DEMO"}, "boundary"),
        ({"NEX_SERVICE_TOKEN_BOOTSTRAP_PROFILE": "one-year"}, "PROFILE"),
        ({SERVICE_CLIENT_SECRET_ENV: ""}, "credential"),
        ({"NEX_OA_BASE_URL": "http://oa"}, "base URL"),
        ({"NEX_OPENBAO_TIMEOUT_SECONDS": "61"}, "timeout"),
        ({"NEX_OPENBAO_TIMEOUT_SECONDS": "bad"}, "timeout"),
    ],
)
def test_startup_token_bootstrap_fails_closed(changes, message) -> None:
    environment = {
        **_environment(),
        SERVICE_CREDENTIAL_ID_ENV: "credential-nex-eos",
        SERVICE_CLIENT_SECRET_ENV: "private-client-secret",
        **changes,
    }
    with pytest.raises(StartupServiceTokenBootstrapError, match=message):
        issue_startup_service_tokens(
            "nex-eos", environment, requester=TokenEndpoint(), clock=lambda: 500
        )


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(403, json={"detail": "denied"}), "rejected"),
        (httpx.Response(200, content=b"{"), "response is invalid"),
        (httpx.Response(200, json=[]), "response is invalid"),
        (httpx.Response(200, json={}), "response is invalid"),
    ],
)
def test_startup_token_bootstrap_rejects_endpoint_failures(response, message) -> None:
    environment = {
        **_environment(),
        SERVICE_CREDENTIAL_ID_ENV: "credential-nex-eos",
        SERVICE_CLIENT_SECRET_ENV: "private-client-secret",
    }

    with pytest.raises(StartupServiceTokenBootstrapError, match=message):
        issue_startup_service_tokens(
            "nex-eos",
            environment,
            requester=lambda *args, **kwargs: response,
            clock=lambda: 500,
        )


def test_startup_token_bootstrap_rejects_unavailable_and_misbound_token() -> None:
    environment = {
        **_environment(),
        SERVICE_CREDENTIAL_ID_ENV: "credential-nex-eos",
        SERVICE_CLIENT_SECRET_ENV: "private-client-secret",
    }

    def unavailable(*args, **kwargs):
        raise httpx.ConnectError("private endpoint detail")

    with pytest.raises(StartupServiceTokenBootstrapError, match="unavailable"):
        issue_startup_service_tokens(
            "nex-eos", environment, requester=unavailable, clock=lambda: 500
        )
    with pytest.raises(StartupServiceTokenBootstrapError, match="owner"):
        issue_startup_service_tokens(
            "unknown", environment, requester=TokenEndpoint(), clock=lambda: 500
        )
    with pytest.raises(StartupServiceTokenBootstrapError, match="requested profile"):
        issue_startup_service_tokens(
            "nex-eos",
            environment,
            requester=TokenEndpoint(owner="nex-wa"),
            clock=lambda: 500,
        )


def test_canonical_production_bootstrap_materializes_then_issues_tokens() -> None:
    captured: dict[str, Any] = {}

    def issuer(owner: str, values: Any):
        captured.update(owner=owner, values=dict(values))
        result = dict(values)
        result.pop(SERVICE_CREDENTIAL_ID_ENV)
        result.pop(SERVICE_CLIENT_SECRET_ENV)
        result["NEX_EOS_TO_AE_SERVICE_TOKEN"] = "issued-token"
        return result, object()

    resolver = Resolver()
    process_environment, materialization = prepare_production_container_environment(
        "nex-eos",
        _environment(),
        root=ROOT,
        resolver_factory=lambda _: resolver,
        startup_token_issuer=issuer,
    )

    assert resolver.revoked is True
    assert captured["owner"] == "nex-eos"
    assert len(materialization.owner_environment.secrets) == 6
    assert process_environment["NEX_EOS_TO_AE_SERVICE_TOKEN"] == "issued-token"
    assert SERVICE_CREDENTIAL_ID_ENV not in process_environment
    assert not any(name.endswith("_REF") for name in process_environment)


def test_startup_token_profile_is_admitted_only_at_canonical_boundary() -> None:
    environment = _environment()
    assert service_token_exchange_profile_for_environment(environment).name == (
        "startup_service_access"
    )
    with pytest.raises(ValueError, match="boundary"):
        service_token_exchange_profile_for_environment(
            {**environment, "NEX_DEPLOYMENT_BOUNDARY": "P8_DEMO"}
        )
    with pytest.raises(ValueError, match="unsupported"):
        service_token_exchange_profile_for_environment(
            {**environment, "NEX_SERVICE_TOKEN_BOOTSTRAP_PROFILE": "bad"}
        )

    endpoint = TokenEndpoint(owner="nex-ae-api")
    token_environment = {
        **environment,
        SERVICE_CREDENTIAL_ID_ENV: "credential-nex-ae-api",
        SERVICE_CLIENT_SECRET_ENV: "private-client-secret",
    }
    issued, _ = issue_startup_service_tokens(
        "nex-ae-api", token_environment, requester=endpoint, clock=lambda: 500
    )
    runtime = build_oa_local_service_token_admission(
        signing_key_service=object(),
        validation_service=object(),
        environ=environment,
        clock=lambda: 500,
    )
    assert runtime.rollout_profile == "SIGNED_ONLY"
    assert issued["NEX_AE_TO_OA_SERVICE_TOKEN"].count(".") == 2


def test_canonical_principal_provisioning_covers_wa_and_replays() -> None:
    service = OaServicePrincipalService(InMemoryOaServicePrincipalRepository())
    specs = canonical_service_principal_specs()
    secrets = {
        spec.owner: f"private-{spec.owner}-client-secret-material" for spec in specs
    }
    created = provision_canonical_service_principals(
        service,
        generation="v1",
        client_secrets=secrets,
        now_epoch=1_000,
    )
    replayed = provision_canonical_service_principals(
        service,
        generation="v1",
        client_secrets=secrets,
        now_epoch=1_001,
    )

    assert {spec.owner for spec in specs} == set(CANONICAL_PLATFORM_OWNERS) - {"nex-oa"}
    assert created.created_principal_count == 7
    assert replayed.reused_credential_count == 7
    assert created.evidence()["credential_values_included"] is False
    assert created.openbao_values_by_owner()["nex-wa"] == {
        SERVICE_CREDENTIAL_ID_ENV: "canonical-wa-v1",
        SERVICE_CLIENT_SECRET_ENV: secrets["nex-wa"],
    }
    with pytest.raises(CanonicalServicePrincipalProvisioningError, match="coverage"):
        provision_canonical_service_principals(
            service,
            generation="v2",
            client_secrets={"nex-wa": secrets["nex-wa"]},
            now_epoch=1_002,
        )


def test_canonical_principal_provisioning_updates_and_rejects_secret_rebind() -> None:
    service = OaServicePrincipalService(InMemoryOaServicePrincipalRepository())
    specs = canonical_service_principal_specs()
    secrets = {
        spec.owner: f"private-{spec.owner}-client-secret-material" for spec in specs
    }
    provision_canonical_service_principals(
        service,
        generation="v1",
        client_secrets=secrets,
        now_epoch=1_000,
    )
    principal = service.get_principal("canonical-wa")["principal"]
    service.upsert_principal(
        {
            **principal,
            "display_name": "Drifted WA Runtime",
            "expected_revision": principal["revision"],
        }
    )

    updated = provision_canonical_service_principals(
        service,
        generation="v1",
        client_secrets=secrets,
        now_epoch=1_001,
    )
    assert updated.updated_principal_count == 1
    assert service.get_principal("canonical-wa")["principal"]["display_name"] == (
        "Canonical WA Runtime"
    )

    with pytest.raises(CanonicalServicePrincipalProvisioningError, match="different"):
        provision_canonical_service_principals(
            service,
            generation="v1",
            client_secrets={**secrets, "nex-wa": "different-private-secret-material"},
            now_epoch=1_002,
        )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"generation": "latest"}, "generation"),
        ({"now_epoch": True}, "clock"),
        ({"lifetime_days": 0}, "lifetime"),
        ({"lifetime_days": 31}, "lifetime"),
    ],
)
def test_canonical_principal_provisioning_rejects_invalid_policy(
    changes, message
) -> None:
    specs = canonical_service_principal_specs()
    arguments = {
        "generation": "v1",
        "client_secrets": {
            spec.owner: f"private-{spec.owner}-client-secret-material" for spec in specs
        },
        "now_epoch": 1_000,
        **changes,
    }
    with pytest.raises(CanonicalServicePrincipalProvisioningError, match=message):
        provision_canonical_service_principals(
            OaServicePrincipalService(InMemoryOaServicePrincipalRepository()),
            **arguments,
        )


def test_canonical_principal_provisioning_rejects_invalid_authority_and_secret() -> (
    None
):
    with pytest.raises(CanonicalServicePrincipalProvisioningError, match="authority"):
        provision_canonical_service_principals(
            object(), generation="v1", client_secrets={}, now_epoch=1_000
        )

    service = OaServicePrincipalService(InMemoryOaServicePrincipalRepository())
    specs = canonical_service_principal_specs()
    secrets = {
        spec.owner: f"private-{spec.owner}-client-secret-material" for spec in specs
    }
    secrets["nex-wa"] = "short"
    with pytest.raises(CanonicalServicePrincipalProvisioningError, match="secret"):
        provision_canonical_service_principals(
            service,
            generation="v1",
            client_secrets=secrets,
            now_epoch=1_000,
        )
    for spec in specs:
        with pytest.raises(OaServicePrincipalError) as missing:
            service.get_principal(spec.principal_id)
        assert missing.value.status_code == 404


def test_canonical_compose_is_final_and_has_no_active_demo_environment() -> None:
    assert CURRENT_COMPOSE_PATHS[-1] == (
        "deployment/compose/canonical-platform.override.yaml"
    )
    result = admit_current_platform_installation(ROOT)
    assert result["checks"]["canonical_environment_contract"] is True

    overlay = (ROOT / "deployment/compose/canonical-platform.override.yaml").read_text(
        encoding="utf-8"
    )
    assert "NEX_P8_DEMO_" not in overlay
    assert "p8_demo_" not in overlay
    assert (
        "NEX_AE_TO_WA_SERVICE_TOKEN_REF: "
        "secret://openbao/nex-platform/staging/nex-ae-api/"
        "NEX_AE_TO_WA_SERVICE_TOKEN@${NEX_CANONICAL_PLATFORM_SECRET_VERSION:-v1}"
    ) in overlay
    source = _source_admission(
        ROOT,
        inventory=canonical_platform_trust_projection(),
    )
    assert source["slice"] == "GB2-CA00-S18B"
    assert source["compose_source_count"] == 4


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("_SECRET_TARGETS_BY_OWNER", {"nex-oa": ("NEX_OA_DATABASE_URL",)}),
        (
            "CANONICAL_PLATFORM_SECRET_BINDINGS",
            (
                *CANONICAL_PLATFORM_SECRET_BINDINGS,
                CANONICAL_PLATFORM_SECRET_BINDINGS[0],
            ),
        ),
        (
            "CANONICAL_PLATFORM_TRUST_GRANTS",
            (
                *trust.CANONICAL_PLATFORM_TRUST_GRANTS,
                trust.CANONICAL_PLATFORM_TRUST_GRANTS[0],
            ),
        ),
        (
            "CANONICAL_PLATFORM_TLS_HOSTS",
            (
                *trust.CANONICAL_PLATFORM_TLS_HOSTS,
                trust.CANONICAL_PLATFORM_TLS_HOSTS[0],
            ),
        ),
    ],
)
def test_canonical_projection_detects_inventory_drift(monkeypatch, name, value) -> None:
    monkeypatch.setattr(trust, name, value)
    with pytest.raises(CanonicalPlatformTrustError, match="inventory drift"):
        canonical_platform_trust_projection()
