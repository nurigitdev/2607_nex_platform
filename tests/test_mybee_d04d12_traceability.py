from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TRACE = ROOT / "docs/mybee_phase1/traceability/requirements.v1.1.json"
LINKS = ROOT / "docs/mybee_phase1/traceability/nex_srs_links.json"
MATRIX = (
    ROOT
    / "docs/transition/MyBee_Phase1/NeX_MyBee_Implementation_Slice_Plan_Execution_Matrix_v1.2.json"
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _srs_requirement_ids(path: Path) -> set[str]:
    return set(re.findall(r"SRS-[A-Z]+-[0-9]{3}", path.read_text(encoding="utf-8")))


def test_s0_03_all_srs_requirements_have_one_trace_record() -> None:
    trace = _load(TRACE)
    srs_path = ROOT / trace["source_srs"]["path"]
    srs_ids = _srs_requirement_ids(srs_path)
    trace_ids = [item["requirement_id"] for item in trace["requirements"]]

    assert _sha256(srs_path) == trace["source_srs"]["sha256"]
    assert trace["requirement_count"] == len(trace_ids) == len(set(trace_ids)) == 116
    assert set(trace_ids) == srs_ids


def test_s0_03_projection_preserves_matrix_packet_and_gate_links() -> None:
    trace = _load(TRACE)
    matrix = _load(MATRIX)
    assert _sha256(MATRIX) == trace["source_execution_matrix"]["sha256"]

    matrix_requirements = {
        item["requirement_id"]: item for item in matrix["requirements_v12"]
    }
    packet_ids = {item["packet_id"] for item in matrix["original_packets_v12"]}
    for item in trace["requirements"]:
        expected = matrix_requirements[item["requirement_id"]]
        assert item["primary_packet_id"] == expected["primary_packet_id"]
        assert item["primary_packet_id"] in packet_ids
        assert item["canonical_api"] == expected["canonical_api"]
        assert item["canonical_nsl_tool"] == expected["canonical_nsl_tool"]
        assert item["pytest_path"] == expected["pytest_path"]
        assert item["gates"] == expected["gates"]
        assert item["gates"]
        assert item["status"] == "PLANNED_NOT_IMPLEMENTED"


def test_s0_03_requirement_family_counts_and_pdf_gate_are_explicit() -> None:
    trace = _load(TRACE)
    links = _load(LINKS)
    family_counts = Counter(
        item["requirement_id"].split("-")[1] for item in trace["requirements"]
    )

    assert dict(sorted(family_counts.items())) == links["requirement_families"]
    assert links["source_release_gate"] == {
        "gate_id": "G-SRC-PDF",
        "status": "OPEN",
        "required_before": "M2_RELEASE",
        "acceptance": (
            "D04 and D12 page/section semantic reconciliation with named owner sign-off"
        ),
    }
    assert all(
        source["status"] == "REGISTERED_PAGE_LEVEL_RECONCILIATION_OPEN"
        for source in links["source_documents"].values()
    )


def test_s0_03_change_control_does_not_claim_implementation() -> None:
    links = _load(LINKS)
    control = links["change_control"]

    assert control["frozen_semantics"] == "CONTROLLED_AMENDMENT_REQUIRED"
    assert control["new_nsl_tool_activation"] is False
    assert control["silent_requirement_deletion_allowed"] is False
    assert control["implementation_pass_claimed"] is False
