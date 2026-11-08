from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from nex_ae_api import agent_runtime_worker as worker_module
from nex_ae_api.agent_runtime_worker import (
    LOCAL_SKILL_EXECUTOR,
    AgentRuntimeWorkerConfig,
    AgentRuntimeWorkerError,
    build_agent_runtime_worker_profile,
    load_agent_runtime_worker_config,
    load_in_process_nsl_package_readiness,
    main,
    validate_agent_runtime_worker_startup,
)
from nex_ae_api.nsl_backend_profiles import (
    NSL_V01_IN_PROCESS_BACKEND,
    NSL_V02_IN_PROCESS_BACKEND,
)
from nex_runtime.nsl_package_admission import (
    NSL_INSTALLED_V02_PACKAGE_READINESS_SCHEMA_VERSION,
    NslPackageAdmissionError,
    inspect_installed_nsl_package,
)

ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "deployment/locks/nsl-v0.2-wheel.json"
PLATFORM_LOCK_PATH = ROOT / "deployment/locks/python-production.lock"
NOW = "2026-10-21T00:00:00Z"


class _Distribution:
    def __init__(
        self,
        lock: dict[str, Any],
        root: Path,
        *,
        version: str | None = None,
        digest: str | None = None,
        filename: str | None = None,
    ) -> None:
        self.version = version or lock["package_version"]
        self._root = root
        self._direct_url = {
            "archive_info": {
                "hashes": {
                    "sha256": digest
                    or lock["wheel_sha256"].removeprefix("sha256:")
                }
            },
            "url": f"file:///admitted/{filename or lock['wheel_filename']}",
        }

    def read_text(self, name: str) -> str | None:
        return json.dumps(self._direct_url) if name == "direct_url.json" else None

    def locate_file(self, _name: str) -> Path:
        return self._root


def _lock() -> dict[str, Any]:
    return json.loads(LOCK_PATH.read_text(encoding="utf-8"))


def _api(root: Path, symbols: list[str]) -> SimpleNamespace:
    api = SimpleNamespace(__file__=str(root / "nsl/api/__init__.py"))
    for symbol in symbols:
        setattr(api, symbol, object())
    return api


def _readiness(tmp_path: Path) -> dict[str, Any]:
    lock = _lock()
    root = tmp_path / "site-packages"
    return inspect_installed_nsl_package(
        lock,
        platform_lock_path=PLATFORM_LOCK_PATH,
        distribution_loader=lambda _name: _Distribution(lock, root),
        version_loader=lambda _name: lock["locked_cryptography_version"],
        module_loader=lambda _name: _api(root, lock["public_api_symbols"]),
    )


def _config(*profiles: str) -> AgentRuntimeWorkerConfig:
    return AgentRuntimeWorkerConfig(
        mode="enabled",
        profile=build_agent_runtime_worker_profile(
            worker_id="ae-runtime-worker-p8-s04",
            declared_at=NOW,
            supported_backend_profiles=profiles,
        ),
    )


def test_v02_installed_readiness_binds_exact_lock_and_release(tmp_path: Path) -> None:
    readiness = _readiness(tmp_path)
    lock = _lock()

    assert readiness["schema_version"] == (
        NSL_INSTALLED_V02_PACKAGE_READINESS_SCHEMA_VERSION
    )
    assert readiness["lock_schema_version"] == "nsl_wheel_lock.v2"
    assert readiness["package_version"] == "0.2.0"
    assert readiness["source_revision"] == lock["source_revision"]
    assert readiness["source_tree"] == lock["source_tree"]
    assert readiness["wheel_sha256"] == lock["wheel_sha256"]
    assert readiness["release_admission_hash"].startswith("sha256:")
    assert readiness["certification_reference"] == lock["certification_reference"]


@pytest.mark.parametrize(
    ("distribution_values", "crypto", "api_outside", "missing_api", "message"),
    [
        ({"version": "0.1.0"}, "46.0.7", False, False, "package version"),
        ({"digest": "0" * 64}, "46.0.7", False, False, "wheel digest"),
        ({"filename": "other.whl"}, "46.0.7", False, False, "wheel origin"),
        ({}, "46.0.6", False, False, "cryptography"),
        ({}, "46.0.7", True, False, "installed distribution"),
        ({}, "46.0.7", False, True, "public API"),
    ],
)
def test_v02_installed_readiness_fails_closed_on_runtime_drift(
    tmp_path: Path,
    distribution_values: dict[str, str],
    crypto: str,
    api_outside: bool,
    missing_api: bool,
    message: str,
) -> None:
    lock = _lock()
    root = tmp_path / "site-packages"
    api_root = tmp_path / "checkout" if api_outside else root
    symbols = list(lock["public_api_symbols"])
    if missing_api:
        symbols.pop()

    with pytest.raises(NslPackageAdmissionError, match=message):
        inspect_installed_nsl_package(
            lock,
            platform_lock_path=PLATFORM_LOCK_PATH,
            distribution_loader=lambda _name: _Distribution(
                lock, root, **distribution_values
            ),
            version_loader=lambda _name: crypto,
            module_loader=lambda _name: _api(api_root, symbols),
        )


