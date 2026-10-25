from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from nex_eos import (
    NVT_PROJECT_CREATE_OPERATION,
    NVT_PROJECT_UPDATE_OPERATION,
    PROJECT_CREATE_OPERATION,
    PROJECT_DEACTIVATE_OPERATION,
    PROJECT_MEMBERSHIP_ADD_OPERATION,
    PROJECT_MEMBERSHIP_REMOVE_OPERATION,
    create_eos_app,
)
from nex_runtime import DEFAULT_OPERATION_REGISTRY
from nsl.cli_config import load_tool_catalog
from nsl.compiler import NslCompiler
from nsl.tools import OperationKind, ToolCapability

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "contracts/schemas/common/nsl_project_write_artifact_admission.v1.schema.json"
EXAMPLE = ROOT / "contracts/examples/common/nsl_project_write_artifact_admission.pass.json"
LOCK = ROOT / "deployment/locks/nsl-v0.2.1-wheel.json"
SOURCE_ENV = "NEX_P8_S99_NSL_SOURCE"

EXPECTED = {
    NVT_PROJECT_CREATE_OPERATION: (
        "CREATE",
        "project:nvt_project:create",
        "PROJECT.NVT_PROJECT.GET",
    ),
    NVT_PROJECT_UPDATE_OPERATION: (
        "UPDATE",
        "project:nvt_project:admin",
        "PROJECT.NVT_PROJECT.GET",
    ),
    PROJECT_CREATE_OPERATION: ("CREATE", "project:project:create", "PROJECT.PROJECT.GET"),
    PROJECT_DEACTIVATE_OPERATION: (
        "UPDATE",
        "project:project:admin",
        "PROJECT.PROJECT.GET",
    ),
    PROJECT_MEMBERSHIP_ADD_OPERATION: (
        "CREATE",
        "project:membership:manage",
        "PROJECT.MEMBERSHIP.LIST",
    ),
    PROJECT_MEMBERSHIP_REMOVE_OPERATION: (
        "UPDATE",
        "project:membership:manage",
        "PROJECT.MEMBERSHIP.LIST",
    ),
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def test_project_write_admission_contract_routes_and_registry_align() -> None:
    admission = _load(EXAMPLE)
    assert list(Draft202012Validator(_load(SCHEMA)).iter_errors(admission)) == []
    admitted = {
        item["skill_id"]: (
            item["operation_kind"],
            item["required_scope"],
            item["verification_tool_id"],
        )
        for item in admission["skills"]
    }
    assert admitted == EXPECTED
    assert all(
        DEFAULT_OPERATION_REGISTRY.resolve(item).canonical_operation == item
        for item in admitted
    )

    app = create_eos_app(
        environ={
            "NEX_EOS_SERVICE_ID": "nex-eos",
            "NEX_PROFILE": "test",
            "NEX_VERSION": "p8-s99",
            "NEX_BUILD_SHA": "test",
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
        }
    )
    route_ids = {
        operation["operationId"]
        for path, methods in app.openapi()["paths"].items()
        if path.startswith(("/internal/v1/projects", "/internal/v1/nvt-projects"))
        for operation in methods.values()
    }
    assert set(admitted) <= route_ids


def test_project_write_admission_uses_exact_v021_runtime_wheel() -> None:
    admission = _load(EXAMPLE)
    lock = _load(LOCK)

    assert admission["runtime_wheel"] == {
        "package_version": lock["package_version"],
        "source_revision": lock["source_revision"],
        "wheel_sha256": lock["wheel_sha256"],
    }
    assert lock["package_version"] == "0.2.1"


@pytest.mark.skipif(not os.getenv(SOURCE_ENV), reason=f"{SOURCE_ENV} is required")
def test_actual_nsl_write_source_revision_manifest_and_semantics_are_exact() -> None:
    admission = _load(EXAMPLE)
    source = Path(os.environ[SOURCE_ENV]).resolve(strict=True)
    manifest_path = source / admission["artifact_manifest_path"]
    manifest = _load(manifest_path)

    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=source,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert revision == admission["artifact_source_revision"]
    assert _sha256(manifest_path) == admission["artifact_manifest_sha256"]
    assert manifest["runtime_package_version"] == "0.2.1"

    artifact_root = manifest_path.parent
    catalog_path = artifact_root / manifest["tool_catalog"]["path"]
    assert _sha256(catalog_path) == manifest["tool_catalog"]["sha256"]
    catalog = load_tool_catalog(catalog_path)
    admitted = {item["skill_id"]: item for item in admission["skills"]}

    for item in manifest["skills"]:
        source_path = artifact_root / item["path"]
        compiled = NslCompiler(catalog).compile(
            source_path.read_text(encoding="utf-8")
        ).skill
        expected = admitted[compiled.skill_id]
        contract = catalog.get(compiled.skill_id, compiled.skill_version)
        verification = contract.write_semantics.verification

        assert contract.capability is ToolCapability.WRITE
        assert contract.operation_kind is OperationKind(expected["operation_kind"])
        assert contract.required_scope == expected["required_scope"]
        assert verification is not None
        assert verification.tool_id == expected["verification_tool_id"]
        assert item["source_sha256"] == expected["source_sha256"] == _sha256(source_path)
        assert item["semantic_hash"] == expected["semantic_hash"] == compiled.semantic_hash
