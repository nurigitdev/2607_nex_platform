from __future__ import annotations

import tomllib
from pathlib import Path

import mybee_ax


ROOT = Path(__file__).resolve().parents[2]


def test_mb0_01_domain_package_identity_is_stable() -> None:
    assert mybee_ax.DOMAIN_ID == "mybee"
    assert mybee_ax.PACKAGE_VERSION == "0.1.0"
    assert mybee_ax.CANONICAL_PLATFORM_OWNERS == (
        "nex-oa",
        "nex-ae-api",
        "nex-wc",
        "nex-eos",
        "nex-wa",
        "nex-cx",
        "nex-mo",
        "nex-ag",
    )


def test_mb0_01_package_metadata_and_test_discovery_are_admitted() -> None:
    domain_config = tomllib.loads(
        (ROOT / "domains/mybee/pyproject.toml").read_text(encoding="utf-8")
    )
    root_config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert domain_config["project"] == {
        "name": "nex-mybee-ax",
        "version": "0.1.0",
        "description": (
            "MyBee office-work domain policy and NeX canonical API consumers"
        ),
        "requires-python": ">=3.12",
        "license": {"text": "Proprietary"},
    }
    pytest_config = root_config["tool"]["pytest"]["ini_options"]
    assert pytest_config["testpaths"] == ["tests"]
    assert "domains/mybee" in pytest_config["pythonpath"]
    assert "domains" in root_config["tool"]["coverage"]["run"]["source"]


def test_mb0_01_compatibility_lock_is_packaging_independent() -> None:
    assert (ROOT / "domains/mybee/compatibility/platform.lock.json").is_file()
    assert not (ROOT / "domains/mybee/mybee_ax/compatibility").exists()
