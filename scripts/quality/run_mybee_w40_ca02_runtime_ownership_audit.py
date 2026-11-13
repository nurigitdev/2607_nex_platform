#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORT = Path(
    "reports/quality/mybee-w40-ca02-s01-runtime-ownership-audit.json"
)
SCHEMA_VERSION = "mybee_w40_ca02_runtime_ownership_audit.v1"

MYBEE_ROOT = "domains/mybee/mybee_ax"
MYBEE_README = "domains/mybee/README.md"
MYBEE_PROJECT = "domains/mybee/pyproject.toml"
ARTIFACT_CATALOG = "services/_shared/nex_runtime/deployment_artifacts.py"
AE_ACTIVATORS = "services/nex-ae-api/nex_ae_api/domain_intent_products.py"
AE_CAPABILITIES = "deployment/environments/ae-product-capability-registry.v1.json"
AE_RUNTIME_CONTAINERFILE = "deployment/oci/canonical-platform-ae-runtime.Containerfile"
AE_RUNTIME_BUILDER = "scripts/deployment/build_canonical_platform_ae_runtime_image.py"
CANONICAL_COMPOSE = "deployment/compose/canonical-platform.override.yaml"
EOS_DEPENDENCIES = "services/nex-eos/nex_eos/dependencies.py"
EOS_OUTBOX_PROCESS = "services/nex-eos/nex_eos/outbox_publisher_process.py"
MYBEE_CONSUMER = (
    "domains/mybee/mybee_ax/integrations/nex_voucher_candidate_client.py"
)

OWNERSHIP_DECISION = {
    "domain_library_owner": "mybee",
    "execution_process_owner": "nex-ae-api",
    "business_state_owner": "nex-eos",
    "authorization_owner": "nex-oa",
    "approval_owner": "nex-wc",
    "entitlement_delivery_owner": "nex-eos-outbox-publisher",
    "new_mybee_service_required": False,
}


