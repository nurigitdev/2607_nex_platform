from __future__ import annotations

import json
from pathlib import Path

import admit_nsl_wheel as command
import pytest
from nex_ae_api import agent_runtime_worker as worker_module
from nex_ae_api import nsl_v02_public_api as api_module
from nex_ae_api.nsl_v02_public_api import (
    NSL_V02_REQUIRED_PUBLIC_SYMBOLS,
    load_nsl_v02_public_api,
)
from nex_ae_api.nsl_backend_profiles import NSL_V02_IN_PROCESS_BACKEND
from nex_runtime.nsl_package_admission import NslPackageAdmissionError
from nex_runtime.nsl_v02_wheel_lock import normalize_nsl_v02_wheel_lock


ROOT = Path(__file__).resolve().parents[1]
V020_LOCK = ROOT / "deployment/locks/nsl-v0.2-wheel.json"
V021_LOCK = ROOT / "deployment/locks/nsl-v0.2.1-wheel.json"
HASH = "sha256:" + "a" * 64


def _readiness(version: str) -> dict[str, object]:
    return {
        "schema_version": "nsl_installed_package_readiness.v2",
        "status": "PASS",
        "lock_schema_version": "nsl_wheel_lock.v2",
        "distribution": "nex-skill-language",
        "package_version": version,
        "runtime_import_origin": "installed_distribution",
        "public_api_complete": True,
        "in_process_profile_admissible": True,
        "public_api_symbols": list(NSL_V02_REQUIRED_PUBLIC_SYMBOLS),
        "release_admission_hash": HASH,
    }


def _symbols() -> tuple[type, ...]:
    return tuple(type(name, (), {}) for name in NSL_V02_REQUIRED_PUBLIC_SYMBOLS)


def test_v021_lock_is_additive_and_exact() -> None:
    historical = json.loads(V020_LOCK.read_text(encoding="utf-8"))
    current = json.loads(V021_LOCK.read_text(encoding="utf-8"))

    assert historical["package_version"] == "0.2.0"
    assert historical["wheel_sha256"] == (
        "sha256:862958a5eab982a71bec5ee58b9e530867d6c25f65d8b770efb29ca78ce7f135"
    )
    assert current["package_version"] == "0.2.1"
    assert current["source_revision"] == command.P8_V021_SOURCE_REVISION
    assert current["source_tree"] == command.P8_V021_SOURCE_TREE
    assert current["wheel_sha256"] == command.P8_V021_WHEEL_SHA256
    assert normalize_nsl_v02_wheel_lock(historical) == historical
    assert normalize_nsl_v02_wheel_lock(current) == current


def test_v02_lock_rejects_unadmitted_patch_version() -> None:
    lock = json.loads(V021_LOCK.read_text(encoding="utf-8"))
    lock["package_version"] = "0.2.2"
    lock["wheel_filename"] = "nex_skill_language-0.2.2-py3-none-any.whl"

    with pytest.raises(NslPackageAdmissionError, match="version"):
        normalize_nsl_v02_wheel_lock(lock)


def test_v021_release_profile_selects_exact_admission(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, object] = {}

    def fake_run(**kwargs: object) -> dict[str, str]:
        captured.update(kwargs)
        return {"status": "PASS"}

    monkeypatch.setattr(command, "run_nsl_wheel_admission", fake_run)
    monkeypatch.setattr(
        command.sys,
        "argv",
        ["admit_nsl_wheel.py", "--release-profile", "v0.2.1"],
    )

    assert command.main() == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"
    assert captured["expected_version"] == "0.2.1"
    assert captured["expected_source_revision"] == command.P8_V021_SOURCE_REVISION
    assert captured["expected_source_tree"] == command.P8_V021_SOURCE_TREE
    assert captured["expected_wheel_sha256"] == command.P8_V021_WHEEL_SHA256
    assert captured["lock"] == command.P8_V021_LOCK
    assert captured["release_slice"] == "P8-S99A"


def test_worker_selects_v021_lock_and_accepts_only_admitted_v02_versions() -> None:
    assert worker_module.DEFAULT_NSL_V02_WHEEL_LOCK == V021_LOCK

    for version in ("0.2.0", "0.2.1"):
        assert (
            worker_module._in_process_package_status(
                _readiness(version), profile=NSL_V02_IN_PROCESS_BACKEND
            )
            == "PASS"
        )
    assert (
        worker_module._in_process_package_status(
            _readiness("0.2.2"), profile=NSL_V02_IN_PROCESS_BACKEND
        )
        == "FAIL"
    )


def test_public_api_contract_binds_admitted_patch_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api_module, "_import_public_api", _symbols)

    historical = load_nsl_v02_public_api(_readiness("0.2.0"))
    current = load_nsl_v02_public_api(_readiness("0.2.1"))

    assert historical.api_contract_hash != current.api_contract_hash
