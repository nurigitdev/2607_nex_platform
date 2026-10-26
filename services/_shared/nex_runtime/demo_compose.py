from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from .demo_processes import DEMO_INSTALLED_PROCESS_IDS, build_demo_process_manifest

DEMO_COMPOSE_SCHEMA_VERSION = "p8_demo_compose.v1"
DEMO_ADDED_SERVICE_IDS = (
    "nex-wc",
    "nex-eos",
    "nex-ae-agent-runtime-worker",
    "nex-wc-event-delivery-worker",
    "nex-eos-outbox-publisher",
)
DEMO_COMPOSE_SERVICE_BY_PROCESS = {
    "nex-oa-api": "nex-oa",
    "nex-ag-api": "nex-ag",
    "nex-ae-api": "nex-ae-api",
    "nex-cx-api": "nex-cx",
    "nex-mo-api": "nex-mo",
    "nex-wc-api": "nex-wc",
    "nex-eos-api": "nex-eos",
    "nex-ae-web": "nex-ae-web",
    "nex-ae-agent-runtime-worker": "nex-ae-agent-runtime-worker",
    "nex-wc-event-delivery-worker": "nex-wc-event-delivery-worker",
    "nex-eos-outbox-publisher": "nex-eos-outbox-publisher",
}
DEMO_ROUTE_IDS = (
    "oa",
    "ag",
    "ae-api",
    "cx",
    "mo",
    "wc",
    "eos",
    "ae-web",
    "embedding",
    "reranker",
    "generation",
    "identity",
    "object-storage",
)
_IMAGE_ENV_BY_ARTIFACT = {
    "nex-oa-runtime": "NEX_OA_RUNTIME_IMAGE",
    "nex-ag-runtime": "NEX_AG_RUNTIME_IMAGE",
    "nex-ae-runtime": "NEX_AE_RUNTIME_IMAGE",
    "nex-cx-runtime": "NEX_CX_RUNTIME_IMAGE",
    "nex-mo-runtime": "NEX_MO_RUNTIME_IMAGE",
    "nex-wc-runtime": "NEX_WC_RUNTIME_IMAGE",
    "nex-eos-runtime": "NEX_EOS_RUNTIME_IMAGE",
    "nex-ae-web": "NEX_AE_WEB_IMAGE",
}
_IMMUTABLE_IMAGE = re.compile(r"^[^@\s]+@sha256:[0-9a-f]{64}$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_LOCAL_TAG = re.compile(r"^(?P<repository>[^@\s]+):(?P<tag>[A-Za-z0-9_.-]+)$")
_AE_REQUIRED_PLANNING_ENVIRONMENT = {
    "NEX_AE_AGENT_RUNTIME_MODE": "required",
    "NEX_AE_PLANNING_MODE": "required",
}


class DemoComposeError(ValueError):
    pass


def admit_demo_compose_sources(
    root: Path,
    *,
    overlay_path: str = "deployment/compose/p8-demo.override.yaml",
    dynamic_path: str = "deployment/compose/traefik/p8-demo-dynamic.yaml",
) -> dict[str, Any]:
    overlay_text = _read_text(root / overlay_path)
    dynamic_text = _read_text(root / dynamic_path)
    overlay = _load_mapping(overlay_text, "Demo Compose overlay")
    dynamic = _load_mapping(dynamic_text, "Demo Traefik configuration")
    services = _mapping(overlay.get("services"), "Demo Compose services")
    errors: list[str] = []
    if overlay.get("name") != "nex-platform-p8-demo":
        errors.append("Demo Compose project name drift")
    for service_id in DEMO_ADDED_SERVICE_IDS:
        service = _mapping(services.get(service_id), f"service {service_id}")
        if service.get("restart") != "unless-stopped":
            errors.append(f"Demo restart policy drift: {service_id}")
        if service.get("read_only") is not True:
            errors.append(f"Demo read-only policy drift: {service_id}")
        if service.get("cap_drop") != ["ALL"]:
            errors.append(f"Demo capability policy drift: {service_id}")
        if "ports" in service:
            errors.append(f"Demo service host port is forbidden: {service_id}")
    manifest = {
        item.process_id: item
        for item in build_demo_process_manifest()
        if item.process_id in DEMO_ADDED_SERVICE_IDS
    }
    for process_id, binding in manifest.items():
        service = _mapping(services.get(process_id), f"service {process_id}")
        if tuple(str(item) for item in service.get("command") or ()) != tuple(
            binding.command or ()
        ) and binding.kind == "worker":
            errors.append(f"Demo worker command drift: {process_id}")
    overlay_images = json.dumps(services, sort_keys=True)
    for artifact_id in ("nex-wc-runtime", "nex-eos-runtime"):
        environment_name = _IMAGE_ENV_BY_ARTIFACT[artifact_id]
        if environment_name not in overlay_images:
            errors.append(f"Demo image input missing: {artifact_id}")
    for owner in ("wc", "eos"):
        for kind in ("role_id", "secret_id"):
            if f"{owner}_{kind}" not in _mapping(
                overlay.get("secrets"), "Demo Compose secrets"
            ):
                errors.append(f"Demo owner secret missing: {owner}_{kind}")
    ae_environment = _mapping(
        _mapping(services.get("nex-ae-api"), "service nex-ae-api").get("environment"),
        "Demo AE environment",
    )
    for name, expected in _AE_REQUIRED_PLANNING_ENVIRONMENT.items():
        if ae_environment.get(name) != expected:
            errors.append(f"Demo AE planning profile drift: {name}")
    if "NEX_P8_DEMO_SEMANTIC_CALIBRATION_POLICIES_JSON" not in str(
        ae_environment.get("NEX_AE_P65_SEMANTIC_CALIBRATION_POLICIES_JSON") or ""
    ):
        errors.append("Demo AE semantic calibration input missing")
    if "_TEST_DATABASE_URL" in overlay_text or "nuri1004" in overlay_text:
        errors.append("Demo Compose contains a test or raw database credential")

    http = _mapping(dynamic.get("http"), "Demo Traefik http")
    routers = _mapping(http.get("routers"), "Demo Traefik routers")
    route_services = _mapping(http.get("services"), "Demo Traefik services")
    if tuple(routers) != DEMO_ROUTE_IDS or tuple(route_services) != DEMO_ROUTE_IDS:
        errors.append("Demo Traefik route coverage or order drift")
    for route_id, port in (("wc", 8106), ("eos", 8107)):
        router = _mapping(routers.get(route_id), f"router {route_id}")
        service = _mapping(route_services.get(route_id), f"route service {route_id}")
        if router.get("service") != route_id or router.get("tls") != {}:
            errors.append(f"Demo Traefik TLS route drift: {route_id}")
        if f"http://nex-{route_id}:{port}" not in json.dumps(service):
            errors.append(f"Demo Traefik upstream drift: {route_id}")
    if errors:
        raise DemoComposeError("; ".join(errors))
    return {
        "schema_version": DEMO_COMPOSE_SCHEMA_VERSION,
        "status": "ADMITTED",
        "overlay_path": overlay_path,
        "dynamic_path": dynamic_path,
        "overlay_digest": _digest(overlay_text),
        "dynamic_digest": _digest(dynamic_text),
        "added_service_count": len(DEMO_ADDED_SERVICE_IDS),
        "installed_process_count": len(DEMO_INSTALLED_PROCESS_IDS),
        "route_count": len(DEMO_ROUTE_IDS),
        "wc_eos_tls_routes": True,
        "raw_secret_included": False,
        "test_database_included": False,
    }


def admit_rendered_demo_compose(
    rendered: Mapping[str, Any],
    *,
    image_references: Mapping[str, str],
) -> dict[str, Any]:
    services = _mapping(rendered.get("services"), "rendered services")
    expected_runtime = set(DEMO_INSTALLED_PROCESS_IDS)
    expected_services = set(DEMO_COMPOSE_SERVICE_BY_PROCESS.values())
    if set(DEMO_COMPOSE_SERVICE_BY_PROCESS) != expected_runtime or not expected_services.issubset(
        services
    ):
        raise DemoComposeError("rendered installed process coverage is incomplete")
    expected_images = set(_IMAGE_ENV_BY_ARTIFACT)
    if set(image_references) != expected_images or any(
        _IMMUTABLE_IMAGE.fullmatch(value) is None
        for value in image_references.values()
    ):
        raise DemoComposeError("rendered image release set is incomplete or mutable")
    observed_images = {
        str(service.get("image") or "")
        for service in services.values()
        if isinstance(service, Mapping)
    }
    if not set(image_references.values()).issubset(observed_images):
        raise DemoComposeError("rendered image references drift")
    payload = json.dumps(rendered, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    if "nuri1004" in payload or "_TEST_DATABASE_URL" in payload:
        raise DemoComposeError("rendered Compose exposes forbidden database input")
    for process_id in (
        "nex-ae-agent-runtime-worker",
        "nex-wc-event-delivery-worker",
        "nex-eos-outbox-publisher",
    ):
        service = _mapping(services.get(process_id), f"rendered {process_id}")
        if service.get("restart") != "unless-stopped" or "ports" in service:
            raise DemoComposeError(f"rendered worker policy drift: {process_id}")
    return {
        "schema_version": "p8_demo_compose_render.v1",
        "status": "PASS",
        "service_count": len(services),
        "installed_process_count": len(expected_runtime),
        "image_count": len(expected_images),
        "rendered_digest": f"sha256:{hashlib.sha256(payload.encode('ascii')).hexdigest()}",
        "raw_secret_included": False,
        "runtime_values_included": False,
    }


def image_environment_from_release_report(
    report: Mapping[str, Any],
) -> dict[str, str]:
    if report.get("status") != "PASS":
        raise DemoComposeError("P8 Demo OCI release report is not passing")
    records = _mapping(
        _mapping(report.get("image_build"), "image build").get("artifacts"),
        "image artifacts",
        sequence=True,
    )
    references = {
        str(item.get("artifact_id")): str(item.get("image_reference"))
        for item in records.values()
        if isinstance(item, Mapping)
    }
    if set(references) != set(_IMAGE_ENV_BY_ARTIFACT):
        raise DemoComposeError("P8 Demo OCI report artifact coverage drift")
    return {
        _IMAGE_ENV_BY_ARTIFACT[artifact_id]: reference
        for artifact_id, reference in references.items()
    }


def image_environment_from_installed_runtime_reports(
    release_report: Mapping[str, Any],
    ae_runtime_report: Mapping[str, Any],
) -> dict[str, str]:
    """Bind the complete release set to the NSL-bundled AE runtime image."""

    environment = image_environment_from_release_report(release_report)
    artifacts = _mapping(
        _mapping(release_report.get("image_build"), "image build").get("artifacts"),
        "image artifacts",
        sequence=True,
    )
    ae_release = next(
        (
            item
            for item in artifacts.values()
            if isinstance(item, Mapping)
            and item.get("artifact_id") == "nex-ae-runtime"
        ),
        None,
    )
    if ae_release is None:
        raise DemoComposeError("P8 Demo OCI report AE artifact is unavailable")
    for item in artifacts.values():
        if not isinstance(item, Mapping):
            raise DemoComposeError("P8 Demo OCI local image artifact is invalid")
        artifact_id = str(item.get("artifact_id") or "")
        local_match = _LOCAL_TAG.fullmatch(str(item.get("local_tag") or ""))
        image_id = str(item.get("image_id") or "")
        if (
            artifact_id not in _IMAGE_ENV_BY_ARTIFACT
            or local_match is None
            or _SHA256.fullmatch(image_id) is None
            or item.get("manifest_digest") != image_id
        ):
            raise DemoComposeError("P8 Demo OCI local image identity drift")
        environment[_IMAGE_ENV_BY_ARTIFACT[artifact_id]] = (
            f"{local_match.group('repository')}@{image_id}"
        )
    if (
        ae_runtime_report.get("status") != "PASS"
        or ae_runtime_report.get("slice") != "P8-DEMO-S10B"
    ):
        raise DemoComposeError("installed AE runtime report is not passing")
    bundle = _mapping(ae_runtime_report.get("bundle"), "installed AE bundle")
    image = _mapping(ae_runtime_report.get("image"), "installed AE image")
    if bundle.get("status") != "PASS":
        raise DemoComposeError("installed AE runtime bundle is not admitted")
    if ae_runtime_report.get("base_image") not in {
        ae_release.get("local_tag"),
        ae_release.get("image_reference"),
    }:
        raise DemoComposeError("installed AE runtime base image drift")
    image_id = str(image.get("image_id") or "")
    references = tuple(str(value) for value in image.get("repo_digests") or ())
    if _SHA256.fullmatch(image_id) is None or len(references) != 1:
        raise DemoComposeError("installed AE runtime image identity is invalid")
    reference = references[0]
    if _IMMUTABLE_IMAGE.fullmatch(reference) is None or not reference.endswith(image_id):
        raise DemoComposeError("installed AE runtime image reference is mutable")
    output_repository = str(ae_runtime_report.get("output_image") or "").split(":", 1)[0]
    if not output_repository or not reference.startswith(f"{output_repository}@"):
        raise DemoComposeError("installed AE runtime repository drift")
    environment["NEX_AE_RUNTIME_IMAGE"] = reference
    return environment


def _load_mapping(value: str, label: str) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(value)
    except yaml.YAMLError as exc:
        raise DemoComposeError(f"{label} is invalid YAML") from exc
    return _mapping(payload, label)


def _mapping(
    value: object, label: str, *, sequence: bool = False
) -> dict[Any, Any]:
    if sequence:
        if not isinstance(value, list):
            raise DemoComposeError(f"{label} must be an array")
        return {index: item for index, item in enumerate(value)}
    if not isinstance(value, Mapping):
        raise DemoComposeError(f"{label} must be an object")
    return dict(value)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DemoComposeError(f"required Demo Compose source is missing: {path.name}") from exc


def _digest(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"
