from __future__ import annotations

import base64
from collections.abc import Mapping
from dataclasses import dataclass
import re
from typing import Any, Protocol
from urllib.parse import quote, urlsplit

from nex_oa.signed_tokens import OaSignedTokenError


OPENBAO_TRANSIT_PROVIDER_ID = "openbao"
OPENBAO_TRANSIT_MOUNT = "transit"
MAX_SIGNING_INPUT_BYTES = 16_384
RSA_3072_SIGNATURE_BYTES = 384
_REFERENCE = re.compile(
    r"^/transit/keys/(?P<key>[a-z][a-z0-9-]{1,63})/versions/"
    r"(?P<version>[1-9][0-9]*)$"
)
_SIGNATURE = re.compile(
    r"^vault:v(?P<version>[1-9][0-9]*):(?P<value>[A-Za-z0-9+/]+={0,2})$"
)


class OpenBaoTransitTransport(Protocol):
    def request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class OpenBaoTransitKeyReference:
    key_name: str
    key_version: int


class OpenBaoTransitOaRsaSigningProvider:
    def __init__(self, transport: OpenBaoTransitTransport, token: str) -> None:
        if not _valid_credential(token):
            raise _custody_error("OpenBao Transit client token is invalid")
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
    ) -> OpenBaoTransitOaRsaSigningProvider:
        if not _valid_credential(role_id) or not _valid_credential(secret_id):
            raise _custody_error("OpenBao Transit AppRole credential is invalid")
        try:
            response = transport.request(
                "POST",
                "/v1/auth/approle/login",
                payload={"role_id": role_id, "secret_id": secret_id},
            )
        except Exception as exc:
            raise _transport_error() from exc
        auth = response.get("auth")
        token = auth.get("client_token") if isinstance(auth, Mapping) else None
        if not isinstance(token, str) or not _valid_credential(token):
            raise _custody_error("OpenBao Transit AppRole login failed")
        return cls(transport, token)

    def sign_rs256(self, private_key_ref: str, signing_input: bytes) -> bytes:
        if self._closed:
            raise _custody_error("OpenBao Transit signer is closed")
        reference = parse_openbao_transit_key_reference(private_key_ref)
        if (
            not isinstance(signing_input, bytes)
            or not signing_input
            or len(signing_input) > MAX_SIGNING_INPUT_BYTES
        ):
            raise OaSignedTokenError(
                "oa.token_signing_invalid",
                "signing input is invalid",
                400,
            )
        payload = {
            "input": base64.b64encode(signing_input).decode("ascii"),
            "key_version": reference.key_version,
            "prehashed": False,
            "signature_algorithm": "pkcs1v15",
        }
        try:
            response = self._transport.request(
                "POST",
                f"/v1/{OPENBAO_TRANSIT_MOUNT}/sign/"
                f"{quote(reference.key_name, safe='-')}/sha2-256",
                token=self._token,
                payload=payload,
            )
        except OaSignedTokenError:
            raise
        except Exception as exc:
            raise _transport_error() from exc
        data = response.get("data")
        encoded = data.get("signature") if isinstance(data, Mapping) else None
        match = _SIGNATURE.fullmatch(encoded) if isinstance(encoded, str) else None
        if match is None or int(match.group("version")) != reference.key_version:
            raise _custody_error("OpenBao Transit signature response is invalid")
        try:
            signature = base64.b64decode(match.group("value"), validate=True)
        except (ValueError, TypeError):
            raise _custody_error("OpenBao Transit signature response is invalid") from None
        if len(signature) != RSA_3072_SIGNATURE_BYTES:
            raise _custody_error("OpenBao Transit signature size is invalid")
        return signature

    def close(self) -> None:
        if self._closed:
            return
        try:
            self._transport.request(
                "POST",
                "/v1/auth/token/revoke-self",
                token=self._token,
                payload={},
            )
        except Exception as exc:
            raise _transport_error() from exc
        self._token = ""
        self._closed = True


def parse_openbao_transit_key_reference(value: str) -> OpenBaoTransitKeyReference:
    if not isinstance(value, str) or not value:
        raise _custody_error("OpenBao Transit key reference is invalid")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise _custody_error("OpenBao Transit key reference is invalid") from None
    match = _REFERENCE.fullmatch(parsed.path)
    if (
        parsed.scheme != "vault"
        or parsed.hostname != OPENBAO_TRANSIT_PROVIDER_ID
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.query
        or parsed.fragment
        or match is None
    ):
        raise _custody_error("OpenBao Transit key reference is invalid")
    return OpenBaoTransitKeyReference(
        key_name=match.group("key"),
        key_version=int(match.group("version")),
    )


def _valid_credential(value: str) -> bool:
    return (
        isinstance(value, str)
        and 8 <= len(value) <= 4096
        and not any(character.isspace() for character in value)
        and not any(ord(character) < 32 or ord(character) == 127 for character in value)
    )


def _transport_error() -> OaSignedTokenError:
    return OaSignedTokenError(
        "oa.signing_key_custody_unavailable",
        "OpenBao Transit request failed",
        503,
    )


def _custody_error(message: str) -> OaSignedTokenError:
    return OaSignedTokenError("oa.signing_key_custody_unavailable", message, 503)
