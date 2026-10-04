from __future__ import annotations

from dataclasses import replace

import pytest

from nex_runtime.topology import (
    PlatformRuntimeManifest,
    RuntimeEndpoint,
    RuntimeManifestError,
    RuntimeModes,
    RuntimeProbe,
    RuntimeProcess,
    runtime_manifest_public_projection,
    validate_runtime_manifest,
)


def manifest() -> PlatformRuntimeManifest:
    return PlatformRuntimeManifest(
        schema_version="platform_runtime_manifest.v1",
        profile="local_mock",
        modes=RuntimeModes("memory", "mock", "test_mock", "memory"),
        endpoints=(RuntimeEndpoint("nex-oa", "http://127.0.0.1:8101"),),
        processes=(
            RuntimeProcess(
                "nex-oa-api",
                "nex-oa",
                "api",
                ("python", "run_service.py"),
                host="127.0.0.1",
                port=8101,
                liveness_probe=RuntimeProbe("/health"),
                readiness_probe=RuntimeProbe("/ready"),
                environment_names=("NEX_PROFILE",),
            ),
            RuntimeProcess(
                "worker",
                "nex-cx",
                "worker",
                ("python", "worker.py"),
                dependencies=("nex-oa-api",),
            ),
        ),
    )


def test_manifest_validates_and_projects_without_commands() -> None:
    value = manifest()
    validate_runtime_manifest(value)

    projection = runtime_manifest_public_projection(value)

    assert projection["profile"] == "local_mock"
    assert projection["modes"]["provider"] == "mock"
    assert projection["processes"][0]["liveness_path"] == "/health"
    assert projection["processes"][0]["environment_name_count"] == 1
    assert projection["processes"][1]["dependencies"] == ["nex-oa-api"]
    assert all("command" not in item for item in projection["processes"])


@pytest.mark.parametrize(
    ("replacement", "message"),
    [
        ({"schema_version": "v2"}, "schema_version"),
        ({"profile": "unknown"}, "unsupported runtime profile"),
        ({"startup_timeout_seconds": 0}, "startup_timeout_seconds"),
        ({"shutdown_timeout_seconds": -1}, "shutdown_timeout_seconds"),
    ],
)
def test_manifest_rejects_invalid_header_fields(replacement, message) -> None:
    with pytest.raises(RuntimeManifestError, match=message):
        validate_runtime_manifest(replace(manifest(), **replacement))


@pytest.mark.parametrize(
    ("modes", "message"),
    [
        (RuntimeModes("disk", "mock", "test_mock", "memory"), "persistence"),
        (RuntimeModes("memory", "remote", "test_mock", "memory"), "provider"),
        (RuntimeModes("memory", "mock", "opaque", "memory"), "trust"),
        (RuntimeModes("memory", "mock", "test_mock", "database"), "ag_projection"),
    ],
)
def test_manifest_rejects_invalid_modes(modes, message) -> None:
    with pytest.raises(RuntimeManifestError, match=message):
        validate_runtime_manifest(replace(manifest(), modes=modes))


def test_manifest_rejects_endpoint_errors() -> None:
    bad = replace(
        manifest(),
        endpoints=(
            RuntimeEndpoint("", "ftp://host"),
            RuntimeEndpoint("nex-oa", "http://user:secret@host"),
            RuntimeEndpoint("nex-oa", "http://host?token=value"),
        ),
    )
    with pytest.raises(RuntimeManifestError) as raised:
        validate_runtime_manifest(bad)
    message = str(raised.value)
    assert "endpoint service_id must not be empty" in message
    assert "duplicate endpoint service_id" in message
    assert message.count("invalid endpoint base_url") == 3


def test_manifest_rejects_malformed_url_that_cannot_be_parsed() -> None:
    bad = replace(
        manifest(),
        endpoints=(RuntimeEndpoint("nex-oa", "http://[invalid"),),
    )

    with pytest.raises(RuntimeManifestError, match="invalid endpoint base_url"):
        validate_runtime_manifest(bad)


def test_manifest_rejects_process_identity_and_command_errors() -> None:
    bad = replace(
        manifest(),
        processes=(
            RuntimeProcess("", "", "batch", (), host="127.0.0.1", port=8101),
            RuntimeProcess("worker", "nex-cx", "worker", ("python", "")),
            RuntimeProcess("worker", "nex-cx", "worker", ("python",)),
        ),
    )
    with pytest.raises(RuntimeManifestError) as raised:
        validate_runtime_manifest(bad)
    message = str(raised.value)
    assert "process_id must not be empty" in message
    assert "process owner must not be empty" in message
    assert "unsupported process kind" in message
    assert "process command must not be empty" in message
    assert "duplicate process_id" in message


def test_manifest_rejects_network_probe_and_environment_errors() -> None:
    bad = replace(
        manifest(),
        processes=(
            RuntimeProcess("missing-network", "nex-oa", "api", ("python",)),
            RuntimeProcess(
                "bad-port", "nex-ae-api", "api", ("python",), host="127.0.0.1", port=0
            ),
            RuntimeProcess(
                "duplicate-address",
                "nex-cx",
                "api",
                ("python",),
                host="127.0.0.1",
                port=8101,
            ),
            RuntimeProcess(
                "duplicate-address-two",
                "nex-mo",
                "web",
                ("node",),
                host="127.0.0.1",
                port=8101,
                liveness_probe=RuntimeProbe("health", 0),
                environment_names=("PORT", "PORT"),
            ),
            RuntimeProcess(
                "bound-worker", "nex-ag", "daemon", ("python",), host="host", port=1
            ),
        ),
    )
    with pytest.raises(RuntimeManifestError) as raised:
        validate_runtime_manifest(bad)
    message = str(raised.value)
    assert "network process requires host and port" in message
    assert "invalid process port" in message
    assert "duplicate process address" in message
    assert "invalid liveness probe path" in message
    assert "invalid liveness probe timeout" in message
    assert "duplicate environment name" in message
    assert "invalid environment name" in message
    assert "background process must not bind a port" in message


def test_manifest_rejects_dependency_errors() -> None:
    worker = replace(
        manifest().processes[1],
        dependencies=("worker", "missing", "missing"),
    )
    with pytest.raises(RuntimeManifestError) as raised:
        validate_runtime_manifest(replace(manifest(), processes=(worker,)))
    message = str(raised.value)
    assert "self dependency" in message
    assert "unknown dependency" in message
    assert "duplicate dependency" in message
