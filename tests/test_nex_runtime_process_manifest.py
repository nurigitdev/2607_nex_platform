from __future__ import annotations

from pathlib import Path

import pytest

from nex_runtime.process_manifest import (
    BACKGROUND_PROCESS_IDS,
    _command_target,
    _database_environment,
    _network_address,
    build_platform_runtime_manifest,
    validate_runtime_command_targets,
)
from nex_runtime.topology import (
    RuntimeManifestError,
    RuntimeProcess,
    runtime_manifest_public_projection,
)
from nex_runtime.topology_graph import build_runtime_startup_plan


ROOT = Path(__file__).resolve().parents[1]


def test_local_mock_manifest_materializes_complete_process_topology() -> None:
    manifest = build_platform_runtime_manifest(
        environ={}, python_executable="python"
    )
    projection = runtime_manifest_public_projection(manifest)
    plan = build_runtime_startup_plan(manifest)
    validate_runtime_command_targets(manifest, ROOT)

    assert len(manifest.endpoints) == 6
    assert len(manifest.processes) == 13
    assert [item.kind for item in manifest.processes].count("api") == 5
    assert [item.kind for item in manifest.processes].count("web") == 1
    assert [item.kind for item in manifest.processes].count("worker") == 5
    assert [item.kind for item in manifest.processes].count("daemon") == 2
    assert set(BACKGROUND_PROCESS_IDS).issubset(plan.ordered_process_ids)
    assert plan.layers[0] == ("nex-oa-api",)
    assert plan.ordered_process_ids[-1] == "nex-ag-dispatch-daemon"
    assert all("command" not in item for item in projection["processes"])


def test_manifest_uses_endpoint_overrides_and_profile_selection() -> None:
    manifest = build_platform_runtime_manifest(
        environ={
            "NEX_PROFILE": "local_mock",
            "NEX_MO_BASE_URL": "http://mo.internal:9105",
            "NEX_AE_WEB_BASE_URL": "http://web.internal:5174/",
        },
        python_executable="custom-python",
    )
    processes = {item.process_id: item for item in manifest.processes}

    assert processes["nex-mo-api"].host == "mo.internal"
    assert processes["nex-mo-api"].port == 9105
    assert processes["nex-ae-web"].host == "web.internal"
    assert processes["nex-ae-web"].port == 5174
    assert processes["nex-cx-ingestion-worker"].command[0] == "custom-python"


def test_manifest_rejects_invalid_web_endpoint() -> None:
    with pytest.raises(RuntimeManifestError, match="nex-ae-web"):
        build_platform_runtime_manifest(
            environ={"NEX_AE_WEB_BASE_URL": "ftp://web.internal"}
        )


def test_command_target_validation_fails_closed(tmp_path: Path) -> None:
    manifest = build_platform_runtime_manifest(environ={})

    with pytest.raises(RuntimeManifestError, match="runtime command target is missing"):
        validate_runtime_command_targets(manifest, tmp_path)


def test_process_manifest_helpers_cover_defensive_branches() -> None:
    assert _database_environment("nex-cx", "test") == "NEX_CX_TEST_DATABASE_URL"
    assert _network_address("https://secure.internal") == ("secure.internal", 443)
    assert _network_address("http://plain.internal") == ("plain.internal", 80)
    with pytest.raises(RuntimeManifestError, match="host is missing"):
        _network_address("relative-only")

    process = RuntimeProcess("id", "owner", "worker", ("python", "-m", "module"))
    assert _command_target(process) is None
    process = RuntimeProcess(
        "id", "owner", "worker", ("python", "flag", "scripts/run.py")
    )
    assert _command_target(process) == "scripts/run.py"
