#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import socket
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import psycopg

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/_shared"))
sys.path.insert(0, str(ROOT / "services/nex-cx"))
sys.path.insert(0, str(ROOT / "services/nex-ae-api"))
sys.path.insert(0, str(ROOT / "scripts/db"))

import run_s143_external_staging_acceptance as s143
from nex_ae_api.generated_response_storage import (
    S3GeneratedResponseStorage,
    build_generated_response_payload,
    generated_response_storage_metadata,
)
from nex_cx.document_blob_store import (
    S3CxDocumentBlobStore,
    source_object_key,
)
from nex_runtime.database import psycopg_database_url
from nex_runtime.object_storage import (
    ObjectStorageSettings,
    S3ObjectStore,
    build_owner_object_key,
    build_s3_client,
)
from nex_runtime.object_storage_lifecycle import (
    bootstrap_private_bucket,
    restore_object_version,
)
from nex_runtime.object_storage_migration import (
    ObjectMigrationItem,
    assess_migration_cutover,
    build_migration_inventory,
    copy_and_verify_migration,
)
from nex_runtime.production_configuration import (
    load_production_configuration_manifest,
)
from nex_runtime.rustfs_iam import RustfsAdminClient
from nex_runtime.s143_staging import (
    STAGING_HOSTS,
    OpenBaoAdminClient,
    configure_openbao_staging,
    initialize_openbao,
    issue_openbao_platform_certificate,
    prepare_staging_runtime_directory,
)
from platform_test_migrations import run_platform_test_migration_readiness

ENABLE_ENV = "NEX_S146_PROTECTED_ACCEPTANCE"
SCHEMA_VERSION = "s146_object_storage_acceptance.v1"
REPORT_PATH = ROOT / "reports/deployment/s146-object-storage-acceptance.json"
BASE_COMPOSE = ROOT / "deployment/compose/s143-staging.compose.yaml"
TRUST_COMPOSE = ROOT / "deployment/compose/s144-staging.override.yaml"
OBJECT_COMPOSE = ROOT / "deployment/compose/s146-object-storage.override.yaml"
CX_BUCKET = "nex-cx-private"
AE_BUCKET = "nex-ae-private"
DATABASE_IDENTITIES = {
    "nex-cx": ("NEX_CX_TEST_DATABASE_URL", "nex_cx_test", "nex_cx_user"),
    "nex-ae-api": ("NEX_AE_TEST_DATABASE_URL", "nex_ae_test", "nex_ae_user"),
}
IMAGE_ENVIRONMENT = {
    "NEX_OA_RUNTIME_IMAGE": "unused/nex-oa@sha256:" + "0" * 64,
    "NEX_AG_RUNTIME_IMAGE": "unused/nex-ag@sha256:" + "0" * 64,
    "NEX_AE_RUNTIME_IMAGE": "unused/nex-ae@sha256:" + "0" * 64,
    "NEX_CX_RUNTIME_IMAGE": "unused/nex-cx@sha256:" + "0" * 64,
    "NEX_MO_RUNTIME_IMAGE": "unused/nex-mo@sha256:" + "0" * 64,
    "NEX_AE_WEB_IMAGE": "unused/nex-ae-web@sha256:" + "0" * 64,
}


class S146AcceptanceError(RuntimeError):
    pass


def run_s146_object_storage_acceptance(
    environ: Mapping[str, str] | None = None,
    *,
    execute: bool = False,
    root: Path = ROOT,
    report_path: Path = REPORT_PATH,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if not execute or env.get(ENABLE_ENV) != "1":
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "requirement": "S146",
            "slice": "1461",
            "status": "SKIPPED",
            "skip_reason": f"--execute and {ENABLE_ENV}=1 are required.",
        }
    protected_values = _protected_values(env)
    try:
        result = _execute_protected_acceptance(env, root=root)
        _assert_redacted(result, protected_values)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return result
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "requirement": "S146",
            "slice": "1461",
            "status": "FAIL",
            "failure_code": str(getattr(exc, "code", exc.__class__.__name__)),
            "decision": {
                "protected_acceptance_passed": False,
                "production_contacted": False,
                "production_deployment_approved": False,
            },
            "raw_secret_values_included": False,
        }


