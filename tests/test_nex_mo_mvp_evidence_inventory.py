from __future__ import annotations

from pathlib import Path

from nex_mo.mvp_acceptance import (
    MoMvpEvidenceSpec,
    _inspect_evidence_spec,
    _relative_path,
    _single_file_text,
    build_mo_mvp_evidence_inventory,
    mo_mvp_evidence_specs,
)


def test_repository_inventory_is_complete_and_unique() -> None:
    inventory = build_mo_mvp_evidence_inventory()

    assert inventory["status"] == "PASS"
    assert inventory["scope"] == {
        "first_requirement": "S111",
        "last_requirement": "S119",
        "included_requirement_count": 9,
    }
    assert all(inventory["checks"].values())
    assert inventory["issues"] == []
    assert all(entry["status"] == "READY" for entry in inventory["entries"])


def test_evidence_specs_map_s111_through_s119() -> None:
    specs = mo_mvp_evidence_specs()

    assert [spec.requirement for spec in specs] == [
        f"S{number}" for number in range(111, 120)
    ]
    assert specs[0].closure_slice == "1111"
    assert specs[-1].closure_slice == "1191"
    assert specs[-1].capability_group == "operations_integration_acceptance"


def test_inventory_fails_closed_when_repository_is_empty(tmp_path: Path) -> None:
    inventory = build_mo_mvp_evidence_inventory(tmp_path)

    assert inventory["status"] == "FAIL"
    assert inventory["failure_code"] == (
        "mo.mvp_acceptance.evidence_inventory_invalid"
    )
    assert len(inventory["issues"]) == 18
    assert inventory["checks"]["closure_runners_present"] is False
    assert inventory["checks"]["closure_docs_present"] is False


def test_inspector_rejects_duplicate_and_mismatched_evidence(tmp_path: Path) -> None:
    spec = MoMvpEvidenceSpec("S111", "current_state", "1111")
    runner_dir = tmp_path / "scripts/smoke"
    doc_dir = tmp_path / "docs/slices"
    runner_dir.mkdir(parents=True)
    doc_dir.mkdir(parents=True)
    for suffix in ("one", "two"):
        (runner_dir / f"run_s111_{suffix}_closure.py").write_text(
            "SCHEMA_VERSION = 's111_test_closure.v1'", encoding="utf-8"
        )
    (doc_dir / "1111_s111_closure.md").write_text(
        "# Slice 1111", encoding="utf-8"
    )

    duplicate = _inspect_evidence_spec(tmp_path, spec)

    assert duplicate["status"] == "INVALID"
    assert duplicate["closure_runner_count"] == 2
    assert duplicate["closure_runner"] is None
    assert duplicate["issues"][0]["category"] == "closure_runner_count_invalid"

    for path in runner_dir.glob("*.py"):
        path.unlink()
    (runner_dir / "run_s111_one_closure.py").write_text(
        "missing identity", encoding="utf-8"
    )
    mismatched = _inspect_evidence_spec(tmp_path, spec)
    assert mismatched["issues"] == [
        {"category": "closure_identity_token_missing", "requirement": "S111"}
    ]


def test_file_helpers_fail_closed(tmp_path: Path, monkeypatch) -> None:
    assert _single_file_text([]) == ""
    assert _relative_path(tmp_path, []) is None
    path = tmp_path / "evidence"
    path.write_text("ready", encoding="utf-8")
    assert _single_file_text([path]) == "ready"
    assert _relative_path(tmp_path, [path]) == "evidence"

    monkeypatch.setattr(Path, "read_text", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError()))
    assert _single_file_text([path]) == ""
