from __future__ import annotations

import re
from collections.abc import Mapping
from hashlib import sha256
import os
from pathlib import Path
from typing import Any, Protocol

import yaml

from .s143_staging import S143StagingError, validate_s143_compose_assets

S144_STAGING_SCHEMA_VERSION = "s144_staging_trust_federation.v1"
S144_OVERRIDE_PATH = "deployment/compose/s144-staging.override.yaml"
S144_DYNAMIC_PATH = "deployment/compose/traefik/s144-dynamic.yaml"
S144_OPENBAO_CONFIG_PATH = "deployment/compose/openbao/s144-config.hcl"
OIDC_PROVIDER_NAME = "nex-platform"
OIDC_CLIENT_NAME = "nex-platform-oa-staging"
OIDC_ISSUER_ORIGIN = "https://id.nex-staging.test:8443"
OIDC_ISSUER = f"{OIDC_ISSUER_ORIGIN}/v1/identity/oidc/provider/{OIDC_PROVIDER_NAME}"
OIDC_CALLBACK = "https://oa.nex-staging.test:8443/api/v1/auth/federated/callback"
TRANSIT_KEY_NAME = "oa-signing"
TRANSIT_POLICY_NAME = "nex-oa-transit-staging"
TRANSIT_ROLE_NAME = "nex-oa-transit-staging"
TRANSIT_ROLE_ID_FILE = "nex-oa-transit.role-id"
TRANSIT_SECRET_ID_FILE = "nex-oa-transit.secret-id"
_OPAQUE_CLIENT_VALUE = re.compile(r"^[\x21-\x7e]{8,4096}$")


class S144StagingError(S143StagingError):
    pass


class OpenBaoS144AdminClient(Protocol):
    def request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]: ...


def validate_s144_compose_assets(root: Path) -> dict[str, Any]:
    base = validate_s143_compose_assets(root)
    try:
        override_text = (root / S144_OVERRIDE_PATH).read_text(encoding="utf-8")
        override = yaml.safe_load(override_text)
        dynamic_text = (root / S144_DYNAMIC_PATH).read_text(encoding="utf-8")
        dynamic = yaml.safe_load(dynamic_text)
        openbao = (root / S144_OPENBAO_CONFIG_PATH).read_text(encoding="utf-8")
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise S144StagingError("S144 Compose assets are unreadable") from exc
    if not isinstance(override, Mapping) or not isinstance(dynamic, Mapping):
        raise S144StagingError("S144 Compose assets are invalid")
    services = override.get("services")
    if not isinstance(services, Mapping) or set(services) != {
        "openbao",
        "traefik",
        "nex-oa",
    }:
        raise S144StagingError("S144 service override coverage drift")
    if any(
        marker in override_text
        for marker in ("/var/run/docker.sock", "privileged: true", "network_mode: host")
    ):
        raise S144StagingError("S144 Compose privilege boundary drift")
    if "ui = true" not in openbao or 'storage "raft"' not in openbao:
        raise S144StagingError("S144 OpenBao UI or durable storage drift")

    openbao_volumes = services["openbao"].get("volumes")
    if openbao_volumes != [
        "../compose/openbao/s144-config.hcl:/openbao/config/config.hcl:ro"
    ]:
        raise S144StagingError("S144 OpenBao configuration override drift")
    networks = override.get("networks")
    if (
        networks != {"identity": {"internal": True}}
        or "identity" not in services["openbao"].get("networks", ())
    ):
        raise S144StagingError("S144 isolated identity network drift")
    traefik = services["traefik"]
    if (
        traefik.get("volumes")
        != ["../compose/traefik/s144-dynamic.yaml:/etc/traefik/dynamic.yaml:ro"]
        or "openbao_ca" not in traefik.get("secrets", ())
        or "id.nex-staging.test"
        not in traefik.get("networks", {}).get("service", {}).get("aliases", ())
        or traefik.get("networks", {}).get("identity") != {}
    ):
        raise S144StagingError("S144 Traefik identity route override drift")

    oa_environment = services["nex-oa"].get("environment")
    required_oa = {
        "NEX_OA_SIGNING_PROVIDER": "OPENBAO_TRANSIT",
        "NEX_OA_OIDC_PROVIDER_ID": "openbao-staging",
        "NEX_OA_OIDC_ISSUER": OIDC_ISSUER,
        "NEX_OA_OIDC_DISCOVERY_URL": (
            f"{OIDC_ISSUER}/.well-known/openid-configuration"
        ),
        "NEX_OA_OIDC_REDIRECT_URI": OIDC_CALLBACK,
        "NEX_OA_OIDC_SCOPES": "openid",
        "NEX_OA_OIDC_GRANT_TYPE": "authorization_code",
        "NEX_OA_OIDC_RESPONSE_TYPE": "code",
        "NEX_OA_OIDC_PKCE_METHOD": "S256",
        "NEX_OA_OIDC_CLIENT_AUTH_METHOD": "client_secret_basic",
        "NEX_OA_TRANSIT_ROLE_ID_FILE": "/run/secrets/openbao_transit_role_id",
        "NEX_OA_TRANSIT_SECRET_ID_FILE": "/run/secrets/openbao_transit_secret_id",
    }
    if not isinstance(oa_environment, Mapping) or any(
        oa_environment.get(name) != expected for name, expected in required_oa.items()
    ):
        raise S144StagingError("S144 OA trust environment drift")
    if "${NEX_S144_OIDC_CLIENT_ID:?" not in str(
        oa_environment.get("NEX_OA_OIDC_CLIENT_ID")
    ):
        raise S144StagingError("S144 generated OIDC client id boundary drift")
    secret_reference = str(oa_environment.get("NEX_OA_OIDC_CLIENT_SECRET_REF") or "")
    if not secret_reference.startswith(
        "secret://openbao/nex-platform/staging/nex-oa/NEX_OA_OIDC_CLIENT_SECRET@"
    ):
        raise S144StagingError("S144 OIDC secret reference drift")
    oa_secrets = services["nex-oa"].get("secrets")
    required_transit_secrets = {
        ("oa_transit_role_id", "openbao_transit_role_id"),
        ("oa_transit_secret_id", "openbao_transit_secret_id"),
    }
    mounted_transit_secrets = {
        (item.get("source"), item.get("target"))
        for item in oa_secrets or ()
        if isinstance(item, Mapping)
    }
    secret_files = override.get("secrets")
    if (
        not required_transit_secrets.issubset(mounted_transit_secrets)
        or not isinstance(secret_files, Mapping)
        or set(secret_files) != {"oa_transit_role_id", "oa_transit_secret_id"}
    ):
        raise S144StagingError("S144 Transit runtime credential boundary drift")

    http = dynamic.get("http")
    identity = (
        http.get("services", {}).get("identity", {}).get("loadBalancer", {})
        if isinstance(http, Mapping)
        else {}
    )
    transport = (
        http.get("serversTransports", {}).get("openbao-tls", {})
        if isinstance(http, Mapping)
        else {}
    )
    if (
        "Host(`id.nex-staging.test`)" not in dynamic_text
        or identity.get("serversTransport") != "openbao-tls"
        or identity.get("servers") != [{"url": "https://openbao:8200"}]
        or transport.get("rootCAs") != ["/run/secrets/openbao_ca"]
        or transport.get("serverName") != "openbao"
    ):
        raise S144StagingError("S144 managed identity TLS route drift")
    return {
        "schema_version": S144_STAGING_SCHEMA_VERSION,
        "status": "VALID",
        "base_schema_version": base["schema_version"],
        "orchestrator": "docker-compose-single-host",
        "override_service_count": len(services),
        "tls_route_count": 10,
        "oidc_secret_reference_count": 1,
        "transit_runtime_secret_count": 2,
        "openbao_ui_enabled": True,
        "identity_network_internal": True,
        "host_software_install_required": False,
        "raw_secret_values_included": False,
    }


