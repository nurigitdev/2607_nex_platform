from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

MODEL_ARTIFACT_REVISION_SCHEMA_VERSION = "model_artifact_revision.v1"

_HF_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_IMMUTABLE_REVISION = re.compile(
    r"^(?:hf:[0-9a-f]{40}|sha256:[0-9a-f]{64})$"
)


class ModelArtifactRevisionError(ValueError):
    pass


def normalize_immutable_model_revision(value: object) -> str:
    if not isinstance(value, str):
        raise ModelArtifactRevisionError("model revision must be a string")
    normalized = value.strip().lower()
    if _IMMUTABLE_REVISION.fullmatch(normalized) is None:
        raise ModelArtifactRevisionError(
            "model revision must be hf:<40-hex> or sha256:<64-hex>"
        )
    return normalized


def is_immutable_model_revision(value: object) -> bool:
    try:
        normalize_immutable_model_revision(value)
    except ModelArtifactRevisionError:
        return False
    return True


def inspect_huggingface_local_revision(model_directory: Path) -> dict[str, Any]:
    try:
        root = model_directory.resolve()
        is_directory = root.is_dir()
    except OSError as exc:
        raise ModelArtifactRevisionError("model directory is not readable") from exc
    if not is_directory:
        raise ModelArtifactRevisionError("model directory is not readable")
    metadata_root = root / ".cache" / "huggingface" / "download"
    try:
        metadata_paths = sorted(metadata_root.glob("*.metadata"))
    except OSError as exc:
        raise ModelArtifactRevisionError("model metadata is not readable") from exc
    if not metadata_paths:
        raise ModelArtifactRevisionError("Hugging Face local metadata is missing")

    commits: set[str] = set()
    manifest = hashlib.sha256()
    target_count = 0
    weight_count = 0
    for path in metadata_paths:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise ModelArtifactRevisionError("model metadata is not readable") from exc
        if len(lines) < 2 or _HF_COMMIT.fullmatch(lines[0].strip().lower()) is None:
            raise ModelArtifactRevisionError("model metadata revision is malformed")
        commit = lines[0].strip().lower()
        commits.add(commit)
        target = root / path.name.removesuffix(".metadata")
        if not target.is_file():
            raise ModelArtifactRevisionError("model metadata target is missing")
        target_count += 1
        if target.name.endswith((".safetensors", ".bin")):
            weight_count += 1
        try:
            target_size = target.stat().st_size
        except OSError as exc:
            raise ModelArtifactRevisionError("model artifact is not readable") from exc
        manifest.update(path.name.encode("utf-8"))
        manifest.update(b"\0")
        manifest.update(commit.encode("ascii"))
        manifest.update(b"\0")
        manifest.update(lines[1].strip().encode("utf-8"))
        manifest.update(b"\0")
        manifest.update(str(target_size).encode("ascii"))
        manifest.update(b"\0")

    if len(commits) != 1:
        raise ModelArtifactRevisionError(
            "model metadata contains multiple source revisions"
        )
    if weight_count < 1:
        raise ModelArtifactRevisionError("model weight artifact is missing")

    revision = f"hf:{next(iter(commits))}"
    evidence = {
        "schema_version": MODEL_ARTIFACT_REVISION_SCHEMA_VERSION,
        "status": "PASS",
        "revision_source": "HUGGINGFACE_LOCAL_METADATA",
        "artifact_revision": revision,
        "metadata_file_count": len(metadata_paths),
        "metadata_target_count": target_count,
        "weight_artifact_count": weight_count,
        "metadata_manifest_digest": f"sha256:{manifest.hexdigest()}",
        "model_path_persisted": False,
        "artifact_content_persisted": False,
    }
    admit_model_artifact_revision_evidence(evidence)
    return evidence


def admit_model_artifact_revision_evidence(
    evidence: Mapping[str, Any],
) -> str:
    if evidence.get("schema_version") != MODEL_ARTIFACT_REVISION_SCHEMA_VERSION:
        raise ModelArtifactRevisionError("model revision evidence schema is invalid")
    if evidence.get("status") != "PASS":
        raise ModelArtifactRevisionError("model revision evidence did not pass")
    revision = normalize_immutable_model_revision(evidence.get("artifact_revision"))
    if evidence.get("revision_source") != "HUGGINGFACE_LOCAL_METADATA":
        raise ModelArtifactRevisionError("model revision evidence source is invalid")
    for field_name in (
        "metadata_file_count",
        "metadata_target_count",
        "weight_artifact_count",
    ):
        value = evidence.get(field_name)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ModelArtifactRevisionError(
                f"model revision evidence {field_name} is invalid"
            )
    if evidence["metadata_file_count"] != evidence["metadata_target_count"]:
        raise ModelArtifactRevisionError("model metadata target count is incomplete")
    normalize_immutable_model_revision(evidence.get("metadata_manifest_digest"))
    if evidence.get("model_path_persisted") is not False:
        raise ModelArtifactRevisionError("model path must not be persisted")
    if evidence.get("artifact_content_persisted") is not False:
        raise ModelArtifactRevisionError("artifact content must not be persisted")
    return revision


def model_artifact_revision_evidence_digest(
    evidence: Mapping[str, Any],
) -> str:
    admit_model_artifact_revision_evidence(evidence)
    encoded = json.dumps(
        dict(evidence),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
