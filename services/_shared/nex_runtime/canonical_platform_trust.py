from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlsplit

from .production_secret_materialization import (
    OwnerProductionSecretMaterialization,
    OwnerSecretEnvironment,
    ResolvedSecret,
    SecretReferenceResolver,
    SecretResolutionContext,
)
from .semantic_hashes import semantic_sha256_hash_ref

CANONICAL_PLATFORM_TRUST_SCHEMA_VERSION = "canonical_platform_trust.v1"
CANONICAL_PLATFORM_DEPLOYMENT_BOUNDARY = "CANONICAL_PLATFORM"
CANONICAL_PLATFORM_OWNERS = (
    "nex-oa",
    "nex-ae-api",
    "nex-cx",
    "nex-mo",
    "nex-ag",
    "nex-wc",
    "nex-eos",
    "nex-wa",
)
CANONICAL_PLATFORM_TLS_HOSTS = (
    "oa.nex-staging.test",
    "ag.nex-staging.test",
    "ae-api.nex-staging.test",
    "cx.nex-staging.test",
    "mo.nex-staging.test",
    "wc.nex-staging.test",
    "eos.nex-staging.test",
    "wa.nex-staging.test",
    "ae.nex-staging.test",
    "embedding.nex-staging.test",
    "reranker.nex-staging.test",
    "generation.nex-staging.test",
    "id.nex-staging.test",
    "object.nex-staging.test",
)
STARTUP_SERVICE_TOKEN_BOOTSTRAP_ENV = "NEX_STARTUP_SERVICE_TOKEN_BOOTSTRAP"
SERVICE_TOKEN_BOOTSTRAP_PROFILE_ENV = "NEX_SERVICE_TOKEN_BOOTSTRAP_PROFILE"
SERVICE_TOKEN_BOOTSTRAP_PROFILE = "STARTUP_24H"
SERVICE_CREDENTIAL_ID_ENV = "NEX_SERVICE_CREDENTIAL_ID"
SERVICE_CLIENT_SECRET_ENV = "NEX_SERVICE_CLIENT_SECRET"
STARTUP_CREDENTIAL_TARGETS = (
    SERVICE_CREDENTIAL_ID_ENV,
    SERVICE_CLIENT_SECRET_ENV,
)
CANONICAL_RUNTIME_APPROLE_SECRET_ID_TTL = "24h"
CANONICAL_RUNTIME_APPROLE_SECRET_ID_TTL_SECONDS = 86_400
CANONICAL_RUNTIME_APPROLE_SECRET_ID_NUM_USES = 0

_GENERATION = re.compile(r"^[a-z][a-z0-9-]{2,31}:[A-Za-z0-9][A-Za-z0-9._-]{3,127}$")
_VERSION = re.compile(r"^v[1-9][0-9]*$")


class CanonicalPlatformTrustError(ValueError):
    pass


@dataclass(frozen=True)
class CanonicalSecretBinding:
    owner: str
    target_environment_name: str

    @property
    def source_environment_name(self) -> str:
        return f"{self.target_environment_name}_REF"


@dataclass(frozen=True)
class CanonicalTrustGrant:
    environment_name: str
    owner: str
    audience: str
    scopes: tuple[str, ...]


