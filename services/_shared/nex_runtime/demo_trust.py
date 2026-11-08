from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from .production_secret_materialization import (
    OwnerProductionSecretMaterialization,
    OwnerSecretEnvironment,
    ResolvedSecret,
    SecretReferenceResolver,
    SecretResolutionContext,
)
from .semantic_hashes import semantic_sha256_hash_ref

DEMO_TRUST_SCHEMA_VERSION = "p8_demo_trust.v1"
DEMO_DEPLOYMENT_BOUNDARY = "P8_DEMO"
DEMO_OWNERS = (
    "nex-oa",
    "nex-ae-api",
    "nex-cx",
    "nex-mo",
    "nex-ag",
    "nex-wc",
    "nex-eos",
)
DEMO_TLS_HOSTS = (
    "oa.nex-staging.test",
    "ag.nex-staging.test",
    "ae-api.nex-staging.test",
    "cx.nex-staging.test",
    "mo.nex-staging.test",
    "wc.nex-staging.test",
    "eos.nex-staging.test",
    "ae.nex-staging.test",
    "embedding.nex-staging.test",
    "reranker.nex-staging.test",
    "generation.nex-staging.test",
    "id.nex-staging.test",
    "object.nex-staging.test",
)
_GENERATION = re.compile(r"^[a-z][a-z0-9-]{2,31}:[A-Za-z0-9][A-Za-z0-9._-]{3,127}$")
_VERSION = re.compile(r"^v[1-9][0-9]*$")


class DemoTrustError(ValueError):
    pass


@dataclass(frozen=True)
class DemoSecretBinding:
    owner: str
    target_environment_name: str

    @property
    def source_environment_name(self) -> str:
        return f"{self.target_environment_name}_REF"


@dataclass(frozen=True)
class DemoTrustGrant:
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
}

DEMO_SECRET_BINDINGS = tuple(
    DemoSecretBinding(owner, target)
    for owner in DEMO_OWNERS
    for target in _SECRET_TARGETS_BY_OWNER[owner]
)

DEMO_TRUST_GRANTS = (
    DemoTrustGrant(
        "NEX_AE_TO_OA_SERVICE_TOKEN",
        "nex-ae-api",
        "nex-oa",
        ("service:call", "authorization:read"),
    ),
    DemoTrustGrant(
        "NEX_AE_TO_CX_SERVICE_TOKEN", "nex-ae-api", "nex-cx", ("service:call",)
    ),
    DemoTrustGrant(
        "NEX_AE_TO_MO_SERVICE_TOKEN", "nex-ae-api", "nex-mo", ("service:call",)
    ),
    DemoTrustGrant(
        "NEX_AE_TO_AG_SERVICE_TOKEN", "nex-ae-api", "nex-ag", ("service:call",)
    ),
    DemoTrustGrant(
        "NEX_AE_TO_WC_SERVICE_TOKEN", "nex-ae-api", "nex-wc", ("service:call",)
    ),
    DemoTrustGrant(
        "NEX_AE_TO_EOS_SERVICE_TOKEN", "nex-ae-api", "nex-eos", ("service:call",)
    ),
    DemoTrustGrant("NEX_CX_TO_MO_SERVICE_TOKEN", "nex-cx", "nex-mo", ("service:call",)),
    DemoTrustGrant("NEX_AG_TO_OA_SERVICE_TOKEN", "nex-ag", "nex-oa", ("service:call",)),
    DemoTrustGrant(
        "NEX_AG_TO_AE_SERVICE_TOKEN", "nex-ag", "nex-ae-api", ("service:call",)
    ),
    DemoTrustGrant("NEX_AG_TO_CX_SERVICE_TOKEN", "nex-ag", "nex-cx", ("service:call",)),
    DemoTrustGrant("NEX_AG_TO_MO_SERVICE_TOKEN", "nex-ag", "nex-mo", ("service:call",)),
    DemoTrustGrant(
        "NEX_WC_TO_OA_SERVICE_TOKEN",
        "nex-wc",
        "nex-oa",
        ("service:call", "authorization:read"),
    ),
    DemoTrustGrant(
        "NEX_WC_TO_AE_SERVICE_TOKEN", "nex-wc", "nex-ae-api", ("service:call",)
    ),
    DemoTrustGrant(
        "NEX_EOS_TO_WC_SERVICE_TOKEN", "nex-eos", "nex-wc", ("service:call",)
    ),
    DemoTrustGrant(
        "NEX_EOS_TO_AE_SERVICE_TOKEN", "nex-eos", "nex-ae-api", ("service:call",)
    ),
    DemoTrustGrant(
        "NEX_EOS_TO_OA_SERVICE_TOKEN",
        "nex-eos",
        "nex-oa",
        ("service:call", "authorization:read", "identity:employee:resolve"),
    ),
)

DEMO_STARTUP_TOKEN_BOOTSTRAP_ENV = "NEX_P8_DEMO_STARTUP_TOKEN_BOOTSTRAP"
DEMO_STARTUP_CREDENTIAL_TARGETS = (
    "NEX_P8_DEMO_SERVICE_CREDENTIAL_ID",
    "NEX_P8_DEMO_SERVICE_CLIENT_SECRET",
)


