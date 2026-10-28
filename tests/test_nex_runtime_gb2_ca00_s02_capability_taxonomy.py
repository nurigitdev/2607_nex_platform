from __future__ import annotations

from dataclasses import replace

import pytest
from nex_runtime.deployment_artifacts import (
    build_current_deployment_artifact_catalog,
    build_default_deployment_artifact_catalog,
)
from nex_runtime.deployment_entrypoints import (
    PACKAGED_DOMAIN_PROCESS_CAPABILITIES,
    PACKAGED_DOMAIN_WORK_CAPABILITIES,
    PACKAGED_ENTRYPOINT_CAPABILITIES,
    PackagedEntrypointError,
    build_current_packaged_runtime_manifest,
    build_packaged_entrypoint_definitions,
    build_packaged_runtime_manifest,
    packaged_capability_enables_domain_work,
    packaged_entrypoints_projection,
    validate_packaged_entrypoints,
)


def test_capability_taxonomy_is_bounded_and_semantically_distinct() -> None:
    assert PACKAGED_ENTRYPOINT_CAPABILITIES == (
        "request_serving",
        "static_serving",
        "job_claiming",
        "event_delivering",
        "outbox_publishing",
        "scheduled_maintenance",
        "lifecycle_only",
    )
    assert PACKAGED_DOMAIN_WORK_CAPABILITIES == (
        "job_claiming",
        "event_delivering",
        "outbox_publishing",
        "scheduled_maintenance",
    )
    assert {
        capability: packaged_capability_enables_domain_work(capability)
        for capability in PACKAGED_ENTRYPOINT_CAPABILITIES
    } == {
        "request_serving": False,
        "static_serving": False,
        "job_claiming": True,
        "event_delivering": True,
        "outbox_publishing": True,
        "scheduled_maintenance": True,
        "lifecycle_only": False,
    }

    with pytest.raises(PackagedEntrypointError, match="unsupported packaged capability"):
        packaged_capability_enables_domain_work("unknown")


def test_promotion_targets_have_distinct_pre_admitted_capabilities() -> None:
    bindings = dict(PACKAGED_DOMAIN_PROCESS_CAPABILITIES)

    assert bindings["nex-ae-agent-runtime-worker"] == "job_claiming"
    assert bindings["nex-wc-event-delivery-worker"] == "event_delivering"
    assert bindings["nex-eos-outbox-publisher"] == "outbox_publishing"
    assert len(PACKAGED_DOMAIN_PROCESS_CAPABILITIES) == len(bindings)


def test_lifecycle_only_process_cannot_claim_domain_work_acceptance() -> None:
    manifest = build_packaged_runtime_manifest("local_mock", environ={})
    catalog = build_default_deployment_artifact_catalog()
    definitions = build_packaged_entrypoint_definitions(manifest, catalog)
    lifecycle = next(
        entry for entry in definitions if entry.capability == "lifecycle_only"
    )
    forged = replace(lifecycle, capability="event_delivering")

    with pytest.raises(PackagedEntrypointError) as raised:
        validate_packaged_entrypoints(
            manifest,
            catalog,
            tuple(forged if entry is lifecycle else entry for entry in definitions),
        )

    detail = str(raised.value)
    assert "domain-work loop is not admitted" in detail
    assert "packaged capability binding drift" in detail


def test_historical_and_current_manifests_remain_compatible() -> None:
    historical_manifest = build_packaged_runtime_manifest("local_mock", environ={})
    historical = build_packaged_entrypoint_definitions(
        historical_manifest,
        build_default_deployment_artifact_catalog(),
    )
    current_manifest = build_current_packaged_runtime_manifest(
        "local_mock", environ={}
    )
    current = build_packaged_entrypoint_definitions(
        current_manifest,
        build_current_deployment_artifact_catalog(),
    )

    historical_projection = packaged_entrypoints_projection(historical)
    current_projection = packaged_entrypoints_projection(current)

    assert historical_projection["entrypoint_count"] == 13
    assert historical_projection["background_entrypoint_count"] == 7
    assert historical_projection["domain_work_background_count"] == 1
    assert historical_projection["job_claiming_background_count"] == 1
    assert historical_projection["lifecycle_only_background_count"] == 6

    assert current_projection["entrypoint_count"] == 20
    assert current_projection["background_entrypoint_count"] == 11
    assert current_projection["domain_work_background_count"] == 5
    assert current_projection["job_claiming_background_count"] == 3
    assert current_projection["lifecycle_only_background_count"] == 6
    assert current_projection["event_delivering_background_count"] == 1
    assert current_projection["outbox_publishing_background_count"] == 1
    assert current_projection["scheduled_maintenance_background_count"] == 0
    assert current_projection["capability_counts"] == {
        "request_serving": 8,
        "static_serving": 1,
        "job_claiming": 3,
        "event_delivering": 1,
        "outbox_publishing": 1,
        "scheduled_maintenance": 0,
        "lifecycle_only": 6,
    }
    assert all(
        entry["domain_work_enabled"] is False
        for entry in current_projection["entrypoints"]
        if entry["capability"] == "lifecycle_only"
    )
