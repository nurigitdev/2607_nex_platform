from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
import re
from typing import Any
from urllib.parse import urlparse

from nex_oa.subjects import normalize_registry_id


OA_FED_PROVIDER_SCHEMA_VERSION = "oa_fed_provider.v1"
OA_FED_IDENTITY_SCHEMA_VERSION = "oa_fed_identity.v1"
OA_FED_RESOLUTION_SCHEMA_VERSION = "oa_fed_resolution.v1"
FED_PROVIDER_STATUSES = ("ACTIVE", "DISABLED")
FED_IDENTITY_STATUSES = ("ACTIVE", "DISABLED")
FED_ID_TOKEN_ALGORITHMS = ("RS256",)
PROVIDER_FIELDS = frozenset(
    {"provider_id", "issuer", "client_id", "discovery_url", "display_name", "status"}
)
IDENTITY_FIELDS = frozenset(
    {"provider_id", "external_subject", "tenant_id", "subject_id", "status"}
)
PRIVATE_KEY_PARTS = (
    "authorization",
    "email",
    "employee",
    "password",
    "phone",
    "profile",
    "secret",
    "token",
)
_PROVIDER_ID_PATTERN = re.compile(r"^[a-z][a-z0-9._-]{1,63}$")


@dataclass(frozen=True)
class OaFederationError(Exception):
    status_code: int
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


def build_federation_provider(
    payload: Mapping[str, Any],
    *,
    now: datetime | None = None,
    allow_loopback_http: bool = False,
) -> dict[str, Any]:
    _require_mapping(payload, error_code="oa.federation_provider_payload_invalid")
    _reject_fields(payload, allowed=PROVIDER_FIELDS, entity="provider")
    provider_id = _provider_id(payload.get("provider_id"))
    issuer = _https_url(
        payload.get("issuer"),
        field_name="issuer",
        allow_loopback_http=allow_loopback_http,
    )
    discovery_url = _https_url(
        payload.get("discovery_url"),
        field_name="discovery_url",
        allow_loopback_http=allow_loopback_http,
    )
    if urlparse(issuer).hostname != urlparse(discovery_url).hostname:
        raise OaFederationError(
            400,
            "oa.federation_provider_discovery_host_mismatch",
            "OIDC issuer and discovery URL must use the same host.",
        )
    timestamp = _utc_text(now)
    return {
        "provider_schema_version": OA_FED_PROVIDER_SCHEMA_VERSION,
        "provider_id": provider_id,
        "issuer": issuer,
        "client_id": _bounded_text(payload.get("client_id"), "client_id", 255),
        "discovery_url": discovery_url,
        "display_name": _bounded_text(
            payload.get("display_name"), "display_name", 120
        ),
        "status": _status(payload.get("status", "ACTIVE"), FED_PROVIDER_STATUSES),
        "id_token_algorithms": FED_ID_TOKEN_ALGORITHMS,
        "subject_linking": "PREPROVISIONED_EXACT_SUBJECT_DIGEST",
        "revision": 1,
        "created_at": timestamp,
        "updated_at": timestamp,
    }


