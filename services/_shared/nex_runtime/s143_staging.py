from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import ipaddress
import json
import os
from pathlib import Path
import re
import ssl
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import yaml

from .production_configuration import (
    PRODUCTION_SECRET_BINDING_COUNT,
    load_production_configuration_manifest,
)


S143_STAGING_SCHEMA_VERSION = "s143_external_staging.v1"
COMPOSE_PATH = "deployment/compose/s143-staging.compose.yaml"
OPENBAO_IMAGE = (
    "ghcr.io/openbao/openbao:2.7.1@"
    "sha256:6d2b93856e3fcf7b18ad855a0b51eaba474dc8b79cf554379ea32034797d2acf"
)
TRAEFIK_IMAGE = (
    "traefik:3.7.14@"
    "sha256:e849695bc5c317da0cec22bfee4794fd9e15871fe554f864d31b625983e883ff"
)
OWNERS = ("nex-oa", "nex-ae-api", "nex-cx", "nex-mo", "nex-ag")
STAGING_HOSTS = (
    "oa.nex-staging.test",
    "ag.nex-staging.test",
    "ae-api.nex-staging.test",
    "cx.nex-staging.test",
    "mo.nex-staging.test",
    "ae.nex-staging.test",
    "embedding.nex-staging.test",
    "reranker.nex-staging.test",
    "generation.nex-staging.test",
)
_DIGEST_REFERENCE = re.compile(r"^[^@]+@sha256:[0-9a-f]{64}$")


class S143StagingError(ValueError):
    pass


@dataclass(frozen=True)
class OpenBaoBootstrap:
    root_token: str
    unseal_key: str


def validate_s143_compose_assets(root: Path) -> dict[str, Any]:
    compose_path = root / COMPOSE_PATH
    try:
        compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
        dynamic = (root / "deployment/compose/traefik/dynamic.yaml").read_text(
            encoding="utf-8"
        )
        openbao = (root / "deployment/compose/openbao/config.hcl").read_text(
            encoding="utf-8"
        )
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise S143StagingError("S143 Compose assets are unreadable") from exc
    if not isinstance(compose, Mapping):
        raise S143StagingError("S143 Compose document is invalid")
    services = compose.get("services")
    if not isinstance(services, Mapping):
        raise S143StagingError("S143 Compose services are invalid")
    expected_services = {
        "openbao-data-init",
        "openbao",
        "traefik",
        "nex-oa",
        "nex-ag",
        "nex-ae-api",
        "nex-cx",
        "nex-mo",
        "nex-ae-web",
    }
    if set(services) != expected_services:
        raise S143StagingError("S143 Compose service coverage drift")
    if services["openbao-data-init"].get("image") != OPENBAO_IMAGE:
        raise S143StagingError("OpenBao data initializer image digest drift")
    if services["openbao"].get("image") != OPENBAO_IMAGE:
        raise S143StagingError("OpenBao image digest drift")
    if services["traefik"].get("image") != TRAEFIK_IMAGE:
        raise S143StagingError("Traefik image digest drift")
    for service_id in expected_services - {"openbao-data-init", "openbao", "traefik"}:
        image = str(services[service_id].get("image") or "")
        if "immutable" not in image or "${NEX_" not in image:
            raise S143StagingError(
                f"application image is not immutable-gated: {service_id}"
            )
    compose_text = compose_path.read_text(encoding="utf-8")
    forbidden = ("/var/run/docker.sock", "privileged: true", "network_mode: host")
    if any(value in compose_text for value in forbidden):
        raise S143StagingError("S143 Compose privilege boundary drift")
    if "127.0.0.1:8200:8200" not in compose_text:
        raise S143StagingError("OpenBao admin binding is not loopback-only")
    if (
        "NEX_MO_VLLM_BASE_URL: https://generation.nex-staging.test:8443\n"
        not in compose_text
    ):
        raise S143StagingError("generation provider base URL drift")
    initializer = services["openbao-data-init"]
    initializer_command = initializer.get("command")
    if (
        initializer.get("user") != "0:0"
        or initializer.get("cap_add") != ["CHOWN"]
        or initializer.get("cap_drop") != ["ALL"]
        or initializer.get("network_mode") != "none"
        or not isinstance(initializer_command, list)
        or len(initializer_command) != 1
        or "stat -c '%u:%g'" not in initializer_command[0]
        or services["openbao"].get("depends_on", {})
        .get("openbao-data-init", {})
        .get("condition")
        != "service_completed_successfully"
    ):
        raise S143StagingError("OpenBao data initializer boundary drift")
    networks = compose.get("networks")
    if (
        not isinstance(networks, Mapping)
        or networks.get("control", {}).get("internal") is not True
        or set(services["openbao"].get("networks", ())) != {"control", "admin"}
    ):
        raise S143StagingError("OpenBao control/admin network boundary drift")
    if "storage \"raft\"" not in openbao or "tls_cert_file" not in openbao:
        raise S143StagingError("OpenBao durable TLS configuration drift")
    if any(f"Host(`{host}`)" not in dynamic for host in STAGING_HOSTS):
        raise S143StagingError("Traefik staging route coverage drift")
    secret_refs = re.findall(r"secret://openbao/[^\s]+", compose_text)
    if len(secret_refs) != PRODUCTION_SECRET_BINDING_COUNT:
        raise S143StagingError("OpenBao secret reference coverage drift")
    return {
        "schema_version": S143_STAGING_SCHEMA_VERSION,
        "status": "VALID",
        "orchestrator": "docker-compose-single-host",
        "service_count": len(services),
        "runtime_service_count": len(services) - 1,
        "initializer_service_count": 1,
        "secret_reference_count": len(secret_refs),
        "tls_route_count": len(STAGING_HOSTS),
        "external_images": [OPENBAO_IMAGE, TRAEFIK_IMAGE],
        "host_software_install_required": False,
        "raw_secret_values_included": False,
    }


