from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/deployment"))

import run_mybee_w80_ca00g0a_progress_acceptance as acceptance


def test_progress_acceptance_source_admits_product_runner() -> None:
    result = acceptance.run_progress_acceptance({}, execute=False)

    assert result["status"] == "SOURCE_ADMITTED"
    assert result["source_admitted"] is True
    assert result["actual_postgres_required"] is True
    assert result["actual_remote_generation_required"] is True
    assert result["actual_playwright_required"] is True


def test_protected_checks_require_both_product_progress_journeys() -> None:
    item = {
        "status": "PASS",
        "checks": {
            "progress_poll_started_before_chat_response": True,
            "progress_dom_is_append_only": True,
            "progress_debug_time_prefix_visible": True,
            "progress_projection_owner_scoped": True,
            "progress_projection_terminal": True,
            "progress_projection_private_payload_absent": True,
            "progress_polling_stopped_after_terminal": True,
            "progress_projection_ordered_and_unique": True,
            "progress_screen_evidence_captured": True,
        },
    }
    result = {
        "status": "PASS",
        "zero_residue": True,
        "extended_acceptance": {
            "browser": {
                "journal": {"status": "PASS", "progress_acceptance": item},
                "allocation": {"status": "PASS", "progress_acceptance": item},
            }
        },
    }

    assert all(acceptance._protected_checks(result).values())

    item["checks"]["progress_polling_stopped_after_terminal"] = False
    assert acceptance._protected_checks(result)["polling_stopped_after_terminal"] is False


def test_progress_acceptance_summary_is_bounded() -> None:
    assert acceptance.summary_line(
        {
            "status": "PASS",
            "executed": True,
            "progress_checks": {"screen_evidence_captured": True},
        }
    ) == "mybee_w80_ca00g0a_progress=pass executed=true screens=true"
