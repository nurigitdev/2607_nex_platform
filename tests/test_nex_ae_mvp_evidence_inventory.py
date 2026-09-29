from __future__ import annotations

from pathlib import Path

from nex_ae_api.mvp_acceptance import (
    _inspect_evidence_spec,
    _relative_path,
    _single_file_text,
    ae_mvp_evidence_specs,
    build_ae_mvp_evidence_inventory,
)


def test_repository_inventory_is_complete_and_unique() -> None:
    inventory = build_ae_mvp_evidence_inventory()

    assert inventory["status"] == "PASS"
    assert inventory["failure_code"] is None
    assert inventory["scope"] == {
        "first_requirement": "S101",
        "last_requirement": "S109",
        "included_requirement_count": 9,
    }
    assert all(inventory["checks"].values())
    assert inventory["issues"] == []
    assert [entry["requirement"] for entry in inventory["entries"]] == [
        f"S{number}" for number in range(101, 110)
    ]
    assert all(entry["status"] == "READY" for entry in inventory["entries"])
    assert inventory["freshness_contract"]["server_clock_is_authoritative"] is True
    assert (
        inventory["freshness_contract"]["repository_mtime_is_acceptance_evidence"]
        is False
    )


def test_evidence_specs_map_to_exact_closure_slices() -> None:
    specs = ae_mvp_evidence_specs()

    assert len(specs) == 9
    assert specs[0].requirement == "S101"
    assert specs[0].closure_slice == "1011"
    assert specs[-1].requirement == "S109"
    assert specs[-1].closure_slice == "1091"
    assert len({spec.capability_group for spec in specs}) == 9


def test_inventory_fails_closed_when_evidence_is_missing(tmp_path: Path) -> None:
    inventory = build_ae_mvp_evidence_inventory(tmp_path)

    assert inventory["status"] == "FAIL"
    assert inventory["failure_code"] == (
        "ae.mvp_acceptance.evidence_inventory_invalid"
    )
    assert inventory["checks"]["closure_runners_present"] is False
    assert inventory["checks"]["closure_docs_present"] is False
    assert len(inventory["issues"]) == 18
    assert inventory["entries"][0]["closure_runner"] is None


def test_inventory_detects_duplicate_and_invalid_identity(tmp_path: Path) -> None:
    spec = ae_mvp_evidence_specs()[0]
    smoke = tmp_path / "scripts/smoke"
    docs = tmp_path / "docs/slices"
    smoke.mkdir(parents=True)
    docs.mkdir(parents=True)
    (smoke / "run_s101_one_closure.py").write_text(
        'SCHEMA_VERSION = "s101_closure.v1"\n', encoding="utf-8"
    )
    (smoke / "run_s101_two_closure.py").write_text(
        'SCHEMA_VERSION = "s101_closure.v1"\n', encoding="utf-8"
    )
    (docs / "1011_s101_closure.md").write_text(
        "# Slice 1011\n", encoding="utf-8"
    )

    duplicate = _inspect_evidence_spec(tmp_path, spec)
    assert duplicate["status"] == "INVALID"
    assert duplicate["issues"][0]["category"] == "closure_runner_count_invalid"

    (smoke / "run_s101_two_closure.py").unlink()
    (smoke / "run_s101_one_closure.py").write_text(
        "no identity\n", encoding="utf-8"
    )
    invalid = _inspect_evidence_spec(tmp_path, spec)
    assert invalid["issues"] == [
        {"category": "closure_identity_token_missing", "requirement": "S101"}
    ]


def test_inventory_file_helpers_fail_closed(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    bad = tmp_path / "bad"
    bad.write_bytes(b"\xff")

    assert _single_file_text([]) == ""
    assert _single_file_text([missing]) == ""
    assert _single_file_text([bad]) == ""
    assert _relative_path(tmp_path, []) is None
    assert _relative_path(tmp_path, [bad]) == "bad"
