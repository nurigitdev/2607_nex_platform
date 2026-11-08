#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType
from typing import Any

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]
FROZEN_ROOT = Path(
    "docs/frozen/v2.1/10_PLATFORM_v2.1/03_NORMATIVE_V2_1_CONTRACTS/"
    "NeX_Platform_v2.1_Controlled_Amendment_Batch02_CP02_CP06/AE"
)
CANDIDATE_ROOT = Path("docs/transition/P4/P4_CA01_Candidate")
FROZEN_SCHEMA = FROZEN_ROOT / "execution-trigger-v2.1.schema.json"
FROZEN_PROTOCOL = FROZEN_ROOT / "execution_trigger_v2_1.py"
CANDIDATE_SCHEMA = CANDIDATE_ROOT / "execution-trigger-v2.1.schema.json"
CANDIDATE_PROTOCOL = CANDIDATE_ROOT / "execution_trigger_v2_1.py"
MANIFEST = Path("docs/transition/P4/P4_CA01_Controlled_Amendment_Manifest_v1.1.csv")

EXPECTED_FROZEN_HASHES = {
    str(FROZEN_SCHEMA): "f8b50623e5754fee52a335d7d9fd68a05b094e90af7f4874e22674325777ff27",
    str(FROZEN_PROTOCOL): "e312ff9542461b0b28d1b23245fb996c6504d801dbf946b009ecb1505010059a",
}
EXPECTED_SOURCE_TYPES = {"PROMPT", "CLAIMED_WORKITEM"}
EXPECTED_AGENT_TYPES = {"IA", "CA", "PA", "EA"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _load_protocol(path: Path) -> ModuleType:
    module_name = "p4_ca01_execution_trigger_v2_1"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load protocol: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _prompt_payload(*, project_id: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": "2.1",
        "trigger_id": "trg-p4-ca01-prompt",
        "source_type": "PROMPT",
        "source_ref": "interaction-p4-ca01",
        "tenant_id": "tenant-p4-ca01",
        "agent_type": "IA",
        "agent_id": "ia-p4-ca01",
        "project_id": project_id,
        "correlation_id": "corr-p4-ca01",
        "received_at": "2026-10-13T00:00:00Z",
    }


def _claimed_payload(*, agent_type: str = "PA") -> dict[str, Any]:
    return {
        "schema_version": "2.1",
        "trigger_id": "trg-p4-ca01-claim",
        "source_type": "CLAIMED_WORKITEM",
        "source_ref": "claim-p4-ca01",
        "tenant_id": "tenant-p4-ca01",
        "agent_type": agent_type,
        "agent_id": "agent-p4-ca01",
        "project_id": "project-p4-ca01",
        "work_item_ref": "work-p4-ca01",
        "claim_ref": "claim-p4-ca01",
        "claim_generation": 1,
        "assignment_ref": "assignment-p4-ca01",
        "correlation_id": "corr-p4-ca01",
        "received_at": "2026-10-13T00:00:00Z",
    }


def _schema_accepts(validator: Draft202012Validator, payload: dict[str, Any]) -> bool:
    return not list(validator.iter_errors(payload))


def _protocol_accepts(protocol: ModuleType, payload: dict[str, Any]) -> bool:
    constructor_payload = dict(payload)
    constructor_payload.pop("schema_version", None)
    try:
        protocol.ExecutionTriggerV21(**constructor_payload)
    except (TypeError, ValueError):
        return False
    return True


def _probe_cases() -> tuple[tuple[str, dict[str, Any], bool], ...]:
    prompt_with_project = _prompt_payload(project_id="project-p4-ca01")
    prompt_with_pa = {**_prompt_payload(), "agent_type": "PA"}
    claimed_without_project = {**_claimed_payload(), "project_id": None}
    claimed_with_ia = _claimed_payload(agent_type="IA")
    missing_tenant = _prompt_payload()
    missing_tenant.pop("tenant_id")
    blank_project = _prompt_payload(project_id="")
    invalid_generation = {**_claimed_payload(), "claim_generation": 0}
    return (
        ("prompt_ia_null_project", _prompt_payload(), True),
        ("prompt_ia_resolved_project", prompt_with_project, True),
        ("claimed_workitem_pa_project", _claimed_payload(), True),
        ("prompt_pa_rejected", prompt_with_pa, False),
        ("claimed_null_project_rejected", claimed_without_project, False),
        ("claimed_ia_rejected", claimed_with_ia, False),
        ("tenant_missing_rejected", missing_tenant, False),
        ("blank_project_rejected", blank_project, False),
        ("invalid_claim_generation_rejected", invalid_generation, False),
    )


def _manifest_results(root: Path) -> tuple[list[dict[str, Any]], bool]:
    manifest_path = root / MANIFEST
    if not manifest_path.is_file():
        return [], False
    rows: list[dict[str, Any]] = []
    with manifest_path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            path = root / row["path"]
            present = path.is_file()
            actual_hash = _sha256(path) if present else None
            actual_size = path.stat().st_size if present else None
            matched = (
                present
                and actual_hash == row["sha256"]
                and str(actual_size) == row["bytes"]
            )
            rows.append(
                {
                    "path": row["path"],
                    "role": row["role"],
                    "present": present,
                    "hash_and_size_match": matched,
                }
            )
    return rows, bool(rows) and all(row["hash_and_size_match"] for row in rows)


def run_p4_ca01_project_neutral_prompt_closure(
    root: Path = ROOT,
) -> dict[str, Any]:
    paths = {
        "frozen_schema": root / FROZEN_SCHEMA,
        "frozen_protocol": root / FROZEN_PROTOCOL,
        "amended_schema": root / CANDIDATE_SCHEMA,
        "amended_protocol": root / CANDIDATE_PROTOCOL,
    }
    present = {name: path.is_file() for name, path in paths.items()}
    frozen_hashes = {
        str(relative): _sha256(root / relative)
        if (root / relative).is_file()
        else None
        for relative in EXPECTED_FROZEN_HASHES
    }
    frozen_unchanged = frozen_hashes == EXPECTED_FROZEN_HASHES

    schema_valid = False
    contract_identity_preserved = False
    vocabulary_preserved = False
    probe_results: list[dict[str, Any]] = []
    if all(present.values()):
        try:
            schema = _load_json(paths["amended_schema"])
            Draft202012Validator.check_schema(schema)
            validator = Draft202012Validator(schema)
            protocol = _load_protocol(paths["amended_protocol"])
            schema_valid = True
            contract_identity_preserved = (
                schema.get("$id") == "urn:nex:schema:ae:execution-trigger:2.1"
                and schema.get("properties", {})
                .get("schema_version", {})
                .get("const")
                == "2.1"
                and "project_id" in schema.get("required", [])
            )
            vocabulary_preserved = (
                set(schema["properties"]["source_type"]["enum"])
                == EXPECTED_SOURCE_TYPES
                and set(schema["properties"]["agent_type"]["enum"])
                == EXPECTED_AGENT_TYPES
            )
            for name, payload, expected in _probe_cases():
                schema_accepted = _schema_accepts(validator, payload)
                protocol_accepted = _protocol_accepts(protocol, payload)
                probe_results.append(
                    {
                        "name": name,
                        "expected_acceptance": expected,
                        "schema_accepted": schema_accepted,
                        "protocol_accepted": protocol_accepted,
                        "passed": schema_accepted == expected
                        and protocol_accepted == expected,
                    }
                )
        except (ImportError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            schema_valid = False

    probes_passed = len(probe_results) == len(_probe_cases()) and all(
        item["passed"] for item in probe_results
    )
    probe_by_name = {item["name"]: item for item in probe_results}
    e1_focused_probe = all(
        probe_by_name.get(name, {}).get("passed", False)
        for name in (
            "claimed_workitem_pa_project",
            "claimed_null_project_rejected",
            "claimed_ia_rejected",
            "tenant_missing_rejected",
        )
    )
    e2e01_focused_probe = all(
        probe_by_name.get(name, {}).get("passed", False)
        for name in ("prompt_ia_null_project", "prompt_ia_resolved_project")
    )
    manifest_rows, manifest_valid = _manifest_results(root)

    checks = {
        "controlled_assets_present": all(present.values()),
        "frozen_hash_history_unchanged": frozen_unchanged,
        "amended_schema_is_valid_draft_2020_12": schema_valid,
        "contract_identity_and_required_project_field_preserved": (
            contract_identity_preserved
        ),
        "step8_trigger_and_agent_vocabularies_preserved": vocabulary_preserved,
        "json_schema_and_python_probe_matrix_passed": probes_passed,
        "e1_authority_identity_focused_probe_passed": e1_focused_probe,
        "e2e01_project_neutral_ia_read_admission_probe_passed": (
            e2e01_focused_probe
        ),
        "amendment_manifest_hashes_valid": manifest_valid,
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    passed = not failed_checks
    return {
        "schema_version": "p4_ca01_project_neutral_prompt_closure.v1",
        "amendment": "P4-CA01",
        "status": "PASS" if passed else "FAIL",
        "admission_gate": "OPEN_FOR_P4_SOURCE_IMPLEMENTATION" if passed else "BLOCKED",
        "validation_scope": "FOCUSED_CONTRACT_IMPACT_PROBE",
        "checks": checks,
        "failed_checks": failed_checks,
        "summary": {
            "probe_count": len(probe_results),
            "passed_probe_count": sum(item["passed"] for item in probe_results),
            "manifest_entry_count": len(manifest_rows),
            "valid_manifest_entry_count": sum(
                item["hash_and_size_match"] for item in manifest_rows
            ),
        },
        "probe_results": probe_results,
        "frozen_hashes": frozen_hashes,
        "manifest_results": manifest_rows,
        "limitations": [
            "This is focused E1/E2E-01 contract-impact evidence, not a full runtime E2E execution.",
            "No PostgreSQL, remote provider, WC, Enterprise OS, or NSL runtime is required by P4-CA01.",
        ],
    }


def summary_line(result: dict[str, Any]) -> str:
    summary = result.get("summary", {})
    return (
        f"p4_ca01_project_neutral_prompt_closure={str(result.get('status')).lower()} "
        f"probes={summary.get('passed_probe_count', 0)}/{summary.get('probe_count', 0)} "
        "manifest="
        f"{summary.get('valid_manifest_entry_count', 0)}/"
        f"{summary.get('manifest_entry_count', 0)} "
        f"gate={result.get('admission_gate', 'BLOCKED')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the P4-CA01 controlled-amendment closure probes."
    )
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_p4_ca01_project_neutral_prompt_closure()
    rendered = summary_line(result) if args.summary else json.dumps(result, indent=2)
    print(rendered)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
