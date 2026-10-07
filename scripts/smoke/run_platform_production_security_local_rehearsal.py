#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
from pathlib import Path
import secrets
import ssl
import stat
import subprocess
import sys
from tempfile import TemporaryDirectory
import threading
from typing import Any
from urllib.parse import urlsplit
from urllib.request import urlopen

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))

from nex_runtime.production_configuration import (  # noqa: E402
    load_production_configuration_manifest,
)
from nex_runtime.production_secret_materialization import (  # noqa: E402
    ResolvedSecret,
    SecretResolutionContext,
    materialize_production_secrets,
)
from nex_runtime.production_secret_rotation import (  # noqa: E402
    OWNER_ORDER,
    OwnerRotationObservation,
    build_secret_rotation_plan,
    evaluate_secret_rotation,
)
from nex_runtime.production_tls_lifecycle import (  # noqa: E402
    ManagedCertificateMetadata,
    build_production_tls_lifecycle_plan,
    evaluate_production_tls_lifecycle,
)
from run_platform_production_startup_admission import _synthetic_environment  # noqa: E402


ENABLE_ENV = "NEX_S143_LOCAL_SECURITY_REHEARSAL"
SCHEMA_VERSION = "platform_production_security_local_rehearsal_evidence.v1"
NOW = datetime(2026, 10, 7, 6, 0, tzinfo=UTC)
_CHILD_CODE = """
import json, os
owner = os.environ['NEX_REHEARSAL_OWNER']
generation = os.environ['NEX_REHEARSAL_GENERATION']
expected = tuple(json.loads(os.environ['NEX_REHEARSAL_TARGETS']))
provider = ('NEX_MO_REMOTE_EMBEDDING_API_KEY', 'NEX_MO_REMOTE_RERANKER_API_KEY', 'NEX_MO_VLLM_API_KEY')
assert all(os.environ.get(name) for name in expected)
assert owner == 'nex-mo' or not any(name in os.environ for name in provider)
print(json.dumps({'owner': owner, 'generation': generation, 'secret_count': len(expected)}, sort_keys=True))
"""


class LocalRehearsalError(RuntimeError):
    pass


class _FileSecretResolver:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def resolve(
        self,
        reference: str,
        *,
        context: SecretResolutionContext,
    ) -> ResolvedSecret:
        provider = urlsplit(reference).hostname or ""
        path = (self.root / context.reference_version / context.target_environment_name).resolve()
        if self.root not in path.parents or stat.S_IMODE(path.stat().st_mode) != 0o600:
            raise LocalRehearsalError("local secret file custody is invalid")
        return ResolvedSecret(
            owner=context.owner,
            target_environment_name=context.target_environment_name,
            secret_generation=context.secret_generation,
            reference_version=context.reference_version,
            provider_id=provider,
            value=path.read_text(encoding="utf-8"),
        )


