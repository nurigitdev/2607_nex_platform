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
    build_agent_runtime_worker_check,
    build_agent_runtime_worker_profile,
    load_agent_runtime_worker_config,
    load_in_process_nsl_package_readiness,
    main,
    validate_agent_runtime_worker_startup,
)
from nex_ae_api.nsl_backend_profiles import (
    NSL_V01_IN_PROCESS_BACKEND,
    NSL_V01_PROCESS_ISOLATED_BACKEND,
)
from nex_runtime.nsl_package_admission import (
    NSL_INSTALLED_PACKAGE_READINESS_SCHEMA_VERSION,
    NslPackageAdmissionError,
    inspect_installed_nsl_package,
)

ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "deployment/locks/nsl-v0.1-wheel.json"
PLATFORM_LOCK_PATH = ROOT / "deployment/locks/python-production.lock"
NOW = "2026-10-16T08:00:00Z"


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
        resolved_digest = digest or lock["wheel_sha256"].removeprefix("sha256:")
        resolved_filename = filename or lock["wheel_filename"]
        self._direct_url = {
            "archive_info": {"hashes": {"sha256": resolved_digest}},
            "url": f"file:///admitted/{resolved_filename}",
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


def _package_readiness(tmp_path: Path) -> dict[str, Any]:
    lock = _lock()
    root = tmp_path / "site-packages"
    return inspect_installed_nsl_package(
        lock,
        platform_lock_path=PLATFORM_LOCK_PATH,
        distribution_loader=lambda _name: _Distribution(lock, root),
        version_loader=lambda _name: lock["locked_cryptography_version"],
        module_loader=lambda _name: _api(root, lock["public_api_symbols"]),
    )


def _config(profile: str) -> AgentRuntimeWorkerConfig:
    return AgentRuntimeWorkerConfig(
        mode="enabled",
        profile=build_agent_runtime_worker_profile(
            worker_id="ae-runtime-worker-s5",
            declared_at=NOW,
            supported_backend_profiles=(profile,),
            process_isolation_required=(profile == NSL_V01_PROCESS_ISOLATED_BACKEND),
        ),
    )


def test_installed_package_readiness_binds_wheel_dependency_and_public_api(
    tmp_path: Path,
) -> None:
    readiness = _package_readiness(tmp_path)

    assert readiness["status"] == "PASS"
    assert readiness["schema_version"] == (
        NSL_INSTALLED_PACKAGE_READINESS_SCHEMA_VERSION
    )
    assert readiness["wheel_sha256"] == _lock()["wheel_sha256"]
    assert readiness["platform_lock_sha256"] == _lock()["platform_lock_sha256"]
    assert readiness["runtime_import_origin"] == "installed_distribution"
    assert readiness["admission_lock_hash"].startswith("sha256:")


@pytest.mark.parametrize(
    (
        "distribution_values",
        "crypto_version",
        "api_outside",
        "missing_symbol",
        "message",
    ),
    (
        ({"version": "0.2.0"}, "46.0.7", False, False, "package version"),
        ({"digest": "0" * 64}, "46.0.7", False, False, "wheel digest"),
        ({"filename": "other.whl"}, "46.0.7", False, False, "wheel origin"),
        ({}, "45.0.0", False, False, "cryptography"),
        ({}, "46.0.7", True, False, "installed distribution"),
        ({}, "46.0.7", False, True, "public API"),
    ),
)
def test_installed_package_readiness_fails_closed_on_runtime_drift(
    tmp_path: Path,
    distribution_values: dict[str, str],
    crypto_version: str,
    api_outside: bool,
    missing_symbol: bool,
    message: str,
) -> None:
    lock = _lock()
    root = tmp_path / "site-packages"
    api_root = tmp_path / "checkout" if api_outside else root
    symbols = list(lock["public_api_symbols"])
    if missing_symbol:
        symbols.pop()

    with pytest.raises(NslPackageAdmissionError, match=message):
        inspect_installed_nsl_package(
            lock,
            platform_lock_path=PLATFORM_LOCK_PATH,
            distribution_loader=lambda _name: _Distribution(
                lock, root, **distribution_values
            ),
            version_loader=lambda _name: crypto_version,
            module_loader=lambda _name: _api(api_root, symbols),
        )


def test_installed_package_readiness_rejects_lock_and_loader_failures(
    tmp_path: Path,
) -> None:
    lock = _lock()
    for changed in (
        {**lock, "unexpected": True},
        {**lock, "schema_version": "other"},
        {**lock, "distribution": "other"},
        {**lock, "source_revision": "bad"},
        {**lock, "wheel_sha256": "bad"},
        {**lock, "wheel_filename": "../unsafe.whl"},
        {**lock, "public_api_symbols": []},
    ):
        with pytest.raises(NslPackageAdmissionError):
            inspect_installed_nsl_package(
                changed,
                platform_lock_path=PLATFORM_LOCK_PATH,
            )

    with pytest.raises(NslPackageAdmissionError, match="evidence"):
        inspect_installed_nsl_package(
            lock,
            platform_lock_path=PLATFORM_LOCK_PATH,
            distribution_loader=lambda _name: (_ for _ in ()).throw(ImportError()),
        )
    malformed_distribution = _Distribution(lock, tmp_path)
    malformed_distribution._direct_url = []
    with pytest.raises(NslPackageAdmissionError, match="evidence"):
        inspect_installed_nsl_package(
            lock,
            platform_lock_path=PLATFORM_LOCK_PATH,
            distribution_loader=lambda _name: malformed_distribution,
        )
    missing_lock = tmp_path / "missing.lock"
    with pytest.raises(NslPackageAdmissionError, match="dependency lock"):
        inspect_installed_nsl_package(
            lock,
            platform_lock_path=missing_lock,
            distribution_loader=lambda _name: _Distribution(lock, tmp_path),
            version_loader=lambda _name: lock["locked_cryptography_version"],
            module_loader=lambda _name: _api(tmp_path, lock["public_api_symbols"]),
        )


def test_in_process_worker_startup_requires_admitted_package_readiness(
    tmp_path: Path,
) -> None:
    config = _config(NSL_V01_IN_PROCESS_BACKEND)
    readiness = _package_readiness(tmp_path)
    available = {
        "available_executor_kinds": (LOCAL_SKILL_EXECUTOR,),
        "available_backend_profiles": (NSL_V01_IN_PROCESS_BACKEND,),
    }

    startup = validate_agent_runtime_worker_startup(
        config,
        in_process_package_readiness=readiness,
        **available,
    )
    assert startup["startup_ready"] is True
    assert startup["in_process_package_status"] == "PASS"

    for evidence in (None, {**readiness, "status": "FAIL"}, {"status": "PASS"}):
        with pytest.raises(AgentRuntimeWorkerError) as caught:
            validate_agent_runtime_worker_startup(
                config,
                in_process_package_readiness=evidence,
                **available,
            )
        assert caught.value.error_code == "ae.agent_runtime_worker.nsl_package_unready"

    failed = build_agent_runtime_worker_check(config, **available)
    assert failed["status"] == "FAIL"
    assert failed["failure_code"] == "ae.agent_runtime_worker.nsl_package_unready"


def test_process_isolated_compatibility_needs_no_in_process_package() -> None:
    config = _config(NSL_V01_PROCESS_ISOLATED_BACKEND)
    startup = validate_agent_runtime_worker_startup(
        config,
        available_executor_kinds=(LOCAL_SKILL_EXECUTOR,),
        available_backend_profiles=(NSL_V01_PROCESS_ISOLATED_BACKEND,),
    )

    assert startup["startup_ready"] is True
    assert startup["in_process_package_status"] == "NOT_CONFIGURED"


def test_worker_environment_defaults_to_in_process_and_cli_auto_loads_readiness(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    readiness = _package_readiness(tmp_path)
    config = load_agent_runtime_worker_config({}, declared_at=NOW)
    assert config.profile.supported_backend_profiles == (NSL_V01_IN_PROCESS_BACKEND,)
    assert config.profile.process_isolation_required is False

    monkeypatch.setattr(
        worker_module,
        "load_in_process_nsl_package_readiness",
        lambda _environ, **_kwargs: readiness,
    )
    output = io.StringIO()
    exit_code = main(
        ["--check"],
        environ={"NEX_AE_AGENT_WORKER_MODE": "enabled"},
        stdout=output,
        available_executor_kinds=(LOCAL_SKILL_EXECUTOR,),
        available_backend_profiles=(NSL_V01_IN_PROCESS_BACKEND,),
    )
    assert exit_code == 0
    assert json.loads(output.getvalue())["in_process_package_status"] == "PASS"


def test_readiness_loader_is_fail_closed_for_missing_or_invalid_lock(
    tmp_path: Path,
) -> None:
    missing = load_in_process_nsl_package_readiness(lock_path=tmp_path / "missing")
    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text("[]", encoding="utf-8")
    invalid = load_in_process_nsl_package_readiness(lock_path=invalid_path)

    assert missing["status"] == "FAIL"
    assert invalid["status"] == "FAIL"
    assert missing["in_process_profile_admissible"] is False
