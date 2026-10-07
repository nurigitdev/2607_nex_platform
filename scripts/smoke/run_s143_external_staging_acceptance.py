#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from contextlib import suppress
from datetime import UTC, datetime
import http.client
import json
import os
from pathlib import Path
import secrets
import socket
import ssl
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from typing import Any

from cryptography import x509


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))
sys.path.insert(0, str(ROOT / "scripts" / "db"))

from nex_runtime.openbao_secret_resolver import (  # noqa: E402
    OpenBaoSecretResolverError,
    build_openbao_secret_resolver,
)
from nex_runtime.production_configuration import (  # noqa: E402
    load_production_configuration_manifest,
)
from nex_runtime.production_secret_materialization import (  # noqa: E402
    SecretResolutionContext,
)
from nex_runtime.s143_staging import (  # noqa: E402
    OpenBaoAdminClient,
    configure_openbao_staging,
    initialize_openbao,
    issue_openbao_platform_certificate,
    prepare_staging_runtime_directory,
    refresh_openbao_approle_credentials,
    validate_s143_compose_assets,
    write_openbao_secret_generation,
)
from platform_test_migrations import (  # noqa: E402
    run_platform_test_migration_readiness,
)


ENABLE_ENV = "NEX_S143_EXTERNAL_STAGING_ACCEPTANCE"
SCHEMA_VERSION = "s143_external_staging_acceptance.v1"
REPORT_PATH = ROOT / "reports/deployment/s143-external-staging-acceptance.json"
COMPOSE_FILE = ROOT / "deployment/compose/s143-staging.compose.yaml"
APPLICATION_SERVICES = (
    "nex-oa",
    "nex-ag",
    "nex-ae-api",
    "nex-cx",
    "nex-mo",
    "nex-ae-web",
)
API_HOSTS = (
    "oa.nex-staging.test",
    "ag.nex-staging.test",
    "ae-api.nex-staging.test",
    "cx.nex-staging.test",
    "mo.nex-staging.test",
)
IMAGE_ENV_BY_ARTIFACT = {
    "nex-oa-runtime": "NEX_OA_RUNTIME_IMAGE",
    "nex-ag-runtime": "NEX_AG_RUNTIME_IMAGE",
    "nex-ae-runtime": "NEX_AE_RUNTIME_IMAGE",
    "nex-cx-runtime": "NEX_CX_RUNTIME_IMAGE",
    "nex-mo-runtime": "NEX_MO_RUNTIME_IMAGE",
    "nex-ae-web": "NEX_AE_WEB_IMAGE",
}


class ExternalStagingAcceptanceError(RuntimeError):
    pass