def configure_openbao_s144_trust(
    client: OpenBaoS144AdminClient,
    *,
    root_token: str,
) -> dict[str, Any]:
    if _opaque_value(root_token) is None:
        raise S144StagingError("S144 OpenBao root credential is invalid")
    client.request(
        "POST",
        "/v1/sys/mounts/transit",
        token=root_token,
        payload={"type": "transit"},
    )
    client.request(
        "POST",
        f"/v1/transit/keys/{TRANSIT_KEY_NAME}",
        token=root_token,
        payload={
            "type": "rsa-3072",
            "derived": False,
            "exportable": False,
            "allow_plaintext_backup": False,
        },
    )
    key_data = _data(
        client.request(
            "GET",
            f"/v1/transit/keys/{TRANSIT_KEY_NAME}",
            token=root_token,
        ),
        "Transit key",
    )
    if (
        key_data.get("type") != "rsa-3072"
        or key_data.get("latest_version") != 1
        or key_data.get("derived") is not False
        or key_data.get("exportable") is not False
        or key_data.get("allow_plaintext_backup") is not False
    ):
        raise S144StagingError("S144 Transit key policy is invalid")

    policy = (
        f'path "transit/sign/{TRANSIT_KEY_NAME}/sha2-256" {{\n'
        '  capabilities = ["update"]\n'
        "}\n"
        f'path "transit/keys/{TRANSIT_KEY_NAME}" {{\n'
        '  capabilities = ["read"]\n'
        "}\n"
    )
    client.request(
        "PUT",
        f"/v1/sys/policies/acl/{TRANSIT_POLICY_NAME}",
        token=root_token,
        payload={"policy": policy},
    )
    client.request(
        "POST",
        f"/v1/auth/approle/role/{TRANSIT_ROLE_NAME}",
        token=root_token,
        payload={
            "token_policies": [TRANSIT_POLICY_NAME],
            "token_ttl": "5m",
            "token_max_ttl": "10m",
            "secret_id_ttl": "24h",
            "secret_id_num_uses": 0,
        },
    )
    client.request(
        "POST",
        f"/v1/identity/oidc/client/{OIDC_CLIENT_NAME}",
        token=root_token,
        payload={
            "key": "default",
            "redirect_uris": [OIDC_CALLBACK],
            "assignments": ["allow_all"],
            "client_type": "confidential",
            "id_token_ttl": "15m",
            "access_token_ttl": "15m",
        },
    )
    client_data = _data(
        client.request(
            "GET",
            f"/v1/identity/oidc/client/{OIDC_CLIENT_NAME}",
            token=root_token,
        ),
        "OIDC client",
    )
    client_id = _opaque_value(client_data.get("client_id"), maximum=255)
    client_secret = _opaque_value(client_data.get("client_secret"))
    if (
        client_id is None
        or client_secret is None
        or client_data.get("client_type") != "confidential"
        or client_data.get("redirect_uris") != [OIDC_CALLBACK]
        or client_data.get("assignments") != ["allow_all"]
    ):
        raise S144StagingError("S144 OIDC client response is invalid")
    kv_data = _data(
        client.request(
            "POST",
            "/v1/kv/data/nex-platform/staging/nex-oa/NEX_OA_OIDC_CLIENT_SECRET",
            token=root_token,
            payload={"data": {"value": client_secret}},
        ),
        "OIDC client secret custody",
    )
    secret_version = kv_data.get("version")
    if (
        not isinstance(secret_version, int)
        or isinstance(secret_version, bool)
        or secret_version < 1
    ):
        raise S144StagingError("S144 OIDC client secret version is invalid")

    client.request(
        "POST",
        f"/v1/identity/oidc/provider/{OIDC_PROVIDER_NAME}",
        token=root_token,
        payload={
            "issuer": OIDC_ISSUER_ORIGIN,
            "allowed_client_ids": [client_id],
            "scopes_supported": [],
        },
    )
    provider_data = _data(
        client.request(
            "GET",
            f"/v1/identity/oidc/provider/{OIDC_PROVIDER_NAME}",
            token=root_token,
        ),
        "OIDC provider",
    )
    if provider_data.get("allowed_client_ids") != [client_id]:
        raise S144StagingError("S144 OIDC provider client binding is invalid")
    return {
        "schema_version": S144_STAGING_SCHEMA_VERSION,
        "status": "CONFIGURED",
        "transit_key_name": TRANSIT_KEY_NAME,
        "transit_key_version": 1,
        "transit_role_name": TRANSIT_ROLE_NAME,
        "oidc_provider_name": OIDC_PROVIDER_NAME,
        "oidc_client_name": OIDC_CLIENT_NAME,
        "oidc_client_id": client_id,
        "oidc_client_id_digest": sha256(client_id.encode("ascii")).hexdigest(),
        "oidc_secret_version": secret_version,
        "oidc_client_secret_included": False,
        "oidc_client_secret_reference_included": False,
        "raw_private_key_included": False,
    }


