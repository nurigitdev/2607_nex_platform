#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

ACTIVATION_ENV = "NEX_MO_DGX_PROCESS_DTYPE_PROBE"
SSH_TARGET_ENV = "NEX_MO_DGX_SSH_TARGET"
EVIDENCE_SCHEMA_VERSION = "mo_dgx_process_dtype_probe_evidence.v1"
RAW_SCHEMA_VERSION = "mo_dgx_process_dtype_probe.raw.v1"
EXPECTED_PROVIDERS = {
    9111: {"capability": "generation", "model": "Qwen3.5-4B"},
    9112: {"capability": "embedding", "model": "Qwen3-Embedding-4B"},
    9113: {"capability": "reranking", "model": "Qwen3-Reranker-4B"},
}
BF16_NAMES = {"bf16", "bfloat16"}
SSH_TARGET_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+@[A-Za-z0-9.-]+$")

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]

REMOTE_PROBE = r'''import json
import os

expected = {
    9111: "Qwen3.5-4B",
    9112: "Qwen3-Embedding-4B",
    9113: "Qwen3-Reranker-4B",
}


def option_value(arguments, name):
    for index, argument in enumerate(arguments):
        if argument == name and index + 1 < len(arguments):
            return arguments[index + 1]
        prefix = name + "="
        if argument.startswith(prefix):
            return argument[len(prefix):]
    return ""


def model_reference(arguments):
    configured = option_value(arguments, "--model")
    if configured:
        return configured, "model_flag"
    for index, argument in enumerate(arguments):
        if argument == "serve" and index + 1 < len(arguments):
            return arguments[index + 1], "serve_positional"
    return "", "missing"


def configured_dtype(arguments, process_id):
    reference, source = model_reference(arguments)
    if not reference:
        return "unknown", source, "reference_missing"
    if not os.path.isabs(reference):
        try:
            reference = os.path.join(os.readlink(f"/proc/{process_id}/cwd"), reference)
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            return "unknown", source, "cwd_unavailable"
    try:
        with open(os.path.join(reference, "config.json"), encoding="utf-8") as stream:
            config = json.load(stream)
    except FileNotFoundError:
        return "unknown", source, "config_missing"
    except NotADirectoryError:
        return "unknown", source, "reference_not_directory"
    except PermissionError:
        return "unknown", source, "config_forbidden"
    except json.JSONDecodeError:
        return "unknown", source, "config_invalid"
    value = config.get("torch_dtype", config.get("dtype", "unknown"))
    normalized = value.strip().lower() if isinstance(value, str) else "unknown"
    if normalized in {"bf16", "bfloat16", "float16", "float32"}:
        return normalized, source, "dtype_found"
    return "unknown", source, "dtype_missing"


observations = []
for entry in os.listdir("/proc"):
    if not entry.isdigit():
        continue
    try:
        raw = open(f"/proc/{entry}/cmdline", "rb").read()
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        continue
    arguments = [part.decode("utf-8", "replace") for part in raw.split(b"\0") if part]
    if not arguments or not any("vllm" in argument.lower() for argument in arguments):
        continue
    raw_port = option_value(arguments, "--port")
    try:
        port = int(raw_port)
    except ValueError:
        continue
    if port not in expected:
        continue
    dtype = option_value(arguments, "--dtype").strip().lower() or "auto"
    task = option_value(arguments, "--task").strip().lower() or "unspecified"
    if task not in {"generate", "embed", "embedding", "score", "rerank", "unspecified"}:
        task = "other"
    expected_model = expected[port]
    model_dtype, model_reference_source, model_config_status = configured_dtype(arguments, entry)
    observations.append(
        {
            "port": port,
            "dtype": dtype,
            "configured_dtype": model_dtype,
            "model_reference_source": model_reference_source,
            "model_config_status": model_config_status,
            "task": task,
            "expected_model_seen": any(
                expected_model == argument or expected_model in argument
                for argument in arguments
            ),
        }
    )

print(json.dumps({"schema_version": "mo_dgx_process_dtype_probe.raw.v1", "observations": observations}))
'''


def run_mo_dgx_process_dtype_probe(
    environ: dict[str, str] | None = None,
    *,
    command_runner: CommandRunner = subprocess.run,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    if env.get(ACTIVATION_ENV) != "1":
        return _evidence(
            status="SKIPPED",
            stage_status={"activation": "SKIPPED"},
            observations=[],
            issues=[{"stage": "activation", "error_code": "dtype_probe_not_enabled"}],
            target_configured=bool(env.get(SSH_TARGET_ENV)),
        )

    target = env.get(SSH_TARGET_ENV, "")
    if not SSH_TARGET_PATTERN.fullmatch(target):
        return _evidence(
            status="FAIL",
            stage_status={"activation": "PASS", "configuration": "FAIL"},
            observations=[],
            issues=[{"stage": "configuration", "error_code": "ssh_target_invalid"}],
            target_configured=bool(target),
        )

    command = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=5",
        target,
        "python3",
        "-",
    ]
    try:
        completed = command_runner(
            command,
            input=REMOTE_PROBE,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return _probe_failure("ssh_probe_timeout", target_configured=True)
    except OSError:
        return _probe_failure("ssh_probe_unavailable", target_configured=True)

    if completed.returncode != 0:
        return _probe_failure("ssh_probe_failed", target_configured=True)

    try:
        payload = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError):
        return _probe_failure("probe_output_invalid", target_configured=True)

    observations = _normalize_observations(payload)
    issues = _observation_issues(observations)
    return _evidence(
        status="PASS" if not issues else "FAIL",
        stage_status={
            "activation": "PASS",
            "configuration": "PASS",
            "ssh": "PASS",
            "assertions": "PASS" if not issues else "FAIL",
        },
        observations=observations,
        issues=issues,
        target_configured=True,
    )