def test_v02_worker_startup_requires_matching_v02_readiness(tmp_path: Path) -> None:
    config = _config(NSL_V02_IN_PROCESS_BACKEND)
    readiness = _readiness(tmp_path)
    available = {
        "available_executor_kinds": (LOCAL_SKILL_EXECUTOR,),
        "available_backend_profiles": (NSL_V02_IN_PROCESS_BACKEND,),
    }

    startup = validate_agent_runtime_worker_startup(
        config, in_process_package_readiness=readiness, **available
    )
    assert startup["startup_ready"] is True
    assert startup["in_process_package_status"] == "PASS"

    for drift in (
        {**readiness, "schema_version": "nsl_installed_package_readiness.v1"},
        {**readiness, "package_version": "0.1.0"},
        {**readiness, "lock_schema_version": "nsl_wheel_lock.v1"},
    ):
        with pytest.raises(AgentRuntimeWorkerError) as caught:
            validate_agent_runtime_worker_startup(
                config, in_process_package_readiness=drift, **available
            )
        assert caught.value.error_code == "ae.agent_runtime_worker.nsl_package_unready"


def test_worker_rejects_multiple_in_process_package_versions(tmp_path: Path) -> None:
    config = _config(NSL_V01_IN_PROCESS_BACKEND, NSL_V02_IN_PROCESS_BACKEND)

    with pytest.raises(AgentRuntimeWorkerError) as caught:
        validate_agent_runtime_worker_startup(
            config,
            available_executor_kinds=(LOCAL_SKILL_EXECUTOR,),
            available_backend_profiles=(
                NSL_V01_IN_PROCESS_BACKEND,
                NSL_V02_IN_PROCESS_BACKEND,
            ),
            in_process_package_readiness=_readiness(tmp_path),
        )
    assert caught.value.error_code == (
        "ae.agent_runtime_worker.nsl_package_profile_conflict"
    )


def test_v02_config_and_loader_select_v02_lock_without_changing_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    default = load_agent_runtime_worker_config({}, declared_at=NOW)
    selected = load_agent_runtime_worker_config(
        {"NEX_AE_AGENT_WORKER_BACKEND_PROFILES": NSL_V02_IN_PROCESS_BACKEND},
        declared_at=NOW,
    )
    assert default.profile.supported_backend_profiles == (
        NSL_V01_IN_PROCESS_BACKEND,
    )
    assert selected.profile.supported_backend_profiles == (
        NSL_V02_IN_PROCESS_BACKEND,
    )

    captured: dict[str, object] = {}

    def fake_inspection(lock, *, platform_lock_path):
        captured.update(lock=lock, platform_lock_path=platform_lock_path)
        return {"status": "PASS"}

    monkeypatch.setattr(worker_module, "inspect_installed_nsl_package", fake_inspection)
    assert load_in_process_nsl_package_readiness(
        {}, backend_profiles=(NSL_V02_IN_PROCESS_BACKEND,)
    ) == {"status": "PASS"}
    assert captured["lock"]["schema_version"] == "nsl_wheel_lock.v2"


def test_v02_worker_check_auto_loads_profile_specific_readiness(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    readiness = _readiness(tmp_path)
    captured: dict[str, object] = {}

    def fake_loader(_environ, **kwargs):
        captured.update(kwargs)
        return readiness

    monkeypatch.setattr(
        worker_module, "load_in_process_nsl_package_readiness", fake_loader
    )
    output = io.StringIO()
    exit_code = main(
        ["--check"],
        environ={
            "NEX_AE_AGENT_WORKER_MODE": "enabled",
            "NEX_AE_AGENT_WORKER_BACKEND_PROFILES": NSL_V02_IN_PROCESS_BACKEND,
        },
        stdout=output,
        available_executor_kinds=(LOCAL_SKILL_EXECUTOR,),
        available_backend_profiles=(NSL_V02_IN_PROCESS_BACKEND,),
    )

    assert exit_code == 0
    assert captured["backend_profiles"] == (NSL_V02_IN_PROCESS_BACKEND,)
    assert json.loads(output.getvalue())["in_process_package_status"] == "PASS"
