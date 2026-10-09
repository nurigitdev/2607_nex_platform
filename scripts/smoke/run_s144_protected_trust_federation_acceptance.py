#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from datetime import UTC, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import ssl
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from typing import Any
from urllib.parse import urlencode
from uuid import uuid4

import psycopg


ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services/_shared",
    ROOT / "services/nex-oa",
    ROOT / "scripts/db",
    ROOT / "scripts/smoke",
):
    sys.path.insert(0, str(path))

from nex_oa.enterprise_oidc_registration import (  # noqa: E402
    load_oa_enterprise_oidc_registration,
    validate_enterprise_oidc_discovery,
)
from nex_oa.federated_identities import (  # noqa: E402
    build_external_identity_link,
    build_federation_provider,
)
from nex_oa.federated_identity_repository import (  # noqa: E402
    build_federated_identity_repository_for_runtime,
)
from nex_oa.memberships import (  # noqa: E402
    build_tenant_membership_registry_for_runtime,
)
from nex_oa.openbao_transit_keys import (  # noqa: E402
    OpenBaoTransitKeyProvisioner,
    register_openbao_transit_key_version,
)
from nex_oa.production_token_profiles import PRODUCTION_TOKEN_ISSUER  # noqa: E402
from nex_oa.service_principal_repository import (  # noqa: E402
    build_service_principal_repository_for_runtime,
)
from nex_oa.service_principal_service import OaServicePrincipalService  # noqa: E402
from nex_oa.signed_token_repository import (  # noqa: E402
    build_signed_token_repository_for_runtime,
)
from nex_oa.signing_key_service import OaSigningKeyService  # noqa: E402
from nex_oa.subjects import build_subject_registry_for_runtime  # noqa: E402
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    attach_service_persistence_runtime,
    build_service_app,
    load_env_file,
    psycopg_database_url,
)
from nex_runtime.production_configuration import (  # noqa: E402
    load_production_configuration_manifest,
)
from nex_runtime.s143_staging import (  # noqa: E402
    OpenBaoAdminClient,
    STAGING_HOSTS,
    configure_openbao_staging,
    initialize_openbao,
    issue_openbao_platform_certificate,
    prepare_staging_runtime_directory,
    refresh_openbao_approle_credentials,
)
from nex_runtime.s144_staging import (  # noqa: E402
    OIDC_CALLBACK,
    OIDC_ISSUER,
    OIDC_PROVIDER_NAME,
    TRANSIT_KEY_NAME,
    configure_openbao_s144_trust,
    refresh_openbao_s144_transit_credentials,
    validate_s144_compose_assets,
)
from run_migrations import run_service_migrations  # noqa: E402
import run_s143_external_staging_acceptance as s143  # noqa: E402


ENABLE_ENV = "NEX_S144_PROTECTED_ACCEPTANCE"
SCHEMA_VERSION = "s144_protected_trust_federation_acceptance.v1"
REPORT_PATH = ROOT / "reports/deployment/s144-protected-trust-federation.json"
BASE_COMPOSE = ROOT / "deployment/compose/s143-staging.compose.yaml"
OVERRIDE_COMPOSE = ROOT / "deployment/compose/s144-staging.override.yaml"
OA_DATABASE_ENV = "NEX_OA_TEST_DATABASE_URL"
ImageEnvironmentLoader = Callable[[Path], tuple[dict[str, str], str]]


class S144ProtectedAcceptanceError(RuntimeError):
    pass


def run_s144_protected_acceptance(
    environ: Mapping[str, str] | None = None,
    *,
    execute: bool = False,
    root: Path = ROOT,
    report_path: Path = REPORT_PATH,
    image_environment_loader: ImageEnvironmentLoader | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if not execute or env.get(ENABLE_ENV) != "1":
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "slice": "1441",
            "requirement": "S144",
            "status": "SKIPPED",
            "skip_reason": f"--execute and {ENABLE_ENV}=1 are required.",
        }
    try:
        result = _execute_protected_acceptance(
            env,
            root=root,
            image_environment_loader=image_environment_loader,
        )
        _assert_value_free(result, _protected_environment_values(env))
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return result
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "slice": "1441",
            "requirement": "S144",
            "status": "FAIL",
            "issues": [exc.__class__.__name__],
            "decision": {
                "protected_acceptance_passed": False,
                "production_deployment_approved": False,
            },
            "raw_secret_values_included": False,
        }