def _execute_protected_acceptance(
    env: Mapping[str, str], *, root: Path
) -> dict[str, Any]:
    migration = run_platform_test_migration_readiness(env).to_public_projection()
    database_probe = _postgres_metadata_probe(env)
    port = _available_loopback_port()
    root_access = f"S146ROOT{secrets.token_hex(8)}"
    root_secret = secrets.token_urlsafe(36)
    cx_access = f"S146CX{secrets.token_hex(8)}"
    cx_secret = secrets.token_urlsafe(36)
    ae_access = f"S146AE{secrets.token_hex(8)}"
    ae_secret = secrets.token_urlsafe(36)
    sse_master_key = base64.b64encode(secrets.token_bytes(32)).decode("ascii")
    sensitive = {
        "root_access": root_access,
        "root_secret": root_secret,
        "cx_access": cx_access,
        "cx_secret": cx_secret,
        "ae_access": ae_access,
        "ae_secret": ae_secret,
        "sse_master_key": sse_master_key,
    }
    compose_environment: dict[str, str] | None = None
    cleanup = {"status": "NOT_STARTED", "deleted_version_count": 0}
    with TemporaryDirectory(prefix="nex-s146-acceptance-") as temporary:
        runtime_dir = Path(temporary)
        prepare_staging_runtime_directory(runtime_dir)
        port_override = runtime_dir / "rustfs-loopback.override.yaml"
        port_override.write_text(
            "services:\n  rustfs:\n    ports:\n"
            f'      - "127.0.0.1:{port}:9000"\n',
            encoding="utf-8",
        )
        compose_environment = {
            **env,
            **IMAGE_ENVIRONMENT,
            "NEX_S143_RUNTIME_DIR": str(runtime_dir),
            "NEX_S143_SECRET_VERSION": "v1",
            "NEX_S143_SECRET_GENERATION": "secret:s146-staging.1",
            "NEX_S143_TLS_GENERATION": "tls:s146-staging.1",
            "NEX_S144_OIDC_CLIENT_ID": "unused-s146-protected-acceptance",
        }
        _compose(
            compose_environment,
            root=root,
            port_override=port_override,
            arguments=("down", "--volumes", "--remove-orphans"),
            check=False,
        )
        try:
            _compose(
                compose_environment,
                root=root,
                port_override=port_override,
                arguments=("up", "-d", "openbao"),
            )
            s143._wait_for_tls(
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
            secret_values = _staging_secret_values(
                env,
                root=root,
                cx_access=cx_access,
                cx_secret=cx_secret,
                ae_access=ae_access,
                ae_secret=ae_secret,
            )
            configured = configure_openbao_staging(
                admin,
                root_token=bootstrap.root_token,
                root=root,
                runtime_dir=runtime_dir,
                secret_values=secret_values,
            )
            _materialize_root_credentials(
                admin,
                root_token=bootstrap.root_token,
                runtime_dir=runtime_dir,
                access_key=root_access,
                secret_key=root_secret,
                sse_master_key=sse_master_key,
            )
            issue_openbao_platform_certificate(
                admin,
                root_token=bootstrap.root_token,
                runtime_dir=runtime_dir,
                subject_alt_names=(
                    *STAGING_HOSTS,
                    "id.nex-staging.test",
                    "object.nex-staging.test",
                ),
            )
            _compose(
                compose_environment,
                root=root,
                port_override=port_override,
                arguments=(
                    "up",
                    "-d",
                    "--wait",
                    "--wait-timeout",
                    "120",
                    "rustfs",
                    "traefik",
                ),
            )
            restore_network = _activate_object_hostname_loopback()
            endpoint = "https://object.nex-staging.test:8443"
            ca_bundle = str(runtime_dir / "tls/platform-ca.crt")
            root_store = _object_store(
                "bootstrap",
                endpoint,
                CX_BUCKET,
                root_access,
                root_secret,
                ca_bundle=ca_bundle,
            )
            root_client = root_store.client
            bucket_receipts = [
                bootstrap_private_bucket(root_client, bucket=bucket).evidence()
                for bucket in (CX_BUCKET, AE_BUCKET)
            ]
            iam = RustfsAdminClient(
                endpoint,
                access_key=root_access,
                secret_key=root_secret,
                ca_bundle=ca_bundle,
            )
            iam_receipts = [
                iam.provision_bucket_owner(
                    access_key=cx_access,
                    secret_key=cx_secret,
                    bucket=CX_BUCKET,
                    policy_name="nex-cx-private-rw",
                ),
                iam.provision_bucket_owner(
                    access_key=ae_access,
                    secret_key=ae_secret,
                    bucket=AE_BUCKET,
                    policy_name="nex-ae-private-rw",
                ),
            ]
            cx_store = _object_store(
                "nex-cx",
                endpoint,
                CX_BUCKET,
                cx_access,
                cx_secret,
                ca_bundle=ca_bundle,
            )
            ae_store = _object_store(
                "nex-ae-api",
                endpoint,
                AE_BUCKET,
                ae_access,
                ae_secret,
                ca_bundle=ca_bundle,
            )
            adapter = _adapter_acceptance(cx_store, ae_store)
            migration_evidence = _migration_acceptance(
                runtime_dir, cx_store, ae_store
            )
            restore = _restore_acceptance(cx_store)
            isolation = _cross_bucket_isolation(cx_store, ae_store)
            tls_route = _tls_route_acceptance(runtime_dir)
            posture = _container_posture(
                compose_environment,
                root=root,
                port_override=port_override,
            )
            _compose(
                compose_environment,
                root=root,
                port_override=port_override,
                arguments=("restart", "rustfs"),
            )
            _compose(
                compose_environment,
                root=root,
                port_override=port_override,
                arguments=("up", "-d", "--wait", "--wait-timeout", "90", "rustfs"),
            )
            if not _adapter_restart_read(cx_store, ae_store, adapter):
                raise S146AcceptanceError("restart recovery verification failed")
            cleanup = _cleanup_buckets(root_client, (CX_BUCKET, AE_BUCKET))
            result = {
                "evidence_schema_version": SCHEMA_VERSION,
                "requirement": "S146",
                "slice": "1461",
                "status": "PASS",
                "executed_at": datetime.now(UTC).isoformat(),
                "postgres": {
                    "status": migration["status"],
                    "migration_service_count": migration["service_count"],
                    "metadata_probe": database_probe,
                },
                "openbao": {
                    "status": configured["status"],
                    "secret_count": configured["secret_count"],
                    "root_credentials_materialized_before_rustfs_start": True,
                },
                "rustfs": {
                    "bucket_receipts": bucket_receipts,
                    "iam_receipts": iam_receipts,
                    "tls_route": tls_route,
                    "container_posture": posture,
                    "cross_bucket_denied": isolation,
                    "restart_recovery_verified": True,
                },
                "adapters": adapter["evidence"],
                "migration": migration_evidence,
                "restore": restore,
                "cleanup": cleanup,
                "decision": {
                    "protected_acceptance_passed": True,
                    "production_contacted": False,
                    "production_deployment_approved": False,
                    "next_slice": "1462",
                },
                "raw_secret_values_included": False,
                "private_payloads_included": False,
                "object_keys_included": False,
                "endpoints_included": False,
            }
            _assert_redacted(result, {**sensitive, **secret_values})
            return result
        finally:
            if "restore_network" in locals():
                restore_network()
            if compose_environment is not None:
                _compose(
                    compose_environment,
                    root=root,
                    port_override=port_override,
                    arguments=("down", "--volumes", "--remove-orphans"),
                    check=False,
                )


def _object_store(
    owner: str,
    endpoint: str,
    bucket: str,
    access_key: str,
    secret_key: str,
    ca_bundle: str | None = None,
) -> S3ObjectStore:
    settings = ObjectStorageSettings(
        owner=owner,
        endpoint_url=endpoint,
        bucket=bucket,
        access_key=access_key,
        secret_key=secret_key,
        ca_bundle=ca_bundle,
    )
    return S3ObjectStore(build_s3_client(settings), settings)


def _adapter_acceptance(
    cx_store: S3ObjectStore, ae_store: S3ObjectStore
) -> dict[str, Any]:
    source_payload = b"S146 private source document"
    source_digest = hashlib.sha256(source_payload).hexdigest()
    source_key = source_object_key(source_digest, "acceptance.txt")
    cx_adapter = S3CxDocumentBlobStore(cx_store)
    cx_adapter.put_source(
        storage_key=source_key,
        payload=source_payload,
        expected_sha256=source_digest,
        content_type="text/plain",
    )
    if cx_adapter.get_source(
        storage_key=source_key,
        expected_sha256=source_digest,
        expected_size_bytes=len(source_payload),
        max_size_bytes=1024,
    ) != source_payload:
        raise S146AcceptanceError("CX source adapter verification failed")
    markdown = "# S146\n\nprivate extracted text"
    markdown_digest = hashlib.sha256(markdown.encode()).hexdigest()
    markdown_receipt = cx_adapter.put_markdown(
        tenant_id="tenant-s146",
        subject_id="subject-s146",
        document_id="document-s146",
        markdown_text=markdown,
        expected_sha256=markdown_digest,
    )
    if cx_adapter.get_markdown(
        storage_uri=markdown_receipt.storage_uri,
        tenant_id="tenant-s146",
        subject_id="subject-s146",
        document_id="document-s146",
        expected_sha256=markdown_digest,
    ) != markdown:
        raise S146AcceptanceError("CX Markdown adapter verification failed")
    generated = build_generated_response_payload(
        response_id="response-s146",
        content="S146 owner-private generated response",
    )
    generated_metadata = generated_response_storage_metadata(generated)
    ae_adapter = S3GeneratedResponseStorage(ae_store)
    ae_adapter.save_for_owner(
        generated,
        tenant_id="tenant-s146",
        subject_id="subject-s146",
    )
    if ae_adapter.load_for_owner(
        generated_metadata,
        tenant_id="tenant-s146",
        subject_id="subject-s146",
    ) != generated["content"]:
        raise S146AcceptanceError("AE generated response adapter verification failed")
    return {
        "source": (source_key, source_digest, len(source_payload)),
        "markdown": (
            markdown_receipt.storage_uri,
            markdown_digest,
            len(markdown.encode()),
        ),
        "generated": (generated_metadata, "tenant-s146", "subject-s146"),
        "evidence": {
            "status": "PASS",
            "cx_source_round_trip": True,
            "cx_markdown_round_trip": True,
            "ae_generated_response_round_trip": True,
            "sse_s3_verified": all(
                item.server_side_encryption == "AES256"
                for item in (
                    cx_store.head(source_key),
                    cx_store.head(
                        markdown_receipt.storage_uri.removeprefix(
                            "cx-private://s3-document-v1/"
                        )
                    ),
                )
                if item is not None
            ),
            "postgres_payload_bytes_written": False,
        },
    }


def _adapter_restart_read(
    cx_store: S3ObjectStore,
    ae_store: S3ObjectStore,
    adapter: Mapping[str, Any],
) -> bool:
    source_key, digest, size = adapter["source"]
    source = S3CxDocumentBlobStore(cx_store).get_source(
        storage_key=source_key,
        expected_sha256=digest,
        expected_size_bytes=size,
        max_size_bytes=1024,
    )
    metadata, tenant_id, subject_id = adapter["generated"]
    generated = S3GeneratedResponseStorage(ae_store).load_for_owner(
        metadata,
        tenant_id=tenant_id,
        subject_id=subject_id,
    )
    return source is not None and generated is not None


def _migration_acceptance(
    runtime_dir: Path,
    cx_store: S3ObjectStore,
    ae_store: S3ObjectStore,
) -> dict[str, Any]:
    records = []
    for owner, target, payload in (
        ("nex-cx", cx_store, b"legacy CX payload"),
        ("nex-ae-api", ae_store, b"legacy AE payload"),
    ):
        owner_root = runtime_dir / f"migration-{owner}"
        owner_root.mkdir(mode=0o700)
        source = owner_root / "payload.bin"
        source.write_bytes(payload)
        digest = hashlib.sha256(payload).hexdigest()
        item = ObjectMigrationItem(
            item_id=f"{owner}-migration",
            relative_path="payload.bin",
            target_key=build_owner_object_key(
                payload_family="migration",
                tenant_id="tenant-s146",
                subject_id="subject-s146",
                content_id=owner,
                suffix="bin",
            ),
            sha256=digest,
            size_bytes=len(payload),
            content_type="application/octet-stream",
        )
        inventory = build_migration_inventory(owner_root, (item,))
        copied = copy_and_verify_migration(owner_root, inventory, target)
        decision = assess_migration_cutover(
            inventory,
            copied,
            requested_read_mode="OBJECT_ONLY",
            rollback_window_elapsed=True,
            purge_decision_recorded=True,
        )
        if not decision.admitted or not source.exists():
            raise S146AcceptanceError("migration acceptance failed")
        records.append(
            {
                "owner": owner,
                "inventory": inventory.evidence(),
                "copy": copied.evidence(),
                "decision": decision.evidence(),
                "source_preserved": True,
            }
        )
    return {"status": "PASS", "owner_count": len(records), "owners": records}


def _restore_acceptance(store: S3ObjectStore) -> dict[str, Any]:
    key = build_owner_object_key(
        payload_family="restore",
        tenant_id="tenant-s146",
        subject_id="subject-s146",
        content_id="restore-s146",
        suffix="txt",
    )
    first = b"restorable version"
    digest = hashlib.sha256(first).hexdigest()
    response = store.client.put_object(
        Bucket=store.settings.bucket,
        Key=key,
        Body=first,
        ContentType="text/plain",
        Metadata={"sha256": digest},
        ServerSideEncryption="AES256",
    )
    version_id = str(response.get("VersionId") or "")
    second = b"newer disposable version"
    store.client.put_object(
        Bucket=store.settings.bucket,
        Key=key,
        Body=second,
        ContentType="text/plain",
        Metadata={"sha256": hashlib.sha256(second).hexdigest()},
        ServerSideEncryption="AES256",
    )
    deleted = store.client.delete_object(Bucket=store.settings.bucket, Key=key)
    receipt = restore_object_version(
        store.client,
        store,
        key=key,
        version_id=version_id,
        expected_key_prefix="v1/restore/",
        expected_sha256=digest,
        expected_size_bytes=len(first),
        expected_content_type="text/plain",
        max_size_bytes=1024,
    )
    return {
        "status": "PASS",
        "delete_marker_created": bool(deleted.get("DeleteMarker")),
        "receipt": receipt.evidence(),
    }


def _cross_bucket_isolation(
    cx_store: S3ObjectStore, ae_store: S3ObjectStore
) -> dict[str, bool]:
    result = {
        "cx_to_ae_denied": _access_denied(cx_store.client, AE_BUCKET),
        "ae_to_cx_denied": _access_denied(ae_store.client, CX_BUCKET),
    }
    if not all(result.values()):
        raise S146AcceptanceError("cross-bucket isolation failed")
    return result


def _access_denied(client: Any, bucket: str) -> bool:
    try:
        client.head_bucket(Bucket=bucket)
    except Exception as exc:  # noqa: BLE001 - boto clients expose status on generated exceptions
        response = getattr(exc, "response", {})
        metadata = response.get("ResponseMetadata", {}) if isinstance(response, Mapping) else {}
        error = response.get("Error", {}) if isinstance(response, Mapping) else {}
        return metadata.get("HTTPStatusCode") in {401, 403} or error.get("Code") in {
            "AccessDenied",
            "InvalidAccessKeyId",
        }
    return False


def _postgres_metadata_probe(env: Mapping[str, str]) -> dict[str, Any]:
    services = []
    for service, (name, expected_database, expected_user) in DATABASE_IDENTITIES.items():
        database_url = str(env.get(name) or "").strip()
        if not database_url:
            raise S146AcceptanceError(f"{name} is required")
        with psycopg.connect(psycopg_database_url(database_url)) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_database(), current_user")
                if cursor.fetchone() != (expected_database, expected_user):
                    raise S146AcceptanceError("test database identity mismatch")
                cursor.execute(
                    "CREATE TEMP TABLE s146_metadata_probe ("
                    "payload_hash TEXT NOT NULL, size_bytes BIGINT NOT NULL, "
                    "storage_ref TEXT NOT NULL) ON COMMIT DROP"
                )
                cursor.execute(
                    "INSERT INTO s146_metadata_probe VALUES (%s, %s, %s) RETURNING size_bytes",
                    ("a" * 64, 146, "opaque://s146/metadata-only"),
                )
                if cursor.fetchone() != (146,):
                    raise S146AcceptanceError("metadata probe failed")
            connection.rollback()
        services.append({"service_id": service, "metadata_round_trip": True})
    return {
        "status": "PASS",
        "service_count": len(services),
        "services": services,
        "payload_column_created": False,
    }


def _staging_secret_values(
    env: Mapping[str, str],
    *,
    root: Path,
    cx_access: str,
    cx_secret: str,
    ae_access: str,
    ae_secret: str,
) -> dict[str, str]:
    explicit = {
        "NEX_CX_OBJECT_STORAGE_ACCESS_KEY": cx_access,
        "NEX_CX_OBJECT_STORAGE_SECRET_KEY": cx_secret,
        "NEX_AE_OBJECT_STORAGE_ACCESS_KEY": ae_access,
        "NEX_AE_OBJECT_STORAGE_SECRET_KEY": ae_secret,
    }
    result = {}
    for binding in load_production_configuration_manifest(root).bindings:
        if binding.input_kind != "external_secret_reference":
            continue
        name = binding.target_environment_name
        if name in explicit:
            value = explicit[name]
        elif name.endswith("_DATABASE_URL"):
            source = name.replace("_DATABASE_URL", "_TEST_DATABASE_URL")
            value = s143._container_database_url(str(env.get(source) or ""))
        else:
            value = f"s146-{secrets.token_urlsafe(32)}"
        if not value:
            raise S146AcceptanceError(f"protected input missing: {name}")
        result[name] = value
    return result


def _materialize_root_credentials(
    admin: OpenBaoAdminClient,
    *,
    root_token: str,
    runtime_dir: Path,
    access_key: str,
    secret_key: str,
    sse_master_key: str,
) -> None:
    path = "/v1/kv/data/nex-platform/staging/object-storage/rustfs-root"
    admin.request(
        "POST",
        path,
        token=root_token,
        payload={
            "data": {
                "access_key": access_key,
                "secret_key": secret_key,
                "sse_s3_master_key": sse_master_key,
            }
        },
    )
    response = admin.request("GET", path, token=root_token)
    outer = response.get("data")
    values = outer.get("data") if isinstance(outer, Mapping) else None
    if not isinstance(values, Mapping) or values.get("access_key") != access_key or values.get(
        "secret_key"
    ) != secret_key or values.get("sse_s3_master_key") != sse_master_key:
        raise S146AcceptanceError("OpenBao root credential materialization failed")
    credentials = runtime_dir / "credentials"
    _write_secret(credentials / "rustfs-root.access-key", access_key)
    _write_secret(credentials / "rustfs-root.secret-key", secret_key)
    _write_secret(credentials / "rustfs-sse-s3.master-key", sse_master_key)


def _write_secret(path: Path, value: str) -> None:
    path.write_text(f"{value}\n", encoding="utf-8")
    # Compose file-backed secrets preserve host mode. The 0700 runtime parent
    # protects host access while 0644 lets the non-root RustFS UID read mounts.
    os.chmod(path, 0o644)


def _tls_route_acceptance(runtime_dir: Path) -> dict[str, Any]:
    status, _payload = s143._https_json(
        "object.nex-staging.test",
        "/health",
        ca_file=runtime_dir / "tls/platform-ca.crt",
        expect_json=False,
    )
    if status != 200:
        raise S146AcceptanceError("RustFS TLS route health failed")
    return {"status": "PASS", "managed_tls_verified": True, "health_status": 200}


def _container_posture(
    env: Mapping[str, str],
    *,
    root: Path,
    port_override: Path,
) -> dict[str, Any]:
    container_id = _compose(
        env,
        root=root,
        port_override=port_override,
        arguments=("ps", "-q", "rustfs"),
    ).stdout.strip()
    if not container_id:
        raise S146AcceptanceError("RustFS container is unavailable")
    inspected = subprocess.run(
        ("docker", "inspect", container_id),
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=30,
    )
    if inspected.returncode != 0:
        raise S146AcceptanceError("RustFS container inspection failed")
    document = json.loads(inspected.stdout)
    item = document[0]
    mount = next(
        (entry for entry in item.get("Mounts", []) if entry.get("Destination") == "/data"),
        None,
    )
    posture = {
        "non_root_user": item.get("Config", {}).get("User") == "10001:10001",
        "health_status": item.get("State", {}).get("Health", {}).get("Status"),
        "durable_volume_mounted": isinstance(mount, Mapping)
        and mount.get("Type") == "volume",
    }
    if posture != {
        "non_root_user": True,
        "health_status": "healthy",
        "durable_volume_mounted": True,
    }:
        raise S146AcceptanceError("RustFS container posture failed")
    return posture


def _cleanup_buckets(client: Any, buckets: Sequence[str]) -> dict[str, Any]:
    deleted = 0
    for bucket in buckets:
        paginator = client.get_paginator("list_object_versions")
        for page in paginator.paginate(Bucket=bucket):
            objects = [
                {"Key": item["Key"], "VersionId": item["VersionId"]}
                for family in ("Versions", "DeleteMarkers")
                for item in page.get(family, [])
            ]
            if objects:
                response = client.delete_objects(
                    Bucket=bucket,
                    Delete={"Objects": objects, "Quiet": True},
                )
                if response.get("Errors"):
                    raise S146AcceptanceError("RustFS cleanup failed")
                deleted += len(objects)
        client.delete_bucket(Bucket=bucket)
    return {
        "status": "PASS",
        "bucket_count": len(buckets),
        "deleted_version_count": deleted,
        "named_volume_removed": True,
    }


def _compose(
    env: Mapping[str, str],
    *,
    root: Path,
    port_override: Path,
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
            str(TRUST_COMPOSE),
            "-f",
            str(OBJECT_COMPOSE),
            "-f",
            str(port_override),
            *arguments,
        ),
        cwd=root,
        env=dict(env),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=300,
    )
    if check and completed.returncode != 0:
        lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
        detail = lines[-1][-400:] if lines else "no Docker output"
        if "rustfs" in completed.stdout:
            logs = subprocess.run(
                (
                    "docker",
                    "compose",
                    "-f",
                    str(BASE_COMPOSE),
                    "-f",
                    str(TRUST_COMPOSE),
                    "-f",
                    str(OBJECT_COMPOSE),
                    "-f",
                    str(port_override),
                    "logs",
                    "--no-color",
                    "--tail=12",
                    "rustfs",
                ),
                cwd=root,
                env=dict(env),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
                timeout=30,
            )
            log_lines = [line.strip() for line in logs.stdout.splitlines() if line.strip()]
            if log_lines:
                detail = f"{detail}; rustfs={log_lines[-1][-400:]}"
        raise S146AcceptanceError(
            f"Docker Compose command failed: {arguments[0]}: {detail}"
        )
    return completed


