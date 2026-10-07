from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
from pathlib import Path
import re
import ssl
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

from .production_secret_materialization import (
    ResolvedSecret,
    SecretResolutionContext,
)


OPENBAO_PROVIDER_ID = "openbao"
OPENBAO_KV_MOUNT = "kv"
_VERSION = re.compile(r"^v([1-9][0-9]*)$")
_RESOURCE = re.compile(
    r"^/nex-platform/(?P<namespace>staging|production)/"
    r"(?P<owner>nex-(?:oa|ae-api|cx|mo|ag))/"
    r"(?P<target>NEX_[A-Z0-9_]+)@(?P<version>v[1-9][0-9]*)$"
)


class OpenBaoSecretResolverError(ValueError):
    pass


@dataclass(frozen=True)
class OpenBaoClientSettings:
    address: str
    ca_certificate_file: Path
    role_id: str
    secret_id: str
    timeout_seconds: float


class OpenBaoTransport(Protocol):
    def request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]: ...


class UrllibOpenBaoTransport:
    def __init__(
        self,
        address: str,
        *,
        ca_certificate_file: Path,
        timeout_seconds: float = 5.0,
    ) -> None:
        parsed = urlsplit(address)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise OpenBaoSecretResolverError("OpenBao address must be an HTTPS origin")
        if timeout_seconds <= 0:
            raise OpenBaoSecretResolverError("OpenBao timeout must be positive")
        try:
            self._context = ssl.create_default_context(
                cafile=str(ca_certificate_file)
            )
        except (OSError, ssl.SSLError):
            raise OpenBaoSecretResolverError(
                "OpenBao CA certificate is unavailable"
            ) from None
        self._address = address.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        if not path.startswith("/v1/"):
            raise OpenBaoSecretResolverError("OpenBao API path is invalid")
        headers = {"Accept": "application/json"}
        if token:
            headers["X-Vault-Token"] = token
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(
                dict(payload), ensure_ascii=True, separators=(",", ":")
            ).encode("ascii")
        request = Request(
            f"{self._address}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(
                request,
                context=self._context,
                timeout=self._timeout_seconds,
            ) as response:
                raw = response.read(1_048_577)
        except HTTPError as exc:
            safe_path = path.split("?", 1)[0]
            raise OpenBaoSecretResolverError(
                f"OpenBao request failed: {method} {safe_path} status={exc.code}"
            ) from None
        except (URLError, OSError, TimeoutError, ssl.SSLError):
            safe_path = path.split("?", 1)[0]
            raise OpenBaoSecretResolverError(
                f"OpenBao request failed: {method} {safe_path} transport"
            ) from None
        if len(raw) > 1_048_576:
            raise OpenBaoSecretResolverError("OpenBao response is too large")
        if not raw:
            return {}
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise OpenBaoSecretResolverError("OpenBao response is invalid") from None
        if not isinstance(value, Mapping):
            raise OpenBaoSecretResolverError("OpenBao response is invalid")
        return value