def _execute_protected_acceptance(
    env: Mapping[str, str],
    *,
    root: Path,
    image_environment_loader: ImageEnvironmentLoader | None = None,
) -> dict[str, Any]:
    compose_contract = validate_s144_compose_assets(root)
    database_url = str(env.get(OA_DATABASE_ENV) or "").strip()
    if not database_url:
        raise S144ProtectedAcceptanceError(f"{OA_DATABASE_ENV} is required")
    migration = run_service_migrations(
        "nex-oa", database_url=database_url, profile="test", dry_run=False
    )
    _verify_database_identity(database_url)
    image_environment, release_set_digest = (
        image_environment_loader or s143._image_environment
    )(root)
    run_id = f"s144-{uuid4().hex[:12]}"
    context = _seed_context(run_id)
    runtime = None
    compose_environment: dict[str, str] | None = None
    with TemporaryDirectory(prefix="nex-s144-staging-") as temporary:
        runtime_directory = Path(temporary)
        prepare_staging_runtime_directory(runtime_directory)
        compose_environment = {
            **env,
            **image_environment,
            "NEX_S143_RUNTIME_DIR": str(runtime_directory),
            "NEX_S143_SECRET_VERSION": "v1",
            "NEX_S143_SECRET_GENERATION": "secret:s144-staging.1",
            "NEX_S143_TLS_GENERATION": "tls:s144-staging.1",
            # Compose validates interpolation for every service even while only
            # OpenBao is bootstrapping. Replace this sentinel before OA starts.
            "NEX_S144_OIDC_CLIENT_ID": "pending-openbao-bootstrap",
        }
        _compose(
            compose_environment,
            root=root,
            arguments=("down", "--volumes", "--remove-orphans"),
            check=False,
        )
        try:
            _compose(compose_environment, root=root, arguments=("up", "-d", "openbao"))
            s143._wait_for_tls(
                "127.0.0.1",
                8200,
                server_hostname="localhost",
                ca_file=runtime_directory / "tls/openbao-ca.crt",
            )
            admin = OpenBaoAdminClient(
                "https://127.0.0.1:8200",
                ca_certificate_file=runtime_directory / "tls/openbao-ca.crt",
            )
            bootstrap = initialize_openbao(admin, runtime_directory)
            secret_values = _staging_secret_values(database_url, root=root)
            configure_openbao_staging(
                admin,
                root_token=bootstrap.root_token,
                root=root,
                runtime_dir=runtime_directory,
                secret_values=secret_values,
            )
            configured = configure_openbao_s144_trust(
                admin, root_token=bootstrap.root_token
            )
            refresh_openbao_s144_transit_credentials(
                admin,
                root_token=bootstrap.root_token,
                runtime_dir=runtime_directory,
            )
            issue_openbao_platform_certificate(
                admin,
                root_token=bootstrap.root_token,
                runtime_dir=runtime_directory,
                subject_alt_names=(*STAGING_HOSTS, "id.nex-staging.test"),
            )
            compose_environment["NEX_S144_OIDC_CLIENT_ID"] = str(
                configured["oidc_client_id"]
            )
            registration = _registration(compose_environment)
            user = _configure_oidc_user(admin, bootstrap.root_token, run_id)

            _compose(
                compose_environment,
                root=root,
                arguments=("up", "-d", "--wait", "--wait-timeout", "90", "traefik"),
            )
            ca_file = runtime_directory / "tls/platform-ca.crt"
            discovery = _https_json(
                "id.nex-staging.test",
                f"/v1/identity/oidc/provider/{OIDC_PROVIDER_NAME}/.well-known/openid-configuration",
                ca_file=ca_file,
            )
            metadata = validate_enterprise_oidc_discovery(registration, discovery)
            initial_oidc_jwks = _https_json(
                "id.nex-staging.test",
                f"/v1/identity/oidc/provider/{OIDC_PROVIDER_NAME}/.well-known/keys",
                ca_file=ca_file,
            )
            oidc = _issue_oidc_authorization_code_token(
                admin,
                user_token=user["token"],
                client_id=str(configured["oidc_client_id"]),
                client_secret=user["client_secret"],
                ca_file=ca_file,
            )
            claims = _jwt_claims(oidc["id_token"])
            runtime = _seed_oa(
                database_url,
                admin=admin,
                root_token=bootstrap.root_token,
                registration=registration,
                external_subject=str(claims["sub"]),
                run_id=run_id,
                context=context,
            )
            compose_environment["NEX_S144_OIDC_CLIENT_ID"] = registration.client_id
            _compose(
                compose_environment,
                root=root,
                arguments=(
                    "up",
                    "-d",
                    "--wait",
                    "--wait-timeout",
                    "120",
                    "nex-oa",
                ),
            )
            _require_ready(ca_file)
            first_token = _issue_oa_token(ca_file, context)
            federation = _post_json(
                "oa.nex-staging.test",
                "/internal/v1/auth/federated-login",
                ca_file=ca_file,
                headers={"Authorization": f"Bearer {first_token}"},
                payload={
                    "provider_id": registration.provider_id,
                    "id_token": oidc["id_token"],
                    "nonce": oidc["nonce"],
                    "requested_scopes": ["workspace:use"],
                    "ttl_seconds": 600,
                },
                expected_status=200,
            )
            admin.request(
                "POST",
                "/v1/identity/oidc/key/default/rotate",
                token=bootstrap.root_token,
                payload={},
            )
            rolled_oidc = _issue_oidc_authorization_code_token(
                admin,
                user_token=user["token"],
                client_id=str(configured["oidc_client_id"]),
                client_secret=user["client_secret"],
                ca_file=ca_file,
            )
            rolled_federation = _post_json(
                "oa.nex-staging.test",
                "/internal/v1/auth/federated-login",
                ca_file=ca_file,
                headers={"Authorization": f"Bearer {first_token}"},
                payload={
                    "provider_id": registration.provider_id,
                    "id_token": rolled_oidc["id_token"],
                    "nonce": rolled_oidc["nonce"],
                    "requested_scopes": ["workspace:use"],
                    "ttl_seconds": 600,
                },
                expected_status=200,
            )
            rolled_oidc_jwks = _https_json(
                "id.nex-staging.test",
                f"/v1/identity/oidc/provider/{OIDC_PROVIDER_NAME}/.well-known/keys",
                ca_file=ca_file,
            )
            initial_oidc_kid = _jwt_key_id(oidc["id_token"])
            rolled_oidc_kid = _jwt_key_id(rolled_oidc["id_token"])
            initial_oidc_key_ids = _jwk_ids(initial_oidc_jwks)
            rolled_oidc_key_ids = _jwk_ids(rolled_oidc_jwks)

            rotation = _rotate_oa_key(
                runtime,
                admin=admin,
                root_token=bootstrap.root_token,
                run_id=run_id,
            )
            prepublished = _https_json(
                "oa.nex-staging.test", "/.well-known/jwks.json", ca_file=ca_file
            )
            rotation["service"].activate_rotation(
                context["key_v1"],
                context["key_v2"],
                expected_previous_revision=2,
                expected_active_revision=1,
            )
            second_token = _issue_oa_token(ca_file, context)
            overlap = _https_json(
                "oa.nex-staging.test", "/.well-known/jwks.json", ca_file=ca_file
            )
            old_active = _introspect(ca_file, second_token, first_token)
            revocation = _post_json(
                "oa.nex-staging.test",
                "/api/v1/auth/revoke",
                ca_file=ca_file,
                headers={"Authorization": f"Bearer {second_token}"},
                payload={
                    "token": first_token,
                    "audience": "nex-oa",
                    "reason_code": "OPERATOR",
                },
                expected_status=200,
            )
            context["revocation_id"] = revocation["revocation_id"]
            old_revoked = _introspect(ca_file, second_token, first_token)

            refresh_openbao_approle_credentials(
                admin,
                root_token=bootstrap.root_token,
                runtime_dir=runtime_directory,
            )
            _compose(
                compose_environment,
                root=root,
                arguments=(
                    "up",
                    "-d",
                    "--force-recreate",
                    "--wait",
                    "--wait-timeout",
                    "120",
                    "nex-oa",
                ),
            )
            _wait_for_oa_ready(ca_file)
            restart_active = _introspect(ca_file, second_token, second_token)

            _compose(
                compose_environment,
                root=root,
                arguments=("stop", "openbao"),
            )
            outage_status, _ = _request_json(
                "oa.nex-staging.test",
                "/api/v1/auth/service-token",
                method="POST",
                ca_file=ca_file,
                payload=_token_request(context),
            )
            _compose(
                compose_environment,
                root=root,
                arguments=("start", "openbao"),
            )
            s143._wait_for_tls(
                "127.0.0.1",
                8200,
                server_hostname="localhost",
                ca_file=runtime_directory / "tls/openbao-ca.crt",
            )
            admin.request(
                "PUT", "/v1/sys/unseal", payload={"key": bootstrap.unseal_key}
            )
            recovered_token = _retry_issue_oa_token(ca_file, context)

            result = {
                "evidence_schema_version": SCHEMA_VERSION,
                "slice": "1441",
                "requirement": "S144",
                "status": "PASS",
                "executed_at": datetime.now(UTC).isoformat(),
                "compose_contract": compose_contract,
                "release_set_digest": release_set_digest,
                "postgres": {
                    "database": "nex_oa_test",
                    "migration_count": len(migration.planned),
                    "applied_count": len(migration.applied),
                    "actual_connection": True,
                },
                "transit": {
                    "key_type": "rsa-3072",
                    "non_exportable": True,
                    "versions_verified": [1, rotation["version"]],
                    "prepublished_jwks_count": len(prepublished.get("keys", [])),
                    "overlap_jwks_count": len(overlap.get("keys", [])),
                    "old_token_active_before_revoke": old_active.get("active") is True,
                    "old_token_inactive_after_revoke": old_revoked.get("active") is False,
                    "restart_token_active": restart_active.get("active") is True,
                    "outage_failed_closed": outage_status == 503,
                    "recovery_succeeded": bool(recovered_token),
                },
                "federation": {
                    "issuer": OIDC_ISSUER,
                    "discovery_valid": metadata["endpoint_origins_match"],
                    "oidc_jwks_count": len(initial_oidc_jwks.get("keys", [])),
                    "authorization_code_exchanged": True,
                    "pkce_method": "S256",
                    "id_token_verified_by_oa": True,
                    "exact_subject_link_resolved": (
                        federation.get("metadata", {}).get("identity_link_verified")
                        is True
                    ),
                    "oa_session_issued": _federated_session_issued(federation),
                    "metadata_key_rollover_verified": (
                        _federated_session_issued(rolled_federation)
                        and initial_oidc_kid != rolled_oidc_kid
                        and initial_oidc_kid in initial_oidc_key_ids
                        and rolled_oidc_kid in rolled_oidc_key_ids
                    ),
                    "metadata_jwks_overlap_verified": (
                        initial_oidc_kid in rolled_oidc_key_ids
                        and rolled_oidc_kid in rolled_oidc_key_ids
                    ),
                    "browser_callback_route_implemented": False,
                },
                "decision": {
                    "single_host_acceptance_passed": True,
                    "protected_acceptance_passed": True,
                    "corporate_idp_contacted": False,
                    "registry_push_performed": False,
                    "production_deployment_approved": False,
                    "browser_callback_deferred": True,
                    "next_slice": "1442",
                },
                "raw_secret_values_included": False,
            }
            _require_acceptance_signals(result)
            _assert_value_free(
                result,
                {
                    **secret_values,
                    "oidc_client_secret": user["client_secret"],
                    "oidc_user_token": user["token"],
                    "oidc_id_token": oidc["id_token"],
                    "rolled_oidc_id_token": rolled_oidc["id_token"],
                    "oa_token_v1": first_token,
                    "oa_token_v2": second_token,
                },
            )
            return result
        finally:
            if runtime is not None:
                _dispose_runtime(runtime)
            if compose_environment is not None:
                _compose(
                    compose_environment,
                    root=root,
                    arguments=("down", "--volumes", "--remove-orphans"),
                    check=False,
                )
            if context:
                _cleanup_database(database_url, context, run_id=run_id)