_SECRET_TARGETS_BY_OWNER = {
    "nex-oa": (
        "NEX_OA_DATABASE_URL",
        "NEX_OA_INTROSPECTION_SERVICE_TOKEN",
    ),
    "nex-ae-api": (
        "NEX_AE_DATABASE_URL",
        "NEX_AE_TO_OA_SERVICE_TOKEN",
        "NEX_AE_TO_CX_SERVICE_TOKEN",
        "NEX_AE_TO_MO_SERVICE_TOKEN",
        "NEX_AE_TO_AG_SERVICE_TOKEN",
        "NEX_AE_TO_WC_SERVICE_TOKEN",
        "NEX_AE_TO_EOS_SERVICE_TOKEN",
        "NEX_AE_TO_WA_SERVICE_TOKEN",
        "NEX_AE_OBJECT_STORAGE_ACCESS_KEY",
        "NEX_AE_OBJECT_STORAGE_SECRET_KEY",
    ),
    "nex-cx": (
        "NEX_CX_DATABASE_URL",
        "NEX_CX_TO_MO_SERVICE_TOKEN",
        "NEX_CX_OBJECT_STORAGE_ACCESS_KEY",
        "NEX_CX_OBJECT_STORAGE_SECRET_KEY",
    ),
    "nex-mo": (
        "NEX_MO_DATABASE_URL",
        "NEX_MO_REMOTE_EMBEDDING_API_KEY",
        "NEX_MO_REMOTE_RERANKER_API_KEY",
        "NEX_MO_VLLM_API_KEY",
    ),
    "nex-ag": (
        "NEX_AG_DATABASE_URL",
        "NEX_AG_TO_OA_SERVICE_TOKEN",
        "NEX_AG_TO_AE_SERVICE_TOKEN",
        "NEX_AG_TO_CX_SERVICE_TOKEN",
        "NEX_AG_TO_MO_SERVICE_TOKEN",
    ),
    "nex-wc": (
        "NEX_WC_DATABASE_URL",
        "NEX_WC_TO_OA_SERVICE_TOKEN",
        "NEX_WC_TO_AE_SERVICE_TOKEN",
    ),
    "nex-eos": (
        "NEX_EOS_DATABASE_URL",
        "NEX_EOS_TO_WC_SERVICE_TOKEN",
        "NEX_EOS_TO_AE_SERVICE_TOKEN",
        "NEX_EOS_TO_OA_SERVICE_TOKEN",
    ),
    "nex-wa": (
        "NEX_WA_DATABASE_URL",
        "NEX_WA_TO_AE_SERVICE_TOKEN",
        "NEX_WA_TO_WC_SERVICE_TOKEN",
        "NEX_WA_TO_OA_SERVICE_TOKEN",
        "NEX_WA_TO_EOS_SERVICE_TOKEN",
    ),
}

CANONICAL_PLATFORM_SECRET_BINDINGS = tuple(
    CanonicalSecretBinding(owner, target)
    for owner in CANONICAL_PLATFORM_OWNERS
    for target in _SECRET_TARGETS_BY_OWNER[owner]
)