def prepare_staging_runtime_directory(
    runtime_dir: Path,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not runtime_dir.is_absolute():
        raise S143StagingError("S143 runtime directory must be absolute")
    if runtime_dir.exists() and any(runtime_dir.iterdir()):
        raise S143StagingError("S143 runtime directory must be empty")
    runtime_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(runtime_dir, 0o700)
    tls_dir = runtime_dir / "tls"
    credential_dir = runtime_dir / "credentials"
    admin_dir = runtime_dir / "admin"
    for path in (tls_dir, credential_dir, admin_dir):
        path.mkdir(mode=0o700)

    current = now or datetime.now(UTC)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "NeX S143 OpenBao Bootstrap CA")]
    )
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(current - timedelta(minutes=5))
        .not_valid_after(current + timedelta(days=7))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    server_name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "openbao")]
    )
    server_cert = (
        x509.CertificateBuilder()
        .subject_name(server_name)
        .issuer_name(ca_cert.subject)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(current - timedelta(minutes=5))
        .not_valid_after(current + timedelta(days=2))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("openbao"),
                    x509.DNSName("localhost"),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                ]
            ),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    _write_bytes(
        tls_dir / "openbao-ca.crt",
        ca_cert.public_bytes(serialization.Encoding.PEM),
        mode=0o644,
    )
    _write_bytes(
        tls_dir / "openbao.crt",
        server_cert.public_bytes(serialization.Encoding.PEM),
        mode=0o644,
    )
    _write_bytes(
        tls_dir / "openbao.key",
        server_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
        mode=0o644,
    )
    for name in ("platform.crt", "platform.key", "platform-ca.crt"):
        _write_bytes(tls_dir / name, b"pending\n", mode=0o644)
    for owner in OWNERS:
        _write_bytes(credential_dir / f"{owner}.role-id", b"pending\n", mode=0o644)
        _write_bytes(credential_dir / f"{owner}.secret-id", b"pending\n", mode=0o644)
    return {
        "schema_version": S143_STAGING_SCHEMA_VERSION,
        "status": "PREPARED",
        "runtime_directory": str(runtime_dir),
        "bootstrap_ca_not_after": ca_cert.not_valid_after_utc.isoformat(),
        "raw_secret_values_included": False,
    }


