#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
from collections.abc import Mapping, Sequence
from contextlib import suppress
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from cryptography import x509

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))

from nex_runtime.demo_compose import image_environment_from_release_report
from nex_runtime.demo_trust import (
    DEMO_OWNERS,
    DEMO_SECRET_BINDINGS,
    DEMO_TLS_HOSTS,
    demo_trust_projection,
)
from nex_runtime.openbao_provisioning import (
    OpenBaoProvisioningSession,
    provision_openbao_environment,
    reactivate_openbao_after_restart,
    verify_openbao_runtime_resolution,
)
from nex_runtime.openbao_secret_resolver import (
    OpenBaoSecretResolverError,
    build_openbao_secret_resolver,
)
from nex_runtime.production_secret_materialization import (
    SecretResolutionContext,
)
from nex_runtime.s143_staging import (
    OpenBaoAdminClient,
    prepare_staging_runtime_directory,
    refresh_openbao_approle_credentials,
    write_openbao_secret_generation,
)

EXECUTION_ENV = "NEX_P8_DEMO_TRUST_ADMISSION"
SCHEMA_VERSION = "p8_demo_trust_admission.v1"
BASE_COMPOSE = "deployment/compose/s143-staging.compose.yaml"
OBJECT_COMPOSE = "deployment/compose/s146-object-storage.override.yaml"
DEMO_COMPOSE = "deployment/compose/p8-demo.override.yaml"
DEFAULT_IMAGE_REPORT = ROOT / "reports/deployment/p8-demo-oci-image-build.json"
DEFAULT_REPORT = ROOT / "reports/deployment/p8-demo-trust-admission.json"
PROJECT_NAME = "nex-platform-p8-demo-s08"


class DemoTrustAdmissionError(RuntimeError):
    pass


