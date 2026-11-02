from __future__ import annotations

from pathlib import Path

import pytest
from nex_runtime import (
    ModelArtifactRevisionError,
    admit_model_artifact_revision_evidence,
    inspect_huggingface_local_revision,
    is_immutable_model_revision,
    model_artifact_revision_evidence_digest,
    normalize_immutable_model_revision,
)


def _model_tree(root: Path, revisions: tuple[str, ...] | None = None) -> Path:
    model = root / "model"
    metadata = model / ".cache" / "huggingface" / "download"
    metadata.mkdir(parents=True)
    commits = revisions or ("a" * 40, "a" * 40)
    for name, commit in zip(("config.json", "model.safetensors"), commits):
        target = model / name
        target.write_bytes(name.encode("ascii"))
        (metadata / f"{name}.metadata").write_text(
            f"{commit}\n{'b' * 64}\n0.0\n",
            encoding="utf-8",
        )
    return model


def test_huggingface_local_revision_is_immutable_and_redacted(tmp_path: Path) -> None:
    evidence = inspect_huggingface_local_revision(_model_tree(tmp_path))

    assert evidence["artifact_revision"] == "hf:" + "a" * 40
    assert evidence["metadata_file_count"] == 2
    assert evidence["metadata_target_count"] == 2
    assert evidence["weight_artifact_count"] == 1
    assert evidence["model_path_persisted"] is False
    assert admit_model_artifact_revision_evidence(evidence) == (
        "hf:" + "a" * 40
    )
    assert model_artifact_revision_evidence_digest(evidence).startswith("sha256:")


@pytest.mark.parametrize(
    ("value", "valid"),
    [
        ("hf:" + "a" * 40, True),
        ("SHA256:" + "B" * 64, True),
        ("Qwen3-Reranker-4B", False),
        ("hf:abc123", False),
        (None, False),
    ],
)
def test_immutable_revision_formats(value: object, valid: bool) -> None:
    assert is_immutable_model_revision(value) is valid
    if valid:
        assert normalize_immutable_model_revision(value).islower()
    else:
        with pytest.raises(ModelArtifactRevisionError):
            normalize_immutable_model_revision(value)


def test_local_revision_inspection_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(ModelArtifactRevisionError, match="directory"):
        inspect_huggingface_local_revision(tmp_path / "missing")
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ModelArtifactRevisionError, match="metadata"):
        inspect_huggingface_local_revision(empty)
    with pytest.raises(ModelArtifactRevisionError, match="multiple"):
        inspect_huggingface_local_revision(
            _model_tree(tmp_path / "drift", ("a" * 40, "b" * 40))
        )

    malformed = _model_tree(tmp_path / "malformed")
    metadata = malformed / ".cache" / "huggingface" / "download"
    (metadata / "config.json.metadata").write_text("bad\n", encoding="utf-8")
    with pytest.raises(ModelArtifactRevisionError, match="malformed"):
        inspect_huggingface_local_revision(malformed)

    missing_target = _model_tree(tmp_path / "target")
    (missing_target / "config.json").unlink()
    with pytest.raises(ModelArtifactRevisionError, match="target"):
        inspect_huggingface_local_revision(missing_target)

    no_weight = _model_tree(tmp_path / "weight")
    (no_weight / "model.safetensors").rename(no_weight / "model.json")
    weight_metadata = (
        no_weight / ".cache" / "huggingface" / "download" /
        "model.safetensors.metadata"
    )
    weight_metadata.rename(weight_metadata.with_name("model.json.metadata"))
    with pytest.raises(ModelArtifactRevisionError, match="weight"):
        inspect_huggingface_local_revision(no_weight)

    original_is_dir = Path.is_dir

    def denied(path: Path) -> bool:
        if path.name == "denied":
            raise PermissionError("denied")
        return original_is_dir(path)

    monkeypatch.setattr(Path, "is_dir", denied)
    with pytest.raises(ModelArtifactRevisionError, match="not readable"):
        inspect_huggingface_local_revision(tmp_path / "denied")


def test_evidence_admission_rejects_tamper(tmp_path: Path) -> None:
    evidence = inspect_huggingface_local_revision(_model_tree(tmp_path))
    mutations = (
        {**evidence, "schema_version": "unknown"},
        {**evidence, "status": "FAIL"},
        {**evidence, "revision_source": "OPERATOR_INPUT"},
        {**evidence, "metadata_target_count": 1},
        {**evidence, "metadata_manifest_digest": "mutable"},
        {**evidence, "model_path_persisted": True},
        {**evidence, "artifact_content_persisted": True},
        {**evidence, "metadata_file_count": True},
        {**evidence, "weight_artifact_count": 0},
    )
    for mutation in mutations:
        with pytest.raises(ModelArtifactRevisionError):
            admit_model_artifact_revision_evidence(mutation)