CANONICAL_PLATFORM_TRUST_GRANTS = (
    CanonicalTrustGrant(
        "NEX_AE_TO_OA_SERVICE_TOKEN",
        "nex-ae-api",
        "nex-oa",
        ("service:call", "authorization:read"),
    ),
    CanonicalTrustGrant(
        "NEX_AE_TO_CX_SERVICE_TOKEN", "nex-ae-api", "nex-cx", ("service:call",)
    ),
    CanonicalTrustGrant(
        "NEX_AE_TO_MO_SERVICE_TOKEN", "nex-ae-api", "nex-mo", ("service:call",)
    ),
    CanonicalTrustGrant(
        "NEX_AE_TO_AG_SERVICE_TOKEN", "nex-ae-api", "nex-ag", ("service:call",)
    ),
    CanonicalTrustGrant(
        "NEX_AE_TO_WC_SERVICE_TOKEN", "nex-ae-api", "nex-wc", ("service:call",)
    ),
    CanonicalTrustGrant(
        "NEX_AE_TO_EOS_SERVICE_TOKEN", "nex-ae-api", "nex-eos", ("service:call",)
    ),
    CanonicalTrustGrant(
        "NEX_AE_TO_WA_SERVICE_TOKEN", "nex-ae-api", "nex-wa", ("service:call",)
    ),
    CanonicalTrustGrant(
        "NEX_CX_TO_MO_SERVICE_TOKEN", "nex-cx", "nex-mo", ("service:call",)
    ),
    CanonicalTrustGrant(
        "NEX_AG_TO_OA_SERVICE_TOKEN", "nex-ag", "nex-oa", ("service:call",)
    ),
    CanonicalTrustGrant(
        "NEX_AG_TO_AE_SERVICE_TOKEN", "nex-ag", "nex-ae-api", ("service:call",)
    ),
    CanonicalTrustGrant(
        "NEX_AG_TO_CX_SERVICE_TOKEN", "nex-ag", "nex-cx", ("service:call",)
    ),
    CanonicalTrustGrant(
        "NEX_AG_TO_MO_SERVICE_TOKEN", "nex-ag", "nex-mo", ("service:call",)
    ),
    CanonicalTrustGrant(
        "NEX_WC_TO_OA_SERVICE_TOKEN",
        "nex-wc",
        "nex-oa",
        ("service:call", "authorization:read"),
    ),
    CanonicalTrustGrant(
        "NEX_WC_TO_AE_SERVICE_TOKEN", "nex-wc", "nex-ae-api", ("service:call",)
    ),
    CanonicalTrustGrant(
        "NEX_EOS_TO_WC_SERVICE_TOKEN", "nex-eos", "nex-wc", ("service:call",)
    ),
    CanonicalTrustGrant(
        "NEX_EOS_TO_AE_SERVICE_TOKEN", "nex-eos", "nex-ae-api", ("service:call",)
    ),
    CanonicalTrustGrant(
        "NEX_EOS_TO_OA_SERVICE_TOKEN",
        "nex-eos",
        "nex-oa",
        ("service:call", "authorization:read", "identity:employee:resolve"),
    ),
    CanonicalTrustGrant(
        "NEX_WA_TO_AE_SERVICE_TOKEN", "nex-wa", "nex-ae-api", ("service:call",)
    ),
    CanonicalTrustGrant(
        "NEX_WA_TO_WC_SERVICE_TOKEN", "nex-wa", "nex-wc", ("service:call",)
    ),
    CanonicalTrustGrant(
        "NEX_WA_TO_OA_SERVICE_TOKEN",
        "nex-wa",
        "nex-oa",
        ("service:call", "authorization:read"),
    ),
    CanonicalTrustGrant(
        "NEX_WA_TO_EOS_SERVICE_TOKEN", "nex-wa", "nex-eos", ("service:call",)
    ),
)


def canonical_secret_bindings_for_owner(
    owner: str,
) -> tuple[CanonicalSecretBinding, ...]:
    _require_owner(owner)
    return tuple(
        binding
        for binding in CANONICAL_PLATFORM_SECRET_BINDINGS
        if binding.owner == owner
    )


def canonical_startup_credential_bindings_for_owner(
    owner: str,
) -> tuple[CanonicalSecretBinding, ...]:
    _require_owner(owner)
    if owner == "nex-oa":
        return ()
    return tuple(
        CanonicalSecretBinding(owner, target) for target in STARTUP_CREDENTIAL_TARGETS
    )