def _normalize_observations(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or payload.get("schema_version") != RAW_SCHEMA_VERSION:
        return []
    raw_observations = payload.get("observations")
    if not isinstance(raw_observations, list):
        return []

    normalized = []
    for item in raw_observations:
        if not isinstance(item, dict):
            continue
        port = item.get("port")
        provider = EXPECTED_PROVIDERS.get(port)
        if provider is None:
            continue
        dtype = item.get("dtype")
        configured_dtype = item.get("configured_dtype")
        model_reference_source = item.get("model_reference_source")
        model_config_status = item.get("model_config_status")
        task = item.get("task")
        dtype_value = dtype if isinstance(dtype, str) else "invalid"
        configured_dtype_value = (
            configured_dtype if isinstance(configured_dtype, str) else "invalid"
        )
        bf16_explicit = dtype_value.lower() in BF16_NAMES
        bf16_from_auto = (
            provider["capability"] == "generation"
            and dtype_value.lower() == "auto"
            and configured_dtype_value.lower() in BF16_NAMES
        )
        normalized.append(
            {
                "capability": provider["capability"],
                "port": port,
                "dtype": dtype_value,
                "configured_dtype": configured_dtype_value,
                "model_reference_source": (
                    model_reference_source
                    if isinstance(model_reference_source, str)
                    else "invalid"
                ),
                "model_config_status": (
                    model_config_status
                    if isinstance(model_config_status, str)
                    else "invalid"
                ),
                "task": task if isinstance(task, str) else "invalid",
                "expected_model_seen": item.get("expected_model_seen") is True,
                "bf16_explicit": bf16_explicit,
                "bf16_confirmed": bf16_explicit or bf16_from_auto,
            }
        )
    return sorted(normalized, key=lambda item: item["port"])


def _observation_issues(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    by_port: dict[int, list[dict[str, Any]]] = {}
    for item in observations:
        by_port.setdefault(item["port"], []).append(item)

    for port, provider in EXPECTED_PROVIDERS.items():
        matches = by_port.get(port, [])
        if not matches:
            issues.append(
                {
                    "stage": "assertions",
                    "error_code": "provider_process_missing",
                    "capability": provider["capability"],
                }
            )
            continue
        if len(matches) > 1:
            issues.append(
                {
                    "stage": "assertions",
                    "error_code": "provider_process_ambiguous",
                    "capability": provider["capability"],
                }
            )
            continue
        observation = matches[0]
        if not observation["expected_model_seen"]:
            issues.append(
                {
                    "stage": "assertions",
                    "error_code": "expected_model_not_observed",
                    "capability": provider["capability"],
                }
            )
        if not observation["bf16_confirmed"]:
            issues.append(
                {
                    "stage": "assertions",
                    "error_code": "bf16_not_confirmed",
                    "capability": provider["capability"],
                }
            )
    return issues


def _probe_failure(error_code: str, *, target_configured: bool) -> dict[str, Any]:
    return _evidence(
        status="FAIL",
        stage_status={
            "activation": "PASS",
            "configuration": "PASS",
            "ssh": "FAIL",
        },
        observations=[],
        issues=[{"stage": "ssh", "error_code": error_code}],
        target_configured=target_configured,
    )


def _evidence(
    *,
    status: str,
    stage_status: dict[str, str],
    observations: list[dict[str, Any]],
    issues: list[dict[str, Any]],
    target_configured: bool,
) -> dict[str, Any]:
    return {
        "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
        "evidence_generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "status": status,
        "stage_status": stage_status,
        "target_configured": target_configured,
        "observations": observations,
        "issues": issues,
        "redaction": {
            "status": "PASS",
            "excluded": [
                "ssh_target",
                "process_id",
                "process_command_line",
                "model_path",
                "api_key",
            ],
        },
    }


def summary_line(evidence: dict[str, Any]) -> str:
    status = evidence["status"].lower()
    if evidence["status"] == "SKIPPED":
        return f"mo_dgx_process_dtype_probe={status} reason={ACTIVATION_ENV}"
    bf16_count = sum(item["bf16_confirmed"] for item in evidence["observations"])
    explicit_count = sum(item["bf16_explicit"] for item in evidence["observations"])
    return (
        f"mo_dgx_process_dtype_probe={status} "
        f"providers={len(evidence['observations'])}/3 "
        f"bf16={bf16_count}/3 explicit={explicit_count}/3"
    )


def write_evidence(output_path: Path, evidence: dict[str, Any]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        f"{json.dumps(evidence, ensure_ascii=False, indent=2)}\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Probe redacted DGX vLLM process dtype evidence over SSH."
    )
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_mo_dgx_process_dtype_probe()
    if args.output:
        write_evidence(args.output, evidence)
    if args.summary:
        print(summary_line(evidence))
    else:
        print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0 if evidence["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