def demo_secret_bindings_for_owner(owner: str) -> tuple[DemoSecretBinding, ...]:
    if owner not in DEMO_OWNERS:
        raise DemoTrustError("Demo trust owner is invalid")
    return tuple(binding for binding in DEMO_SECRET_BINDINGS if binding.owner == owner)


def demo_startup_credential_bindings_for_owner(
    owner: str,
) -> tuple[DemoSecretBinding, ...]:
    if owner not in DEMO_OWNERS:
        raise DemoTrustError("Demo trust owner is invalid")
    if owner == "nex-oa":
        return ()
    return tuple(DemoSecretBinding(owner, target) for target in DEMO_STARTUP_CREDENTIAL_TARGETS)


def materialize_demo_owner_secrets(
    environ: Mapping[str, str],
    resolver: SecretReferenceResolver,
    *,
    owner: str,
    profile: str,
) -> OwnerProductionSecretMaterialization:
    if (
        str(environ.get("NEX_DEPLOYMENT_BOUNDARY") or "").strip()
        != DEMO_DEPLOYMENT_BOUNDARY
    ):
        raise DemoTrustError("Demo deployment boundary is invalid")
    if profile not in {"staging_live", "production"}:
        raise DemoTrustError("Demo trust profile is invalid")
    generation = str(environ.get("NEX_SECRET_GENERATION") or "").strip()
    if _GENERATION.fullmatch(generation) is None:
        raise DemoTrustError("Demo secret generation is invalid")

    bindings = demo_secret_bindings_for_owner(owner)
    if str(environ.get(DEMO_STARTUP_TOKEN_BOOTSTRAP_ENV) or "").strip().lower() == "true":
        bindings = (*bindings, *demo_startup_credential_bindings_for_owner(owner))

    secrets: list[ResolvedSecret] = []
    metadata = []
    for binding in bindings:
        if str(environ.get(binding.target_environment_name) or "").strip():
            raise DemoTrustError(
                f"raw Demo secret input is prohibited: {binding.target_environment_name}"
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
        # Resolver implementations may use different transport exception types;
        # none may escape with provider diagnostics or secret-adjacent detail.
        except Exception:  # noqa: BLE001
            raise DemoTrustError(
                f"Demo secret resolution failed: {binding.target_environment_name}"
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
            "boundary": DEMO_DEPLOYMENT_BOUNDARY,
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


def demo_trust_projection() -> dict[str, Any]:
    targets = [binding.target_environment_name for binding in DEMO_SECRET_BINDINGS]
    trust_names = [grant.environment_name for grant in DEMO_TRUST_GRANTS]
    if (
        set(_SECRET_TARGETS_BY_OWNER) != set(DEMO_OWNERS)
        or len(targets) != len(set(targets))
        or len(trust_names) != len(set(trust_names))
        or not set(trust_names).issubset(targets)
        or len(DEMO_TLS_HOSTS) != len(set(DEMO_TLS_HOSTS))
    ):
        raise DemoTrustError("Demo trust inventory drift")
    return {
        "schema_version": DEMO_TRUST_SCHEMA_VERSION,
        "deployment_boundary": DEMO_DEPLOYMENT_BOUNDARY,
        "owner_count": len(DEMO_OWNERS),
        "secret_binding_count": len(DEMO_SECRET_BINDINGS),
        "trust_grant_count": len(DEMO_TRUST_GRANTS),
        "tls_host_count": len(DEMO_TLS_HOSTS),
        "owner_secret_counts": {
            owner: len(demo_secret_bindings_for_owner(owner)) for owner in DEMO_OWNERS
        },
        "raw_secret_values_included": False,
        "token_values_included": False,
    }


def _reference_version(
    reference: str,
    *,
    binding: DemoSecretBinding,
    profile: str,
) -> str:
    namespace = "staging" if profile == "staging_live" else "production"
    parsed = urlsplit(reference)
    prefix = (
        f"/nex-platform/{namespace}/{binding.owner}/"
        f"{binding.target_environment_name}@"
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
        raise DemoTrustError(
            f"Demo secret reference is invalid: {binding.source_environment_name}"
        )
    version = parsed.path[len(prefix) :]
    if _VERSION.fullmatch(version) is None:
        raise DemoTrustError(
            f"Demo secret reference is invalid: {binding.source_environment_name}"
        )
    return version


def _validate_resolved_secret(
    value: object,
    *,
    context: SecretResolutionContext,
) -> None:
    if not isinstance(value, ResolvedSecret):
        raise DemoTrustError("Demo secret resolver result is invalid")
    if (
        value.owner != context.owner
        or value.target_environment_name != context.target_environment_name
        or value.secret_generation != context.secret_generation
        or value.reference_version != context.reference_version
        or value.provider_id != "openbao"
    ):
        raise DemoTrustError("Demo secret resolver metadata mismatch")
    if (
        not isinstance(value.value, str)
        or not value.value.strip()
        or value.value != value.value.strip()
        or any(
            ord(character) < 32 or ord(character) == 127 for character in value.value
        )
    ):
        raise DemoTrustError("Demo secret resolver value is invalid")