def run_s143_external_staging_acceptance(
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
            "slice": "1431",
            "requirement": "S143",
            "status": "SKIPPED",
            "skip_reason": f"--execute and {ENABLE_ENV}=1 are required.",
        }
    runtime_directory = None
    compose_environment = None
    try:
        compose_contract = validate_s143_compose_assets(root)
        secret_values = _staging_secret_values(env, root=root)
        migration = _migration_projection(
            run_platform_test_migration_readiness(env)
        )
        if migration.get("status") != "PASS":
            raise ExternalStagingAcceptanceError(
                "platform test database migration readiness failed"
            )
        image_environment, release_set_digest = _image_environment(root)
        with TemporaryDirectory(prefix="nex-s143-staging-") as temporary:
            runtime_directory = Path(temporary)
            prepare_staging_runtime_directory(runtime_directory)
            compose_environment = {
                **env,
                **image_environment,
                "NEX_S143_RUNTIME_DIR": str(runtime_directory),
                "NEX_S143_SECRET_VERSION": "v1",
                "NEX_S143_SECRET_GENERATION": "secret:s143-staging.1",
                "NEX_S143_TLS_GENERATION": "tls:s143-staging.1",
            }
            _compose(
                compose_environment,
                root=root,
                arguments=("down", "--volumes", "--remove-orphans"),
                check=False,
            )
            try:
                _compose(
                    compose_environment,
                    root=root,
                    arguments=("up", "-d", "openbao"),
                )
                _wait_for_tls(
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
                configured = configure_openbao_staging(
                    admin,
                    root_token=bootstrap.root_token,
                    root=root,
                    runtime_dir=runtime_directory,
                    secret_values=secret_values,
                )
                initial_serial = _normalize_serial(configured["certificate_serial"])
                _compose_up_platform(compose_environment, root=root)
                initial_services = _service_acceptance(runtime_directory)
                initial_providers = _provider_acceptance(
                    runtime_directory,
                    provider_key=secret_values["NEX_MO_VLLM_API_KEY"],
                )
                refresh_openbao_approle_credentials(
                    admin,
                    root_token=bootstrap.root_token,
                    runtime_dir=runtime_directory,
                )
                least_privilege = _verify_openbao_owner_isolation(runtime_directory)

                bindings = tuple(
                    binding
                    for binding in load_production_configuration_manifest(root).bindings
                    if binding.input_kind == "external_secret_reference"
                )
                rotated_values = _rotated_secret_values(secret_values)
                versions = write_openbao_secret_generation(
                    admin,
                    root_token=bootstrap.root_token,
                    bindings=bindings,
                    secret_values=rotated_values,
                )
                _require_secret_generation(versions, expected=2)
                refresh_openbao_approle_credentials(
                    admin,
                    root_token=bootstrap.root_token,
                    runtime_dir=runtime_directory,
                )
                rotated_environment = {
                    **compose_environment,
                    "NEX_S143_SECRET_VERSION": "v2",
                    "NEX_S143_SECRET_GENERATION": "secret:s143-staging.2",
                }
                _compose_recreate_python(rotated_environment, root=root)
                rotated_services = _service_acceptance(runtime_directory)

                tls_dir = runtime_directory / "tls"
                previous_certificate = (tls_dir / "platform.crt").read_bytes()
                previous_private_key = (tls_dir / "platform.key").read_bytes()
                renewed = issue_openbao_platform_certificate(
                    admin,
                    root_token=bootstrap.root_token,
                    runtime_dir=runtime_directory,
                )
                _compose(
                    rotated_environment,
                    root=root,
                    arguments=("restart", "traefik"),
                )
                _wait_compose_healthy(rotated_environment, root=root)
                renewed_serial = _peer_certificate_serial(runtime_directory)
                _require_tls_rotation(initial_serial, renewed_serial)

                (tls_dir / "platform.crt").write_bytes(previous_certificate)
                (tls_dir / "platform.key").write_bytes(previous_private_key)
                os.chmod(tls_dir / "platform.crt", 0o644)
                os.chmod(tls_dir / "platform.key", 0o644)
                refresh_openbao_approle_credentials(
                    admin,
                    root_token=bootstrap.root_token,
                    runtime_dir=runtime_directory,
                )
                rollback_environment = {
                    **compose_environment,
                    "NEX_S143_SECRET_GENERATION": "secret:s143-staging.rollback",
                    "NEX_S143_TLS_GENERATION": "tls:s143-staging.rollback",
                }
                _compose_recreate_python(rollback_environment, root=root)
                _compose(
                    rollback_environment,
                    root=root,
                    arguments=("restart", "traefik"),
                )
                _wait_compose_healthy(rollback_environment, root=root)
                rollback_services = _service_acceptance(runtime_directory)
                rollback_serial = _peer_certificate_serial(runtime_directory)
                _require_tls_rollback(initial_serial, rollback_serial)
                result = {
                    "evidence_schema_version": SCHEMA_VERSION,
                    "slice": "1431",
                    "requirement": "S143",
                    "status": "PASS",
                    "executed_at": datetime.now(UTC).isoformat(),
                    "compose_contract": compose_contract,
                    "release_set_digest": release_set_digest,
                    "postgres_migration": {
                        "status": migration["status"],
                        "service_count": migration["summary"]["service_count"],
                    },
                    "openbao": {
                        "storage": "integrated-raft",
                        "tls": True,
                        "owner_count": configured["owner_count"],
                        "secret_count": configured["secret_count"],
                        "generations_verified": [1, 2, 1],
                        "least_privilege_cross_owner_denied": least_privilege,
                    },
                    "tls": {
                        "termination": "traefik",
                        "route_count": compose_contract["tls_route_count"],
                        "initial_serial": initial_serial,
                        "renewed_serial": _normalize_serial(
                            renewed["serial_number"]
                        ),
                        "observed_renewed_serial": renewed_serial,
                        "rollback_serial": rollback_serial,
                    },
                    "services": {
                        "initial_ready_count": len(initial_services),
                        "rotated_ready_count": len(rotated_services),
                        "rollback_ready_count": len(rollback_services),
                    },
                    "providers": initial_providers,
                    "decision": {
                        "external_staging_acceptance_passed": True,
                        "registry_push_performed": False,
                        "production_contacted": False,
                        "production_deployment_approved": False,
                        "next_slice": "1432",
                    },
                    "raw_secret_values_included": False,
                }
                _assert_evidence_redacted(result, secret_values, rotated_values)
            finally:
                _compose(
                    compose_environment,
                    root=root,
                    arguments=("down", "--volumes", "--remove-orphans"),
                    check=False,
                )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return result
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "slice": "1431",
            "requirement": "S143",
            "status": "FAIL",
            "issues": [str(exc)],
            "decision": {
                "external_staging_acceptance_passed": False,
                "production_deployment_approved": False,
            },
            "raw_secret_values_included": False,
        }


