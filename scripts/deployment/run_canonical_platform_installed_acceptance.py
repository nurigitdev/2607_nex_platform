#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import http.client
import json
import os
import re
import secrets
import socket
import ssl
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import psycopg
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[2]
for relative in (
    "services/_shared",
    "services/nex-oa",
    "services/nex-ag",
    "services/nex-ae-api",
    "services/nex-cx",
    "services/nex-mo",
    "services/nex-wc",
    "services/nex-eos",
    "services/nex-wa",
):
    path = ROOT / relative
    sys.path.insert(0, str(path))

from nex_oa.canonical_service_principal_provisioning import (
    canonical_service_principal_specs,
    provision_canonical_service_principals,
)
from nex_oa.openbao_transit_keys import (
    OpenBaoTransitKeyProvisioner,
    register_openbao_transit_key_version,
)
from nex_oa.production_token_profiles import PRODUCTION_TOKEN_ISSUER
from nex_oa.service_principal_repository import (
    SqlAlchemyOaServicePrincipalRepository,
)
from nex_oa.service_principal_service import OaServicePrincipalService
from nex_oa.signed_token_repository import SqlAlchemyOaSignedTokenRepository
from nex_oa.signing_key_policy import MINIMUM_PUBLICATION_LEAD_SECONDS
from nex_oa.signing_key_service import OaSigningKeyService
from nex_runtime.canonical_platform_trust import (
    CANONICAL_PLATFORM_OWNERS,
    CANONICAL_PLATFORM_SECRET_BINDINGS,
    CANONICAL_PLATFORM_TLS_HOSTS,
    configure_canonical_runtime_approles,
)
from nex_runtime.current_platform_installation import (
    admit_current_platform_installation,
)
from nex_runtime.demo_database import (
    demo_database_admission_public_projection,
    inspect_demo_database_targets,
    resolve_demo_database_targets,
)
from nex_runtime.demo_domain_activation import (
    DEMO_DOMAIN_PROCESSES,
    demo_domain_activation_projection,
)
from nex_runtime.demo_domain_installation import (
    DEMO_DOMAIN_WORKERS,
    admit_demo_domain_runtime_evidence,
)
from nex_runtime.deployment_environments import (
    CURRENT_ARTIFACT_REFERENCE_ENVIRONMENTS,
)
from nex_runtime.object_storage import ObjectStorageSettings, build_s3_client
from nex_runtime.object_storage_lifecycle import bootstrap_private_bucket
from nex_runtime.object_storage_provisioning import (
    OBJECT_STORAGE_OWNER_SPECS,
    ObjectStorageOwnerCredential,
    provision_object_storage_environment,
)
from nex_runtime.rustfs_iam import RustfsAdminClient
from nex_runtime.s143_staging import (
    OpenBaoAdminClient,
    configure_openbao_staging,
    initialize_openbao,
    prepare_staging_runtime_directory,
    refresh_openbao_approle_credentials,
)
from nex_runtime.s144_staging import (
    TRANSIT_KEY_NAME,
    configure_openbao_s144_trust,
    refresh_openbao_s144_transit_credentials,
)
from nex_runtime.startup_service_token_bootstrap import (
    STARTUP_SERVICE_TOKEN_TTL_SECONDS,
)

EXECUTION_ENV = "NEX_CANONICAL_PLATFORM_INSTALLED_ACCEPTANCE"
LEGACY_EXECUTION_ENV = "NEX_P8_DEMO_S10_LIVE"
CALIBRATION_ENV = "NEX_CANONICAL_PLATFORM_SEMANTIC_CALIBRATION_POLICIES_JSON"
LEGACY_CALIBRATION_ENV = "NEX_P8_DEMO_SEMANTIC_CALIBRATION_POLICIES_JSON"
SCHEMA_VERSION = "canonical_platform_installed_acceptance.v1"
DEFAULT_IMAGE_REPORT = (
    ROOT / "reports/deployment/canonical-platform-oci-image-build.json"
)
DEFAULT_AE_IMAGE_REPORT = (
    ROOT / "reports/deployment/canonical-platform-ae-runtime-image.json"
)
DEFAULT_REPORT = (
    ROOT / "reports/deployment/canonical-platform-installed-acceptance.json"
)
COMPOSE_FILES = (
    ROOT / "deployment/compose/s143-staging.compose.yaml",
    ROOT / "deployment/compose/s146-object-storage.override.yaml",
    ROOT / "deployment/compose/p9-wa.override.yaml",
    ROOT / "deployment/compose/canonical-platform.override.yaml",
)
PROJECT_NAME = "nex-platform-canonical"
DOMAIN_SERVICES = (
    "nex-oa",
    "nex-ae-api",
    "nex-wc",
    "nex-eos",
    *DEMO_DOMAIN_PROCESSES,
)
# Historical P8 acceptance imports this inventory name through the compatibility
# wrapper. The active canonical runner uses the canonical inventory above.
DEMO_SECRET_BINDINGS = CANONICAL_PLATFORM_SECRET_BINDINGS


class CanonicalPlatformInstalledAcceptanceError(RuntimeError):
    pass