class OpenBaoAdminClient:
    def __init__(
        self,
        address: str,
        *,
        ca_certificate_file: Path,
        timeout_seconds: float = 10.0,
    ) -> None:
        if not address.startswith("https://") or timeout_seconds <= 0:
            raise S143StagingError("OpenBao admin endpoint is invalid")
        try:
            self._context = ssl.create_default_context(cafile=str(ca_certificate_file))
        except (OSError, ssl.SSLError):
            raise S143StagingError("OpenBao bootstrap CA is unavailable") from None
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
            raise S143StagingError("OpenBao admin API path is invalid")
        headers = {"Accept": "application/json"}
        if token:
            headers["X-Vault-Token"] = token
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(dict(payload), separators=(",", ":")).encode("utf-8")
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
                raw = response.read(2_097_153)
        except HTTPError as exc:
            raise S143StagingError(
                f"OpenBao admin request failed: {method} {path} status={exc.code}"
            ) from None
        except (URLError, OSError, TimeoutError, ssl.SSLError):
            raise S143StagingError(
                f"OpenBao admin request failed: {method} {path} transport"
            ) from None
        if len(raw) > 2_097_152:
            raise S143StagingError("OpenBao admin response is too large")
        if not raw:
            return {}
        try:
            result = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise S143StagingError("OpenBao admin response is invalid") from None
        if not isinstance(result, Mapping):
            raise S143StagingError("OpenBao admin response is invalid")
        return result


def initialize_openbao(
    client: OpenBaoAdminClient,
    runtime_dir: Path,
) -> OpenBaoBootstrap:
    _wait_for_openbao_uninitialized(client)
    response = client.request(
        "PUT",
        "/v1/sys/init",
        payload={"secret_shares": 1, "secret_threshold": 1},
    )
    root_token = response.get("root_token")
    keys = response.get("keys_base64")
    unseal_key = keys[0] if isinstance(keys, list) and len(keys) == 1 else None
    if not _credential(root_token) or not _credential(unseal_key):
        raise S143StagingError("OpenBao initialization response is invalid")
    client.request("PUT", "/v1/sys/unseal", payload={"key": unseal_key})
    _wait_for_openbao_active(client, root_token=root_token)
    _write_bytes(
        runtime_dir / "admin/root-token",
        f"{root_token}\n".encode("utf-8"),
        mode=0o600,
    )
    _write_bytes(
        runtime_dir / "admin/unseal-key",
        f"{unseal_key}\n".encode("utf-8"),
        mode=0o600,
    )
    return OpenBaoBootstrap(root_token=root_token, unseal_key=unseal_key)


def _wait_for_openbao_uninitialized(
    client: OpenBaoAdminClient,
    *,
    attempts: int = 50,
    interval_seconds: float = 0.1,
) -> dict[str, Any]:
    if attempts <= 0 or interval_seconds < 0:
        raise S143StagingError("OpenBao initialization wait policy is invalid")
    for attempt in range(1, attempts + 1):
        try:
            status = client.request("GET", "/v1/sys/init")
        except S143StagingError:
            status = {}
        if status.get("initialized") is False:
            return {"status": "UNINITIALIZED", "attempts": attempt}
        if status.get("initialized") is True:
            raise S143StagingError("OpenBao is already initialized")
        if attempt < attempts:
            time.sleep(interval_seconds)
    raise S143StagingError("OpenBao initialization API did not become ready")


def _wait_for_openbao_active(
    client: OpenBaoAdminClient,
    *,
    root_token: str,
    attempts: int = 50,
    interval_seconds: float = 0.1,
) -> dict[str, Any]:
    if attempts <= 0 or interval_seconds < 0:
        raise S143StagingError("OpenBao active wait policy is invalid")
    for attempt in range(1, attempts + 1):
        leader = client.request("GET", "/v1/sys/leader", token=root_token)
        if leader.get("ha_enabled") is True and leader.get("is_self") is True:
            return {"status": "ACTIVE", "attempts": attempt}
        if attempt < attempts:
            time.sleep(interval_seconds)
    raise S143StagingError("OpenBao did not become writable active leader")