def _staging_secret_values(
    environ: Mapping[str, str],
    *,
    root: Path,
) -> dict[str, str]:
    manifest = load_production_configuration_manifest(root)
    result = {}
    for binding in manifest.bindings:
        if binding.input_kind != "external_secret_reference":
            continue
        target = binding.target_environment_name
        if target.endswith("_DATABASE_URL"):
            source = target.replace("_DATABASE_URL", "_TEST_DATABASE_URL")
            value = _container_database_url(str(environ.get(source) or ""))
        elif target.endswith("_API_KEY"):
            value = str(environ.get(target) or "").strip()
        else:
            value = f"s143-{secrets.token_urlsafe(32)}"
        if not value:
            raise ExternalStagingAcceptanceError(
                f"required protected input is missing: {target}"
            )
        result[target] = value
    return result


def _migration_projection(result: object) -> Mapping[str, Any]:
    if isinstance(result, Mapping):
        projection = dict(result)
    else:
        projector = getattr(result, "to_public_projection", None)
        if not callable(projector):
            raise ExternalStagingAcceptanceError(
                "platform migration readiness result is invalid"
            )
        projection = projector()
    if not isinstance(projection, Mapping):
        raise ExternalStagingAcceptanceError(
            "platform migration readiness projection is invalid"
        )
    normalized = dict(projection)
    service_count = normalized.get("service_count")
    if service_count is None:
        summary = normalized.get("summary")
        service_count = summary.get("service_count") if isinstance(summary, Mapping) else None
    if service_count != 5:
        raise ExternalStagingAcceptanceError(
            "platform migration readiness service coverage drift"
        )
    normalized["summary"] = {"service_count": service_count}
    return normalized


def _container_database_url(value: str) -> str:
    candidate = value.strip()
    if not candidate:
        return ""
    for host in ("127.0.0.1", "localhost"):
        candidate = candidate.replace(f"@{host}:", "@host.docker.internal:")
    if "@host.docker.internal:" not in candidate:
        raise ExternalStagingAcceptanceError(
            "S143 test database URL must target the local PostgreSQL host"
        )
    return candidate