def refresh_openbao_s144_transit_credentials(
    client: OpenBaoS144AdminClient,
    *,
    root_token: str,
    runtime_dir: Path,
) -> dict[str, Any]:
    if _opaque_value(root_token) is None:
        raise S144StagingError("S144 OpenBao root credential is invalid")
    credential_dir = runtime_dir / "credentials"
    if not runtime_dir.is_absolute() or not credential_dir.is_dir():
        raise S144StagingError("S144 runtime credential directory is unavailable")
    role_data = _data(
        client.request(
            "GET",
            f"/v1/auth/approle/role/{TRANSIT_ROLE_NAME}/role-id",
            token=root_token,
        ),
        "Transit role ID",
    )
    secret_data = _data(
        client.request(
            "POST",
            f"/v1/auth/approle/role/{TRANSIT_ROLE_NAME}/secret-id",
            token=root_token,
            payload={},
        ),
        "Transit secret ID",
    )
    role_id = _opaque_value(role_data.get("role_id"))
    secret_id = _opaque_value(secret_data.get("secret_id"))
    if role_id is None or secret_id is None:
        raise S144StagingError("S144 Transit AppRole credential is invalid")
    _replace_credential(credential_dir / TRANSIT_ROLE_ID_FILE, role_id)
    _replace_credential(credential_dir / TRANSIT_SECRET_ID_FILE, secret_id)
    return {
        "schema_version": S144_STAGING_SCHEMA_VERSION,
        "status": "REFRESHED",
        "role_name": TRANSIT_ROLE_NAME,
        "role_id_digest": sha256(role_id.encode("utf-8")).hexdigest(),
        "secret_id_included": False,
    }


def _data(response: Mapping[str, Any], label: str) -> Mapping[str, Any]:
    data = response.get("data")
    if not isinstance(data, Mapping):
        raise S144StagingError(f"S144 {label} response is invalid")
    return data


def _opaque_value(value: object, *, maximum: int = 4096) -> str | None:
    if not isinstance(value, str) or len(value) > maximum:
        return None
    return value if _OPAQUE_CLIENT_VALUE.fullmatch(value) else None


def _replace_credential(path: Path, value: str) -> None:
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(f"{value}\n")
        os.chmod(path, 0o644)
    except OSError:
        raise S144StagingError("S144 Transit credential write failed") from None
