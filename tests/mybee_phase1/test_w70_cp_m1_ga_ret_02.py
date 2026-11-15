from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from build_mybee_w70_golden_a_quarantine import (
    ACTIVATION_PATH,
    ACTIVE_CAPABILITIES,
    ADMISSION_PATH,
    QUARANTINE_PATH,
    REGISTRY_PATH,
    ROLLBACK_PATH,
    build_quarantine_artifacts,
    render_json,
)
from nex_ae_api.product_runtime_profile import _verify_activation_lock
from run_mybee_w70_golden_a_quarantine_gate import run_gate
from run_mybee_w70_golden_a_quarantine_postgres import (
    DATABASE_ENV,
    SMOKE_ENV,
    run_postgres_smoke,
)

ROOT = Path(__file__).resolve().parents[2]


def _json(relative: Path) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def test_successor_artifacts_are_exact_and_active_gate_passes() -> None:
    artifacts = build_quarantine_artifacts(ROOT)

    assert set(artifacts) == {
        REGISTRY_PATH,
        ADMISSION_PATH,
        ROLLBACK_PATH,
        ACTIVATION_PATH,
        QUARANTINE_PATH,
    }
    for relative, value in artifacts.items():
        assert (ROOT / relative).read_bytes() == render_json(value)
    result = run_gate(ROOT)
    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert tuple(result["active_capabilities"]) == ACTIVE_CAPABILITIES
    assert result["historical_asset_count"] >= 10


def test_successor_registry_and_rollback_are_scenario_free() -> None:
    registry = _json(REGISTRY_PATH)
    activation = _json(ACTIVATION_PATH)
    rollback = _json(ROLLBACK_PATH)
    quarantine = _json(QUARANTINE_PATH)

    assert (
        tuple(item["capability"]["capability_id"] for item in registry["registrations"])
        == ACTIVE_CAPABILITIES
    )
    assert "FINANCE.CREATE_VOUCHER_DRAFT" not in json.dumps(registry)
    assert activation["activation_state"] == "ACTIVE_GENERALIZED"
    assert activation["rollback_target"]["golden_a_dependency"] is False
    assert rollback["golden_a_dependency"] is False
    assert quarantine["historical_policy"] == {
        "new_selection": "DENY",
        "active_runtime_import": "DENY",
        "canonical_image_packaging": "DENY",
        "execution": "OFFLINE_REPLAY_ONLY",
        "database_cleanup": "DENY",
    }


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("rollback_profile", "profile has drifted"),
        ("golden_dependency", "cannot depend"),
        ("receipt_payload", "not admitted"),
    ),
)
def test_generalized_rollback_fails_closed(
    tmp_path: Path, mutation: str, message: str
) -> None:
    admission = _json(ADMISSION_PATH)
    activation = _json(ACTIVATION_PATH)
    root = ROOT
    if mutation == "rollback_profile":
        activation["rollback_target"]["profile"] = "LEGACY"
    elif mutation == "golden_dependency":
        activation["rollback_target"]["golden_a_dependency"] = True
    else:
        receipt = deepcopy(_json(ROLLBACK_PATH))
        receipt["runtime_admission_hash"] = "sha256:" + "0" * 64
        path = tmp_path / "receipt.json"
        path.write_text(json.dumps(receipt), encoding="utf-8")
        activation["rollback_target"].update(
            receipt_ref="receipt.json",
            receipt_sha256=("sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()),
        )
        root = tmp_path

    with pytest.raises(ValueError, match=message):
        _verify_activation_lock(activation, admission=admission, repository_root=root)


def test_postgres_quarantine_smoke_is_opt_in_and_target_protected() -> None:
    skipped = run_postgres_smoke({})
    rejected = run_postgres_smoke(
        {
            SMOKE_ENV: "1",
            DATABASE_ENV: "postgresql://wrong@127.0.0.1/other",
        }
    )

    assert skipped["status"] == "SKIPPED"
    assert rejected["status"] == "FAIL"
    assert rejected["failure_code"] == "target_not_allowed"