class OpenBaoSecretResolver:
    def __init__(
        self,
        transport: OpenBaoTransport,
        token: str,
        *,
        namespace: str = "staging",
    ) -> None:
        if not _valid_credential(token):
            raise OpenBaoSecretResolverError("OpenBao client token is invalid")
        if namespace not in {"staging", "production"}:
            raise OpenBaoSecretResolverError("OpenBao secret namespace is invalid")
        self._transport = transport
        self._token = token
        self._namespace = namespace
        self._revoked = False

    @classmethod
    def authenticate(
        cls,
        transport: OpenBaoTransport,
        *,
        role_id: str,
        secret_id: str,
        namespace: str = "staging",
    ) -> OpenBaoSecretResolver:
        if not _valid_credential(role_id) or not _valid_credential(secret_id):
            raise OpenBaoSecretResolverError("OpenBao AppRole credential is invalid")
        response = transport.request(
            "POST",
            "/v1/auth/approle/login",
            payload={"role_id": role_id, "secret_id": secret_id},
        )
        auth = response.get("auth")
        token = auth.get("client_token") if isinstance(auth, Mapping) else None
        if not isinstance(token, str) or not _valid_credential(token):
            raise OpenBaoSecretResolverError("OpenBao AppRole login failed")
        return cls(transport, token, namespace=namespace)

    def resolve(
        self,
        reference: str,
        *,
        context: SecretResolutionContext,
    ) -> ResolvedSecret:
        if self._revoked:
            raise OpenBaoSecretResolverError("OpenBao resolver is closed")
        try:
            parsed = urlsplit(reference)
            port = parsed.port
        except ValueError:
            raise OpenBaoSecretResolverError(
                "OpenBao secret reference is invalid"
            ) from None
        match = _RESOURCE.fullmatch(parsed.path)
        if (
            parsed.scheme != "secret"
            or parsed.hostname != OPENBAO_PROVIDER_ID
            or parsed.username is not None
            or parsed.password is not None
            or port is not None
            or parsed.query
            or parsed.fragment
            or match is None
        ):
            raise OpenBaoSecretResolverError("OpenBao secret reference is invalid")
        owner = match.group("owner")
        target = match.group("target")
        version = match.group("version")
        if (
            match.group("namespace") != self._namespace
            or owner != context.owner
            or target != context.target_environment_name
            or version != context.reference_version
        ):
            raise OpenBaoSecretResolverError("OpenBao secret reference scope mismatch")
        version_number = version[1:]
        resource = f"nex-platform/{self._namespace}/{owner}/{target}"
        response = self._transport.request(
            "GET",
            f"/v1/{OPENBAO_KV_MOUNT}/data/{quote(resource, safe='/-_')}"
            f"?version={version_number}",
            token=self._token,
        )
        outer = response.get("data")
        inner = outer.get("data") if isinstance(outer, Mapping) else None
        value = inner.get("value") if isinstance(inner, Mapping) else None
        if not isinstance(value, str) or not value:
            raise OpenBaoSecretResolverError("OpenBao secret response is invalid")
        return ResolvedSecret(
            owner=context.owner,
            target_environment_name=context.target_environment_name,
            secret_generation=context.secret_generation,
            reference_version=context.reference_version,
            provider_id=OPENBAO_PROVIDER_ID,
            value=value,
        )

    def revoke(self) -> None:
        if self._revoked:
            return
        self._transport.request(
            "POST",
            "/v1/auth/token/revoke-self",
            token=self._token,
            payload={},
        )
        self._token = ""
        self._revoked = True


def build_openbao_secret_resolver(
    environ: Mapping[str, str],
) -> OpenBaoSecretResolver:
    settings = load_openbao_client_settings(environ)
    namespace = str(environ.get("NEX_OPENBAO_SECRET_NAMESPACE") or "").strip()
    if namespace not in {"staging", "production"}:
        raise OpenBaoSecretResolverError("OpenBao secret namespace is invalid")

    transport = UrllibOpenBaoTransport(
        settings.address,
        ca_certificate_file=settings.ca_certificate_file,
        timeout_seconds=settings.timeout_seconds,
    )
    return OpenBaoSecretResolver.authenticate(
        transport,
        role_id=settings.role_id,
        secret_id=settings.secret_id,
        namespace=namespace,
    )


def load_openbao_client_settings(
    environ: Mapping[str, str],
) -> OpenBaoClientSettings:
    address = str(environ.get("NEX_OPENBAO_ADDR") or "").strip()
    ca_file = _required_path(environ, "NEX_OPENBAO_CA_CERT_FILE")
    role_id = _read_credential(
        _required_path(environ, "NEX_OPENBAO_ROLE_ID_FILE"), "role ID"
    )
    secret_id = _read_credential(
        _required_path(environ, "NEX_OPENBAO_SECRET_ID_FILE"), "secret ID"
    )
    timeout_raw = str(environ.get("NEX_OPENBAO_TIMEOUT_SECONDS") or "5").strip()
    try:
        timeout_seconds = float(timeout_raw)
    except ValueError:
        raise OpenBaoSecretResolverError("OpenBao timeout is invalid") from None
    return OpenBaoClientSettings(
        address=address,
        ca_certificate_file=ca_file,
        role_id=role_id,
        secret_id=secret_id,
        timeout_seconds=timeout_seconds,
    )


def _required_path(environ: Mapping[str, str], name: str) -> Path:
    raw = str(environ.get(name) or "").strip()
    if not raw:
        raise OpenBaoSecretResolverError(f"OpenBao file setting is missing: {name}")
    path = Path(raw)
    if not path.is_absolute() or not path.is_file():
        raise OpenBaoSecretResolverError(f"OpenBao file is unavailable: {name}")
    return path


def _read_credential(path: Path, label: str) -> str:
    try:
        if path.stat().st_size > 4096:
            raise OpenBaoSecretResolverError(
                f"OpenBao {label} credential is invalid"
            )
        value = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        raise OpenBaoSecretResolverError(
            f"OpenBao {label} credential is unavailable"
        ) from None
    if not _valid_credential(value):
        raise OpenBaoSecretResolverError(f"OpenBao {label} credential is invalid")
    return value


def _valid_credential(value: str) -> bool:
    return (
        isinstance(value, str)
        and 8 <= len(value) <= 4096
        and not any(character.isspace() for character in value)
        and not any(ord(character) < 32 or ord(character) == 127 for character in value)
    )