def run_platform_production_security_local_rehearsal(
    environ: Mapping[str, str] | None = None,
    *,
    executor: Callable[[], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(ENABLE_ENV) != "1":
        return {
            "evidence_schema_version": SCHEMA_VERSION,
            "slice": "1430",
            "requirement": "S143",
            "status": "SKIPPED",
            "skip_reason": f"{ENABLE_ENV} is not enabled.",
            "actual_local_execution": False,
        }
    if env.get("NEX_PROFILE", "test") != "test":
        return _failure("protected local rehearsal requires the test profile")
    try:
        evidence = dict((executor or _execute_rehearsal)())
    except Exception:
        return _failure("protected local security rehearsal failed")
    checks = dict(evidence.get("checks") or {})
    passed = bool(checks) and all(value is True for value in checks.values())
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1430",
        "requirement": "S143",
        "status": "PASS" if passed else "FAIL",
        "actual_local_execution": True,
        "checks": checks,
        "summary": dict(evidence.get("summary") or {}),
        "decision": {
            "local_rotation_tls_rehearsal_passed": passed,
            "external_secret_provider_contacted": False,
            "external_tls_endpoint_contacted": False,
            "production_deployment_approved": False,
            "next_slice": "1431" if passed else "blocked",
        },
    }


def _execute_rehearsal() -> dict[str, Any]:
    temporary_path: Path | None = None
    protected: dict[str, Any]
    with TemporaryDirectory(prefix="nex-s143-security-") as temporary:
        temporary_path = Path(temporary)
        secret_root = temporary_path / "secrets"
        secret_file_count, secret_modes_valid = _write_secret_generations(secret_root)
        previous_env = _rehearsal_environment("v1", "secret:local-rehearsal.1")
        candidate_env = _rehearsal_environment("v2", "secret:local-rehearsal.2")
        resolver = _FileSecretResolver(secret_root)
        previous = materialize_production_secrets(previous_env, resolver, root=ROOT)
        candidate = materialize_production_secrets(candidate_env, resolver, root=ROOT)
        private_values = tuple(
            secret.value
            for materialization in (previous, candidate)
            for owner_environment in materialization.owner_environments
            for secret in owner_environment.secrets
        )
        rotation = build_secret_rotation_plan(previous, candidate)
        candidate_processes = _run_owner_processes(candidate, OWNER_ORDER)
        candidate_observations = _process_observations(
            candidate_processes, rotation.candidate_generation
        )
        verified = evaluate_secret_rotation(rotation, candidate_observations)
        failed_values = list(candidate_observations)
        failed_values[2] = replace(failed_values[2], readiness_verified=False)
        rollback_decision = evaluate_secret_rotation(rotation, failed_values)
        rollback_processes = _run_owner_processes(
            previous, tuple(reversed(OWNER_ORDER))
        )
        tls = _run_tls_rehearsal(temporary_path)
        protected = {
            "checks": {
                "candidate_owner_processes_verified": (
                    verified.status == "VERIFIED"
                    and len(candidate_processes) == 5
                ),
                "rollback_required_on_failed_owner": (
                    rollback_decision.status == "ROLLBACK_REQUIRED"
                    and rollback_decision.rollback_owners
                    == tuple(reversed(OWNER_ORDER))
                ),
                "previous_generation_restored": (
                    len(rollback_processes) == 5
                    and all(
                        item["generation"] == previous.secret_generation
                        for item in rollback_processes
                    )
                ),
                "current_candidate_and_rollback_tls_probed": tls["probe_count"] == 3,
                "secret_files_mode_0600": secret_modes_valid,
                "tls_private_key_mode_0600": tls["private_key_mode"] == "0600",
                "private_values_absent_from_evidence": False,
            },
            "summary": {
                "secret_file_count": secret_file_count,
                "candidate_owner_process_count": len(candidate_processes),
                "rollback_owner_process_count": len(rollback_processes),
                "tls_probe_count": tls["probe_count"],
                "temporary_residue_count": 0,
            },
        }
        protected["checks"]["private_values_absent_from_evidence"] = (
            _evidence_excludes_private_values(protected, private_values)
        )
    residue_count = int(temporary_path is not None and temporary_path.exists())
    protected["checks"]["temporary_residue_removed"] = residue_count == 0
    protected["summary"]["temporary_residue_count"] = residue_count
    return protected


def _evidence_excludes_private_values(
    evidence: dict[str, Any], private_values: tuple[str, ...]
) -> bool:
    serialized = json.dumps(evidence, ensure_ascii=True, sort_keys=True)
    return bool(private_values) and all(
        private_value not in serialized for private_value in private_values
    )


def _write_secret_generations(root: Path) -> tuple[int, bool]:
    manifest = load_production_configuration_manifest(ROOT)
    targets = tuple(
        item.target_environment_name
        for item in manifest.bindings
        if item.input_kind == "external_secret_reference"
    )
    for version in ("v1", "v2"):
        directory = root / version
        directory.mkdir(parents=True)
        directory.chmod(0o700)
        for target in targets:
            path = directory / target
            path.write_text(secrets.token_urlsafe(32), encoding="utf-8")
            path.chmod(0o600)
    paths = tuple(path for path in root.glob("*/*") if path.is_file())
    return len(paths), all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in paths)


def _rehearsal_environment(version: str, generation: str) -> dict[str, str]:
    environment = _synthetic_environment(ROOT)
    environment["NEX_SECRET_GENERATION"] = generation
    for name, value in tuple(environment.items()):
        if name.endswith("_REF") and value.startswith("secret://"):
            target = name.removesuffix("_REF").lower().replace("_", "-")
            environment[name] = f"secret://local/rehearsal/{target}@{version}"
    return environment