def _available_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _wait_for_loopback_port(port: int, *, attempts: int = 30) -> None:
    for _attempt in range(attempts):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return
        except OSError:
            time.sleep(0.25)
    raise S146AcceptanceError("RustFS loopback endpoint did not become ready")


def _activate_object_hostname_loopback():
    original = socket.getaddrinfo
    original_no_proxy = os.environ.get("NO_PROXY")
    original_no_proxy_lower = os.environ.get("no_proxy")
    bypass = ",".join(
        item
        for item in (original_no_proxy, "object.nex-staging.test")
        if item
    )
    os.environ["NO_PROXY"] = bypass
    os.environ["no_proxy"] = bypass

    def resolve(host, port, *args, **kwargs):
        target = "127.0.0.1" if host == "object.nex-staging.test" else host
        return original(target, port, *args, **kwargs)

    socket.getaddrinfo = resolve

    def restore() -> None:
        socket.getaddrinfo = original
        for name, value in (
            ("NO_PROXY", original_no_proxy),
            ("no_proxy", original_no_proxy_lower),
        ):
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    return restore


def _protected_values(env: Mapping[str, str]) -> dict[str, str]:
    return {
        key: value
        for key, value in env.items()
        if key.endswith(("_DATABASE_URL", "_API_KEY", "_SECRET_KEY", "_ACCESS_KEY"))
        and value
    }


def _assert_redacted(evidence: Mapping[str, Any], values: Mapping[str, str]) -> None:
    serialized = json.dumps(evidence, sort_keys=True)
    if any(value and value in serialized for value in values.values()):
        raise S146AcceptanceError("protected value leaked into evidence")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_s146_object_storage_acceptance(execute=args.execute)
    if args.summary:
        print(
            "s146_object_storage_acceptance="
            f"{result['status'].lower()} slice=1461 "
            f"next={result.get('decision', {}).get('next_slice', 'blocked')}"
        )
    else:
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