def build_external_identity_link(
    payload: Mapping[str, Any],
    *,
    provider: Mapping[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    _require_mapping(payload, error_code="oa.federated_identity_payload_invalid")
    _reject_fields(payload, allowed=IDENTITY_FIELDS, entity="identity")
    provider_id = _provider_id(payload.get("provider_id"))
    if provider.get("provider_id") != provider_id:
        raise OaFederationError(
            400,
            "oa.federated_identity_provider_mismatch",
            "External identity provider does not match the trust record.",
        )
    if provider.get("status") != "ACTIVE":
        raise OaFederationError(
            409,
            "oa.federation_provider_inactive",
            "External identity provider is not active.",
        )
    external_subject = _bounded_text(
        payload.get("external_subject"), "external_subject", 512
    )
    tenant_id = normalize_registry_id(payload.get("tenant_id"), field_name="tenant_id")
    subject_id = normalize_registry_id(
        payload.get("subject_id"), field_name="subject_id"
    )
    timestamp = _utc_text(now)
    return {
        "identity_schema_version": OA_FED_IDENTITY_SCHEMA_VERSION,
        "provider_id": provider_id,
        "external_subject_digest": external_subject_digest(
            str(provider.get("issuer") or ""), external_subject
        ),
        "tenant_id": tenant_id,
        "subject_id": subject_id,
        "status": _status(payload.get("status", "ACTIVE"), FED_IDENTITY_STATUSES),
        "revision": 1,
        "created_at": timestamp,
        "updated_at": timestamp,
    }


def resolve_federated_identity(
    assertion: Mapping[str, Any],
    *,
    provider: Mapping[str, Any],
    identity_link: Mapping[str, Any],
) -> dict[str, Any]:
    _require_mapping(assertion, error_code="oa.federated_assertion_invalid")
    if provider.get("status") != "ACTIVE":
        raise OaFederationError(
            403,
            "oa.federation_provider_inactive",
            "External identity provider is not active.",
        )
    issuer = _bounded_text(assertion.get("issuer"), "issuer", 2048)
    if issuer != provider.get("issuer"):
        raise OaFederationError(
            401,
            "oa.federated_assertion_issuer_invalid",
            "Federated assertion issuer is invalid.",
        )
    audiences = _audiences(assertion.get("audience"))
    if provider.get("client_id") not in audiences:
        raise OaFederationError(
            401,
            "oa.federated_assertion_audience_invalid",
            "Federated assertion audience is invalid.",
        )
    subject = _bounded_text(assertion.get("subject"), "subject", 512)
    digest = external_subject_digest(issuer, subject)
    if (
        identity_link.get("provider_id") != provider.get("provider_id")
        or identity_link.get("external_subject_digest") != digest
        or identity_link.get("status") != "ACTIVE"
    ):
        raise OaFederationError(
            403,
            "oa.federated_identity_not_linked",
            "Federated identity is not linked to an active OA subject.",
        )
    return {
        "resolution_schema_version": OA_FED_RESOLUTION_SCHEMA_VERSION,
        "resolution_status": "RESOLVED",
        "auth_method": "federated_oidc",
        "provider_id": provider["provider_id"],
        "tenant_id": identity_link["tenant_id"],
        "subject_id": identity_link["subject_id"],
        "external_subject_digest": digest,
        "raw_external_subject_included": False,
        "external_profile_included": False,
    }


def external_subject_digest(issuer: str, external_subject: str) -> str:
    normalized_issuer = _bounded_text(issuer, "issuer", 2048)
    normalized_subject = _bounded_text(external_subject, "external_subject", 512)
    return sha256(f"{normalized_issuer}\x00{normalized_subject}".encode()).hexdigest()


def federation_provider_projection(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: deepcopy(record[key])
        for key in (
            "provider_schema_version",
            "provider_id",
            "issuer",
            "client_id",
            "discovery_url",
            "display_name",
            "status",
            "id_token_algorithms",
            "subject_linking",
            "revision",
            "created_at",
            "updated_at",
        )
        if key in record
    }


def external_identity_projection(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: deepcopy(record[key])
        for key in (
            "identity_schema_version",
            "provider_id",
            "external_subject_digest",
            "tenant_id",
            "subject_id",
            "status",
            "revision",
            "created_at",
            "updated_at",
        )
        if key in record
    }


def _reject_fields(
    payload: Mapping[str, Any], *, allowed: frozenset[str], entity: str
) -> None:
    for key in payload:
        key_text = str(key)
        if key_text in allowed:
            continue
        if any(part in key_text.lower() for part in PRIVATE_KEY_PARTS):
            raise OaFederationError(
                400,
                f"oa.federated_{entity}_private_payload_rejected",
                "Federation payload must not include private identity material.",
            )
        raise OaFederationError(
            400,
            f"oa.federated_{entity}_field_unsupported",
            f"Federation {entity} payload contains an unsupported field.",
        )


def _require_mapping(payload: object, *, error_code: str) -> None:
    if not isinstance(payload, Mapping):
        raise OaFederationError(400, error_code, "Federation payload must be an object.")


def _provider_id(value: object) -> str:
    provider_id = str(value or "").strip()
    if not _PROVIDER_ID_PATTERN.fullmatch(provider_id):
        raise OaFederationError(
            400,
            "oa.federation_provider_id_invalid",
            "provider_id format is invalid.",
        )
    return provider_id


def _https_url(value: object, *, field_name: str, allow_loopback_http: bool) -> str:
    text = _bounded_text(value, field_name, 2048)
    parsed = urlparse(text)
    loopback = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    if (
        not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
        or (parsed.scheme != "https" and not (allow_loopback_http and loopback and parsed.scheme == "http"))
    ):
        raise OaFederationError(
            400,
            f"oa.federation_{field_name}_invalid",
            f"{field_name} must be an HTTPS URL without credentials or fragments.",
        )
    return text


def _bounded_text(value: object, field_name: str, maximum: int) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > maximum:
        raise OaFederationError(
            400,
            f"oa.federation_{field_name}_invalid",
            f"{field_name} is invalid.",
        )
    return value


def _status(value: object, allowed: tuple[str, ...]) -> str:
    status = str(value or "").strip().upper()
    if status not in allowed:
        raise OaFederationError(
            400,
            "oa.federation_status_invalid",
            "Federation status is invalid.",
        )
    return status


def _audiences(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Sequence) and not isinstance(value, (bytes, str)):
        audiences = tuple(item for item in value if isinstance(item, str) and item)
        if audiences and len(audiences) == len(value):
            return audiences
    raise OaFederationError(
        401,
        "oa.federated_assertion_audience_invalid",
        "Federated assertion audience is invalid.",
    )


def _utc_text(value: datetime | None) -> str:
    timestamp = value or datetime.now(UTC)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC).isoformat().replace("+00:00", "Z")