def _rotated_secret_values(values: Mapping[str, str]) -> dict[str, str]:
    return {
        name: (
            value
            if name.endswith("_DATABASE_URL") or name.endswith("_API_KEY")
            else f"s143-rotated-{secrets.token_urlsafe(32)}"
        )
        for name, value in values.items()
    }


def _image_environment(root: Path) -> tuple[dict[str, str], str]:
    path = root / "reports/deployment/s142-oci-image-build.json"
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ExternalStagingAcceptanceError(
            "current OCI image build evidence is unavailable"
        ) from None
    image_build = report.get("image_build")
    if (
        not isinstance(image_build, Mapping)
        or image_build.get("status") != "RELEASE_SET_BUILT"
    ):
        raise ExternalStagingAcceptanceError("OCI release set is not ready")
    source_revision = _git(root, "rev-parse", "HEAD")
    if image_build.get("source_revision") != source_revision:
        raise ExternalStagingAcceptanceError("OCI release set source revision is stale")
    artifacts = image_build.get("artifacts")
    if not isinstance(artifacts, list):
        raise ExternalStagingAcceptanceError("OCI release set artifact list is invalid")
    references = {
        str(item.get("artifact_id")): str(item.get("image_reference"))
        for item in artifacts
        if isinstance(item, Mapping)
    }
    if set(references) != set(IMAGE_ENV_BY_ARTIFACT):
        raise ExternalStagingAcceptanceError("OCI release set coverage drift")
    if any("@sha256:" not in reference for reference in references.values()):
        raise ExternalStagingAcceptanceError("OCI image reference is not immutable")
    return (
        {
            IMAGE_ENV_BY_ARTIFACT[artifact]: reference
            for artifact, reference in references.items()
        },
        str(image_build.get("release_set_digest")),
    )


def _compose_up_platform(environ: Mapping[str, str], *, root: Path) -> None:
    _compose(
        environ,
        root=root,
        arguments=("up", "-d", "--wait", "--wait-timeout", "120"),
    )


def _compose_recreate_python(environ: Mapping[str, str], *, root: Path) -> None:
    _compose(
        environ,
        root=root,
        arguments=(
            "up",
            "-d",
            "--force-recreate",
            "--wait",
            "--wait-timeout",
            "120",
            *APPLICATION_SERVICES[:5],
        ),
    )


def _wait_compose_healthy(environ: Mapping[str, str], *, root: Path) -> None:
    _wait_for_tls(
        "127.0.0.1",
        8443,
        server_hostname="oa.nex-staging.test",
        ca_file=Path(environ["NEX_S143_RUNTIME_DIR"]) / "tls/platform-ca.crt",
    )


def _compose(
    environ: Mapping[str, str],
    *,
    root: Path,
    arguments: Sequence[str],
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ("docker", "compose", "-f", str(COMPOSE_FILE), *arguments),
        cwd=root,
        env=dict(environ),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=300,
    )
    if check and completed.returncode != 0:
        lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
        detail = lines[-1][-400:] if lines else "no Docker output"
        bootstrap = _controlled_bootstrap_failure(
            environ,
            root=root,
            compose_output=completed.stdout,
        )
        if bootstrap:
            detail = f"{detail}; {bootstrap}"
        raise ExternalStagingAcceptanceError(
            f"Docker Compose command failed: {arguments[0]}: {detail}"
        )
    return completed


def _controlled_bootstrap_failure(
    environ: Mapping[str, str],
    *,
    root: Path,
    compose_output: str,
) -> str | None:
    service = next(
        (item for item in APPLICATION_SERVICES if item in compose_output),
        None,
    )
    if service is None:
        return None
    completed = subprocess.run(
        (
            "docker",
            "compose",
            "-f",
            str(COMPOSE_FILE),
            "logs",
            "--no-color",
            "--tail=20",
            service,
        ),
        cwd=root,
        env=dict(environ),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=30,
    )
    controlled = [
        line.strip()[-300:]
        for line in completed.stdout.splitlines()
        if "production_container_bootstrap=fail" in line
    ]
    return controlled[-1] if controlled else None


