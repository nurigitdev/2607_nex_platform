from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from nex_runtime.deployment_artifacts import (
    DeploymentArtifactCatalog,
    build_default_deployment_artifact_catalog,
)
from nex_runtime.deployment_locks import (
    DEPLOYMENT_BUILD_INPUTS_SCHEMA_VERSION,
    NODE_LOCK_PATH,
    PYTHON_LOCK_COMMAND,
    PYTHON_LOCK_PATH,
    DependencyLockRecord,
    DeploymentBuildInputs,
    DeploymentLockError,
    _file_sha256,
    _node_lock_record,
    _python_lock_record,
    build_deployment_build_inputs,
    canonical_deployment_build_inputs,
    deployment_build_inputs_digest,
    deployment_build_inputs_projection,
    validate_deployment_build_inputs,
)


ROOT = Path(__file__).resolve().parents[1]
HASH = "a" * 64


def test_repository_build_inputs_are_locked_and_deterministic() -> None:
    inputs = build_deployment_build_inputs(ROOT)
    projection = deployment_build_inputs_projection(inputs)

    assert inputs.python_runtime == "3.12"
    assert inputs.node_runtime == "22"
    assert [item["lock_id"] for item in projection["locks"]] == [
        "node-production",
        "python-production",
    ]
    assert projection["locks"][0]["package_count"] == 4
    assert projection["locks"][1]["package_count"] == 52
    assert projection["locks"][1]["integrity_count"] > 1000
    assert deployment_build_inputs_digest(inputs).startswith("sha256:")

    reversed_inputs = replace(inputs, locks=tuple(reversed(inputs.locks)))
    assert canonical_deployment_build_inputs(inputs) == (
        canonical_deployment_build_inputs(reversed_inputs)
    )
    assert deployment_build_inputs_digest(inputs) == (
        deployment_build_inputs_digest(reversed_inputs)
    )


def test_build_inputs_reject_invalid_records_and_catalog_drift() -> None:
    catalog = build_default_deployment_artifact_catalog()
    invalid = DependencyLockRecord("python-production", "other", "../lock", "bad", 0, 0)
    duplicate = DependencyLockRecord(
        "python-production", "python", PYTHON_LOCK_PATH, HASH, 2, 1
    )
    inputs = DeploymentBuildInputs(
        "wrong.v1",
        "python3",
        "node22",
        "bad",
        (invalid, duplicate, DependencyLockRecord("unused", "node", "lock", HASH, 1, 1)),
    )

    with pytest.raises(DeploymentLockError) as raised:
        validate_deployment_build_inputs(inputs, catalog)

    detail = str(raised.value)
    for expected in (
        "schema_version",
        "Python runtime",
        "Node runtime",
        "artifact catalog digest",
        "unsupported lock ecosystem",
        "invalid dependency lock path",
        "invalid dependency lock digest",
        "empty dependency lock",
        "duplicate dependency lock",
        "incomplete dependency integrity",
        "artifact dependency family is unlocked: node-production",
        "unused dependency lock: unused",
        "artifact catalog digest mismatch",
    ):
        assert expected in detail


def test_python_lock_parser_accepts_exact_hashed_packages(tmp_path: Path) -> None:
    path = tmp_path / "python.lock"
    path.write_text(
        f"# {PYTHON_LOCK_COMMAND}\nalpha==1.0 \\\n    --hash=sha256:{HASH}\n",
        encoding="utf-8",
    )

    record = _python_lock_record(path)

    assert record.lock_id == "python-production"
    assert record.package_count == 1
    assert record.integrity_count == 1
    assert len(record.sha256) == 64


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("alpha==1.0 --hash=sha256:" + HASH, "compile command"),
        (f"# {PYTHON_LOCK_COMMAND}\n--index-url https://example.test\n", "forbidden source"),
        (f"# {PYTHON_LOCK_COMMAND}\n# empty\n", "no exact packages"),
        (
            f"# {PYTHON_LOCK_COMMAND}\nalpha==1.0 \\\n    --hash=sha256:{HASH}\n"
            f"alpha==1.0 \\\n    --hash=sha256:{HASH}\n",
            "duplicate packages",
        ),
        (f"# {PYTHON_LOCK_COMMAND}\nalpha==1.0\n", "missing a SHA-256 hash"),
    ],
)
def test_python_lock_parser_fails_closed(tmp_path: Path, content, message) -> None:
    path = tmp_path / "python.lock"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(DeploymentLockError, match=message):
        _python_lock_record(path)


def _write_node_lock(path: Path, package: dict[str, object]) -> None:
    path.write_text(
        json.dumps(
            {
                "lockfileVersion": 3,
                "packages": {"": {"version": "1.0.0"}, "node_modules/a": package},
            }
        ),
        encoding="utf-8",
    )


def test_node_lock_parser_accepts_exact_integrity(tmp_path: Path) -> None:
    path = tmp_path / "package-lock.json"
    _write_node_lock(
        path,
        {"version": "1.2.3", "resolved": "https://example.test/a", "integrity": "sha512-ok"},
    )

    record = _node_lock_record(path)

    assert record.lock_id == "node-production"
    assert record.path == NODE_LOCK_PATH
    assert record.package_count == record.integrity_count == 1


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ("not-json", "valid JSON"),
        (json.dumps({"lockfileVersion": 2, "packages": {}}), "lockfileVersion"),
        (json.dumps({"lockfileVersion": 3}), "packages are missing"),
        (json.dumps({"lockfileVersion": 3, "packages": {"": {}}}), "no resolved packages"),
    ],
)
def test_node_lock_parser_rejects_invalid_document(tmp_path: Path, payload, message) -> None:
    path = tmp_path / "package-lock.json"
    path.write_text(payload, encoding="utf-8")

    with pytest.raises(DeploymentLockError, match=message):
        _node_lock_record(path)


@pytest.mark.parametrize(
    ("package", "message"),
    [
        (
            {"version": "^1.0", "resolved": "https://example.test/a", "integrity": "sha512-ok"},
            "version is not exact",
        ),
        ({"version": "1.0", "resolved": "http://example.test/a", "integrity": "sha512-ok"}, "source is not HTTPS"),
        ({"version": "1.0", "resolved": "https://example.test/a"}, "integrity is missing"),
    ],
)
def test_node_lock_parser_rejects_invalid_package(tmp_path: Path, package, message) -> None:
    path = tmp_path / "package-lock.json"
    _write_node_lock(path, package)

    with pytest.raises(DeploymentLockError, match=message):
        _node_lock_record(path)


def test_build_inputs_fail_when_required_files_are_missing(tmp_path: Path) -> None:
    with pytest.raises(DeploymentLockError, match="required build input is missing"):
        build_deployment_build_inputs(tmp_path)
    with pytest.raises(DeploymentLockError, match="required build input is missing"):
        _python_lock_record(tmp_path / "missing.lock")
    with pytest.raises(DeploymentLockError, match="required build input is missing"):
        _file_sha256(tmp_path / "missing.lock")


def test_custom_catalog_with_no_artifacts_rejects_unused_locks() -> None:
    inputs = build_deployment_build_inputs(ROOT)
    empty_catalog = DeploymentArtifactCatalog(
        schema_version="deployment_artifact_catalog.v1",
        artifacts=(),
        process_bindings=(),
    )

    with pytest.raises(DeploymentLockError, match="unused dependency lock"):
        validate_deployment_build_inputs(inputs, empty_catalog)