def audit_runtime_ownership(root: Path = ROOT) -> dict[str, Any]:
    issues: list[str] = []
    texts = {
        path: _read_text(root, path, issues)
        for path in (
            MYBEE_README,
            MYBEE_PROJECT,
            ARTIFACT_CATALOG,
            AE_ACTIVATORS,
            AE_RUNTIME_CONTAINERFILE,
            AE_RUNTIME_BUILDER,
            CANONICAL_COMPOSE,
            EOS_DEPENDENCIES,
            EOS_OUTBOX_PROCESS,
            MYBEE_CONSUMER,
        )
    }
    capability_registry = _read_json(root, AE_CAPABILITIES, issues)
    compose = _read_yaml(root, CANONICAL_COMPOSE, issues)

    forbidden_entrypoints = _mybee_runtime_entrypoints(root)
    if forbidden_entrypoints:
        issues.append("MyBee defines a forbidden second product runtime")

    service_imports = _service_mybee_imports(root, issues)
    non_ae_imports = [
        path
        for path in service_imports
        if not path.startswith("services/nex-ae-api/")
    ]
    if non_ae_imports:
        issues.append("a non-AE service imports the MyBee domain package")

    readme = " ".join(texts[MYBEE_README].lower().split())
    ownership_documented = all(
        token.lower() in readme
        for token in (
            "does not own or duplicate",
            "Agent Runtime or NSL execution",
            "accounting, GL, Project, allocation, or P&L state",
            "a second MyBee runtime are forbidden",
        )
    )
    if not ownership_documented:
        issues.append("MyBee ownership boundary is not documented")

    package_identity_valid = (
        'name = "nex-mybee-ax"' in texts[MYBEE_PROJECT]
        and 'include = ["mybee_ax*"]' in texts[MYBEE_PROJECT]
    )
    if not package_identity_valid:
        issues.append("MyBee package identity is unavailable")

    ae_source_roots = _artifact_source_roots(
        texts[ARTIFACT_CATALOG], "nex-ae-runtime", issues
    )
    ae_package_admitted = _ae_package_admitted(texts, ae_source_roots)
    capability_admitted = _capability_admitted(capability_registry)
    activator_admitted = any(
        token in texts[AE_ACTIVATORS]
        for token in ("mybee_ax", "VoucherCandidate", "MYBEE")
    )

    services = compose.get("services", {}) if isinstance(compose, Mapping) else {}
    required_services = {
        "nex-ae-api",
        "nex-ae-agent-runtime-worker",
        "nex-eos",
        "nex-eos-outbox-publisher",
        "nex-oa",
        "nex-wc",
    }
    canonical_processes_present = required_services.issubset(services)
    if not canonical_processes_present:
        issues.append("canonical accounting process topology is incomplete")

    eos_environment = _compose_environment(services, "nex-eos")
    publisher_environment = _compose_environment(
        services, "nex-eos-outbox-publisher"
    )
    eos_oa_trust_configured = all(
        name in {**eos_environment, **publisher_environment}
        for name in ("NEX_OA_BASE_URL", "NEX_EOS_TO_OA_SERVICE_TOKEN_REF")
    )
    if not eos_oa_trust_configured:
        issues.append("canonical EOS-to-OA trust configuration is incomplete")

    outbox_oa_route_present = all(
        token in texts[EOS_OUTBOX_PROCESS]
        for token in (
            "RoutingEosOutboxTransport",
            "HttpOaProjectEntitlementTransport",
            "NEX_EOS_TO_OA_SERVICE_TOKEN",
        )
    )
    if not outbox_oa_route_present:
        issues.append("installed EOS outbox does not own the OA route")

    eos_product_composition_present = all(
        token in texts[EOS_DEPENDENCIES]
        for token in (
            "SqlAlchemyEosVoucherCandidateRepository",
            "EosProjectAuthorizationGate",
            "HttpOaProjectAuthorizationDecisionSource",
        )
    )
    if not eos_product_composition_present:
        issues.append("EOS product composition is incomplete")

    mybee_http_consumer_present = all(
        token in texts[MYBEE_CONSUMER]
        for token in (
            "class NexVoucherCandidateClient",
            "class HttpVoucherCandidateProviderTransport",
            "Authorization",
        )
    )
    if not mybee_http_consumer_present:
        issues.append("MyBee installed HTTP consumer contract is incomplete")

    integration_gaps = []
    if not ae_package_admitted:
        integration_gaps.append("MYBEE_AE_PACKAGE_NOT_ADMITTED")
    if not capability_admitted:
        integration_gaps.append("MYBEE_PRODUCT_CAPABILITY_NOT_ADMITTED")
    if not activator_admitted:
        integration_gaps.append("MYBEE_PRODUCT_ACTIVATOR_NOT_ADMITTED")

    checks = {
        "ownership_documented": ownership_documented,
        "package_identity_valid": package_identity_valid,
        "no_second_mybee_runtime": not forbidden_entrypoints,
        "no_non_ae_service_import": not non_ae_imports,
        "canonical_processes_present": canonical_processes_present,
        "eos_oa_trust_configured": eos_oa_trust_configured,
        "outbox_oa_route_present": outbox_oa_route_present,
        "eos_product_composition_present": eos_product_composition_present,
        "mybee_http_consumer_present": mybee_http_consumer_present,
    }
    status = "PASS" if not issues and all(checks.values()) else "FAIL"
    return {
        "schema_version": SCHEMA_VERSION,
        "slice": "W40-CA02-S01",
        "status": status,
        "integration_readiness": "READY" if not integration_gaps else "NOT_READY",
        "ownership_decision": dict(OWNERSHIP_DECISION),
        "checks": checks,
        "current_composition": {
            "ae_source_roots": list(ae_source_roots),
            "ae_package_admitted": ae_package_admitted,
            "mybee_capability_admitted": capability_admitted,
            "mybee_activator_admitted": activator_admitted,
            "mybee_service_imports": service_imports,
            "forbidden_mybee_runtime_entrypoints": forbidden_entrypoints,
        },
        "integration_gaps": integration_gaps,
        "next_slice": (
            "W40-CA02-S02"
            if "MYBEE_AE_PACKAGE_NOT_ADMITTED" in integration_gaps
            else "W40-CA02-S03"
        ),
        "remote_provider_required": False,
        "database_migration_required": False,
        "issues": issues,
        "content_included": False,
        "secret_included": False,
    }


def _read_text(root: Path, relative: str, issues: list[str]) -> str:
    try:
        return (root / relative).read_text(encoding="utf-8")
    except OSError:
        issues.append(f"required source is unavailable: {relative}")
        return ""