def _wait_for_tls(
    host: str,
    port: int,
    *,
    server_hostname: str,
    ca_file: Path,
    timeout_seconds: float = 60.0,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    context = ssl.create_default_context(cafile=str(ca_file))
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=2) as connection:
                with context.wrap_socket(
                    connection,
                    server_hostname=server_hostname,
                ):
                    return
        except (OSError, ssl.SSLError):
            time.sleep(0.5)
    raise ExternalStagingAcceptanceError("TLS endpoint did not become ready")


def _service_acceptance(runtime_dir: Path) -> list[str]:
    ca_file = runtime_dir / "tls/platform-ca.crt"
    ready = []
    for host in API_HOSTS:
        status, payload = _https_json(host, "/ready", ca_file=ca_file)
        if status != 200 or payload.get("readiness_status") != "READY":
            raise ExternalStagingAcceptanceError(
                f"staging service readiness failed: {host}"
            )
        ready.append(host)
    status, _ = _https_json(
        "ae.nex-staging.test",
        "/",
        ca_file=ca_file,
        expect_json=False,
    )
    if status != 200:
        raise ExternalStagingAcceptanceError("AE Web staging endpoint is unavailable")
    ready.append("ae.nex-staging.test")
    return ready


def _provider_acceptance(runtime_dir: Path, *, provider_key: str) -> dict[str, Any]:
    ca_file = runtime_dir / "tls/platform-ca.crt"
    results = {}
    for capability, host in (
        ("embedding", "embedding.nex-staging.test"),
        ("reranking", "reranker.nex-staging.test"),
        ("generation", "generation.nex-staging.test"),
    ):
        status, payload = _https_json(
            host,
            "/v1/models",
            ca_file=ca_file,
            headers={"Authorization": f"Bearer {provider_key}"},
        )
        models = payload.get("data")
        if status != 200 or not isinstance(models, list) or not models:
            raise ExternalStagingAcceptanceError(
                f"DGX provider HTTPS route failed: {capability}"
            )
        results[capability] = {
            "status": "PASS",
            "model_count": len(models),
        }
    return {
        "status": "PASS",
        "capabilities": results,
        "provider_api_key_included": False,
    }


def _https_json(
    server_hostname: str,
    path: str,
    *,
    ca_file: Path,
    headers: Mapping[str, str] | None = None,
    expect_json: bool = True,
) -> tuple[int, dict[str, Any]]:
    context = ssl.create_default_context(cafile=str(ca_file))
    connection = _ResolvedHttpsConnection(
        server_hostname,
        8443,
        connect_host="127.0.0.1",
        context=context,
        timeout=10,
    )
    try:
        connection.request("GET", path, headers=dict(headers or {}))
        response = connection.getresponse()
        body = response.read(2_097_153)
    finally:
        connection.close()
    if len(body) > 2_097_152:
        raise ExternalStagingAcceptanceError("staging HTTPS response is too large")
    if not expect_json:
        return response.status, {}
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ExternalStagingAcceptanceError(
            "staging HTTPS response is invalid"
        ) from None
    if not isinstance(payload, dict):
        raise ExternalStagingAcceptanceError("staging HTTPS response is invalid")
    return response.status, payload


class _ResolvedHttpsConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, port: int, *, connect_host: str, **kwargs) -> None:
        super().__init__(host, port, **kwargs)
        self._connect_host = connect_host

    def connect(self) -> None:
        self.sock = self._create_connection(
            (self._connect_host, self.port),
            self.timeout,
            self.source_address,
        )
        if self._tunnel_host:
            self._tunnel()
        self.sock = self._context.wrap_socket(
            self.sock,
            server_hostname=self.host,
        )


