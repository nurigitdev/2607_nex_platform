from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import re
from typing import Any

from .production_secret_materialization import ProductionSecretMaterialization


PRODUCTION_API_KEY_CUSTODY_SCHEMA_VERSION = "production_api_key_custody.v1"
PROVIDER_API_KEY_ENV_NAMES = (
    "NEX_MO_REMOTE_EMBEDDING_API_KEY",
    "NEX_MO_REMOTE_RERANKER_API_KEY",
    "NEX_MO_VLLM_API_KEY",
)
REDACTED_VALUE = "<redacted>"
_SENSITIVE_KEY_PARTS = (
    "api_key",
    "authorization",
    "credential",
    "password",
    "passwd",
    "secret",
    "token",
)
_BEARER = re.compile(r"(?i)\bBearer\s+[^\s,;]+")


class ProductionApiKeyCustodyError(ValueError):
    pass


@dataclass(frozen=True)
class ProductionApiKeyCustody:
    schema_version: str
    owner: str
    provider_api_key_environment_names: tuple[str, ...]
    configured_key_count: int
    non_owner_exposure_count: int
    status: str


def admit_production_api_key_custody(
    materialization: ProductionSecretMaterialization,
) -> ProductionApiKeyCustody:
    owner_environments = {
        item.owner: item.process_environment()
        for item in materialization.owner_environments
    }
    mo_environment = owner_environments.get("nex-mo")
    if mo_environment is None:
        raise ProductionApiKeyCustodyError("MO secret environment is missing")
    configured = tuple(
        name
        for name in PROVIDER_API_KEY_ENV_NAMES
        if isinstance(mo_environment.get(name), str) and mo_environment[name]
    )
    if configured != PROVIDER_API_KEY_ENV_NAMES:
        raise ProductionApiKeyCustodyError(
            "MO provider API key custody coverage is incomplete"
        )
    exposures = tuple(
        (owner, name)
        for owner, environment in owner_environments.items()
        if owner != "nex-mo"
        for name in PROVIDER_API_KEY_ENV_NAMES
        if name in environment
    )
    if exposures:
        raise ProductionApiKeyCustodyError(
            "provider API key escaped the MO process boundary"
        )
    return ProductionApiKeyCustody(
        schema_version=PRODUCTION_API_KEY_CUSTODY_SCHEMA_VERSION,
        owner="nex-mo",
        provider_api_key_environment_names=PROVIDER_API_KEY_ENV_NAMES,
        configured_key_count=len(configured),
        non_owner_exposure_count=0,
        status="ADMITTED",
    )


def production_api_key_custody_projection(
    custody: ProductionApiKeyCustody,
) -> dict[str, Any]:
    if (
        custody.schema_version != PRODUCTION_API_KEY_CUSTODY_SCHEMA_VERSION
        or custody.owner != "nex-mo"
        or custody.provider_api_key_environment_names != PROVIDER_API_KEY_ENV_NAMES
        or custody.configured_key_count != 3
        or custody.non_owner_exposure_count != 0
        or custody.status != "ADMITTED"
    ):
        raise ProductionApiKeyCustodyError(
            "production API key custody projection is invalid"
        )
    return {
        "schema_version": custody.schema_version,
        "owner": custody.owner,
        "provider_api_key_environment_names": list(
            custody.provider_api_key_environment_names
        ),
        "configured_key_count": custody.configured_key_count,
        "non_owner_exposure_count": custody.non_owner_exposure_count,
        "status": custody.status,
        "raw_api_key_values_included": False,
        "api_key_hashes_included": False,
    }


def redact_sensitive_runtime_data(
    value: Any,
    *,
    sensitive_values: Sequence[str] = (),
) -> Any:
    secrets = tuple(
        item for item in sensitive_values if isinstance(item, str) and item
    )
    if isinstance(value, Mapping):
        return {
            str(key): (
                REDACTED_VALUE
                if _sensitive_key(str(key))
                else redact_sensitive_runtime_data(item, sensitive_values=secrets)
            )
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        return tuple(
            redact_sensitive_runtime_data(item, sensitive_values=secrets)
            for item in value
        )
    if isinstance(value, list):
        return [
            redact_sensitive_runtime_data(item, sensitive_values=secrets)
            for item in value
        ]
    if isinstance(value, str):
        redacted = _BEARER.sub(f"Bearer {REDACTED_VALUE}", value)
        for secret in sorted(secrets, key=len, reverse=True):
            redacted = redacted.replace(secret, REDACTED_VALUE)
        return redacted
    return value


def _sensitive_key(key: str) -> bool:
    normalized = key.casefold().replace("-", "_")
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)
