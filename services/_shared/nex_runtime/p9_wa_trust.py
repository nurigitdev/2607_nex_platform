from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from .demo_trust import DEMO_DEPLOYMENT_BOUNDARY, materialize_demo_owner_secrets
from .production_secret_materialization import (
    OwnerProductionSecretMaterialization,
    OwnerSecretEnvironment,
    ResolvedSecret,
    SecretReferenceResolver,
    SecretResolutionContext,
)
from .semantic_hashes import semantic_sha256_hash_ref

P9_WA_DEPLOYMENT_BOUNDARY = "P9_WA"
P9_WA_OWNERS = ("nex-ae-api", "nex-wa")
P9_WA_SECRET_TARGETS_BY_OWNER = {
    "nex-ae-api": ("NEX_AE_TO_WA_SERVICE_TOKEN",),
    "nex-wa": (
        "NEX_WA_DATABASE_URL",
        "NEX_WA_TO_AE_SERVICE_TOKEN",
        "NEX_WA_TO_WC_SERVICE_TOKEN",
        "NEX_WA_TO_OA_SERVICE_TOKEN",
        "NEX_WA_TO_EOS_SERVICE_TOKEN",
    ),
}
_GENERATION = re.compile(r"^[a-z][a-z0-9-]{2,31}:[A-Za-z0-9][A-Za-z0-9._-]{3,127}$")
_VERSION = re.compile(r"^v[1-9][0-9]*$")


class P9WaTrustError(ValueError):
    pass


def materialize_p9_wa_owner_secrets(
    environ: Mapping[str, str],
    resolver: SecretReferenceResolver,
    *,
    owner: str,
    profile: str,
) -> OwnerProductionSecretMaterialization:
    if owner not in P9_WA_OWNERS:
        raise P9WaTrustError("P9 WA trust owner is invalid")
    if str(environ.get("NEX_DEPLOYMENT_BOUNDARY") or "").strip() != (
        P9_WA_DEPLOYMENT_BOUNDARY
    ):
        raise P9WaTrustError("P9 WA deployment boundary is invalid")
    if profile not in {"staging_live", "production"}:
        raise P9WaTrustError("P9 WA trust profile is invalid")
    generation = str(environ.get("NEX_SECRET_GENERATION") or "").strip()
    if _GENERATION.fullmatch(generation) is None:
        raise P9WaTrustError("P9 WA secret generation is invalid")

    inherited: tuple[ResolvedSecret, ...] = ()
    inherited_digest: str | None = None
    if owner == "nex-ae-api":
        base_environment = dict(environ)
        base_environment["NEX_DEPLOYMENT_BOUNDARY"] = DEMO_DEPLOYMENT_BOUNDARY
        base = materialize_demo_owner_secrets(
            base_environment,
            resolver,
            owner=owner,
            profile=profile,
        )
        inherited = base.owner_environment.secrets
        inherited_digest = base.materialization_digest

    extensions = tuple(
        _resolve_extension(
            environ,
            resolver,
            owner=owner,
            target=target,
            profile=profile,
            generation=generation,
        )
        for target in P9_WA_SECRET_TARGETS_BY_OWNER[owner]
    )
    secrets = (*inherited, *extensions)
    configuration_digest = semantic_sha256_hash_ref(
        {
            "boundary": P9_WA_DEPLOYMENT_BOUNDARY,
            "profile": profile,
            "owner": owner,
            "inherited_materialization_digest": inherited_digest,
            "references": [
                (f"{target}_REF", environ[f"{target}_REF"])
                for target in P9_WA_SECRET_TARGETS_BY_OWNER[owner]
            ],
        }
    )
    materialization_digest = semantic_sha256_hash_ref(
        {
            "configuration_digest": configuration_digest,
            "secret_generation": generation,
            "metadata": [
                (
                    secret.owner,
                    secret.target_environment_name,
                    secret.provider_id,
                    secret.reference_version,
                )
                for secret in secrets
            ],
        }
    )
    return OwnerProductionSecretMaterialization(
        schema_version="production_secret_materialization.v1",
        profile=profile,
        status="MATERIALIZED_FOR_OWNER_PROCESS",
        configuration_digest=configuration_digest,
        materialization_digest=materialization_digest,
        secret_generation=generation,
        owner_environment=OwnerSecretEnvironment(owner, secrets),
    )


def p9_wa_trust_projection() -> dict[str, Any]:
    return {
        "schema_version": "p9_wa_trust.v1",
        "deployment_boundary": P9_WA_DEPLOYMENT_BOUNDARY,
        "owners": list(P9_WA_OWNERS),
        "owner_extension_secret_counts": {
            owner: len(targets)
            for owner, targets in P9_WA_SECRET_TARGETS_BY_OWNER.items()
        },
        "ae_inherits_p8_demo_secrets": True,
        "raw_secret_values_included": False,
    }


def _resolve_extension(
    environ: Mapping[str, str],
    resolver: SecretReferenceResolver,
    *,
    owner: str,
    target: str,
    profile: str,
    generation: str,
) -> ResolvedSecret:
    if str(environ.get(target) or "").strip():
        raise P9WaTrustError(f"raw P9 WA secret input is prohibited: {target}")
    source = f"{target}_REF"
    reference = str(environ.get(source) or "").strip()
    version = _reference_version(reference, owner=owner, target=target, profile=profile)
    context = SecretResolutionContext(
        owner=owner,
        target_environment_name=target,
        secret_generation=generation,
        reference_version=version,
    )
    try:
        resolved = resolver.resolve(reference, context=context)
    except Exception:  # noqa: BLE001
        raise P9WaTrustError(f"P9 WA secret resolution failed: {target}") from None
    if (
        not isinstance(resolved, ResolvedSecret)
        or resolved.owner != owner
        or resolved.target_environment_name != target
        or resolved.secret_generation != generation
        or resolved.reference_version != version
        or resolved.provider_id != "openbao"
        or not isinstance(resolved.value, str)
        or not resolved.value.strip()
        or resolved.value != resolved.value.strip()
        or any(
            ord(character) < 32 or ord(character) == 127
            for character in resolved.value
        )
    ):
        raise P9WaTrustError("P9 WA secret resolver result is invalid")
    return resolved


def _reference_version(
    reference: str,
    *,
    owner: str,
    target: str,
    profile: str,
) -> str:
    namespace = "staging" if profile == "staging_live" else "production"
    parsed = urlsplit(reference)
    prefix = f"/nex-platform/{namespace}/{owner}/{target}@"
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
        raise P9WaTrustError(f"P9 WA secret reference is invalid: {target}_REF")
    version = parsed.path[len(prefix) :]
    if _VERSION.fullmatch(version) is None:
        raise P9WaTrustError(f"P9 WA secret reference is invalid: {target}_REF")
    return version