def run_canonical_platform_installed_acceptance(
    environ: Mapping[str, str] | None = None,
    *,
    execute: bool = False,
    root: Path = ROOT,
    image_report_path: Path = DEFAULT_IMAGE_REPORT,
    ae_image_report_path: Path = DEFAULT_AE_IMAGE_REPORT,
    protected_runner: Callable[..., Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    source = _source_admission(root)
    if not execute or not _execution_enabled(env):
        return {**source, "status": "SOURCE_ADMITTED", "executed": False}
    try:
        runner = protected_runner or execute_canonical_platform_acceptance
        protected = runner(
            env,
            root=root,
            image_report_path=image_report_path,
            ae_image_report_path=ae_image_report_path,
        )
        return {**source, **dict(protected), "executed": True}
    except (
        OSError,
        KeyError,
        TypeError,
        ValueError,
        RuntimeError,
        psycopg.Error,
        subprocess.SubprocessError,
    ) as exc:
        return {
            **source,
            "status": "FAIL",
            "executed": True,
            "issues": [str(exc)],
            "secret_included": False,
            "token_value_included": False,
        }


def _source_admission(root: Path) -> dict[str, Any]:
    compose = admit_current_platform_installation(root)
    activation = demo_domain_activation_projection()
    if activation["process_count"] != 3 or activation["mock_token_fallback_allowed"]:
        raise CanonicalPlatformInstalledAcceptanceError(
            "Demo domain activation inventory drift"
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "slice": "GB2-CA00-S18B",
        "source_admitted": True,
        "compose_source": compose,
        "domain_activation": activation,
        "new_business_behavior_added": False,
        "secret_included": False,
        "token_value_included": False,
    }


def execute_canonical_platform_acceptance(
    env: Mapping[str, str],
    *,
    root: Path,
    image_report_path: Path,
    ae_image_report_path: Path,
    additional_services: Sequence[str] = (),
    live_hook: Callable[..., Mapping[str, Any]] | None = None,
    restart_services: Sequence[str] = DEMO_DOMAIN_PROCESSES,
    post_restart_hook: Callable[..., Mapping[str, Any]] | None = None,
    worker_inventory: Mapping[str, tuple[str, str, str]] = DEMO_DOMAIN_WORKERS,
) -> dict[str, Any]:
    admitted_restart_services = tuple(dict.fromkeys(restart_services))
    if not admitted_restart_services:
        raise CanonicalPlatformInstalledAcceptanceError(
            "installed acceptance restart services are required"
        )
    image_report = _load_json(image_report_path)
    ae_image_report = _load_json(ae_image_report_path)
    image_environment = _image_environment_from_installed_runtime_reports(
        image_report, ae_image_report
    )
    targets = resolve_demo_database_targets(env)
    inspections = inspect_demo_database_targets(
        targets,
        database_root=root / "database",
        connect=psycopg.connect,
    )
    database_admission = demo_database_admission_public_projection(inspections)
    if database_admission["migration_current_count"] != len(targets):
        raise CanonicalPlatformInstalledAcceptanceError(
            "all seven Demo dev databases must be migration-current"
        )
    urls = {item.target.service_id: item.database_url for item in targets}
    queue_counts = _pending_domain_counts(urls)
    if any(queue_counts.values()):
        raise CanonicalPlatformInstalledAcceptanceError(
            "Demo domain consumers require an empty pre-activation queue"
        )

    client_secrets = {
        spec.owner: secrets.token_urlsafe(36)
        for spec in canonical_service_principal_specs()
    }
    root_access = f"P8S10ROOT{secrets.token_hex(8)}"
    root_secret = secrets.token_urlsafe(36)
    sse_master_key = base64.b64encode(secrets.token_bytes(32)).decode("ascii")
    object_credentials = {
        "NEX_AE_OBJECT_STORAGE_ACCESS_KEY": f"P8S10AE{secrets.token_hex(8)}",
        "NEX_AE_OBJECT_STORAGE_SECRET_KEY": secrets.token_urlsafe(36),
        "NEX_CX_OBJECT_STORAGE_ACCESS_KEY": f"P8S10CX{secrets.token_hex(8)}",
        "NEX_CX_OBJECT_STORAGE_SECRET_KEY": secrets.token_urlsafe(36),
    }
    sensitive = {
        *client_secrets.values(),
        root_access,
        root_secret,
        sse_master_key,
        *object_credentials.values(),
    }
    runtime_env: dict[str, str] | None = None
    provisioned: Any = None
    key_id: str | None = None
    created_principal_ids: tuple[str, ...] = ()
    oa_engine: Any = None
    with TemporaryDirectory(prefix="nex-canonical-platform-s10-") as temporary:
        runtime_dir = Path(temporary) / "runtime"
        prepare_staging_runtime_directory(runtime_dir, owners=CANONICAL_PLATFORM_OWNERS)
        runtime_env = {
            **env,
            **image_environment,
            "NEX_S143_RUNTIME_DIR": str(runtime_dir),
            "NEX_S143_SECRET_VERSION": "v1",
            "NEX_CANONICAL_PLATFORM_SECRET_VERSION": "v1",
            CALIBRATION_ENV: str(
                env.get(CALIBRATION_ENV) or env.get(LEGACY_CALIBRATION_ENV) or "[]"
            ),
            "NEX_CANONICAL_PLATFORM_SECRET_GENERATION": ("secret:canonical-platform.1"),
            "NEX_CANONICAL_PLATFORM_TLS_GENERATION": "tls:canonical-platform.1",
        }
        _compose(
            runtime_env,
            root=root,
            arguments=("down", "--volumes", "--remove-orphans"),
            check=False,
        )
        try:
            _compose(runtime_env, root=root, arguments=("up", "-d", "openbao"))
            _wait_for_tls(
                "127.0.0.1",
                8200,
                server_hostname="localhost",
                ca_file=runtime_dir / "tls/openbao-ca.crt",
            )
            admin = OpenBaoAdminClient(
                "https://127.0.0.1:8200",
                ca_certificate_file=runtime_dir / "tls/openbao-ca.crt",
            )
            bootstrap = initialize_openbao(admin, runtime_dir)
            generation = f"v{int(time.time())}"
            secret_values = _secret_values(
                env,
                urls=urls,
                object_credentials=object_credentials,
            )
            configure_openbao_staging(
                admin,
                root_token=bootstrap.root_token,
                root=root,
                runtime_dir=runtime_dir,
                secret_values=secret_values,
                bindings=CANONICAL_PLATFORM_SECRET_BINDINGS,
                owners=CANONICAL_PLATFORM_OWNERS,
                subject_alt_names=CANONICAL_PLATFORM_TLS_HOSTS,
            )
            approles = configure_canonical_runtime_approles(
                admin,
                root_token=bootstrap.root_token,
                owners=CANONICAL_PLATFORM_OWNERS,
            )
            refresh_openbao_approle_credentials(
                admin,
                root_token=bootstrap.root_token,
                runtime_dir=runtime_dir,
                owners=CANONICAL_PLATFORM_OWNERS,
            )
            configure_openbao_s144_trust(admin, root_token=bootstrap.root_token)
            refresh_openbao_s144_transit_credentials(
                admin,
                root_token=bootstrap.root_token,
                runtime_dir=runtime_dir,
            )
            _write_secret(
                runtime_dir / "credentials/rustfs-root.access-key", root_access
            )
            _write_secret(
                runtime_dir / "credentials/rustfs-root.secret-key", root_secret
            )
            _write_secret(
                runtime_dir / "credentials/rustfs-sse-s3.master-key", sse_master_key
            )

            oa_engine = create_engine(urls["nex-oa"], poolclass=NullPool)
            provisioned, key_id, created_principal_ids = _provision_oa_trust(
                oa_engine,
                admin=admin,
                root_token=bootstrap.root_token,
                generation=generation,
                client_secrets=client_secrets,
            )
            credential_values = provisioned.openbao_values_by_owner()
            for owner, values in credential_values.items():
                for target, value in values.items():
                    admin.request(
                        "POST",
                        f"/v1/kv/data/nex-platform/staging/{owner}/{target}",
                        token=bootstrap.root_token,
                        payload={"data": {"value": value}},
                    )

            installed_services = tuple(
                dict.fromkeys((*DOMAIN_SERVICES, *additional_services))
            )
            _compose(
                runtime_env,
                root=root,
                arguments=(
                    "up",
                    "-d",
                    "--wait",
                    "--wait-timeout",
                    "180",
                    *installed_services,
                ),
            )
            _wait_for_tls(
                "127.0.0.1",
                8443,
                server_hostname="oa.nex-staging.test",
                ca_file=runtime_dir / "tls/platform-ca.crt",
            )
            object_storage = _provision_demo_object_storage(
                runtime_dir=runtime_dir,
                root_access=root_access,
                root_secret=root_secret,
                object_credentials=object_credentials,
            )
            readiness = _service_readiness(runtime_dir)
            initial_heartbeats = _wait_for_heartbeats(
                urls, worker_inventory=worker_inventory
            )
            materials = {item.owner: item for item in provisioned.materials}
            token_runtimes = _signed_token_runtime_acceptance(
                runtime_dir, materials=materials
            )
            extended_acceptance = None
            if live_hook is not None:
                extended_acceptance = dict(
                    live_hook(
                        runtime_env=runtime_env,
                        root=root,
                        runtime_dir=runtime_dir,
                        urls=urls,
                        materials=materials,
                        root_access=root_access,
                        root_secret=root_secret,
                        object_credentials=object_credentials,
                    )
                )
                if extended_acceptance.get("status") != "PASS":
                    raise CanonicalPlatformInstalledAcceptanceError(
                        "extended installed acceptance did not pass"
                    )

            _compose(
                runtime_env,
                root=root,
                arguments=("restart", *admitted_restart_services),
            )
            restarted_readiness = _wait_for_service_readiness(runtime_dir)
            restarted_heartbeats = _wait_for_heartbeats(
                urls,
                previous=initial_heartbeats,
                worker_inventory=worker_inventory,
            )
            post_restart_acceptance = None
            if post_restart_hook is not None:
                post_restart_acceptance = dict(
                    post_restart_hook(
                        runtime_env=runtime_env,
                        root=root,
                        runtime_dir=runtime_dir,
                        urls=urls,
                        materials=materials,
                        root_access=root_access,
                        root_secret=root_secret,
                        object_credentials=object_credentials,
                        live_acceptance=extended_acceptance,
                    )
                )
                if post_restart_acceptance.get("status") != "PASS":
                    raise CanonicalPlatformInstalledAcceptanceError(
                        "post-restart installed acceptance did not pass"
                    )
            bootstrap_counts = _bootstrap_log_counts(runtime_env, root=root)
            domain = admit_demo_domain_runtime_evidence(
                initial_heartbeats=initial_heartbeats,
                restarted_heartbeats=restarted_heartbeats,
                token_runtimes=token_runtimes,
                bootstrap_log_counts=bootstrap_counts,
                worker_inventory=worker_inventory,
            )
            post_counts = _pending_domain_counts(urls)
            if post_counts != queue_counts:
                raise CanonicalPlatformInstalledAcceptanceError(
                    "idle consumer activation changed durable domain queues"
                )
            result = {
                "status": "PASS",
                "actual_postgres": True,
                "actual_openbao": True,
                "actual_compose": True,
                "actual_rustfs": True,
                "object_storage_bootstrap": object_storage,
                "database_admission": database_admission,
                "pre_activation_queue_counts": queue_counts,
                "post_restart_queue_counts": post_counts,
                "approle_profile": approles,
                "service_principal_provisioning": provisioned.evidence(),
                "readiness": readiness,
                "restarted_readiness": restarted_readiness,
                "domain_acceptance": domain,
                "release_set_digest": image_report["release_manifest"][
                    "release_set_digest"
                ],
                "ae_runtime_image_id": ae_image_report["image"]["image_id"],
                "startup_token_ttl_seconds": STARTUP_SERVICE_TOKEN_TTL_SECONDS,
                "provider_contacted": False,
                "database_mutation_added": False,
                "secret_included": False,
                "token_value_included": False,
            }
            if extended_acceptance is not None:
                result["extended_acceptance"] = extended_acceptance
            if post_restart_acceptance is not None:
                result["post_restart_acceptance"] = post_restart_acceptance
            _assert_redacted(result, sensitive)
            return result
        finally:
            if runtime_env is not None:
                _compose(
                    runtime_env,
                    root=root,
                    arguments=("down", "--volumes", "--remove-orphans"),
                    check=False,
                )
            if oa_engine is not None:
                _cleanup_oa_acceptance_rows(
                    oa_engine,
                    provisioned=provisioned,
                    key_id=key_id,
                    created_principal_ids=created_principal_ids,
                )
                oa_engine.dispose()


def _secret_values(
    env: Mapping[str, str],
    *,
    urls: Mapping[str, str],
    object_credentials: Mapping[str, str],
) -> dict[str, str]:
    database_by_target = {
        "NEX_OA_DATABASE_URL": urls["nex-oa"],
        "NEX_AG_DATABASE_URL": urls["nex-ag"],
        "NEX_AE_DATABASE_URL": urls["nex-ae-api"],
        "NEX_CX_DATABASE_URL": urls["nex-cx"],
        "NEX_MO_DATABASE_URL": urls["nex-mo"],
        "NEX_WC_DATABASE_URL": urls["nex-wc"],
        "NEX_EOS_DATABASE_URL": urls["nex-eos"],
    }
    values = {
        target: _container_database_url(value)
        for target, value in database_by_target.items()
    }
    values.update(object_credentials)
    provider_names = (
        "NEX_MO_REMOTE_EMBEDDING_API_KEY",
        "NEX_MO_REMOTE_RERANKER_API_KEY",
        "NEX_MO_VLLM_API_KEY",
    )
    for name in provider_names:
        values[name] = str(env.get(name) or f"unused-{name.lower()}-p8-s10")
    for binding in CANONICAL_PLATFORM_SECRET_BINDINGS:
        values.setdefault(binding.target_environment_name, secrets.token_urlsafe(32))
    expected = {
        binding.target_environment_name
        for binding in CANONICAL_PLATFORM_SECRET_BINDINGS
    }
    if set(values) != expected:
        raise CanonicalPlatformInstalledAcceptanceError(
            "Demo secret value coverage drift"
        )
    return values


def _provision_oa_trust(
    engine: Any,
    *,
    admin: OpenBaoAdminClient,
    root_token: str,
    generation: str,
    client_secrets: Mapping[str, str],
) -> tuple[Any, str, tuple[str, ...]]:
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    principals = OaServicePrincipalService(
        SqlAlchemyOaServicePrincipalRepository(factory)
    )
    specs = canonical_service_principal_specs()
    existing_principal_ids = _existing_demo_principal_ids(engine, specs=specs)
    created_principal_ids = tuple(
        spec.principal_id
        for spec in specs
        if spec.principal_id not in existing_principal_ids
    )
    credential_ids = tuple(f"{spec.principal_id}-{generation}" for spec in specs)
    keys = OaSigningKeyService(
        repository=SqlAlchemyOaSignedTokenRepository(factory),
        deployment_profile="production",
    )
    now = int(time.time())
    active = [
        item
        for item in keys.list_keys()["items"]
        if item["state"] == "ACTIVE"
        and int(item["activate_at"]) <= now < int(item["sign_until"])
    ]
    if active:
        raise CanonicalPlatformInstalledAcceptanceError(
            "OA Demo dev database already has an active signing key"
        )
    key_id = f"canonical-platform-s10-{secrets.token_hex(8)}"
    try:
        provisioned = provision_canonical_service_principals(
            principals,
            generation=generation,
            client_secrets=client_secrets,
            now_epoch=now,
        )
        register_openbao_transit_key_version(
            OpenBaoTransitKeyProvisioner(admin, root_token),
            keys,
            key_name=TRANSIT_KEY_NAME,
            key_version=1,
            key_id=key_id,
            issuer=PRODUCTION_TOKEN_ISSUER,
            **_signing_key_window(now),
        )
        keys.set_key_state(
            key_id,
            target_state="ACTIVE",
            expected_revision=1,
            now_epoch=now,
        )
    except Exception:
        _delete_oa_acceptance_rows(
            engine,
            credential_ids=credential_ids,
            principal_ids=created_principal_ids,
            key_id=key_id,
        )
        raise
    return provisioned, key_id, created_principal_ids


def _existing_demo_principal_ids(engine: Any, *, specs: Sequence[Any]) -> set[str]:
    existing = set()
    with engine.connect() as connection:
        for spec in specs:
            present = connection.execute(
                text(
                    "SELECT principal_id FROM oa_service_principals "
                    "WHERE principal_id=:principal_id"
                ),
                {"principal_id": spec.principal_id},
            ).scalar_one_or_none()
            if present is not None:
                existing.add(str(present))
    return existing


def _signing_key_window(now_epoch: int) -> dict[str, int]:
    return {
        "published_at": now_epoch - MINIMUM_PUBLICATION_LEAD_SECONDS,
        "activate_at": now_epoch,
        "sign_until": now_epoch + 172_800,
        "verify_until": now_epoch + 259_200,
    }


def _signed_token_runtime_acceptance(
    runtime_dir: Path,
    *,
    materials: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    ca_file = runtime_dir / "tls/platform-ca.crt"
    calls = {
        "nex-oa": ("nex-ae-api", "oa.nex-staging.test"),
        "nex-ae-api": ("nex-wc", "ae-api.nex-staging.test"),
        "nex-wc": ("nex-ae-api", "wc.nex-staging.test"),
        "nex-eos": ("nex-ae-api", "eos.nex-staging.test"),
    }
    results = {}
    for audience, (owner, host) in calls.items():
        material = materials[owner]
        status, payload = _https_json(
            "oa.nex-staging.test",
            "/api/v1/auth/service-token",
            ca_file=ca_file,
            method="POST",
            body={
                "grant_type": "client_credentials",
                "credential_id": material.credential_id,
                "client_secret": material.client_secret,
                "audience": audience,
                "scope": "service:call",
            },
        )
        token = payload.get("access_token")
        if status != 200 or not isinstance(token, str):
            raise CanonicalPlatformInstalledAcceptanceError(
                "OA service token exchange failed"
            )
        runtime_status, runtime = _https_json(
            host,
            "/internal/v1/auth/service-token-runtime",
            ca_file=ca_file,
            headers={"Authorization": f"Bearer {token}"},
        )
        if runtime_status != 200:
            raise CanonicalPlatformInstalledAcceptanceError(
                "signed service-token runtime admission failed: "
                f"{audience}: status={runtime_status} "
                f"error={payload.get('error_code', 'unknown')}"
            )
        results[audience] = runtime
    return results


def _service_readiness(runtime_dir: Path) -> dict[str, str]:
    result = {}
    for service_id, host in (
        ("nex-oa", "oa.nex-staging.test"),
        ("nex-ae-api", "ae-api.nex-staging.test"),
        ("nex-wc", "wc.nex-staging.test"),
        ("nex-eos", "eos.nex-staging.test"),
    ):
        status, payload = _https_json(
            host,
            "/ready",
            ca_file=runtime_dir / "tls/platform-ca.crt",
        )
        if status != 200 or payload.get("readiness_status") != "READY":
            raise CanonicalPlatformInstalledAcceptanceError(
                f"Demo service is not ready: {service_id}"
            )
        result[service_id] = "READY"
    return result


def _wait_for_service_readiness(
    runtime_dir: Path, *, timeout_seconds: float = 90.0
) -> dict[str, str]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            return _service_readiness(runtime_dir)
        except (
            OSError,
            CanonicalPlatformInstalledAcceptanceError,
            http.client.HTTPException,
            ssl.SSLError,
        ):
            time.sleep(0.5)
    raise CanonicalPlatformInstalledAcceptanceError(
        "Demo services did not become ready after restart"
    )


def _pending_domain_counts(urls: Mapping[str, str]) -> dict[str, int]:
    queries = {
        "ae_runtime_jobs": (
            "nex-ae-api",
            "SELECT count(*) FROM ae_runtime_job WHERE state IN ('QUEUED','RUNNING')",
        ),
        "wc_delivery_rows": (
            "nex-wc",
            (
                "SELECT (SELECT count(*) FROM wc_event_outbox WHERE delivery_state "
                "IN ('PENDING','ENQUEUED')) + (SELECT count(*) FROM "
                "wc_approval_outbox WHERE delivery_state IN ('PENDING','ENQUEUED'))"
            ),
        ),
        "eos_outbox_rows": (
            "nex-eos",
            "SELECT count(*) FROM eos_outbox WHERE delivery_state = 'PENDING'",
        ),
    }
    result = {}
    for name, (service, query) in queries.items():
        engine = create_engine(urls[service], poolclass=NullPool)
        try:
            with engine.connect() as connection:
                result[name] = int(connection.execute(text(query)).scalar_one())
        finally:
            engine.dispose()
    return result


def _wait_for_heartbeats(
    urls: Mapping[str, str],
    *,
    previous: Mapping[str, Mapping[str, Any]] | None = None,
    timeout_seconds: float = 60.0,
    worker_inventory: Mapping[str, tuple[str, str, str]] = DEMO_DOMAIN_WORKERS,
) -> dict[str, dict[str, Any]]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        observed = _heartbeats(urls, worker_inventory=worker_inventory)
        if (
            len(observed) == len(worker_inventory)
            and all(item.get("status") == "IDLE" for item in observed.values())
            and (
                previous is None
                or all(
                    observed[process]["observed_at"] != previous[process]["observed_at"]
                    for process in worker_inventory
                )
            )
        ):
            return observed
        time.sleep(0.5)
    raise CanonicalPlatformInstalledAcceptanceError(
        "Demo domain worker heartbeat timed out"
    )


def _heartbeats(
    urls: Mapping[str, str],
    *,
    worker_inventory: Mapping[str, tuple[str, str, str]] = DEMO_DOMAIN_WORKERS,
) -> dict[str, dict[str, Any]]:
    result = {}
    for process_id, (service_id, worker_id, worker_type) in worker_inventory.items():
        engine = create_engine(urls[service_id], poolclass=NullPool)
        try:
            with engine.connect() as connection:
                row = (
                    connection.execute(
                        text(
                            "SELECT service_id, worker_id, worker_type, status, last_seen_at "
                            "FROM service_worker_heartbeats WHERE service_id=:service "
                            "AND worker_id=:worker"
                        ),
                        {"service": service_id, "worker": worker_id},
                    )
                    .mappings()
                    .one_or_none()
                )
            if row is not None:
                result[process_id] = {
                    "service_id": str(row["service_id"]),
                    "worker_id": str(row["worker_id"]),
                    "worker_type": str(row["worker_type"]),
                    "status": str(row["status"]),
                    "observed_at": str(row["last_seen_at"]),
                }
        finally:
            engine.dispose()
    return result


def _bootstrap_log_counts(env: Mapping[str, str], *, root: Path) -> dict[str, int]:
    result = {}
    for process_id in DEMO_DOMAIN_PROCESSES:
        completed = _compose(
            env,
            root=root,
            arguments=("logs", "--no-color", process_id),
        )
        result[process_id] = completed.stdout.count(
            "production_container_bootstrap=pass"
        )
    return result


def _cleanup_oa_acceptance_rows(
    engine: Any,
    *,
    provisioned: Any,
    key_id: str | None,
    created_principal_ids: Sequence[str],
) -> None:
    if provisioned is None and key_id is None:
        return
    credential_ids = (
        tuple(item.credential_id for item in provisioned.materials)
        if provisioned is not None
        else ()
    )
    _delete_oa_acceptance_rows(
        engine,
        credential_ids=credential_ids,
        principal_ids=created_principal_ids,
        key_id=key_id,
    )


def _delete_oa_acceptance_rows(
    engine: Any,
    *,
    credential_ids: Sequence[str],
    principal_ids: Sequence[str],
    key_id: str | None,
) -> None:
    with engine.begin() as connection:
        if key_id is not None:
            connection.execute(
                text("DELETE FROM oa_signing_keys WHERE key_id=:key_id"),
                {"key_id": key_id},
            )
        for credential_id in credential_ids:
            connection.execute(
                text("DELETE FROM oa_service_creds WHERE credential_id=:id"),
                {"id": credential_id},
            )
        for principal_id in principal_ids:
            connection.execute(
                text(
                    "DELETE FROM oa_service_principals WHERE principal_id=:principal_id"
                ),
                {"principal_id": principal_id},
            )


def _container_database_url(value: str) -> str:
    parsed = make_url(value)
    if parsed.get_backend_name() != "postgresql":
        raise CanonicalPlatformInstalledAcceptanceError(
            "Demo database URL must use PostgreSQL"
        )
    return parsed.set(host="host.docker.internal").render_as_string(hide_password=False)


def _provision_demo_object_storage(
    *,
    runtime_dir: Path,
    root_access: str,
    root_secret: str,
    object_credentials: Mapping[str, str],
    client_builder: Callable[[ObjectStorageSettings], Any] = build_s3_client,
    bucket_bootstrap: Callable[..., Any] = bootstrap_private_bucket,
    iam_factory: Callable[..., Any] = RustfsAdminClient,
) -> dict[str, Any]:
    endpoint = "https://object.nex-staging.test:8443"
    ca_bundle = str(runtime_dir / "tls/platform-ca.crt")
    with _object_hostname_loopback():
        root_client = client_builder(
            ObjectStorageSettings(
                owner="bootstrap",
                endpoint_url=endpoint,
                bucket=OBJECT_STORAGE_OWNER_SPECS[0].bucket,
                access_key=root_access,
                secret_key=root_secret,
                ca_bundle=ca_bundle,
            )
        )
        iam = iam_factory(
            endpoint,
            access_key=root_access,
            secret_key=root_secret,
            ca_bundle=ca_bundle,
        )
        owner_clients = {}
        credentials = []
        for spec in OBJECT_STORAGE_OWNER_SPECS:
            prefix = "AE" if spec.owner == "nex-ae-api" else "CX"
            access_key = object_credentials[f"NEX_{prefix}_OBJECT_STORAGE_ACCESS_KEY"]
            secret_key = object_credentials[f"NEX_{prefix}_OBJECT_STORAGE_SECRET_KEY"]
            owner_clients[spec.owner] = client_builder(
                ObjectStorageSettings(
                    owner=spec.owner,
                    endpoint_url=endpoint,
                    bucket=spec.bucket,
                    access_key=access_key,
                    secret_key=secret_key,
                    ca_bundle=ca_bundle,
                )
            )
            credentials.append(
                ObjectStorageOwnerCredential(
                    owner=spec.owner,
                    access_key=access_key,
                    secret_key=secret_key,
                )
            )
        return provision_object_storage_environment(
            root_client,
            iam,
            owner_clients=owner_clients,
            credentials=tuple(credentials),
            bucket_bootstrap=bucket_bootstrap,
        )


@contextmanager
def _object_hostname_loopback():
    original = socket.getaddrinfo
    original_no_proxy = os.environ.get("NO_PROXY")
    original_no_proxy_lower = os.environ.get("no_proxy")
    bypass = ",".join(
        item for item in (original_no_proxy, "object.nex-staging.test") if item
    )
    os.environ["NO_PROXY"] = bypass
    os.environ["no_proxy"] = bypass

    def resolve(host: str, port: Any, *args: Any, **kwargs: Any):
        target = "127.0.0.1" if host == "object.nex-staging.test" else host
        return original(target, port, *args, **kwargs)

    socket.getaddrinfo = resolve
    try:
        yield
    finally:
        socket.getaddrinfo = original
        for name, value in (
            ("NO_PROXY", original_no_proxy),
            ("no_proxy", original_no_proxy_lower),
        ):
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _compose(
    env: Mapping[str, str],
    *,
    root: Path,
    arguments: Sequence[str],
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    command: list[str] = ["docker", "compose", "--project-name", PROJECT_NAME]
    for path in COMPOSE_FILES:
        command.extend(("-f", str(path)))
    command.extend(arguments)
    completed = subprocess.run(
        command,
        cwd=root,
        env=dict(env),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=360,
    )
    if check and completed.returncode != 0:
        lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
        detail = lines[-1][-500:] if lines else "no Docker output"
        raise CanonicalPlatformInstalledAcceptanceError(
            f"Demo Compose command failed: {arguments[0]}: {detail}"
        )
    return completed


def _https_json(
    server_hostname: str,
    path: str,
    *,
    ca_file: Path,
    method: str = "GET",
    headers: Mapping[str, str] | None = None,
    body: Mapping[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    context = ssl.create_default_context(cafile=str(ca_file))
    connection = _ResolvedHttpsConnection(
        server_hostname,
        8443,
        connect_host="127.0.0.1",
        context=context,
        timeout=15,
    )
    request_headers = {"Accept": "application/json", **dict(headers or {})}
    encoded = None
    if body is not None:
        encoded = json.dumps(dict(body), separators=(",", ":")).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    try:
        connection.request(method, path, body=encoded, headers=request_headers)
        response = connection.getresponse()
        raw = response.read(2_097_153)
    finally:
        connection.close()
    if len(raw) > 2_097_152:
        raise CanonicalPlatformInstalledAcceptanceError(
            "Demo HTTPS response is too large"
        )
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise CanonicalPlatformInstalledAcceptanceError(
            "Demo HTTPS response is invalid"
        ) from None
    if not isinstance(payload, dict):
        raise CanonicalPlatformInstalledAcceptanceError(
            "Demo HTTPS response is invalid"
        )
    return response.status, payload


class _ResolvedHttpsConnection(http.client.HTTPSConnection):
    def __init__(
        self, host: str, port: int, *, connect_host: str, **kwargs: Any
    ) -> None:
        super().__init__(host, port, **kwargs)
        self._connect_host = connect_host

    def connect(self) -> None:
        self.sock = self._create_connection(
            (self._connect_host, self.port), self.timeout, self.source_address
        )
        self.sock = self._context.wrap_socket(self.sock, server_hostname=self.host)


def _wait_for_tls(
    host: str,
    port: int,
    *,
    server_hostname: str,
    ca_file: Path,
    timeout_seconds: float = 60,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    context = ssl.create_default_context(cafile=str(ca_file))
    while time.monotonic() < deadline:
        try:
            import socket

            with (
                socket.create_connection((host, port), timeout=2) as connection,
                context.wrap_socket(connection, server_hostname=server_hostname),
            ):
                return
        except (OSError, ssl.SSLError):
            time.sleep(0.5)
    raise CanonicalPlatformInstalledAcceptanceError(
        "Demo TLS endpoint did not become ready"
    )


def _write_secret(path: Path, value: str) -> None:
    path.write_text(f"{value}\n", encoding="utf-8")
    os.chmod(path, 0o644)


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CanonicalPlatformInstalledAcceptanceError("Demo report must be an object")
    return value


def _execution_enabled(environ: Mapping[str, str]) -> bool:
    return environ.get(EXECUTION_ENV) == "1" or environ.get(LEGACY_EXECUTION_ENV) == "1"


def _image_environment_from_installed_runtime_reports(
    release_report: Mapping[str, Any],
    ae_runtime_report: Mapping[str, Any],
) -> dict[str, str]:
    artifacts = (release_report.get("image_build") or {}).get("artifacts")
    if release_report.get("status") != "PASS" or not isinstance(artifacts, list):
        raise CanonicalPlatformInstalledAcceptanceError(
            "canonical image release report is not passing"
        )
    records = {
        str(item.get("artifact_id")): item
        for item in artifacts
        if isinstance(item, Mapping)
    }
    expected = dict(CURRENT_ARTIFACT_REFERENCE_ENVIRONMENTS)
    if set(records) != set(expected):
        raise CanonicalPlatformInstalledAcceptanceError(
            "canonical image release artifact coverage drift"
        )
    environment: dict[str, str] = {}
    for artifact_id, environment_name in expected.items():
        item = records[artifact_id]
        local_tag = str(item.get("local_tag") or "")
        image_id = str(item.get("image_id") or "")
        if (
            re.fullmatch(r"[^@\s]+:[A-Za-z0-9_.-]+", local_tag) is None
            or re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None
            or item.get("manifest_digest") != image_id
        ):
            raise CanonicalPlatformInstalledAcceptanceError(
                f"canonical local image identity drift: {artifact_id}"
            )
        repository = local_tag.rsplit(":", 1)[0]
        environment[environment_name] = f"{repository}@{image_id}"

    ae_release = records["nex-ae-runtime"]
    if (
        ae_runtime_report.get("status") != "PASS"
        or ae_runtime_report.get("slice") != "GB2-CA00-S18A"
    ):
        raise CanonicalPlatformInstalledAcceptanceError(
            "canonical AE runtime report is not passing"
        )
    if ae_runtime_report.get("base_image") not in {
        ae_release.get("local_tag"),
        ae_release.get("image_reference"),
    }:
        raise CanonicalPlatformInstalledAcceptanceError(
            "canonical AE runtime base image drift"
        )
    image = ae_runtime_report.get("image")
    if not isinstance(image, Mapping):
        raise CanonicalPlatformInstalledAcceptanceError(
            "canonical AE runtime image evidence is unavailable"
        )
    image_id = str(image.get("image_id") or "")
    references = tuple(str(value) for value in image.get("repo_digests") or ())
    if (
        re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None
        or len(references) != 1
        or not references[0].endswith(f"@{image_id}")
    ):
        raise CanonicalPlatformInstalledAcceptanceError(
            "canonical AE runtime image identity is invalid"
        )
    environment["NEX_AE_RUNTIME_IMAGE"] = references[0]
    return environment


_execute_protected_acceptance = execute_canonical_platform_acceptance
P8DemoS10AcceptanceError = CanonicalPlatformInstalledAcceptanceError
run_p8_demo_s10_installed_domain_acceptance = (
    run_canonical_platform_installed_acceptance
)


def _assert_redacted(value: Mapping[str, Any], sensitive: set[str]) -> None:
    encoded = json.dumps(dict(value), sort_keys=True)
    if any(secret and secret in encoded for secret in sensitive):
        raise CanonicalPlatformInstalledAcceptanceError(
            "Demo S10 evidence contains protected material"
        )


def _write_report(path: Path, result: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(dict(result), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def summary_line(result: Mapping[str, Any]) -> str:
    domain = result.get("domain_acceptance") or {}
    return (
        "canonical_platform_installed_acceptance="
        f"{str(result.get('status', 'FAIL')).lower()} "
        f"postgres={str(bool(result.get('actual_postgres'))).lower()} "
        f"openbao={str(bool(result.get('actual_openbao'))).lower()} "
        f"consumers={domain.get('process_count', 0)} "
        f"signed={domain.get('signed_service_count', 0)}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--image-report", type=Path, default=DEFAULT_IMAGE_REPORT)
    parser.add_argument("--ae-image-report", type=Path, default=DEFAULT_AE_IMAGE_REPORT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_canonical_platform_installed_acceptance(
        os.environ,
        execute=args.execute,
        image_report_path=args.image_report,
        ae_image_report_path=args.ae_image_report,
    )
    _write_report(args.report, result)
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result["status"] in {"PASS", "SOURCE_ADMITTED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