def configure_openbao_staging(
    client: OpenBaoAdminClient,
    *,
    root_token: str,
    root: Path,
    runtime_dir: Path,
    secret_values: Mapping[str, str],
) -> dict[str, Any]:
    bindings = tuple(
        binding
        for binding in load_production_configuration_manifest(root).bindings
        if binding.input_kind == "external_secret_reference"
    )
    expected = {binding.target_environment_name for binding in bindings}
    if set(secret_values) != expected or any(
        not _secret_value(value) for value in secret_values.values()
    ):
        raise S143StagingError("S143 staging secret input coverage is invalid")

    client.request(
        "POST",
        "/v1/sys/mounts/kv",
        token=root_token,
        payload={"type": "kv", "options": {"version": "2"}},
    )
    client.request(
        "POST",
        "/v1/sys/auth/approle",
        token=root_token,
        payload={"type": "approle"},
    )
    versions = write_openbao_secret_generation(
        client,
        root_token=root_token,
        bindings=bindings,
        secret_values=secret_values,
    )
    for owner in OWNERS:
        policy_name = owner.replace("nex-", "nex-") + "-staging"
        policy = (
            f'path "kv/data/nex-platform/staging/{owner}/*" {{\n'
            '  capabilities = ["read"]\n'
            "}\n"
        )
        client.request(
            "PUT",
            f"/v1/sys/policies/acl/{quote(policy_name, safe='-_')}",
            token=root_token,
            payload={"policy": policy},
        )
        role_name = f"{owner}-staging"
        client.request(
            "POST",
            f"/v1/auth/approle/role/{quote(role_name, safe='-_')}",
            token=root_token,
            payload={
                "token_policies": [policy_name],
                "token_ttl": "5m",
                "token_max_ttl": "10m",
                "secret_id_ttl": "15m",
                "secret_id_num_uses": 1,
            },
        )
    refresh_openbao_approle_credentials(
        client,
        root_token=root_token,
        runtime_dir=runtime_dir,
    )
    client.request(
        "POST",
        "/v1/sys/mounts/pki",
        token=root_token,
        payload={"type": "pki", "config": {"max_lease_ttl": "168h"}},
    )
    ca_response = client.request(
        "POST",
        "/v1/pki/root/generate/internal",
        token=root_token,
        payload={
            "common_name": "NeX S143 Staging Root CA",
            "ttl": "168h",
            "key_type": "rsa",
            "key_bits": 2048,
        },
    )
    client.request(
        "POST",
        "/v1/pki/roles/nex-platform-staging",
        token=root_token,
        payload={
            "allowed_domains": ["nex-staging.test"],
            "allow_subdomains": True,
            "allow_bare_domains": True,
            "max_ttl": "48h",
        },
    )
    certificate = issue_openbao_platform_certificate(
        client,
        root_token=root_token,
        runtime_dir=runtime_dir,
    )
    ca_data = ca_response.get("data")
    if not isinstance(ca_data, Mapping) or not _pem(ca_data.get("certificate")):
        raise S143StagingError("OpenBao PKI root response is invalid")
    return {
        "schema_version": S143_STAGING_SCHEMA_VERSION,
        "status": "CONFIGURED",
        "secret_count": len(bindings),
        "owner_count": len(OWNERS),
        "secret_versions": sorted(set(versions.values())),
        "certificate_serial": certificate["serial_number"],
        "raw_secret_values_included": False,
    }


def write_openbao_secret_generation(
    client: OpenBaoAdminClient,
    *,
    root_token: str,
    bindings: tuple[Any, ...],
    secret_values: Mapping[str, str],
) -> dict[str, int]:
    versions = {}
    for binding in bindings:
        target = binding.target_environment_name
        response = client.request(
            "POST",
            "/v1/kv/data/nex-platform/staging/"
            f"{quote(binding.owner, safe='-_')}/{quote(target, safe='-_')}",
            token=root_token,
            payload={"data": {"value": secret_values[target]}},
        )
        data = response.get("data")
        version = data.get("version") if isinstance(data, Mapping) else None
        if not isinstance(version, int) or version < 1:
            raise S143StagingError("OpenBao KV version response is invalid")
        versions[target] = version
    return versions