def _peer_certificate_serial(runtime_dir: Path) -> str:
    context = ssl.create_default_context(
        cafile=str(runtime_dir / "tls/platform-ca.crt")
    )
    with socket.create_connection(("127.0.0.1", 8443), timeout=10) as connection:
        with context.wrap_socket(
            connection,
            server_hostname="oa.nex-staging.test",
        ) as wrapped:
            certificate = wrapped.getpeercert(binary_form=True)
    if not certificate:
        raise ExternalStagingAcceptanceError("managed TLS certificate is unavailable")
    parsed = x509.load_der_x509_certificate(certificate)
    return format(parsed.serial_number, "x")


def _normalize_serial(value: str) -> str:
    normalized = value.replace(":", "").lstrip("0").lower()
    return normalized or "0"


def _require_secret_generation(
    versions: Mapping[str, int],
    *,
    expected: int,
) -> None:
    if set(versions.values()) != {expected}:
        raise ExternalStagingAcceptanceError(
            "OpenBao secret generation did not advance atomically"
        )


def _require_tls_rotation(initial_serial: str, renewed_serial: str) -> None:
    if renewed_serial == initial_serial:
        raise ExternalStagingAcceptanceError(
            "managed TLS certificate serial did not rotate"
        )


def _require_tls_rollback(initial_serial: str, rollback_serial: str) -> None:
    if rollback_serial != initial_serial:
        raise ExternalStagingAcceptanceError(
            "managed TLS certificate rollback did not restore prior serial"
        )


def _verify_openbao_owner_isolation(runtime_dir: Path) -> bool:
    environment = {
        "NEX_OPENBAO_ADDR": "https://127.0.0.1:8200",
        "NEX_OPENBAO_CA_CERT_FILE": str(runtime_dir / "tls/openbao-ca.crt"),
        "NEX_OPENBAO_ROLE_ID_FILE": str(
            runtime_dir / "credentials/nex-oa.role-id"
        ),
        "NEX_OPENBAO_SECRET_ID_FILE": str(
            runtime_dir / "credentials/nex-oa.secret-id"
        ),
        "NEX_OPENBAO_SECRET_NAMESPACE": "staging",
    }
    resolver = build_openbao_secret_resolver(environment)
    try:
        resolver.resolve(
            "secret://openbao/nex-platform/staging/nex-mo/NEX_MO_DATABASE_URL@v1",
            context=SecretResolutionContext(
                owner="nex-mo",
                target_environment_name="NEX_MO_DATABASE_URL",
                secret_generation="secret:s143-staging.1",
                reference_version="v1",
            ),
        )
    except OpenBaoSecretResolverError:
        return True
    finally:
        with suppress(Exception):
            resolver.revoke()
    raise ExternalStagingAcceptanceError("OpenBao owner isolation failed")


def _assert_evidence_redacted(
    evidence: Mapping[str, Any],
    *secret_sets: Mapping[str, str],
) -> None:
    serialized = json.dumps(evidence, sort_keys=True)
    if any(
        value and value in serialized
        for secret_set in secret_sets
        for value in secret_set.values()
    ):
        raise ExternalStagingAcceptanceError("raw secret leaked into S143 evidence")


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ("git", *arguments),
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=10,
    )
    if completed.returncode != 0:
        raise ExternalStagingAcceptanceError("git metadata is unavailable")
    return completed.stdout.strip()


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") == "SKIPPED":
        return "s143_external_staging_acceptance=skipped"
    if result.get("status") != "PASS":
        return "s143_external_staging_acceptance=fail"
    return (
        "s143_external_staging_acceptance=pass "
        f"services={result['services']['initial_ready_count']} "
        f"secrets={result['openbao']['secret_count']} "
        f"tls_routes={result['tls']['route_count']} "
        "provider_capabilities=3 next=1432"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    args = parser.parse_args(argv)
    result = run_s143_external_staging_acceptance(
        execute=args.execute,
        report_path=args.report,
    )
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