def _verify_database_identity(database_url: str) -> None:
    with psycopg.connect(psycopg_database_url(database_url)) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database(), current_user")
            if cursor.fetchone() != ("nex_oa_test", "nex_oa_user"):
                raise S144ProtectedAcceptanceError("OA test database identity mismatch")


def _staging_secret_values(database_url: str, *, root: Path) -> dict[str, str]:
    container_url = s143._container_database_url(database_url)
    result = {}
    for binding in load_production_configuration_manifest(root).bindings:
        if binding.input_kind != "external_secret_reference":
            continue
        name = binding.target_environment_name
        if name == "NEX_OA_DATABASE_URL":
            value = container_url
        elif name.endswith("_DATABASE_URL"):
            value = "postgresql+psycopg://unused:unused@host.docker.internal:5432/unused"
        else:
            value = f"s144-{secrets.token_urlsafe(32)}"
        result[name] = value
    return result


def _registration(environ: Mapping[str, str]):
    return load_oa_enterprise_oidc_registration(
        {
            **environ,
            "NEX_PROFILE": "staging_live",
            "NEX_OA_BASE_URL": "https://oa.nex-staging.test:8443",
            "NEX_OA_OIDC_PROVIDER_ID": "openbao-staging",
            "NEX_OA_OIDC_ISSUER": OIDC_ISSUER,
            "NEX_OA_OIDC_DISCOVERY_URL": f"{OIDC_ISSUER}/.well-known/openid-configuration",
            "NEX_OA_OIDC_CLIENT_ID": str(
                environ.get("NEX_S144_OIDC_CLIENT_ID") or ""
            ),
            "NEX_OA_OIDC_CLIENT_SECRET_REF": (
                "secret://openbao/nex-platform/staging/nex-oa/"
                "NEX_OA_OIDC_CLIENT_SECRET@v1"
            ),
            "NEX_OA_OIDC_REDIRECT_URI": OIDC_CALLBACK,
            "NEX_OA_OIDC_SCOPES": "openid",
            "NEX_OA_OIDC_GRANT_TYPE": "authorization_code",
            "NEX_OA_OIDC_RESPONSE_TYPE": "code",
            "NEX_OA_OIDC_PKCE_METHOD": "S256",
            "NEX_OA_OIDC_CLIENT_AUTH_METHOD": "client_secret_basic",
        }
    )


