#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "p8_s06_nsl_compatibility_evidence.v1"
SMOKE_ENV = "NEX_AE_P8_S06_NSL_COMPATIBILITY_SMOKE"
DEFAULT_SOURCE = Path("/home/tprover/2608_nsl")
DEFAULT_V01_LOCK = ROOT / "deployment/locks/nsl-v0.1-wheel.json"
DEFAULT_V02_LOCK = ROOT / "deployment/locks/nsl-v0.2-wheel.json"
DEFAULT_V02_WHEEL_DIRECTORY = ROOT / "reports/deployment/p8-nsl-v0.2-wheel"
DEFAULT_PLATFORM_LOCK = ROOT / "deployment/locks/python-production.lock"
DEFAULT_REPORT = ROOT / "reports/quality/p8-s06-nsl-compatibility.json"
SHARED_SOURCE = ROOT / "services/_shared"
AE_SOURCE = ROOT / "services/nex-ae-api"


class P8S06CompatibilityError(RuntimeError):
    pass


def run_p8_s06_nsl_compatibility(
    environ: Mapping[str, str] | None = None,
    *,
    execute: bool,
    source: Path = DEFAULT_SOURCE,
    v01_lock_path: Path = DEFAULT_V01_LOCK,
    v02_lock_path: Path = DEFAULT_V02_LOCK,
    wheel_directory: Path = DEFAULT_V02_WHEEL_DIRECTORY,
    report_path: Path = DEFAULT_REPORT,
    python_bin: str = sys.executable,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if not execute or env.get(SMOKE_ENV) != "1":
        return {
            "schema_version": SCHEMA_VERSION,
            "slice": "P8-S06",
            "status": "SKIPPED",
            "skip_reason": f"--execute and {SMOKE_ENV}=1 are required",
        }
    try:
        v01_lock = _load_object(v01_lock_path, "NSL v0.1 wheel lock")
        v02_lock = _load_object(v02_lock_path, "NSL v0.2 wheel lock")
        release = _verify_v02_release(source, wheel_directory, v02_lock)
        host_version_before = _installed_distribution_version(
            str(v01_lock["distribution"])
        )
        v01_read = _run_json(
            (
                python_bin,
                "-m",
                "nsl",
                "run",
                "--profile",
                str(source / "examples/project_budget_check.profile.json"),
                "--execution-id",
                "p8-s06-v01-read",
            ),
            operation="execute NSL v0.1 READ regression",
            env=env,
        )
        with TemporaryDirectory(prefix="p8-s06-nsl-v02-") as temporary:
            temporary_root = Path(temporary)
            target = temporary_root / "site-packages"
            wheel = wheel_directory / str(v02_lock["wheel_filename"])
            _install_wheel(python_bin, wheel, target, env)
            v02_env = _isolated_environment(env, target)
            adapter = _inspect_v02_adapter(
                python_bin=python_bin,
                target=target,
                lock_path=v02_lock_path,
                env=v02_env,
            )
            v02_read = _run_json(
                (
                    python_bin,
                    "-m",
                    "nsl",
                    "run",
                    "--profile",
                    str(source / "examples/voucher_draft_validation/profile.json"),
                    "--no-isolate",
                    "--execution-id",
                    "p8-s06-v02-read",
                ),
                operation="execute NSL v0.2 READ smoke",
                env=v02_env,
            )
            checkpoint = temporary_root / "controlled-prefix.nsc"
            approval = temporary_root / "approval-request.json"
            audit = temporary_root / "controlled-prefix.audit.jsonl"
            controlled = _run_json(
                (
                    python_bin,
                    "-m",
                    "nsl",
                    "run",
                    "--profile",
                    str(
                        source
                        / "examples/voucher_draft_validation/controlled.profile.json"
                    ),
                    "--execution-id",
                    "p8-s06-v02-controlled-prefix",
                    "--business-operation-id",
                    "p8-s06-controlled-prefix",
                    "--checkpoint-out",
                    str(checkpoint),
                    "--approval-request-out",
                    str(approval),
                    "--audit-out",
                    str(audit),
                ),
                operation="execute NSL v0.2 controlled WRITE prefix",
                env=v02_env,
            )
            protected_artifacts = {
                "checkpoint_created": checkpoint.is_file()
                and checkpoint.stat().st_size > 0,
                "approval_request_created": approval.is_file()
                and approval.stat().st_size > 0,
            }
            audit_summary = _audit_summary(audit)
        host_version_after = _installed_distribution_version(
            str(v01_lock["distribution"])
        )
        checks = _compatibility_checks(
            v01_lock=v01_lock,
            v02_lock=v02_lock,
            release=release,
            host_version_before=host_version_before,
            host_version_after=host_version_after,
            v01_read=v01_read,
            adapter=adapter,
            v02_read=v02_read,
            controlled=controlled,
            protected_artifacts=protected_artifacts,
            audit_summary=audit_summary,
        )
        evidence = {
            "schema_version": SCHEMA_VERSION,
            "slice": "P8-S06",
            "status": "PASS" if all(checks.values()) else "FAIL",
            "release": release,
            "v01_read": _read_summary(v01_read, host_version_before),
            "v02_adapter": adapter,
            "v02_read": _read_summary(v02_read, str(v02_lock["package_version"])),
            "controlled_prefix": _controlled_summary(
                controlled, protected_artifacts, audit_summary
            ),
            "checks": checks,
            "checks_passed": sum(checks.values()),
            "checks_total": len(checks),
            "decision": {
                "p8_1_closed": all(checks.values()),
                "eos_adapter_configured": False,
                "eos_mutation_count": 0 if checks["zero_eos_mutation"] else None,
                "remote_provider_required": False,
            },
        }
    except (
        json.JSONDecodeError,
        KeyError,
        OSError,
        P8S06CompatibilityError,
        subprocess.SubprocessError,
        TypeError,
        ValueError,
    ) as exc:
        evidence = {
            "schema_version": SCHEMA_VERSION,
            "slice": "P8-S06",
            "status": "FAIL",
            "issues": [str(exc)],
            "decision": {
                "p8_1_closed": False,
                "eos_adapter_configured": False,
            },
        }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return evidence


def _verify_v02_release(
    source: Path, wheel_directory: Path, lock: Mapping[str, Any]
) -> dict[str, Any]:
    wheel = wheel_directory / str(lock.get("wheel_filename", ""))
    if not wheel.is_file():
        raise P8S06CompatibilityError("admitted NSL v0.2 wheel is missing")
    revision = _capture(
        ("git", "-C", str(source), "rev-parse", "HEAD"),
        operation="read NSL v0.2 source revision",
    ).strip()
    tree = _capture(
        ("git", "-C", str(source), "rev-parse", "HEAD^{tree}"),
        operation="read NSL v0.2 source tree",
    ).strip()
    dirty = _capture(
        ("git", "-C", str(source), "status", "--porcelain"),
        operation="inspect NSL v0.2 source status",
    ).strip()
    wheel_sha256 = _sha256_ref(wheel.read_bytes())
    if (
        revision != lock.get("source_revision")
        or tree != lock.get("source_tree")
        or dirty
        or wheel_sha256 != lock.get("wheel_sha256")
    ):
        raise P8S06CompatibilityError("NSL v0.2 release identity drifted")
    return {
        "source_revision": revision,
        "source_tree": tree,
        "wheel_sha256": wheel_sha256,
        "source_tree_clean": True,
    }


def _install_wheel(
    python_bin: str,
    wheel: Path,
    target: Path,
    env: Mapping[str, str],
) -> None:
    _capture(
        (
            python_bin,
            "-m",
            "pip",
            "install",
            "--quiet",
            "--no-deps",
            "--target",
            str(target),
            str(wheel),
        ),
        operation="install admitted NSL v0.2 wheel",
        env=env,
    )


def _inspect_v02_adapter(
    *,
    python_bin: str,
    target: Path,
    lock_path: Path,
    env: Mapping[str, str],
) -> dict[str, Any]:
    script = (
        "import json; "
        "from pathlib import Path; "
        "from nex_runtime.nsl_package_admission import inspect_installed_nsl_package; "
        "from nex_ae_api.nsl_v02_public_api import load_nsl_v02_public_api; "
        f"lock=json.loads(Path({str(lock_path)!r}).read_text(encoding='utf-8')); "
        f"ready=inspect_installed_nsl_package(lock,platform_lock_path=Path({str(DEFAULT_PLATFORM_LOCK)!r})); "
        "adapter=load_nsl_v02_public_api(ready); "
        "print(json.dumps({'readiness_status':ready['status'],"
        "'readiness_schema_version':ready['schema_version'],"
        "'adapter_schema_version':adapter.schema_version,"
        "'release_admission_hash':adapter.release_admission_hash,"
        "'api_contract_hash':adapter.api_contract_hash,"
        "'public_api_symbols':list(adapter.symbols())},sort_keys=True))"
    )
    adapter_env = dict(env)
    adapter_env["PYTHONPATH"] = os.pathsep.join(
        (str(target), str(AE_SOURCE), str(SHARED_SOURCE))
    )
    return _run_json(
        (python_bin, "-c", script),
        operation="inspect admitted NSL v0.2 public API adapter",
        env=adapter_env,
    )


def _compatibility_checks(
    *,
    v01_lock: Mapping[str, Any],
    v02_lock: Mapping[str, Any],
    release: Mapping[str, Any],
    host_version_before: str,
    host_version_after: str,
    v01_read: Mapping[str, Any],
    adapter: Mapping[str, Any],
    v02_read: Mapping[str, Any],
    controlled: Mapping[str, Any],
    protected_artifacts: Mapping[str, bool],
    audit_summary: Mapping[str, Any],
) -> dict[str, bool]:
    v01_result = _object(v01_read.get("result"), "v0.1 READ result")
    v02_result = _object(v02_read.get("result"), "v0.2 READ result")
    controlled_result = _object(
        controlled.get("result"), "v0.2 controlled-prefix result"
    )
    validation = _object(v02_result.get("validation"), "v0.2 READ validation")
    controlled_validation = _object(
        controlled_result.get("validation"), "controlled-prefix validation"
    )
    event_types = tuple(audit_summary.get("event_types", ()))
    tool_ids = tuple(audit_summary.get("tool_ids", ()))
    return {
        "release_identity_exact": release.get("source_revision")
        == v02_lock.get("source_revision")
        and release.get("source_tree") == v02_lock.get("source_tree")
        and release.get("wheel_sha256") == v02_lock.get("wheel_sha256"),
        "v01_host_preserved": host_version_before
        == host_version_after
        == v01_lock.get("package_version"),
        "v01_read_regression": v01_result.get("status") == "COMPLETED"
        and v01_result.get("error") is None
        and bool(v01_result.get("outputs")),
        "v02_public_api_admitted": adapter.get("readiness_status") == "PASS"
        and adapter.get("readiness_schema_version")
        == "nsl_installed_package_readiness.v2"
        and adapter.get("adapter_schema_version")
        == "ae_nsl_v02_public_api_adapter.v1"
        and tuple(adapter.get("public_api_symbols", ()))
        == tuple(v02_lock.get("public_api_symbols", ())),
        "v02_read_smoke": v02_result.get("status") == "COMPLETED"
        and v02_result.get("error") is None
        and v02_result.get("write") is None
        and validation.get("status") == "ALL_PASS",
        "v02_controlled_prefix": controlled_result.get("status")
        == "WAITING_FOR_APPROVAL"
        and controlled_result.get("write") is None
        and controlled_result.get("pre_write_eligibility") == "REQUIRES_APPROVAL"
        and controlled_validation.get("status") == "ALL_PASS",
        "protected_suspend_artifacts": all(protected_artifacts.values())
        and "CLI_APPROVAL_SUSPENDED" in event_types,
        "zero_eos_mutation": "WRITE_REQUESTED" not in event_types
        and "FINANCE.CREATE_VOUCHER_DRAFT" not in tool_ids
        and controlled_result.get("write") is None
        and not controlled_result.get("outputs"),
    }


def _read_summary(payload: Mapping[str, Any], package_version: str) -> dict[str, Any]:
    result = _object(payload.get("result"), "NSL READ result")
    resources = _object(result.get("resources"), "NSL READ resources")
    return {
        "package_version": package_version,
        "skill_id": result.get("skill_id"),
        "runtime_status": result.get("status"),
        "tool_calls": resources.get("tool_calls"),
        "output_count": len(result.get("outputs", ())),
    }


def _controlled_summary(
    payload: Mapping[str, Any],
    protected_artifacts: Mapping[str, bool],
    audit_summary: Mapping[str, Any],
) -> dict[str, Any]:
    result = _object(payload.get("result"), "controlled-prefix result")
    return {
        "runtime_status": result.get("status"),
        "pre_write_eligibility": result.get("pre_write_eligibility"),
        "write_result_present": result.get("write") is not None,
        "output_count": len(result.get("outputs", ())),
        "protected_artifacts": dict(protected_artifacts),
        "audit": dict(audit_summary),
    }


def _audit_summary(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise P8S06CompatibilityError("controlled-prefix audit is missing")
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    if not events or not all(isinstance(item, Mapping) for item in events):
        raise P8S06CompatibilityError("controlled-prefix audit is invalid")
    event_types = [str(item.get("event_type", "")) for item in events]
    tool_ids = [
        str(item["payload"].get("tool_id"))
        for item in events
        if item.get("event_type") == "TOOL_STARTED"
        and isinstance(item.get("payload"), Mapping)
    ]
    return {
        "event_count": len(events),
        "event_types": sorted(set(event_types)),
        "tool_ids": tool_ids,
        "write_requested_count": event_types.count("WRITE_REQUESTED"),
    }


def _isolated_environment(
    env: Mapping[str, str], target: Path
) -> dict[str, str]:
    isolated = dict(env)
    isolated["PYTHONPATH"] = str(target)
    isolated["PYTHONDONTWRITEBYTECODE"] = "1"
    return isolated


def _run_json(
    command: Sequence[str], *, operation: str, env: Mapping[str, str]
) -> dict[str, Any]:
    output = _capture(command, operation=operation, env=env)
    value = json.loads(output)
    return _object(value, f"{operation} output")


def _capture(
    command: Sequence[str],
    *,
    operation: str,
    env: Mapping[str, str] | None = None,
) -> str:
    completed = subprocess.run(
        tuple(command),
        cwd=ROOT,
        env=None if env is None else dict(env),
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise P8S06CompatibilityError(
            f"{operation} failed with exit code {completed.returncode}"
        )
    return completed.stdout


def _load_object(path: Path, label: str) -> dict[str, Any]:
    return _object(json.loads(path.read_text(encoding="utf-8")), label)


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise P8S06CompatibilityError(f"{label} must be an object")
    return dict(value)


def _installed_distribution_version(distribution: str) -> str:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError as exc:
        raise P8S06CompatibilityError(
            f"installed distribution is missing: {distribution}"
        ) from exc


def _sha256_ref(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def summary_line(evidence: Mapping[str, Any]) -> str:
    return (
        "p8_s06_nsl_compatibility="
        f"{str(evidence.get('status', 'FAIL')).lower()} "
        f"checks={evidence.get('checks_passed', 0)}/"
        f"{evidence.get('checks_total', 0)} "
        "eos_mutations="
        f"{evidence.get('decision', {}).get('eos_mutation_count', 'not-run')}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run P8-S06 NSL compatibility smoke")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--python-bin", default=sys.executable)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    result = run_p8_s06_nsl_compatibility(
        execute=args.execute,
        source=args.source,
        report_path=args.report,
        python_bin=args.python_bin,
    )
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
