from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from nex_eos import create_eos_app
from nex_runtime import DEFAULT_OPERATION_REGISTRY
from nsl.cli_config import load_tool_catalog
from nsl.compiler import NslCompiler

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = (
    ROOT / "contracts/schemas/common/nsl_voucher_read_artifact_admission.v1.schema.json"
)
EXAMPLE = (
    ROOT / "contracts/examples/common/nsl_voucher_read_artifact_admission.pass.json"
)
LOCK = ROOT / "deployment/locks/nsl-v0.2.1-wheel.json"
SOURCE_ENV = "NEX_P8_S101_NSL_SOURCE"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def test_voucher_read_admission_contract_and_eos_routes_align() -> None:
    admission = _load(EXAMPLE)
    assert list(Draft202012Validator(_load(SCHEMA)).iter_errors(admission)) == []
    skill_ids = {item["skill_id"] for item in admission["skills"]}
    assert skill_ids == {
        "FINANCE.VOUCHER_DRAFT.GET",
        "FINANCE.VOUCHER_DRAFT.LIST",
    }
    assert all(
        DEFAULT_OPERATION_REGISTRY.resolve(item).canonical_operation == item
        for item in skill_ids
    )

    app = create_eos_app(
        environ={
            "NEX_EOS_SERVICE_ID": "nex-eos",
            "NEX_PROFILE": "test",
            "NEX_VERSION": "p8-s101",
            "NEX_BUILD_SHA": "test",
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
        }
    )
    route_ids = {
        operation["operationId"]
        for path, methods in app.openapi()["paths"].items()
        if path.startswith("/internal/v1/finance/voucher-drafts")
        for operation in methods.values()
    }
    assert skill_ids <= route_ids


@pytest.mark.skipif(not os.getenv(SOURCE_ENV), reason=f"{SOURCE_ENV} is required")
def test_actual_nsl_voucher_read_source_manifest_and_semantics_are_exact() -> None:
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
    lock = _load(LOCK)
    assert admission["runtime_wheel"] == {
        "package_version": lock["package_version"],
        "source_revision": lock["source_revision"],
        "wheel_sha256": lock["wheel_sha256"],
    }

    artifact_root = manifest_path.parent
    catalog = load_tool_catalog(artifact_root / manifest["tool_catalog"]["path"])
    admitted = {item["skill_id"]: item for item in admission["skills"]}
    for item in manifest["skills"]:
        source_path = artifact_root / item["path"]
        compiled = (
            NslCompiler(catalog).compile(source_path.read_text(encoding="utf-8")).skill
        )
        expected = admitted[compiled.skill_id]
        assert (
            item["source_sha256"] == expected["source_sha256"] == _sha256(source_path)
        )
        assert (
            item["semantic_hash"] == expected["semantic_hash"] == compiled.semantic_hash
        )