def run_p8_demo_trust_admission(
    environ: Mapping[str, str] | None = None,
    *,
    execute: bool = False,
    root: Path = ROOT,
    image_report_path: Path = DEFAULT_IMAGE_REPORT,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    inventory = demo_trust_projection()
    source = _source_admission(root, inventory=inventory)
    if not execute or env.get(EXECUTION_ENV) != "1":
        return {**source, "status": "SOURCE_ADMITTED", "executed": False}

    compose_environment: dict[str, str] | None = None
    secret_values: dict[str, str] = {}
    rotated_values: dict[str, str] = {}
    try:
        image_report = json.loads(image_report_path.read_text(encoding="utf-8"))
        image_environment = image_environment_from_release_report(image_report)
        with TemporaryDirectory(prefix="nex-p8-demo-s08-") as temporary:
            runtime_dir = Path(temporary) / "runtime"
            prepare_staging_runtime_directory(runtime_dir, owners=DEMO_OWNERS)
            compose_environment = {
                **env,
                **image_environment,
                "NEX_S143_RUNTIME_DIR": str(runtime_dir),
                "NEX_P8_DEMO_SEMANTIC_CALIBRATION_POLICIES_JSON": str(
                    env.get("NEX_P8_DEMO_SEMANTIC_CALIBRATION_POLICIES_JSON")
                    or "[]"
                ),
                "NEX_P8_DEMO_SECRET_VERSION": "v1",
                "NEX_P8_DEMO_SECRET_GENERATION": "secret:p8-demo.1",
                "NEX_P8_DEMO_TLS_GENERATION": "tls:p8-demo.1",
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
                client = OpenBaoAdminClient(
                    "https://127.0.0.1:8200",
                    ca_certificate_file=runtime_dir / "tls/openbao-ca.crt",
                )
                secret_values = _synthetic_secret_values()
                provisioning = provision_openbao_environment(
                    client,
                    root=root,
                    runtime_dir=runtime_dir,
                    secret_values=secret_values,
                    bindings=DEMO_SECRET_BINDINGS,
                    owners=DEMO_OWNERS,
                    subject_alt_names=DEMO_TLS_HOSTS,
                )
                initial = _resolve_generation(
                    provisioning,
                    runtime_dir,
                    version="v1",
                )
                _compose(
                    compose_environment,
                    root=root,
                    arguments=("restart", "openbao"),
                )
                restart_recovery = reactivate_openbao_after_restart(
                    client,
                    provisioning,
                )
                refresh_openbao_approle_credentials(
                    client,
                    root_token=provisioning.root_token,
                    runtime_dir=runtime_dir,
                    owners=DEMO_OWNERS,
                )
                cross_owner_denied = _cross_owner_denied(runtime_dir)

                rotated_values = {
                    name: f"p8-demo-rotated-{secrets.token_urlsafe(32)}"
                    for name in secret_values
                }
                versions = write_openbao_secret_generation(
                    client,
                    root_token=provisioning.root_token,
                    bindings=DEMO_SECRET_BINDINGS,
                    secret_values=rotated_values,
                )
                if set(versions.values()) != {2}:
                    raise DemoTrustAdmissionError(
                        "OpenBao Demo secret generation did not rotate atomically"
                    )
                refresh_openbao_approle_credentials(
                    client,
                    root_token=provisioning.root_token,
                    runtime_dir=runtime_dir,
                    owners=DEMO_OWNERS,
                )
                rotated = _resolve_generation(
                    provisioning,
                    runtime_dir,
                    version="v2",
                )
                certificate_hosts = _certificate_hosts(runtime_dir)
                routed_hosts = set(DEMO_TLS_HOSTS)
                if not routed_hosts.issubset(certificate_hosts) or (
                    certificate_hosts - routed_hosts
                ) - {"nex-staging.test"}:
                    raise DemoTrustAdmissionError("Demo PKI SAN coverage drift")
                result = {
                    **source,
                    "status": "PASS",
                    "executed": True,
                    "openbao": {
                        "storage": "integrated-raft",
                        "owner_count": len(provisioning.owners),
                        "secret_count": provisioning.secret_count,
                        "generations_verified": [1, 2],
                        "initial_owner_resolution_count": initial[
                            "resolved_owner_count"
                        ],
                        "rotated_owner_resolution_count": rotated[
                            "resolved_owner_count"
                        ],
                        "cross_owner_access_denied": cross_owner_denied,
                        "restart_recovery": restart_recovery,
                        "dependency_readiness": rotated["dependency_readiness"],
                    },
                    "pki": {
                        "routed_tls_host_count": len(routed_hosts),
                        "certificate_san_count": len(certificate_hosts),
                        "wc_eos_hosts_present": {
                            "wc.nex-staging.test",
                            "eos.nex-staging.test",
                        }.issubset(certificate_hosts),
                    },
                    "release_set_digest": image_report["release_manifest"][
                        "release_set_digest"
                    ],
                    "raw_secret_values_included": False,
                    "token_values_included": False,
                    "runtime_residue_retained": False,
                }
                _assert_redacted(result, secret_values, rotated_values)
            finally:
                _compose(
                    compose_environment,
                    root=root,
                    arguments=("down", "--volumes", "--remove-orphans"),
                    check=False,
                )
        return result
    except (
        OSError,
        KeyError,
        TypeError,
        ValueError,
        RuntimeError,
        subprocess.SubprocessError,
    ) as exc:
        return {
            **source,
            "status": "FAIL",
            "executed": True,
            "issues": [str(exc)],
            "raw_secret_values_included": False,
            "token_values_included": False,
        }


def _source_admission(root: Path, *, inventory: Mapping[str, Any]) -> dict[str, Any]:
    paths = (BASE_COMPOSE, OBJECT_COMPOSE, DEMO_COMPOSE)
    if not all((root / path).is_file() for path in paths):
        raise DemoTrustAdmissionError("P8 Demo Compose source is unavailable")
    compose_text = "\n".join(
        (root / path).read_text(encoding="utf-8") for path in paths
    )
    required = tuple(
        f"{binding.source_environment_name}: secret://openbao/"
        f"nex-platform/staging/{binding.owner}/{binding.target_environment_name}@"
        for binding in DEMO_SECRET_BINDINGS
    )
    missing = [
        value.split(":", 1)[0] for value in required if value not in compose_text
    ]
    if missing:
        raise DemoTrustAdmissionError(
            f"P8 Demo OpenBao reference coverage drift: {missing[0]}"
        )
    if any(
        marker in compose_text
        for marker in (
            "nuri1004",
            "NEX_WC_TEST_DATABASE_URL",
            "NEX_EOS_TEST_DATABASE_URL",
        )
    ):
        raise DemoTrustAdmissionError(
            "P8 Demo Compose contains a forbidden secret input"
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "slice": "P8-DEMO-S08",
        "inventory": dict(inventory),
        "compose_source_count": len(paths),
        "source_admitted": True,
        "raw_secret_values_included": False,
        "token_values_included": False,
    }


def _synthetic_secret_values() -> dict[str, str]:
    return {
        binding.target_environment_name: f"p8-demo-{secrets.token_urlsafe(32)}"
        for binding in DEMO_SECRET_BINDINGS
    }


def _resolve_generation(
    provisioning: OpenBaoProvisioningSession,
    runtime_dir: Path,
    *,
    version: str,
) -> dict[str, Any]:
    return verify_openbao_runtime_resolution(
        provisioning,
        resolver_environments={
            owner: _resolver_environment(runtime_dir, owner) for owner in DEMO_OWNERS
        },
        bindings=DEMO_SECRET_BINDINGS,
        namespace="staging",
        reference_version=version,
        secret_generation=f"secret:p8-demo.{version[1:]}",
    )


def _cross_owner_denied(runtime_dir: Path) -> bool:
    refresh_error = "OpenBao owner isolation was not denied"
    resolver = build_openbao_secret_resolver(
        _resolver_environment(runtime_dir, "nex-oa")
    )
    binding = next(item for item in DEMO_SECRET_BINDINGS if item.owner == "nex-mo")
    try:
        resolver.resolve(
            _reference(binding.owner, binding.target_environment_name, "v1"),
            context=SecretResolutionContext(
                owner="nex-mo",
                target_environment_name=binding.target_environment_name,
                secret_generation="secret:p8-demo.1",
                reference_version="v1",
            ),
        )
    except OpenBaoSecretResolverError:
        return True
    finally:
        with suppress(Exception):
            resolver.revoke()
    raise DemoTrustAdmissionError(refresh_error)


def _resolver_environment(runtime_dir: Path, owner: str) -> dict[str, str]:
    return {
        "NEX_OPENBAO_ADDR": "https://127.0.0.1:8200",
        "NEX_OPENBAO_CA_CERT_FILE": str(runtime_dir / "tls/openbao-ca.crt"),
        "NEX_OPENBAO_ROLE_ID_FILE": str(runtime_dir / f"credentials/{owner}.role-id"),
        "NEX_OPENBAO_SECRET_ID_FILE": str(
            runtime_dir / f"credentials/{owner}.secret-id"
        ),
        "NEX_OPENBAO_SECRET_NAMESPACE": "staging",
        "NEX_OPENBAO_TIMEOUT_SECONDS": "10",
    }


def _reference(owner: str, target: str, version: str) -> str:
    return f"secret://openbao/nex-platform/staging/{owner}/{target}@{version}"


def _certificate_hosts(runtime_dir: Path) -> set[str]:
    certificate = x509.load_pem_x509_certificate(
        (runtime_dir / "tls/platform.crt").read_bytes()
    )
    extension = certificate.extensions.get_extension_for_class(
        x509.SubjectAlternativeName
    )
    return set(extension.value.get_values_for_type(x509.DNSName))


def _compose(
    environ: Mapping[str, str],
    *,
    root: Path,
    arguments: Sequence[str],
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    command = ["docker", "compose", "-p", PROJECT_NAME]
    for path in (BASE_COMPOSE, OBJECT_COMPOSE, DEMO_COMPOSE):
        command.extend(("-f", str(root / path)))
    completed = subprocess.run(
        (*command, *arguments),
        cwd=root,
        env=dict(environ),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=300,
    )
    if check and completed.returncode != 0:
        detail = next(
            (
                line.strip()[-400:]
                for line in reversed(completed.stdout.splitlines())
                if line.strip()
            ),
            "no Docker output",
        )
        raise DemoTrustAdmissionError(f"P8 Demo OpenBao Compose failed: {detail}")
    return completed


def _assert_redacted(
    result: Mapping[str, Any], *secret_sets: Mapping[str, str]
) -> None:
    serialized = json.dumps(result, sort_keys=True)
    if any(value in serialized for values in secret_sets for value in values.values()):
        raise DemoTrustAdmissionError("raw secret leaked into P8 Demo trust evidence")


def _write_report(path: Path, result: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def summary_line(result: Mapping[str, Any]) -> str:
    openbao = dict(result.get("openbao") or {})
    return (
        f"p8_demo_trust={str(result.get('status') or 'FAIL').lower()} "
        f"executed={str(result.get('executed') is True).lower()} "
        f"owners={openbao.get('owner_count', result['inventory']['owner_count'])} "
        f"secrets={openbao.get('secret_count', result['inventory']['secret_binding_count'])} "
        "raw_secret=false"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Admit P8 Demo OpenBao trust and PKI.")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--image-report", type=Path, default=DEFAULT_IMAGE_REPORT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    result = run_p8_demo_trust_admission(
        execute=args.execute,
        image_report_path=args.image_report,
    )
    _write_report(args.report, result)
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] in {"PASS", "SOURCE_ADMITTED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