def _run_owner_processes(materialization, owners) -> tuple[dict[str, Any], ...]:
    results = []
    for owner in owners:
        owner_environment = materialization.environment_for(owner)
        process_environment = {
            "PATH": os.environ.get("PATH", ""),
            "NEX_REHEARSAL_OWNER": owner,
            "NEX_REHEARSAL_GENERATION": materialization.secret_generation,
            "NEX_REHEARSAL_TARGETS": json.dumps(sorted(owner_environment)),
            **owner_environment,
        }
        completed = subprocess.run(
            [sys.executable, "-c", _CHILD_CODE],
            env=process_environment,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if completed.returncode != 0:
            raise LocalRehearsalError("owner process rehearsal failed")
        results.append(json.loads(completed.stdout))
    return tuple(results)


def _process_observations(results, generation):
    return tuple(
        OwnerRotationObservation(
            owner=item["owner"],
            generation=generation,
            restart_completed=True,
            readiness_verified=True,
            secret_count=int(item["secret_count"]),
        )
        for item in results
    )


def _run_tls_rehearsal(root: Path) -> dict[str, Any]:
    current_cert, current_key = _write_loopback_certificate(root, "current")
    candidate_cert, candidate_key = _write_loopback_certificate(root, "candidate")
    environment = _rehearsal_environment("v2", "secret:local-rehearsal.2")
    environment["NEX_TLS_GENERATION"] = "tls:local-rehearsal.2"
    environment["NEX_TLS_CERTIFICATE_REF"] = "tls://local/platform/certificate@v2"
    environment["NEX_TLS_TRUST_BUNDLE_REF"] = "tls://local/platform/trust-bundle@v2"
    current = ManagedCertificateMetadata("current", "v1", "ACTIVE", NOW - timedelta(minutes=5), NOW + timedelta(days=1), "local-ca", 1)
    candidate = ManagedCertificateMetadata("candidate", "v2", "CANDIDATE", NOW - timedelta(hours=2), NOW + timedelta(days=2), "local-ca", 1)
    plan = build_production_tls_lifecycle_plan(environment, current, candidate, root=ROOT)
    verified = evaluate_production_tls_lifecycle(
        plan,
        observed_at=NOW,
        activation_attempted=True,
        candidate_probe_verified=True,
        candidate_verified_at=NOW - timedelta(hours=2),
    )
    rollback = evaluate_production_tls_lifecycle(
        plan,
        observed_at=NOW,
        activation_attempted=True,
        candidate_probe_verified=False,
    )
    probes = 0
    for cert_path, key_path in (
        (current_cert, current_key),
        (candidate_cert, candidate_key),
        (current_cert, current_key),
    ):
        server = _TlsHealthServer(cert_path, key_path)
        try:
            server.start()
            server.probe()
            probes += 1
        finally:
            server.stop()
    if verified.status != "VERIFIED" or rollback.status != "ROLLBACK_REQUIRED":
        raise LocalRehearsalError("TLS lifecycle rehearsal decision failed")
    return {
        "probe_count": probes,
        "private_key_mode": oct(stat.S_IMODE(candidate_key.stat().st_mode))[2:].zfill(4),
    }


class _TlsHealthServer:
    def __init__(self, cert_path: Path, key_path: Path) -> None:
        self.cert_path = cert_path
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(str(cert_path), str(key_path))
        self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.started = False

    def start(self) -> None:
        self.thread.start()
        self.started = True

    def probe(self) -> None:
        context = ssl.create_default_context(cafile=str(self.cert_path))
        port = int(self.server.server_address[1])
        with urlopen(f"https://127.0.0.1:{port}/healthz", context=context, timeout=5) as response:
            if response.status != 200 or json.loads(response.read()) != {"status": "ok"}:
                raise LocalRehearsalError("loopback TLS probe failed")

    def stop(self) -> None:
        if self.started:
            self.server.shutdown()
            self.thread.join(timeout=5)
        self.server.server_close()

    @staticmethod
    def _handler():
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                if self.path != "/healthz":
                    self.send_error(404)
                    return
                body = b'{"status":"ok"}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_: Any) -> None:
                return None

        return Handler


def _write_loopback_certificate(root: Path, name: str) -> tuple[Path, Path]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"nex-s143-{name}")])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(minutes=1))
        .not_valid_after(datetime.now(UTC) + timedelta(minutes=10))
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path = root / f"{name}-cert.pem"
    key_path = root / f"{name}-key.pem"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    cert_path.chmod(0o644)
    key_path.chmod(0o600)
    return cert_path, key_path


def _failure(reason: str) -> dict[str, Any]:
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1430",
        "requirement": "S143",
        "status": "FAIL",
        "failure_code": "production_security_local_rehearsal_failed",
        "reason": reason,
        "actual_local_execution": False,
        "decision": {"next_slice": "blocked"},
    }


def summary_line(result: Mapping[str, Any]) -> str:
    status = str(result.get("status") or "FAIL")
    if status == "SKIPPED":
        return "platform_production_security_local_rehearsal=skip"
    if status != "PASS":
        return "platform_production_security_local_rehearsal=fail"
    summary = dict(result.get("summary") or {})
    return (
        "platform_production_security_local_rehearsal=pass "
        f"candidate_processes={summary.get('candidate_owner_process_count', 0)} "
        f"rollback_processes={summary.get('rollback_owner_process_count', 0)} "
        f"tls_probes={summary.get('tls_probe_count', 0)} "
        f"residue={summary.get('temporary_residue_count', 0)} next=1431"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_platform_production_security_local_rehearsal()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 1 if result["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
