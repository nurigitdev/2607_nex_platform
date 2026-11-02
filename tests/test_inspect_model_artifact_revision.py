from __future__ import annotations

import json
from pathlib import Path

import inspect_model_artifact_revision as cli


def test_cli_writes_redacted_revision_evidence(tmp_path: Path, capsys) -> None:
    model = tmp_path / "model"
    metadata = model / ".cache" / "huggingface" / "download"
    metadata.mkdir(parents=True)
    (model / "model.safetensors").write_bytes(b"weights")
    (metadata / "model.safetensors.metadata").write_text(
        f"{'a' * 40}\n{'b' * 64}\n0\n",
        encoding="utf-8",
    )
    output = tmp_path / "evidence.json"

    assert cli.main(
        [
            "--model-directory",
            str(model),
            "--output",
            str(output),
            "--summary",
        ]
    ) == 0
    evidence = json.loads(output.read_text(encoding="utf-8"))
    assert evidence["artifact_revision"] == "hf:" + "a" * 40
    assert str(model) not in output.read_text(encoding="utf-8")
    assert "model_artifact_revision=pass" in capsys.readouterr().out


def test_cli_returns_failure_without_leaking_path(tmp_path: Path, capsys) -> None:
    missing = tmp_path / "private-model"
    assert cli.main(["--model-directory", str(missing)]) == 1
    output = capsys.readouterr().out
    assert "model_artifact_revision_inspection_failed" in output
    assert str(missing) not in output
