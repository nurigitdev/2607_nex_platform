from __future__ import annotations

from dataclasses import replace

import pytest

from nex_runtime.deployment_acceptance import (
    NETWORK_PROCESS_IDS,
    PACKAGED_RUNTIME_ACCEPTANCE_SCHEMA_VERSION,
    PackagedRuntimeAcceptanceError,
    build_packaged_runtime_acceptance_evidence,
    packaged_runtime_acceptance_projection,
    validate_packaged_runtime_acceptance_evidence,
)
from nex_runtime.deployment_artifacts import (
    build_default_deployment_artifact_catalog,
)
from nex_runtime.postgres_orchestration import POSTGRES_SERVICE_ORDER
from nex_runtime.process_manifest import BACKGROUND_PROCESS_IDS


def _context_digests() -> tuple[tuple[str, str], ...]:
    catalog = build_default_deployment_artifact_catalog()
    return tuple(
        (artifact.artifact_id, f"sha256:{index:064x}")
        for index, artifact in enumerate(catalog.artifacts, start=1)
    )


def _evidence():
    return build_packaged_runtime_acceptance_evidence(
        artifact_context_digests=_context_digests(),
        migrated_service_ids=tuple(POSTGRES_SERVICE_ORDER),
        background_check_process_ids=tuple(BACKGROUND_PROCESS_IDS),
        startup_generations=(NETWORK_PROCESS_IDS, NETWORK_PROCESS_IDS),
        postgres_identity_count=5,
        oci_daemon_status="UNAVAILABLE_PERMISSION_OR_SOCKET",
    )


def test_package_context_acceptance_is_complete_and_private() -> None:
    evidence = _evidence()
    projection = packaged_runtime_acceptance_projection(evidence)

    assert evidence.schema_version == PACKAGED_RUNTIME_ACCEPTANCE_SCHEMA_VERSION
    assert projection["status"] == "PACKAGE_CONTEXT_ACCEPTED"
    assert projection["profile"] == "test"
    assert projection["execution_mode"] == "materialized_package_context"
    assert len(projection["artifact_contexts"]) == 6
    assert len(projection["migrated_service_ids"]) == 5
    assert len(projection["background_check_process_ids"]) == 7
    assert projection["startup_generations"] == [
        list(NETWORK_PROCESS_IDS),
        list(NETWORK_PROCESS_IDS),
    ]
    assert projection["image_build_performed"] is False
    assert projection["production_contacted"] is False
    assert projection["runtime_values_included"] is False
    assert projection["machine_paths_included"] is False
    assert projection["credentials_included"] is False


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({"schema_version": "wrong"}, "schema version"),
        ({"status": "wrong"}, "status drift"),
        ({"profile": "production"}, "profile must be test"),
        ({"execution_mode": "image"}, "execution mode drift"),
        ({"artifact_context_digests": ()}, "context coverage"),
        (
            {
                "artifact_context_digests": tuple(
                    (artifact_id, "bad")
                    for artifact_id, _ in _context_digests()
                )
            },
            "context digest is invalid",
        ),
        (
            {
                "artifact_context_digests": tuple(
                    (artifact_id, "sha256:" + "0" * 64)
                    for artifact_id, _ in _context_digests()
                )
            },
            "digests must be unique",
        ),
        ({"migrated_service_ids": ()}, "migration service order"),
        ({"background_check_process_ids": ()}, "background packaged check"),
        ({"startup_generations": ()}, "restart evidence"),
        ({"postgres_identity_count": 4}, "identity evidence"),
        ({"oci_daemon_status": "UNKNOWN"}, "daemon status"),
        ({"image_build_performed": True}, "cannot claim an image build"),
        ({"complete_set_restart_observed": False}, "restart was not observed"),
        ({"mixed_artifact_set_allowed": True}, "mixed artifact sets"),
        ({"database_downgrade_performed": True}, "downgrade"),
        ({"production_contacted": True}, "production contact"),
    ),
)
def test_acceptance_rejects_drift(changes, message: str) -> None:
    with pytest.raises(PackagedRuntimeAcceptanceError, match=message):
        validate_packaged_runtime_acceptance_evidence(
            replace(_evidence(), **changes)
        )


def test_all_supported_oci_daemon_states_are_metadata_only() -> None:
    for status in (
        "AVAILABLE_NOT_USED",
        "UNAVAILABLE_PERMISSION_OR_SOCKET",
        "UNAVAILABLE_NOT_INSTALLED",
    ):
        evidence = replace(_evidence(), oci_daemon_status=status)
        validate_packaged_runtime_acceptance_evidence(evidence)