def materialize_canonical_owner_secrets(
    environ: Mapping[str, str],
    resolver: SecretReferenceResolver,
    *,
    owner: str,
    profile: str,
) -> OwnerProductionSecretMaterialization:
    _require_owner(owner)
    if str(environ.get("NEX_DEPLOYMENT_BOUNDARY") or "").strip() != (
        CANONICAL_PLATFORM_DEPLOYMENT_BOUNDARY
    ):
        raise CanonicalPlatformTrustError("canonical deployment boundary is invalid")
    if profile not in {"staging_live", "production"}:
        raise CanonicalPlatformTrustError("canonical trust profile is invalid")
    generation = str(environ.get("NEX_SECRET_GENERATION") or "").strip()
    if _GENERATION.fullmatch(generation) is None:
        raise CanonicalPlatformTrustError("canonical secret generation is invalid")

    bindings = canonical_secret_bindings_for_owner(owner)
    if _enabled(environ.get(STARTUP_SERVICE_TOKEN_BOOTSTRAP_ENV)):
        bindings = (*bindings, *canonical_startup_credential_bindings_for_owner(owner))

    secrets: list[ResolvedSecret] = []
    metadata = []
    for binding in bindings:
        if str(environ.get(binding.target_environment_name) or "").strip():
            raise CanonicalPlatformTrustError(
                f"raw canonical secret input is prohibited: {binding.target_environment_name}"
            )
        reference = str(environ.get(binding.source_environment_name) or "").strip()
        version = _reference_version(reference, binding=binding, profile=profile)
        context = SecretResolutionContext(
            owner=owner,
            target_environment_name=binding.target_environment_name,
            secret_generation=generation,
            reference_version=version,
        )
        try:
            resolved = resolver.resolve(reference, context=context)
        except Exception:  # noqa: BLE001
            raise CanonicalPlatformTrustError(
                f"canonical secret resolution failed: {binding.target_environment_name}"
            ) from None
        _validate_resolved_secret(resolved, context=context)
        secrets.append(resolved)
        metadata.append(
            (
                owner,
                binding.target_environment_name,
                resolved.provider_id,
                resolved.reference_version,
            )
        )

    configuration_digest = semantic_sha256_hash_ref(
        {
            "boundary": CANONICAL_PLATFORM_DEPLOYMENT_BOUNDARY,
            "profile": profile,
            "owner": owner,
            "references": [
                (
                    binding.source_environment_name,
                    environ[binding.source_environment_name],
                )
                for binding in bindings
            ],
        }
    )
    materialization_digest = semantic_sha256_hash_ref(
        {
            "configuration_digest": configuration_digest,
            "secret_generation": generation,
            "metadata": metadata,
        }
    )
    return OwnerProductionSecretMaterialization(
        schema_version="production_secret_materialization.v1",
        profile=profile,
        status="MATERIALIZED_FOR_OWNER_PROCESS",
        configuration_digest=configuration_digest,
        materialization_digest=materialization_digest,
        secret_generation=generation,
        owner_environment=OwnerSecretEnvironment(owner, tuple(secrets)),
    )


def canonical_platform_trust_projection() -> dict[str, Any]:
    targets = [
        binding.target_environment_name
        for binding in CANONICAL_PLATFORM_SECRET_BINDINGS
    ]
    grants = [grant.environment_name for grant in CANONICAL_PLATFORM_TRUST_GRANTS]
    if (
        set(_SECRET_TARGETS_BY_OWNER) != set(CANONICAL_PLATFORM_OWNERS)
        or len(targets) != len(set(targets))
        or len(grants) != len(set(grants))
        or not set(grants).issubset(targets)
        or len(CANONICAL_PLATFORM_TLS_HOSTS) != len(set(CANONICAL_PLATFORM_TLS_HOSTS))
    ):
        raise CanonicalPlatformTrustError("canonical trust inventory drift")
    return {
        "schema_version": CANONICAL_PLATFORM_TRUST_SCHEMA_VERSION,
        "deployment_boundary": CANONICAL_PLATFORM_DEPLOYMENT_BOUNDARY,
        "owner_count": len(CANONICAL_PLATFORM_OWNERS),
        "secret_binding_count": len(CANONICAL_PLATFORM_SECRET_BINDINGS),
        "trust_grant_count": len(CANONICAL_PLATFORM_TRUST_GRANTS),
        "tls_host_count": len(CANONICAL_PLATFORM_TLS_HOSTS),
        "owner_secret_counts": {
            owner: len(canonical_secret_bindings_for_owner(owner))
            for owner in CANONICAL_PLATFORM_OWNERS
        },
        "raw_secret_values_included": False,
        "token_values_included": False,
    }


