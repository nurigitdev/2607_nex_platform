#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY = Path("scripts/quality/golden_journey_runners.v1.json")
DEFAULT_REPORT = Path("reports/quality/golden-journey-transition-audit.json")
REGISTRY_SCHEMA_VERSION = "golden_journey_runner_registry.v1"
AUDIT_SCHEMA_VERSION = "golden_journey_transition_audit.v1"
EVIDENCE_CONTRACT_NAME = "GOLDEN_JOURNEY_EVIDENCE_CONTRACT"
EVIDENCE_CONTRACT = {
    "platform_integrated": True,
    "runtime_transition_fixture": False,
    "manual_domain_transition": False,
    "installed_process_continuity": True,
}
EVIDENCE_CLASSES = {
    "COMPONENT",
    "PROTECTED_COMPONENT",
    "EVIDENCE_AGGREGATOR",
    "INSTALLED_PLATFORM",
    "GOLDEN_JOURNEY",
}
FORBIDDEN_CALLS = {
    "acknowledge_result_delivery",
    "create_assignment",
    "create_claim",
    "create_runtime_job",
    "create_work_item",
    "enqueue_runtime_job",
    "record_approval_decision",
    "schedule_next",
    "submit_work_result",
}
FORBIDDEN_REPOSITORY_TOKENS = (
    "AgentExecution",
    "AgentResult",
    "Approval",
    "DelegationRuntime",
    "ExecutableStep",
    "ResultDelivery",
    "RuntimeJob",
    "WaitRegistration",
    "WorkAsset",
    "WorkEvidence",
    "WorkItem",
    "WorkResult",
)
FORBIDDEN_IMPORTS = {
    "MultiStepEngine",
    "SqlAlchemyMultiStepEngine",
    "SqlAlchemyRuntimeJobQueue",
}
FORBIDDEN_TABLES = {
    "ae_agent_execution",
    "ae_agent_result",
    "ae_executable_step",
    "ae_result_delivery",
    "ae_runtime_job",
    "ae_wait_registration",
    "eos_business_operation",
    "eos_outbox",
    "wa_work_asset",
    "wa_work_asset_evidence",
    "wa_work_evidence",
    "wc_approval_decision",
    "wc_approval_work_item",
    "wc_assignment",
    "wc_claim",
    "wc_work_item",
    "wc_work_result",
}
SQL_MUTATION = re.compile(
    r"\b(?:insert\s+into|update|merge\s+into)\s+"
    r"(?P<table>[A-Za-z_][A-Za-z0-9_.$\"]*)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RunnerRegistration:
    path: str
    evidence_class: str
    enforce_transition_boundary: bool


@dataclass(frozen=True)
class AuditFinding:
    code: str
    path: str
    line: int
    detail: str


class GoldenJourneyRegistryError(ValueError):
    pass


def discover_journey_runners(root: Path) -> tuple[str, ...]:
    discovered = []
    for location in ("scripts/deployment", "scripts/smoke"):
        scripts = root / location
        if not scripts.is_dir():
            continue
        for path in scripts.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            name = path.stem.lower()
            if "journey" in name and ("golden" in name or "chairman" in name):
                discovered.append(path.relative_to(root).as_posix())
    return tuple(sorted(discovered))


def load_runner_registry(
    root: Path, registry_path: Path | None = None
) -> tuple[RunnerRegistration, ...]:
    path = root / (registry_path or DEFAULT_REGISTRY)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GoldenJourneyRegistryError("runner registry is unavailable") from exc
    if not isinstance(payload, Mapping) or set(payload) != {
        "schema_version",
        "runners",
    }:
        raise GoldenJourneyRegistryError("runner registry fields are invalid")
    if payload["schema_version"] != REGISTRY_SCHEMA_VERSION:
        raise GoldenJourneyRegistryError("runner registry schema is unsupported")
    rows = payload["runners"]
    if not isinstance(rows, list) or not rows:
        raise GoldenJourneyRegistryError("runner registry must not be empty")
    registrations = tuple(_registration(root, row) for row in rows)
    paths = tuple(item.path for item in registrations)
    if len(set(paths)) != len(paths):
        raise GoldenJourneyRegistryError("runner registry paths must be unique")
    if paths != tuple(sorted(paths)):
        raise GoldenJourneyRegistryError("runner registry must be canonically ordered")
    discovered = discover_journey_runners(root)
    if set(paths) != set(discovered):
        missing = sorted(set(discovered) - set(paths))
        stale = sorted(set(paths) - set(discovered))
        raise GoldenJourneyRegistryError(
            f"runner registry inventory differs (missing={missing}, stale={stale})"
        )
    return registrations


def _registration(root: Path, value: object) -> RunnerRegistration:
    fields = {"path", "evidence_class", "enforce_transition_boundary"}
    if not isinstance(value, Mapping) or set(value) != fields:
        raise GoldenJourneyRegistryError("runner registration fields are invalid")
    raw_path = value["path"]
    if not isinstance(raw_path, str) or not raw_path:
        raise GoldenJourneyRegistryError("runner path is invalid")
    path = Path(raw_path)
    if (
        path.is_absolute()
        or ".." in path.parts
        or not raw_path.startswith("scripts/")
        or path.suffix != ".py"
        or not (root / path).is_file()
    ):
        raise GoldenJourneyRegistryError(f"runner path is unsafe: {raw_path}")
    evidence_class = value["evidence_class"]
    enforced = value["enforce_transition_boundary"]
    if evidence_class not in EVIDENCE_CLASSES:
        raise GoldenJourneyRegistryError("runner evidence class is invalid")
    if not isinstance(enforced, bool):
        raise GoldenJourneyRegistryError("runner enforcement flag is invalid")
    if (evidence_class == "GOLDEN_JOURNEY") != enforced:
        raise GoldenJourneyRegistryError(
            "GOLDEN_JOURNEY is the only transition-enforced evidence class"
        )
    return RunnerRegistration(raw_path, str(evidence_class), enforced)


def audit_repository(
    root: Path = ROOT, registry_path: Path | None = None
) -> dict[str, Any]:
    findings: list[AuditFinding] = []
    try:
        registrations = load_runner_registry(root, registry_path)
    except GoldenJourneyRegistryError as exc:
        findings.append(AuditFinding("REGISTRY_INVALID", str(registry_path or DEFAULT_REGISTRY), 0, str(exc)))
        registrations = ()
    for registration in registrations:
        if registration.enforce_transition_boundary:
            findings.extend(_audit_runner(root / registration.path, registration.path))
    return {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "status": "PASS" if not findings else "FAIL",
        "registered_runner_count": len(registrations),
        "discovered_runner_count": len(discover_journey_runners(root)),
        "enforced_runner_count": sum(
            item.enforce_transition_boundary for item in registrations
        ),
        "evidence_contract": dict(EVIDENCE_CONTRACT),
        "findings": [asdict(item) for item in findings],
        "secret_included": False,
    }


def _audit_runner(path: Path, relative_path: str) -> list[AuditFinding]:
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=relative_path)
    except (OSError, SyntaxError) as exc:
        line = exc.lineno if isinstance(exc, SyntaxError) and exc.lineno else 0
        return [AuditFinding("RUNNER_PARSE_FAILED", relative_path, line, "runner source cannot be parsed")]
    findings: list[AuditFinding] = []
    findings.extend(_audit_imports(tree, relative_path))
    findings.extend(_audit_calls(tree, relative_path))
    findings.extend(_audit_sql(tree, relative_path))
    findings.extend(_audit_evidence_contract(tree, relative_path))
    return findings


