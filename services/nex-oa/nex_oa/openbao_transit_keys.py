from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from nex_oa.openbao_transit_signer import (
    OPENBAO_TRANSIT_MOUNT,
    OpenBaoTransitTransport,
)
from nex_oa.signed_tokens import OaSignedTokenError
from nex_oa.signing_key_service import OaSigningKeyService
from nex_oa.token_signing import public_jwk_from_public_key

TRANSIT_RSA_KEY_TYPE = "rsa-3072"
RSA_3072_BITS = 3072
_KEY_NAME = re.compile(r"^[a-z][a-z0-9-]{1,63}$")


@dataclass(frozen=True)
class OpenBaoTransitKeyProjection:
    key_name: str
    key_version: int
    custody_reference: str
    public_jwk: dict[str, str]


class OpenBaoTransitKeyProvisioner:
    """Operator-only Transit key provisioning and public-key projection."""

    def __init__(self, transport: OpenBaoTransitTransport, token: str) -> None:
        if not _valid_credential(token):
            raise _custody_error("OpenBao Transit provisioning token is invalid")
        self._transport = transport
        self._token = token
        self._closed = False

    @classmethod
    def authenticate(
        cls,
        transport: OpenBaoTransitTransport,
        *,
        role_id: str,
        secret_id: str,
    ) -> OpenBaoTransitKeyProvisioner:
        if not _valid_credential(role_id) or not _valid_credential(secret_id):
            raise _custody_error("OpenBao Transit provisioning credential is invalid")
        response = _request(
            transport,
            "POST",
            "/v1/auth/approle/login",
            payload={"role_id": role_id, "secret_id": secret_id},
        )
        auth = response.get("auth")
        token = auth.get("client_token") if isinstance(auth, Mapping) else None
        if not isinstance(token, str) or not _valid_credential(token):
            raise _custody_error("OpenBao Transit provisioning login failed")
        return cls(transport, token)

    def provision_rsa3072(self, key_name: str) -> int:
        self._ensure_open()
        normalized = _normalize_key_name(key_name)
        _request(
            self._transport,
            "POST",
            f"/v1/{OPENBAO_TRANSIT_MOUNT}/keys/{quote(normalized, safe='-')}",
            token=self._token,
            payload={
                "type": TRANSIT_RSA_KEY_TYPE,
                "derived": False,
                "exportable": False,
                "allow_plaintext_backup": False,
            },
        )
        data = self._read_key_data(normalized)
        return _positive_version(data.get("latest_version"))

    def project_key_version(
        self,
        key_name: str,
        *,
        key_version: int,
        key_id: str,
    ) -> OpenBaoTransitKeyProjection:
        self._ensure_open()
        normalized = _normalize_key_name(key_name)
        version = _positive_version(key_version)
        if not isinstance(key_id, str) or not key_id or key_id != key_id.strip():
            raise _invalid("OA key id is invalid")
        data = self._read_key_data(normalized)
        latest_version = _positive_version(data.get("latest_version"))
        if version > latest_version:
            raise _custody_error("OpenBao Transit key version is unavailable")
        keys = data.get("keys")
        entry = keys.get(str(version)) if isinstance(keys, Mapping) else None
        pem = entry.get("public_key") if isinstance(entry, Mapping) else None
        if not isinstance(pem, str) or not pem or len(pem) > 16_384:
            raise _custody_error("OpenBao Transit public key is unavailable")
        try:
            public_key = serialization.load_pem_public_key(pem.encode("ascii"))
        except (UnicodeError, ValueError, TypeError):
            raise _custody_error("OpenBao Transit public key is invalid") from None
        if not isinstance(public_key, rsa.RSAPublicKey):
            raise _custody_error("OpenBao Transit public key must be RSA")
        if public_key.key_size != RSA_3072_BITS:
            raise _custody_error("OpenBao Transit public key must be RSA-3072")
        return OpenBaoTransitKeyProjection(
            key_name=normalized,
            key_version=version,
            custody_reference=build_openbao_transit_custody_reference(
                normalized, version
            ),
            public_jwk=public_jwk_from_public_key(public_key, key_id=key_id),
        )

    def close(self) -> None:
        if self._closed:
            return
        _request(
            self._transport,
            "POST",
            "/v1/auth/token/revoke-self",
            token=self._token,
            payload={},
        )
        self._token = ""
        self._closed = True

    def _read_key_data(self, key_name: str) -> Mapping[str, Any]:
        response = _request(
            self._transport,
            "GET",
            f"/v1/{OPENBAO_TRANSIT_MOUNT}/keys/{quote(key_name, safe='-')}",
            token=self._token,
        )
        data = response.get("data")
        if not isinstance(data, Mapping):
            raise _custody_error("OpenBao Transit key metadata is unavailable")
        if (
            data.get("type") != TRANSIT_RSA_KEY_TYPE
            or data.get("supports_signing") is not True
            or data.get("derived") is not False
            or data.get("exportable") is not False
            or data.get("allow_plaintext_backup") is not False
        ):
            raise _custody_error("OpenBao Transit key policy is invalid")
        return data

    def _ensure_open(self) -> None:
        if self._closed:
            raise _custody_error("OpenBao Transit provisioner is closed")


def build_openbao_transit_custody_reference(
    key_name: str,
    key_version: int,
) -> str:
    normalized = _normalize_key_name(key_name)
    version = _positive_version(key_version)
    return (
        f"vault://openbao/transit/keys/{normalized}/versions/{version}"
    )


def register_openbao_transit_key_version(
    provisioner: OpenBaoTransitKeyProvisioner,
    signing_key_service: OaSigningKeyService,
    *,
    key_name: str,
    key_version: int,
    key_id: str,
    issuer: str,
    published_at: int,
    activate_at: int,
    sign_until: int,
    verify_until: int,
) -> dict[str, Any]:
    projection = provisioner.project_key_version(
        key_name,
        key_version=key_version,
        key_id=key_id,
    )
    return signing_key_service.register_key(
        {
            "key_id": key_id,
            "issuer": issuer,
            "public_jwk": projection.public_jwk,
            "private_key_ref": projection.custody_reference,
            "published_at": published_at,
            "activate_at": activate_at,
            "sign_until": sign_until,
            "verify_until": verify_until,
        }
    )


def _request(
    transport: OpenBaoTransitTransport,
    method: str,
    path: str,
    *,
    token: str | None = None,
    payload: Mapping[str, Any] | None = None,
) -> Mapping[str, Any]:
    try:
        return transport.request(method, path, token=token, payload=payload)
    except OaSignedTokenError:
        raise
    except Exception as exc:
        raise _custody_error("OpenBao Transit provisioning request failed") from exc


def _normalize_key_name(value: object) -> str:
    if not isinstance(value, str) or _KEY_NAME.fullmatch(value) is None:
        raise _invalid("OpenBao Transit key name is invalid")
    return value


def _positive_version(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise _invalid("OpenBao Transit key version is invalid")
    return value


def _valid_credential(value: object) -> bool:
    return (
        isinstance(value, str)
        and 8 <= len(value) <= 4096
        and not any(character.isspace() for character in value)
        and not any(ord(character) < 32 or ord(character) == 127 for character in value)
    )


def _invalid(message: str) -> OaSignedTokenError:
    return OaSignedTokenError("oa.signing_key_provisioning_invalid", message, 400)


def _custody_error(message: str) -> OaSignedTokenError:
    return OaSignedTokenError("oa.signing_key_custody_unavailable", message, 503)
