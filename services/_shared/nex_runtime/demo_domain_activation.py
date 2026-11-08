from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .demo_trust import DEMO_DEPLOYMENT_BOUNDARY, DEMO_TRUST_GRANTS
from .semantic_hashes import semantic_sha256_hash_ref

DEMO_DOMAIN_ACTIVATION_SCHEMA_VERSION = "p8_demo_domain_activation.v1"
DEMO_DOMAIN_CLAIMING_ENV = "NEX_P8_DEMO_DOMAIN_CLAIMING_ENABLED"
DEMO_DOMAIN_PROCESSES = (
    "nex-ae-agent-runtime-worker",
    "nex-wc-event-delivery-worker",
    "nex-eos-outbox-publisher",
)
_TRUE = frozenset({"1", "true", "yes", "on"})


class DemoDomainActivationError(ValueError):
    pass


@dataclass(frozen=True)
class DemoDomainActivation:
    process_id: str
    enabled: bool
    profile: str
    deployment_boundary: str
    token_rollout_profile: str

    def to_projection(self) -> dict[str, Any]:
        return {
            "schema_version": DEMO_DOMAIN_ACTIVATION_SCHEMA_VERSION,
            "process_id": self.process_id,
            "domain_claiming_enabled": self.enabled,
            "profile": self.profile,
            "deployment_boundary": self.deployment_boundary,
            "token_rollout_profile": self.token_rollout_profile,
            "trust_grant_count": len(DEMO_TRUST_GRANTS),
            "activation_digest": semantic_sha256_hash_ref(
                {
                    "process_id": self.process_id,
                    "enabled": self.enabled,
                    "profile": self.profile,
                    "deployment_boundary": self.deployment_boundary,
                    "token_rollout_profile": self.token_rollout_profile,
                    "trust_grants": [
                        {
                            "owner": grant.owner,
                            "audience": grant.audience,
                            "scopes": list(grant.scopes),
                        }
                        for grant in DEMO_TRUST_GRANTS
                    ],
                }
            ),
            "secret_included": False,
            "token_value_included": False,
        }


def resolve_demo_domain_activation(
    environ: Mapping[str, str],
    *,
    process_id: str,
    required_secret_names: Sequence[str] = (),
) -> DemoDomainActivation:
    if process_id not in DEMO_DOMAIN_PROCESSES:
        raise DemoDomainActivationError("Demo domain process is not admitted")
    raw_enabled = str(environ.get(DEMO_DOMAIN_CLAIMING_ENV) or "").strip().lower()
    if raw_enabled and raw_enabled not in _TRUE:
        raise DemoDomainActivationError("Demo domain claiming flag is invalid")
    enabled = raw_enabled in _TRUE
    profile = str(environ.get("NEX_PROFILE") or "").strip()
    boundary = str(environ.get("NEX_DEPLOYMENT_BOUNDARY") or "").strip()
    rollout = str(environ.get("NEX_SERVICE_TOKEN_ROLLOUT_PROFILE") or "").strip()
    if enabled:
        if profile != "staging_live":
            raise DemoDomainActivationError(
                "Demo domain claiming requires the staging_live profile"
            )
        if boundary != DEMO_DEPLOYMENT_BOUNDARY:
            raise DemoDomainActivationError(
                "Demo domain claiming requires the P8_DEMO boundary"
            )
        if rollout != "SIGNED_ONLY":
            raise DemoDomainActivationError(
                "Demo domain claiming requires SIGNED_ONLY trust"
            )
        missing = sorted(
            name
            for name in required_secret_names
            if not str(environ.get(name) or "").strip()
        )
        if missing:
            raise DemoDomainActivationError(
                "Demo domain claiming required material is unavailable"
            )
    return DemoDomainActivation(
        process_id=process_id,
        enabled=enabled,
        profile=profile,
        deployment_boundary=boundary,
        token_rollout_profile=rollout,
    )


def demo_domain_activation_projection() -> dict[str, Any]:
    identities = [
        (grant.environment_name, grant.owner, grant.audience, grant.scopes)
        for grant in DEMO_TRUST_GRANTS
    ]
    if len(identities) != len(set(identities)):
        raise DemoDomainActivationError("Demo trust grant inventory is ambiguous")
    required_edges = {
        ("nex-ae-api", "nex-wc"),
        ("nex-ae-api", "nex-eos"),
        ("nex-wc", "nex-ae-api"),
        ("nex-eos", "nex-ae-api"),
        ("nex-eos", "nex-wc"),
    }
    observed_edges = {(grant.owner, grant.audience) for grant in DEMO_TRUST_GRANTS}
    if not required_edges.issubset(observed_edges):
        raise DemoDomainActivationError("Demo domain trust edges are incomplete")
    return {
        "schema_version": DEMO_DOMAIN_ACTIVATION_SCHEMA_VERSION,
        "processes": list(DEMO_DOMAIN_PROCESSES),
        "process_count": len(DEMO_DOMAIN_PROCESSES),
        "trust_grant_count": len(DEMO_TRUST_GRANTS),
        "required_edges_admitted": True,
        "mock_token_fallback_allowed": False,
        "secret_included": False,
    }


def required_demo_domain_material(
    owner: str,
    *,
    database_environment_name: str,
) -> tuple[str, ...]:
    if not isinstance(database_environment_name, str) or not database_environment_name:
        raise DemoDomainActivationError("Demo database environment name is invalid")
    token_names = tuple(
        grant.environment_name for grant in DEMO_TRUST_GRANTS if grant.owner == owner
    )
    if not token_names:
        raise DemoDomainActivationError(
            "Demo domain owner has no admitted trust grants"
        )
    return (database_environment_name, *token_names)