def refresh_openbao_approle_credentials(
    client: OpenBaoAdminClient,
    *,
    root_token: str,
    runtime_dir: Path,
) -> None:
    credential_dir = runtime_dir / "credentials"
    for owner in OWNERS:
        role_name = f"{owner}-staging"
        role_response = client.request(
            "GET",
            f"/v1/auth/approle/role/{quote(role_name, safe='-_')}/role-id",
            token=root_token,
        )
        secret_response = client.request(
            "POST",
            f"/v1/auth/approle/role/{quote(role_name, safe='-_')}/secret-id",
            token=root_token,
            payload={},
        )
        role_data = role_response.get("data")
        secret_data = secret_response.get("data")
        role_id = role_data.get("role_id") if isinstance(role_data, Mapping) else None
        secret_id = (
            secret_data.get("secret_id") if isinstance(secret_data, Mapping) else None
        )
        if not _credential(role_id) or not _credential(secret_id):
            raise S143StagingError("OpenBao AppRole credential response is invalid")
        _write_bytes(
            credential_dir / f"{owner}.role-id",
            f"{role_id}\n".encode("utf-8"),
            mode=0o644,
            replace=True,
        )
        _write_bytes(
            credential_dir / f"{owner}.secret-id",
            f"{secret_id}\n".encode("utf-8"),
            mode=0o644,
            replace=True,
        )


def issue_openbao_platform_certificate(
    client: OpenBaoAdminClient,
    *,
    root_token: str,
    runtime_dir: Path,
    subject_alt_names: Sequence[str] = STAGING_HOSTS,
) -> dict[str, str]:
    hostnames = tuple(subject_alt_names)
    if not hostnames or any(
        not isinstance(hostname, str) or not hostname or "," in hostname
        for hostname in hostnames
    ):
        raise S143StagingError("OpenBao PKI subject alternative names are invalid")
    response = client.request(
        "POST",
        "/v1/pki/issue/nex-platform-staging",
        token=root_token,
        payload={
            "common_name": "nex-staging.test",
            "alt_names": ",".join(hostnames),
            "ttl": "24h",
            "private_key_format": "pkcs8",
        },
    )
    data = response.get("data")
    if not isinstance(data, Mapping):
        raise S143StagingError("OpenBao PKI issue response is invalid")
    certificate = data.get("certificate")
    private_key = data.get("private_key")
    issuing_ca = data.get("issuing_ca")
    serial_number = data.get("serial_number")
    if not all(_pem(value) for value in (certificate, private_key, issuing_ca)):
        raise S143StagingError("OpenBao PKI issue response is invalid")
    if not isinstance(serial_number, str) or not serial_number:
        raise S143StagingError("OpenBao PKI serial is invalid")
    tls_dir = runtime_dir / "tls"
    _write_bytes(
        tls_dir / "platform.crt",
        f"{certificate.rstrip()}\n{issuing_ca.rstrip()}\n".encode("utf-8"),
        mode=0o644,
        replace=True,
    )
    _write_bytes(
        tls_dir / "platform.key",
        f"{private_key.rstrip()}\n".encode("utf-8"),
        mode=0o644,
        replace=True,
    )
    _write_bytes(
        tls_dir / "platform-ca.crt",
        f"{issuing_ca.rstrip()}\n".encode("utf-8"),
        mode=0o644,
        replace=True,
    )
    return {"serial_number": serial_number}


def _write_bytes(
    path: Path,
    value: bytes,
    *,
    mode: int,
    replace: bool = False,
) -> None:
    flags = os.O_WRONLY | os.O_CREAT | (os.O_TRUNC if replace else os.O_EXCL)
    try:
        descriptor = os.open(path, flags, mode)
        with os.fdopen(descriptor, "wb") as output:
            output.write(value)
        os.chmod(path, mode)
    except OSError as exc:
        raise S143StagingError(f"S143 runtime file write failed: {path.name}") from exc


def _credential(value: object) -> bool:
    return (
        isinstance(value, str)
        and 8 <= len(value) <= 4096
        and not any(character.isspace() for character in value)
    )


def _secret_value(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 65_536


def _pem(value: object) -> bool:
    return isinstance(value, str) and value.startswith("-----BEGIN ")
