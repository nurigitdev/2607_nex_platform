from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from capture_mybee_w70_installed_runtime_baseline import (
    DATA_ORIGINS,
    OUTPUT,
    SOURCE_COMPONENTS,
    _semantic_hash,
    build_baseline,
    validate_baseline,
)

ROOT = Path(__file__).resolve().parents[2]


def test_captured_baseline_is_exact_and_complete() -> None:
    recorded = json.loads(OUTPUT.read_text(encoding="utf-8"))

    assert recorded == build_baseline(ROOT)
    assert validate_baseline(recorded) is recorded
    assert len(recorded["installed_composition"]) == len(SOURCE_COMPONENTS)
    assert len(recorded["data_origin_matrix"]) == len(DATA_ORIGINS)
    assert recorded["database_migration"] is False
    assert recorded["remote_provider_required"] is False
    assert recorded["residue_baseline"]


@pytest.mark.parametrize(
    "mutation", ("type", "fields", "hash", "schema", "origins", "components")
)
def test_baseline_drift_is_rejected(mutation: str) -> None:
    value: object = deepcopy(build_baseline(ROOT))
    assert isinstance(value, dict)
    if mutation == "type":
        value = []
    elif mutation == "fields":
        value["unexpected"] = True
    elif mutation == "hash":
        value["content_hash"] = "sha256:" + "0" * 64
    elif mutation == "schema":
        value["schema_version"] = "unsupported"
        _rehash(value)
    elif mutation == "origins":
        value["data_origin_matrix"] = []
        _rehash(value)
    elif mutation == "components":
        value["installed_composition"] = []
        _rehash(value)

    with pytest.raises(ValueError):
        validate_baseline(value)


def _rehash(value: dict) -> None:
    value["content_hash"] = _semantic_hash(
        {key: item for key, item in value.items() if key != "content_hash"}
    )