def configure_canonical_runtime_approles(
    client: Any,
    *,
    root_token: str,
    owners: tuple[str, ...] = CANONICAL_PLATFORM_OWNERS,
) -> dict[str, Any]:
    admitted = tuple(owners)
    if (
        not admitted
        or len(admitted) != len(set(admitted))
        or any(owner not in CANONICAL_PLATFORM_OWNERS for owner in admitted)
    ):
        raise CanonicalPlatformTrustError("canonical AppRole owner set is invalid")
    if not isinstance(root_token, str) or not root_token.strip():
        raise CanonicalPlatformTrustError("canonical OpenBao root token is invalid")
    for owner in admitted:
        role_name = f"{owner}-staging"
        client.request(
            "POST",
            f"/v1/auth/approle/role/{quote(role_name, safe='-_')}",
            token=root_token,
            payload={
                "token_policies": [f"{owner}-staging"],
                "token_ttl": "5m",
                "token_max_ttl": "10m",
                "secret_id_ttl": CANONICAL_RUNTIME_APPROLE_SECRET_ID_TTL,
                "secret_id_num_uses": CANONICAL_RUNTIME_APPROLE_SECRET_ID_NUM_USES,
            },
        )
        response = client.request(
            "GET",
            f"/v1/auth/approle/role/{quote(role_name, safe='-_')}",
            token=root_token,
        )
        data = response.get("data")
        if not isinstance(data, Mapping) or (
            _integer(data.get("secret_id_ttl"), default=0)
            != CANONICAL_RUNTIME_APPROLE_SECRET_ID_TTL_SECONDS
            or _integer(data.get("secret_id_num_uses"), default=-1)
            != CANONICAL_RUNTIME_APPROLE_SECRET_ID_NUM_USES
        ):
            raise CanonicalPlatformTrustError(
                f"canonical runtime AppRole policy drift: {owner}"
            )
    payload = {
        "schema_version": "canonical_runtime_approle.v1",
        "status": "CONFIGURED",
        "deployment_boundary": CANONICAL_PLATFORM_DEPLOYMENT_BOUNDARY,
        "owner_count": len(admitted),
        "secret_id_ttl_seconds": CANONICAL_RUNTIME_APPROLE_SECRET_ID_TTL_SECONDS,
        "secret_id_num_uses": CANONICAL_RUNTIME_APPROLE_SECRET_ID_NUM_USES,
        "shared_api_worker_credential": True,
        "restart_reauthentication_supported": True,
        "credential_values_included": False,
    }
    return {**payload, "policy_hash": semantic_sha256_hash_ref(payload)}


def _require_owner(owner: str) -> None:
    if owner not in CANONICAL_PLATFORM_OWNERS:
        raise CanonicalPlatformTrustError("canonical trust owner is invalid")


def _enabled(value: object) -> bool:
    return str(value or "").strip().lower() == "true"


def _integer(value: object, *, default: int) -> int:
    if value is None or isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _reference_version(
    reference: str,
    *,
    binding: CanonicalSecretBinding,
    profile: str,
) -> str:
    namespace = "staging" if profile == "staging_live" else "production"
    parsed = urlsplit(reference)
    prefix = (
        f"/nex-platform/{namespace}/{binding.owner}/{binding.target_environment_name}@"
    )
    if (
        parsed.scheme != "secret"
        or parsed.hostname != "openbao"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.query
        or parsed.fragment
        or not parsed.path.startswith(prefix)
    ):
        raise CanonicalPlatformTrustError(
            f"canonical secret reference is invalid: {binding.source_environment_name}"
        )
    version = parsed.path[len(prefix) :]
    if _VERSION.fullmatch(version) is None:
        raise CanonicalPlatformTrustError(
            f"canonical secret reference is invalid: {binding.source_environment_name}"
        )
    return version


def _validate_resolved_secret(
    value: object,
    *,
    context: SecretResolutionContext,
) -> None:
    if not isinstance(value, ResolvedSecret):
        raise CanonicalPlatformTrustError("canonical secret resolver result is invalid")
    if (
        value.owner != context.owner
        or value.target_environment_name != context.target_environment_name
        or value.secret_generation != context.secret_generation
        or value.reference_version != context.reference_version
        or value.provider_id != "openbao"
    ):
        raise CanonicalPlatformTrustError("canonical secret resolver metadata mismatch")
    if (
        not isinstance(value.value, str)
        or not value.value.strip()
        or value.value != value.value.strip()
        or any(
            ord(character) < 32 or ord(character) == 127 for character in value.value
        )
    ):
        raise CanonicalPlatformTrustError("canonical secret resolver value is invalid")