def _audit_imports(tree: ast.AST, path: str) -> list[AuditFinding]:
    findings = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        for alias in node.names:
            name = alias.name.rsplit(".", 1)[-1]
            repository = name.startswith("SqlAlchemy") and name.endswith("Repository")
            if name in FORBIDDEN_IMPORTS or (
                repository and any(token in name for token in FORBIDDEN_REPOSITORY_TOKENS)
            ):
                findings.append(
                    AuditFinding(
                        "FORBIDDEN_DOMAIN_IMPORT",
                        path,
                        node.lineno,
                        f"direct runtime-transition import is forbidden: {name}",
                    )
                )
    return findings


def _audit_calls(tree: ast.AST, path: str) -> list[AuditFinding]:
    findings = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node.func)
        if name in FORBIDDEN_CALLS:
            findings.append(
                AuditFinding(
                    "FORBIDDEN_TRANSITION_CALL",
                    path,
                    node.lineno,
                    f"manual runtime transition call is forbidden: {name}",
                )
            )
    return findings


def _call_name(value: ast.expr) -> str:
    if isinstance(value, ast.Name):
        return value.id
    if isinstance(value, ast.Attribute):
        return value.attr
    return ""


def _audit_sql(tree: ast.AST, path: str) -> list[AuditFinding]:
    findings = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        for match in SQL_MUTATION.finditer(node.value):
            raw_table = match.group("table").replace('"', "")
            table = raw_table.rsplit(".", 1)[-1].lower()
            if table in FORBIDDEN_TABLES:
                findings.append(
                    AuditFinding(
                        "FORBIDDEN_TRANSITION_SQL",
                        path,
                        node.lineno,
                        f"runtime-transition SQL mutation is forbidden: {table}",
                    )
                )
    return findings


def _audit_evidence_contract(tree: ast.AST, path: str) -> list[AuditFinding]:
    assignment: ast.AST | None = None
    value: object | None = None
    for node in tree.body if isinstance(tree, ast.Module) else ():
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
            if any(isinstance(target, ast.Name) and target.id == EVIDENCE_CONTRACT_NAME for target in targets):
                assignment = node
                try:
                    value = ast.literal_eval(node.value)
                except (TypeError, ValueError):
                    value = None
                break
    if assignment is None or value != EVIDENCE_CONTRACT:
        return [
            AuditFinding(
                "EVIDENCE_CONTRACT_INVALID",
                path,
                getattr(assignment, "lineno", 0),
                "Golden Journey evidence metadata is missing or non-canonical",
            )
        ]
    exposed = any(
        isinstance(node, ast.Dict)
        and any(
            key is None
            and isinstance(item, ast.Name)
            and item.id == EVIDENCE_CONTRACT_NAME
            for key, item in zip(node.keys, node.values, strict=True)
        )
        for node in ast.walk(tree)
    )
    if not exposed:
        return [
            AuditFinding(
                "EVIDENCE_CONTRACT_NOT_EXPOSED",
                path,
                getattr(assignment, "lineno", 0),
                "Golden Journey report does not expose the evidence contract",
            )
        ]
    return []


def summary_line(evidence: Mapping[str, Any]) -> str:
    return (
        "golden_journey_transition_audit="
        f"{str(evidence.get('status', 'FAIL')).lower()} "
        f"registered={int(evidence.get('registered_runner_count', 0))} "
        f"enforced={int(evidence.get('enforced_runner_count', 0))} "
        f"findings={len(evidence.get('findings', ()))}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    root = args.root.resolve()
    evidence = audit_repository(root, args.registry)
    report = args.report if args.report.is_absolute() else root / args.report
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