def _configure_oidc_user(
    admin: OpenBaoAdminClient, root_token: str, run_id: str
) -> dict[str, str]:
    username = f"user-{run_id}"
    password = f"S144-{secrets.token_urlsafe(24)}"
    admin.request(
        "POST", "/v1/sys/auth/userpass", token=root_token, payload={"type": "userpass"}
    )
    admin.request(
        "POST",
        f"/v1/auth/userpass/users/{username}",
        token=root_token,
        payload={"password": password},
    )
    login = admin.request(
        "POST",
        f"/v1/auth/userpass/login/{username}",
        payload={"password": password},
    )
    auth = login.get("auth")
    token = auth.get("client_token") if isinstance(auth, Mapping) else None
    client = admin.request(
        "GET",
        "/v1/identity/oidc/client/nex-platform-oa-staging",
        token=root_token,
    ).get("data")
    secret = client.get("client_secret") if isinstance(client, Mapping) else None
    if not isinstance(token, str) or not isinstance(secret, str):
        raise S144ProtectedAcceptanceError("OpenBao OIDC user bootstrap failed")
    return {"token": token, "client_secret": secret}


def _issue_oidc_authorization_code_token(
    admin: OpenBaoAdminClient,
    *,
    user_token: str,
    client_id: str,
    client_secret: str,
    ca_file: Path,
) -> dict[str, str]:
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(48)
    challenge = _base64url(sha256(verifier.encode("ascii")).digest())
    query = urlencode(
        {
            "scope": "openid",
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": OIDC_CALLBACK,
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    authorized = admin.request(
        "GET",
        f"/v1/identity/oidc/provider/{OIDC_PROVIDER_NAME}/authorize?{query}",
        token=user_token,
    )
    if authorized.get("state") != state or not isinstance(authorized.get("code"), str):
        raise S144ProtectedAcceptanceError("OpenBao OIDC authorization failed")
    credentials = base64.b64encode(
        f"{client_id}:{client_secret}".encode("ascii")
    ).decode("ascii")
    status, token = _request_json(
        "id.nex-staging.test",
        f"/v1/identity/oidc/provider/{OIDC_PROVIDER_NAME}/token",
        method="POST",
        ca_file=ca_file,
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        body=urlencode(
            {
                "code": authorized["code"],
                "grant_type": "authorization_code",
                "redirect_uri": OIDC_CALLBACK,
                "code_verifier": verifier,
            }
        ).encode("ascii"),
    )
    if status != 200 or not isinstance(token.get("id_token"), str):
        raise S144ProtectedAcceptanceError("OpenBao OIDC token exchange failed")
    return {"id_token": token["id_token"], "nonce": nonce}


def _seed_context(run_id: str) -> dict[str, Any]:
    return {
        "tenant_id": f"tenant-{run_id}",
        "subject_id": f"subject-{run_id}",
        "provider_id": "openbao-staging",
        "principal_id": f"ae-{run_id}",
        "credential_id": f"cred-{run_id}",
        "client_secret": f"s144-{secrets.token_urlsafe(24)}",
        "key_v1": f"oa-{run_id}-v1",
        "key_v2": f"oa-{run_id}-v2",
    }


def _seed_oa(
    database_url: str,
    *,
    admin: OpenBaoAdminClient,
    root_token: str,
    registration: Any,
    external_subject: str,
    run_id: str,
    context: dict[str, Any],
) -> Any:
    environment = {
        "NEX_PROFILE": "staging_live",
        "NEX_PERSISTENCE_MODE": "postgres",
        "NEX_OA_DATABASE_URL": database_url,
    }
    app = build_service_app(SERVICE_SPECS["nex-oa"], include_oa_mock_auth_routes=False)
    runtime = attach_service_persistence_runtime(
        app, SERVICE_SPECS["nex-oa"], environ=environment
    )
    subjects = build_subject_registry_for_runtime(runtime)
    memberships = build_tenant_membership_registry_for_runtime(
        runtime, subject_registry=subjects
    )
    principals = OaServicePrincipalService(
        build_service_principal_repository_for_runtime(runtime)
    )
    keys = OaSigningKeyService(
        repository=build_signed_token_repository_for_runtime(runtime),
        deployment_profile="production",
    )
    federation = build_federated_identity_repository_for_runtime(runtime)
    tenant_id = str(context["tenant_id"])
    subject_id = str(context["subject_id"])
    principal_id = str(context["principal_id"])
    credential_id = str(context["credential_id"])
    client_secret = str(context["client_secret"])
    key_v1 = str(context["key_v1"])
    now = int(time.time())
    memberships.ensure_membership(
        {
            "tenant_id": tenant_id,
            "subject_id": subject_id,
            "tenant_display_name": "S144 Trust Tenant",
            "subject_display_name": "S144 Federated User",
            "roles": ["employee"],
            "scopes": ["workspace:use"],
        }
    )
    principals.upsert_principal(
        {
            "principal_id": principal_id,
            "service_id": "nex-ae-api",
            "display_name": "S144 AE federation caller",
            "allowed_audiences": ["nex-oa"],
            "allowed_scopes": ["service:call", "token:introspect", "token:revoke"],
            "expected_revision": 0,
        }
    )
    principals.issue_credential(
        principal_id,
        lifetime_days=1,
        credential_id=credential_id,
        client_secret=client_secret,
    )
    provisioner = OpenBaoTransitKeyProvisioner(admin, root_token)
    register_openbao_transit_key_version(
        provisioner,
        keys,
        key_name=TRANSIT_KEY_NAME,
        key_version=1,
        key_id=key_v1,
        issuer=PRODUCTION_TOKEN_ISSUER,
        published_at=now - 700,
        activate_at=now - 350,
        sign_until=now + 1_800,
        verify_until=now + 2_150,
    )
    keys.set_key_state(key_v1, target_state="ACTIVE", expected_revision=1)
    provider = build_federation_provider(
        registration.provider_payload(display_name="OpenBao staging enterprise OIDC")
    )
    federation.save_provider(provider)
    federation.save_identity(
        build_external_identity_link(
            {
                "provider_id": registration.provider_id,
                "external_subject": external_subject,
                "tenant_id": tenant_id,
                "subject_id": subject_id,
            },
            provider=provider,
        )
    )
    context["signing_keys"] = keys
    return runtime


def _rotate_oa_key(
    runtime: Any,
    *,
    admin: OpenBaoAdminClient,
    root_token: str,
    run_id: str,
) -> dict[str, Any]:
    service = OaSigningKeyService(
        repository=build_signed_token_repository_for_runtime(runtime),
        deployment_profile="production",
    )
    provisioner = OpenBaoTransitKeyProvisioner(admin, root_token)
    version = provisioner.rotate_rsa3072(
        TRANSIT_KEY_NAME, expected_current_version=1
    )
    now = int(time.time())
    register_openbao_transit_key_version(
        provisioner,
        service,
        key_name=TRANSIT_KEY_NAME,
        key_version=version,
        key_id=f"oa-{run_id}-v2",
        issuer=PRODUCTION_TOKEN_ISSUER,
        published_at=now - 700,
        activate_at=now - 350,
        sign_until=now + 1_800,
        verify_until=now + 2_150,
    )
    return {"version": version, "service": service}


def _token_request(context: Mapping[str, Any]) -> dict[str, str]:
    return {
        "grant_type": "client_credentials",
        "credential_id": str(context["credential_id"]),
        "client_secret": str(context["client_secret"]),
        "audience": "nex-oa",
        "scope": "service:call token:introspect token:revoke",
    }


def _issue_oa_token(ca_file: Path, context: Mapping[str, Any]) -> str:
    response = _post_json(
        "oa.nex-staging.test",
        "/api/v1/auth/service-token",
        ca_file=ca_file,
        payload=_token_request(context),
        expected_status=200,
    )
    token = response.get("access_token")
    if not isinstance(token, str):
        raise S144ProtectedAcceptanceError("OA token response is invalid")
    return token


def _retry_issue_oa_token(ca_file: Path, context: Mapping[str, Any]) -> str:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        with suppress(S144ProtectedAcceptanceError):
            return _issue_oa_token(ca_file, context)
        time.sleep(0.5)
    raise S144ProtectedAcceptanceError("OA Transit signing did not recover")


def _introspect(ca_file: Path, control_token: str, target_token: str) -> dict[str, Any]:
    return _post_json(
        "oa.nex-staging.test",
        "/api/v1/auth/introspect",
        ca_file=ca_file,
        headers={"Authorization": f"Bearer {control_token}"},
        payload={"token": target_token, "audience": "nex-oa"},
        expected_status=200,
    )


def _require_ready(ca_file: Path) -> None:
    payload = _https_json("oa.nex-staging.test", "/ready", ca_file=ca_file)
    if payload.get("readiness_status") != "READY":
        raise S144ProtectedAcceptanceError("OA staging readiness failed")


def _wait_for_oa_ready(ca_file: Path) -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        with suppress(OSError, S144ProtectedAcceptanceError):
            _require_ready(ca_file)
            return
        time.sleep(0.5)
    raise S144ProtectedAcceptanceError("OA did not recover after restart")


def _https_json(host: str, path: str, *, ca_file: Path) -> dict[str, Any]:
    status, payload = _request_json(host, path, method="GET", ca_file=ca_file)
    if status != 200:
        raise S144ProtectedAcceptanceError(f"HTTPS request failed: {host} {status}")
    return payload


def _post_json(
    host: str,
    path: str,
    *,
    ca_file: Path,
    payload: Mapping[str, Any],
    expected_status: int,
    headers: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    status, response = _request_json(
        host,
        path,
        method="POST",
        ca_file=ca_file,
        headers=headers,
        payload=payload,
    )
    if status != expected_status:
        raise S144ProtectedAcceptanceError(
            f"HTTPS request failed: {host} {path} status={status}"
        )
    return response


def _request_json(
    host: str,
    path: str,
    *,
    method: str,
    ca_file: Path,
    headers: Mapping[str, str] | None = None,
    payload: Mapping[str, Any] | None = None,
    body: bytes | None = None,
) -> tuple[int, dict[str, Any]]:
    context = ssl.create_default_context(cafile=str(ca_file))
    connection = s143._ResolvedHttpsConnection(
        host,
        8443,
        connect_host="127.0.0.1",
        context=context,
        timeout=10,
    )
    request_headers = {"Accept": "application/json", **dict(headers or {})}
    request_body = body
    if payload is not None:
        request_headers.setdefault("Content-Type", "application/json")
        request_body = json.dumps(dict(payload), separators=(",", ":")).encode()
    try:
        connection.request(method, path, body=request_body, headers=request_headers)
        response = connection.getresponse()
        raw = response.read(2_097_153)
    finally:
        connection.close()
    if len(raw) > 2_097_152:
        raise S144ProtectedAcceptanceError("HTTPS response is too large")
    try:
        decoded = json.loads(raw) if raw else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise S144ProtectedAcceptanceError(
            f"HTTPS response is invalid: status={response.status}"
        ) from None
    if not isinstance(decoded, dict):
        raise S144ProtectedAcceptanceError(
            f"HTTPS response is invalid: status={response.status}"
        )
    return response.status, decoded


def _jwt_claims(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise S144ProtectedAcceptanceError("OIDC ID token shape is invalid")
    try:
        raw = base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4))
        claims = json.loads(raw)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        raise S144ProtectedAcceptanceError("OIDC ID token claims are invalid") from None
    if not isinstance(claims, dict) or not isinstance(claims.get("sub"), str):
        raise S144ProtectedAcceptanceError("OIDC ID token subject is invalid")
    return claims


def _jwt_key_id(token: str) -> str:
    parts = token.split(".")
    if len(parts) != 3:
        raise S144ProtectedAcceptanceError("OIDC ID token shape is invalid")
    try:
        raw = base64.urlsafe_b64decode(parts[0] + "=" * (-len(parts[0]) % 4))
        header = json.loads(raw)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        raise S144ProtectedAcceptanceError("OIDC ID token header is invalid") from None
    key_id = header.get("kid") if isinstance(header, Mapping) else None
    if not isinstance(key_id, str) or not key_id:
        raise S144ProtectedAcceptanceError("OIDC ID token key id is invalid")
    return key_id


def _federated_session_issued(response: Mapping[str, Any]) -> bool:
    session = response.get("session")
    session_id = session.get("session_id") if isinstance(session, Mapping) else None
    return isinstance(session_id, str) and bool(session_id)


def _require_acceptance_signals(result: Mapping[str, Any]) -> None:
    transit = result.get("transit")
    federation = result.get("federation")
    required = {
        "transit.old_token_active_before_revoke": (
            transit.get("old_token_active_before_revoke")
            if isinstance(transit, Mapping)
            else False
        ),
        "transit.old_token_inactive_after_revoke": (
            transit.get("old_token_inactive_after_revoke")
            if isinstance(transit, Mapping)
            else False
        ),
        "transit.restart_token_active": (
            transit.get("restart_token_active")
            if isinstance(transit, Mapping)
            else False
        ),
        "transit.outage_failed_closed": (
            transit.get("outage_failed_closed")
            if isinstance(transit, Mapping)
            else False
        ),
        "transit.recovery_succeeded": (
            transit.get("recovery_succeeded")
            if isinstance(transit, Mapping)
            else False
        ),
        "federation.discovery_valid": (
            federation.get("discovery_valid")
            if isinstance(federation, Mapping)
            else False
        ),
        "federation.exact_subject_link_resolved": (
            federation.get("exact_subject_link_resolved")
            if isinstance(federation, Mapping)
            else False
        ),
        "federation.oa_session_issued": (
            federation.get("oa_session_issued")
            if isinstance(federation, Mapping)
            else False
        ),
        "federation.metadata_key_rollover_verified": (
            federation.get("metadata_key_rollover_verified")
            if isinstance(federation, Mapping)
            else False
        ),
        "federation.metadata_jwks_overlap_verified": (
            federation.get("metadata_jwks_overlap_verified")
            if isinstance(federation, Mapping)
            else False
        ),
    }
    failed = sorted(name for name, value in required.items() if value is not True)
    if failed:
        raise S144ProtectedAcceptanceError(
            "S144 protected acceptance required signal failed: " + ",".join(failed)
        )


def _jwk_ids(document: Mapping[str, Any]) -> frozenset[str]:
    keys = document.get("keys")
    if not isinstance(keys, list):
        raise S144ProtectedAcceptanceError("OIDC JWKS is invalid")
    result = frozenset(
        str(item.get("kid"))
        for item in keys
        if isinstance(item, Mapping) and isinstance(item.get("kid"), str)
    )
    if not result:
        raise S144ProtectedAcceptanceError("OIDC JWKS has no key ids")
    return result


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _compose(
    environ: Mapping[str, str],
    *,
    root: Path,
    arguments: Sequence[str],
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        (
            "docker",
            "compose",
            "-f",
            str(BASE_COMPOSE),
            "-f",
            str(OVERRIDE_COMPOSE),
            *arguments,
        ),
        cwd=root,
        env=dict(environ),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=300,
    )
    if check and completed.returncode != 0:
        raise S144ProtectedAcceptanceError(
            f"Docker Compose command failed: {arguments[0]}"
        )
    return completed


def _cleanup_database(
    database_url: str, context: Mapping[str, Any], *, run_id: str
) -> None:
    engine = getattr(context.get("runtime"), "api_engine", None)
    if engine is not None:
        engine.dispose()
    key_ids = [str(context[name]) for name in ("key_v1", "key_v2")]
    with psycopg.connect(psycopg_database_url(database_url), autocommit=True) as connection:
        with connection.cursor() as cursor:
            if context.get("revocation_id"):
                cursor.execute(
                    "DELETE FROM oa_token_revocations WHERE revocation_id = %s",
                    (context["revocation_id"],),
                )
            cursor.execute(
                "DELETE FROM oa_auth_events WHERE request_id LIKE %s", (f"{run_id}%",)
            )
            cursor.execute(
                "DELETE FROM service_operational_events WHERE request_id LIKE %s",
                (f"{run_id}%",),
            )
            cursor.execute(
                "DELETE FROM oa_user_sessions WHERE tenant_id = %s",
                (context["tenant_id"],),
            )
            cursor.execute(
                "DELETE FROM oa_fed_identities WHERE provider_id = %s",
                (context["provider_id"],),
            )
            cursor.execute(
                "DELETE FROM oa_fed_providers WHERE provider_id = %s",
                (context["provider_id"],),
            )
            cursor.execute(
                "DELETE FROM oa_service_creds WHERE principal_id = %s",
                (context["principal_id"],),
            )
            cursor.execute(
                "DELETE FROM oa_service_principals WHERE principal_id = %s",
                (context["principal_id"],),
            )
            cursor.execute(
                "DELETE FROM oa_signing_keys WHERE key_id = ANY(%s)", (key_ids,)
            )
            cursor.execute(
                "DELETE FROM oa_tenant_memberships WHERE tenant_id = %s",
                (context["tenant_id"],),
            )
            cursor.execute(
                "DELETE FROM oa_subjects WHERE tenant_id = %s", (context["tenant_id"],)
            )
            cursor.execute(
                "DELETE FROM oa_tenants WHERE tenant_id = %s", (context["tenant_id"],)
            )


def _dispose_runtime(runtime: Any) -> None:
    for engine_name in ("api_engine", "worker_engine"):
        engine = getattr(runtime, engine_name, None)
        if engine is not None:
            engine.dispose()


def _assert_value_free(evidence: Mapping[str, Any], values: Mapping[str, str]) -> None:
    serialized = json.dumps(evidence, sort_keys=True)
    forbidden = [value for value in values.values() if isinstance(value, str) and len(value) >= 8]
    if any(value in serialized for value in forbidden):
        raise S144ProtectedAcceptanceError("raw protected value leaked into evidence")


def _protected_environment_values(environ: Mapping[str, str]) -> dict[str, str]:
    markers = ("PASSWORD", "SECRET", "TOKEN", "API_KEY", "DATABASE_URL")
    return {
        name: value
        for name, value in environ.items()
        if any(marker in name.upper() for marker in markers)
    }


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") == "SKIPPED":
        return "s144_protected_acceptance=skipped"
    if result.get("status") != "PASS":
        return "s144_protected_acceptance=fail"
    transit = result["transit"]
    federation = result["federation"]
    return (
        "s144_protected_acceptance=pass "
        f"transit_versions={len(transit['versions_verified'])} "
        f"oidc_jwks={federation['oidc_jwks_count']} "
        "postgres=actual restart=pass outage=fail-closed next=1442"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env.local")
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    args = parser.parse_args(argv)
    load_env_file(args.env_file)
    result = run_s144_protected_acceptance(
        execute=args.execute,
        report_path=args.report,
    )
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
