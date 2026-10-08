from __future__ import annotations

from pathlib import Path

import run_s146_private_object_storage_boundary as boundary


def test_repository_boundary_freezes_s146_scope() -> None:
    result = boundary.run_private_object_storage_boundary()
    assert result["status"] == "PASS", result
    assert result["boundary_readiness"] == "BOUNDARY_FROZEN"
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["summary"] == {
        "required_path_count": len(boundary.REQUIRED_PATHS),
        "check_count": 11,
        "payload_family_count": 7,
        "bucket_count": 2,
        "slice_count": 10,
        "missing_path_count": 0,
    }
    assert result["decision"]["deployment_product"] == "RUSTFS"
    assert result["decision"]["vector_migration_in_scope"] is False
    assert result["decision"]["next_slice"] == "1454"


def test_payload_inventory_is_exact_and_value_free() -> None:
    result = boundary.run_private_object_storage_boundary()
    assert [item["family"] for item in result["payload_families"]] == [
        item.family for item in boundary.PAYLOAD_FAMILIES
    ]
    assert {item["owner"] for item in result["payload_families"]} == {
        "nex-cx",
        "nex-ae-api",
    }
    assert all("current_anchor" not in item for item in result["payload_families"])


def test_empty_repository_fails_closed(tmp_path: Path) -> None:
    result = boundary.run_private_object_storage_boundary(tmp_path)
    assert result["status"] == "FAIL"
    assert result["boundary_readiness"] == "AUDIT_FAILED"
    assert result["summary"]["missing_path_count"] == len(boundary.REQUIRED_PATHS)
    assert result["decision"]["next_slice"] == "blocked"
    assert result["issues"]


def test_helpers_summary_and_main_branches(tmp_path: Path, monkeypatch, capsys) -> None:
    assert boundary._read_text(tmp_path / "missing") == ""
    source = tmp_path / "source"
    source.write_text("value", encoding="utf-8")
    assert boundary._read_text(source) == "value"

    passing = boundary.run_private_object_storage_boundary()
    assert boundary.summary_line(passing) == (
        "private_object_storage_boundary=pass checks=11/11 payloads=7 "
        "buckets=2 product=rustfs next=1454"
    )
    assert boundary.summary_line({"status": "FAIL", "issues": ["one"]}) == (
        "private_object_storage_boundary=fail issues=1"
    )
    monkeypatch.setattr(boundary, "run_private_object_storage_boundary", lambda: passing)
    assert boundary.main(["--summary"]) == 0
    assert "boundary=pass" in capsys.readouterr().out
    assert boundary.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        boundary,
        "run_private_object_storage_boundary",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert boundary.main([]) == 1