def _read_json(root: Path, relative: str, issues: list[str]) -> Any:
    source = _read_text(root, relative, issues)
    if not source:
        return {}
    try:
        return json.loads(source)
    except (TypeError, ValueError):
        issues.append(f"required JSON is malformed: {relative}")
        return {}


def _read_yaml(root: Path, relative: str, issues: list[str]) -> Any:
    source = _read_text(root, relative, issues)
    if not source:
        return {}
    try:
        return yaml.safe_load(source) or {}
    except yaml.YAMLError:
        issues.append(f"required YAML is malformed: {relative}")
        return {}


def _mybee_runtime_entrypoints(root: Path) -> list[str]:
    package = root / MYBEE_ROOT
    if not package.is_dir():
        return []
    forbidden = {"app.py", "main.py", "runtime_process.py", "worker_process.py"}
    return sorted(
        path.relative_to(root).as_posix()
        for path in package.rglob("*.py")
        if path.name in forbidden
    )


def _service_mybee_imports(root: Path, issues: list[str]) -> list[str]:
    service_root = root / "services"
    if not service_root.is_dir():
        issues.append("service source inventory is unavailable")
        return []
    result = []
    for path in sorted(service_root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError):
            issues.append(
                f"service source cannot be parsed: {path.relative_to(root).as_posix()}"
            )
            continue
        if any(_imports_mybee(node) for node in ast.walk(tree)):
            result.append(path.relative_to(root).as_posix())
    return result


def _imports_mybee(node: ast.AST) -> bool:
    if isinstance(node, ast.Import):
        return any(
            alias.name == "mybee_ax" or alias.name.startswith("mybee_ax.")
            for alias in node.names
        )
    if isinstance(node, ast.ImportFrom):
        return bool(node.module) and (
            node.module == "mybee_ax" or node.module.startswith("mybee_ax.")
        )
    return False


def _artifact_source_roots(
    source: str, artifact_id: str, issues: list[str]
) -> tuple[str, ...]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        issues.append("deployment artifact catalog cannot be parsed")
        return ()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or len(node.args) < 6:
            continue
        function = node.func
        name = function.id if isinstance(function, ast.Name) else ""
        if name != "DeploymentArtifactDefinition":
            continue
        try:
            identity = ast.literal_eval(node.args[0])
            roots = ast.literal_eval(node.args[5])
        except (TypeError, ValueError):
            continue
        if identity == artifact_id and isinstance(roots, tuple):
            return tuple(str(item) for item in roots)
    issues.append(f"deployment artifact is unavailable: {artifact_id}")
    return ()


def _ae_package_admitted(
    texts: Mapping[str, str], source_roots: tuple[str, ...]
) -> bool:
    tokens = "\n".join(
        (
            *source_roots,
            texts[AE_RUNTIME_CONTAINERFILE],
            texts[AE_RUNTIME_BUILDER],
        )
    ).lower()
    return (
        "domains/mybee" in tokens
        or "nex-mybee-ax" in tokens
        or "mybee_ax" in tokens
    )


def _capability_admitted(value: Any) -> bool:
    serialized = json.dumps(value, sort_keys=True).upper()
    return "MYBEE" in serialized or "VOUCHER_CANDIDATE" in serialized


def _compose_environment(services: Any, service: str) -> dict[str, Any]:
    if not isinstance(services, Mapping):
        return {}
    value = services.get(service, {})
    if not isinstance(value, Mapping):
        return {}
    environment = value.get("environment", {})
    return dict(environment) if isinstance(environment, Mapping) else {}


def _write_report(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(dict(value), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def summary_line(result: Mapping[str, Any]) -> str:
    return (
        "mybee_w40_ca02_runtime_ownership_audit="
        f"{str(result.get('status', 'FAIL')).lower()} "
        f"readiness={result.get('integration_readiness', 'UNKNOWN')} "
        f"gaps={len(result.get('integration_gaps', []))} "
        f"next={result.get('next_slice', 'blocked')}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    result = audit_runtime_ownership(args.root)
    report = args.report if args.report.is_absolute() else args.root / args.report
    _write_report(report, result)
    print(summary_line(result) if args.summary else json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
