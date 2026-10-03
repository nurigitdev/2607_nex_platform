from __future__ import annotations

from collections.abc import Mapping, Sequence
import base64
import binascii
from dataclasses import asdict, dataclass
import json
import re
from typing import Any

from fastapi import Request


AG_FEDERATED_OPERATOR_CONTEXT_STATE_KEY = "ag_federated_operator_context"
AG_FEDERATED_OPERATOR_CONTEXT_HEADER = "X-NEX-Federated-Operator-Context"
AG_FEDERATED_OPERATOR_CONTEXT_FIELDS = frozenset(
    {
        "tenant_id",
        "subject_id",
        "roles",
        "scopes",
        "auth_method",
        "session_id_digest",
    }
)
MAX_CONTEXT_ITEMS = 32
MAX_CONTEXT_TEXT_LENGTH = 128
MAX_CONTEXT_HEADER_BYTES = 4_096
MAX_CONTEXT_JSON_BYTES = 2_048
_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_PRIVATE_KEY_PARTS = (
    "authorization",
    "cookie",
    "external",
    "id_token",
    "password",
    "provider",
    "secret",
    "session_id",
    "token",
)


@dataclass(frozen=True)
class AgFederatedOperatorContextError(Exception):
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class AgFederatedOperatorContext:
    tenant_id: str
    subject_id: str
    roles: tuple[str, ...]
    scopes: tuple[str, ...]
    auth_method: str
    session_id_digest: str

    def to_wire(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["roles"] = list(self.roles)
        payload["scopes"] = list(self.scopes)
        return payload

    def operator_ref(self) -> dict[str, str]:
        return {"operator_type": "user", "operator_id": self.subject_id}


def build_ag_federated_operator_context(
    payload: Mapping[str, Any],
) -> AgFederatedOperatorContext:
    if not isinstance(payload, Mapping):
        raise _invalid("Federated operator context must be an object.")
    unsupported = sorted(str(key) for key in payload if key not in AG_FEDERATED_OPERATOR_CONTEXT_FIELDS)
    if unsupported:
        if any(_private_key(name) for name in unsupported):
            raise AgFederatedOperatorContextError(
                "ag.federated_operator_context_private_payload_rejected",
                "Federated operator context must not include private identity data.",
            )
        raise AgFederatedOperatorContextError(
            "ag.federated_operator_context_field_unsupported",
            "Federated operator context contains an unsupported field.",
        )
    tenant_id = _text(payload.get("tenant_id"), "tenant_id")
    subject_id = _text(payload.get("subject_id"), "subject_id")
    roles = _string_sequence(payload.get("roles"), "roles")
    scopes = _string_sequence(payload.get("scopes"), "scopes")
    if payload.get("auth_method") != "federated_oidc":
        raise _invalid("Federated operator auth_method is invalid.")
    digest = payload.get("session_id_digest")
    if not isinstance(digest, str) or _DIGEST_PATTERN.fullmatch(digest) is None:
        raise _invalid("Federated operator session digest is invalid.")
    return AgFederatedOperatorContext(
        tenant_id=tenant_id,
        subject_id=subject_id,
        roles=roles,
        scopes=scopes,
        auth_method="federated_oidc",
        session_id_digest=digest,
    )


def adopt_ag_federated_operator_context(
    request: Request,
    payload: Mapping[str, Any],
) -> AgFederatedOperatorContext:
    context = build_ag_federated_operator_context(payload)
    setattr(request.state, AG_FEDERATED_OPERATOR_CONTEXT_STATE_KEY, context)
    return context


def encode_ag_federated_operator_context_header(
    payload: Mapping[str, Any],
) -> str:
    context = build_ag_federated_operator_context(payload)
    encoded = base64.urlsafe_b64encode(
        json.dumps(
            context.to_wire(), separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
    ).decode("ascii")
    return encoded.rstrip("=")


def decode_ag_federated_operator_context_header(
    value: object,
) -> AgFederatedOperatorContext:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > MAX_CONTEXT_HEADER_BYTES
        or re.fullmatch(r"[A-Za-z0-9_-]+", value) is None
    ):
        raise _invalid("Federated operator context header is invalid.")
    try:
        padding = "=" * (-len(value) % 4)
        decoded = base64.b64decode(
            value + padding,
            altchars=b"-_",
            validate=True,
        )
        if len(decoded) > MAX_CONTEXT_JSON_BYTES:
            raise ValueError("decoded context is too large")
        payload = json.loads(decoded.decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise _invalid("Federated operator context header is invalid.") from exc
    return build_ag_federated_operator_context(payload)


def ag_federated_operator_context_from_request(
    request: Request,
) -> AgFederatedOperatorContext | None:
    context = getattr(request.state, AG_FEDERATED_OPERATOR_CONTEXT_STATE_KEY, None)
    if context is None:
        return None
    if not isinstance(context, AgFederatedOperatorContext):
        raise _invalid("Federated operator request state is invalid.")
    return context


def _string_sequence(value: object, field: str) -> tuple[str, ...]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
        or len(value) > MAX_CONTEXT_ITEMS
    ):
        raise _invalid(f"Federated operator {field} is invalid.")
    normalized = tuple(_text(item, field) for item in value)
    if len(normalized) != len(set(normalized)):
        raise _invalid(f"Federated operator {field} is invalid.")
    return normalized


def _text(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > MAX_CONTEXT_TEXT_LENGTH
    ):
        raise _invalid(f"Federated operator {field} is invalid.")
    return value


def _private_key(name: str) -> bool:
    normalized = name.lower()
    return any(part in normalized for part in _PRIVATE_KEY_PARTS)


def _invalid(detail: str) -> AgFederatedOperatorContextError:
    return AgFederatedOperatorContextError(
        "ag.federated_operator_context_invalid",
        detail,
    )
