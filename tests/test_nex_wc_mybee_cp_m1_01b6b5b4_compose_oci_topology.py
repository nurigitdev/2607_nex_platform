from __future__ import annotations

import json
from copy import deepcopy
from io import StringIO
from pathlib import Path

from nex_runtime import current_platform_installation as installation
from nex_runtime.deployment_artifacts import build_current_deployment_artifact_catalog
from nex_runtime.deployment_entrypoints import (
    build_current_packaged_runtime_manifest,
    build_packaged_entrypoint_definitions,
)
from nex_runtime.deployment_oci import (
    build_current_oci_definitions,
    validate_oci_containerfiles,
)
from nex_runtime.process_manifest import build_current_platform_runtime_manifest
from nex_runtime.runtime_package_admission import (
    RUNTIME_CHECK_MODE_ENV,
    RUNTIME_PACKAGE_CHECK_MODE,
)
from nex_runtime.topology_graph import build_runtime_startup_plan
from nex_wc import assignment_dispatch_process

ROOT = Path(__file__).resolve().parents[1]
PROCESS_ID = "nex-wc-assignment-dispatch-worker"


def test_assignment_dispatcher_is_a_product_job_claiming_process() -> None:
    manifest = build_current_platform_runtime_manifest(
        "local_mock", environ={}, python_executable="python"
    )
    process = next(item for item in manifest.processes if item.process_id == PROCESS_ID)
    catalog = build_current_deployment_artifact_catalog()
    packaged = build_current_packaged_runtime_manifest(
        "local_mock", environ={}, python_executable="python"
    )
    entry = next(
        item
        for item in build_packaged_entrypoint_definitions(packaged, catalog)
        if item.process_id == PROCESS_ID
    )
    binding = next(
        item for item in catalog.process_bindings if item.process_id == PROCESS_ID
    )

    assert process.owner == "nex-wc"
    assert process.kind == "worker"
    assert process.dependencies == ("nex-wc-api", "nex-ae-api", "nex-oa-api")
    assert {
        "NEX_WC_DATABASE_URL",
        "NEX_WC_AE_BASE_URL",
        "NEX_WC_TO_AE_SERVICE_TOKEN",
        "NEX_WC_OA_BASE_URL",
        "NEX_WC_TO_OA_SERVICE_TOKEN",
    }.issubset(process.environment_names)
    assert entry.capability == "job_claiming"
    assert entry.command == (
        "python",
        "-m",
        "nex_wc.assignment_dispatch_process",
        "--profile",
        "local_mock",
    )
    assert binding.artifact_id == "nex-wc-runtime"
    assert binding.entrypoint_id == "assignment-dispatch-worker"
    assert len(catalog.artifacts) == 9


def test_assignment_dispatcher_start_order_and_compose_contract_are_canonical() -> None:
    manifest = build_current_platform_runtime_manifest(
        "local_mock", environ={}, python_executable="python"
    )
    order = build_runtime_startup_plan(manifest).ordered_process_ids
    services, _digests = installation._merged_compose_services(ROOT)
    service = services[PROCESS_ID]

    assert order.index("nex-wc-api") < order.index(PROCESS_ID)
    assert order.index("nex-ae-api") < order.index(PROCESS_ID)
    assert order.index("nex-oa-api") < order.index(PROCESS_ID)
    assert installation._product_wc_assignment_dispatch_profile(service) is True
    assert service["image"].startswith("${NEX_WC_RUNTIME_IMAGE:")
    assert service["restart"] == "unless-stopped"
    assert service["read_only"] is True
    assert "ports" not in service
    assert service["healthcheck"]["test"] == [
        "CMD",
        "python",
        "-c",
        "import os; os.kill(1, 0)",
    ]
    assert service["environment"]["NEX_WC_ASSIGNMENT_DISPATCH_SCAN_LIMIT"] == "100"


def test_assignment_dispatcher_rolls_back_on_drift_or_scenario_residue() -> None:
    services, _digests = installation._merged_compose_services(ROOT)
    service = services[PROCESS_ID]

    removed = None
    command_drift = deepcopy(service)
    command_drift["command"] = ["python", "-m", "nex_wc.demo_runtime"]
    scenario_residue = deepcopy(service)
    scenario_residue["environment"]["NEX_WC_M1_FIXTURE"] = "enabled"
    dependency_drift = deepcopy(service)
    dependency_drift["depends_on"].pop("nex-oa")

    assert installation._product_wc_assignment_dispatch_profile(removed) is False
    assert (
        installation._product_wc_assignment_dispatch_profile(command_drift) is False
    )
    assert (
        installation._product_wc_assignment_dispatch_profile(scenario_residue)
        is False
    )
    assert (
        installation._product_wc_assignment_dispatch_profile(dependency_drift)
        is False
    )


def test_wc_image_is_non_root_and_dispatcher_package_check_is_isolated() -> None:
    definitions = build_current_oci_definitions()
    validate_oci_containerfiles(ROOT, definitions)
    wc = next(item for item in definitions if item.artifact_id == "nex-wc-runtime")
    containerfile = (ROOT / wc.containerfile).read_text(encoding="utf-8")
    output = StringIO()

    assert wc.target == "wc-runtime"
    assert "USER 65532:65532" in containerfile
    assert assignment_dispatch_process.main(
        ["--profile", "staging_live", "--check"],
        environ={RUNTIME_CHECK_MODE_ENV: RUNTIME_PACKAGE_CHECK_MODE},
        stdout=output,
    ) == 0
    record = json.loads(output.getvalue())
    assert record["process_id"] == PROCESS_ID
    assert record["package_ready"] is True
    assert record["runtime_ready"] is False
    assert record["database"] == {"status": "NOT_REQUESTED"}
    assert record["secret_included"] is False
