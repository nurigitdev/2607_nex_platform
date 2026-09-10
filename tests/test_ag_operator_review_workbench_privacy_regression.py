from __future__ import annotations

import json
from typing import Any

import pytest

import run_ag_operator_review_workbench_privacy_regression as audit


def test_ag_operator_review_workbench_privacy_regression_passes() -> None:
    evidence = audit.run_ag_operator_review_workbench_privacy_regression()

    assert evidence["status"] == "PASS"
    assert evidence["audit_schema_version"] == audit.SCHEMA_VERSION
    assert evidence["slice"] == "0639"
    assert evidence["surface_count"] == 4
    assert all(evidence["checks"].values())
    assert all(not surface["leak_labels"] for surface in evidence["surfaces"])
    assert audit.summary_line(evidence) == (
        "ag_operator_review_workbench_privacy_regression=pass "
        "surfaces=4 forbidden_labels=10"
    )
    serialized = json.dumps(evidence, ensure_ascii=False)
    for forbidden in audit.FORBIDDEN_VALUES.values():
        assert forbidden not in serialized


def test_ag_operator_review_workbench_privacy_regression_detects_leak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        audit,
        "_collect_surface_payloads",
        lambda note_store, export_store: [
            audit.SurfacePayload(
                name="workbench",
                status_code=200,
                payload={
                    "items": [
                        {
                            "notes": [
                                {
                                    "operator_note_preview": "safe",
                                    "operator_note": audit.RAW_OPERATOR_NOTE,
                                }
                            ]
                        }
                    ],
                    "redaction": {
                        "raw_operator_note_included": False,
                        "raw_evidence_body_included": False,
                        "raw_prompt_included": False,
                        "raw_source_text_included": False,
                        "storage_paths_included": False,
                        "idempotency_keys_included": False,
                    },
                },
            ),
            audit.SurfacePayload(
                name="rollups",
                status_code=200,
                payload={
                    "attention": {"items": []},
                    "redaction": {
                        "raw_operator_note_included": False,
                        "raw_evidence_body_included": False,
                        "raw_prompt_included": False,
                        "raw_source_text_included": False,
                        "storage_paths_included": False,
                        "idempotency_keys_included": False,
                    },
                },
            ),
            audit.SurfacePayload(
                name="dashboard",
                status_code=200,
                payload={
                    "operator_review_workbench": {
                        "redaction": {
                            "raw_operator_note_included": False,
                            "raw_evidence_body_included": False,
                            "raw_prompt_included": False,
                            "raw_source_text_included": False,
                            "storage_paths_included": False,
                            "idempotency_keys_included": False,
                        }
                    }
                },
            ),
            audit.SurfacePayload(
                name="issue_candidates",
                status_code=200,
                payload={
                    "issue_candidates": [
                        {
                            "rule_id": "operator_review_attention_required.v1",
                            "signal": {"source_type": "operator_review_workbench"},
                        }
                    ]
                },
            ),
        ],
    )

    evidence = audit.run_ag_operator_review_workbench_privacy_regression()

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == (
        "ag_operator_review_workbench_privacy_regression_failed"
    )
    assert evidence["checks"]["no_forbidden_values"] is False
    assert evidence["checks"]["workbench_raw_fields_absent"] is False
    assert evidence["surfaces"][0]["leak_labels"] == [
        "raw_operator_note_full_text",
        "raw_operator_note_sentinel",
    ]
    assert "no_forbidden_values" in audit.summary_line(evidence)


def test_ag_operator_review_workbench_privacy_regression_detects_bad_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        audit,
        "_collect_surface_payloads",
        lambda note_store, export_store: [
            audit.SurfacePayload("workbench", 500, {"items": [], "redaction": {}}),
            audit.SurfacePayload("rollups", 200, {"redaction": {}}),
            audit.SurfacePayload("dashboard", 200, {"operator_review_workbench": {}}),
            audit.SurfacePayload("issue_candidates", 200, {"issue_candidates": []}),
        ],
    )

    evidence = audit.run_ag_operator_review_workbench_privacy_regression()

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["all_routes_200"] is False
    assert evidence["checks"]["workbench_preview_is_bounded"] is False
    assert evidence["checks"]["rollup_redaction_flags_safe"] is False
    assert evidence["checks"]["dashboard_redaction_flags_safe"] is False
    assert evidence["checks"]["issue_candidates_reference_safe_sources"] is False


def test_ag_operator_review_workbench_privacy_helpers() -> None:
    assert audit._leak_labels(
        f"prefix {audit.RAW_PROMPT} suffix",
        audit.FORBIDDEN_VALUES,
    ) == ["raw_prompt"]
    assert audit._workbench_preview_is_bounded(
        {"items": [{"notes": [{"operator_note_preview": "safe preview"}]}]}
    )
    assert not audit._workbench_preview_is_bounded({"items": []})
    assert not audit._workbench_preview_is_bounded(
        {"items": [{"notes": [{"operator_note_preview": audit.RAW_NOTE_SENTINEL}]}]}
    )
    assert audit._workbench_raw_fields_absent({"items": [{"notes": [{"safe": 1}]}]})
    assert not audit._workbench_raw_fields_absent(
        {"items": [{"notes": [{"metadata": {"idempotency_key": "secret"}}]}]}
    )
    assert audit._redaction_flags_safe(
        {
            "redaction": {
                "raw_operator_note_included": False,
                "raw_evidence_body_included": False,
                "raw_prompt_included": False,
                "raw_source_text_included": False,
                "storage_paths_included": False,
                "idempotency_keys_included": False,
            }
        }
    )
    assert not audit._redaction_flags_safe({"redaction": "bad"})
    assert audit._issue_candidates_safe(
        {
            "issue_candidates": [
                {
                    "rule_id": "operator_review_attention_required.v1",
                    "signal": {"source_type": "operator_review_workbench"},
                }
            ]
        }
    )
    assert not audit._issue_candidates_safe({"issue_candidates": "bad"})
    assert audit._contains_forbidden_keys(
        {"items": [{"storage_path": "/tmp/raw"}]},
        {"storage_path"},
    )
    assert not audit._contains_forbidden_keys(["safe", {"safe": True}], {"raw"})


def test_ag_operator_review_workbench_privacy_evidence_redaction_guard() -> None:
    with pytest.raises(ValueError, match="raw_prompt"):
        audit.assert_privacy_evidence_redacted(audit.RAW_PROMPT)
    audit.assert_privacy_evidence_redacted("only labels are safe")


def test_ag_operator_review_workbench_privacy_main(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        audit,
        "run_ag_operator_review_workbench_privacy_regression",
        lambda: {
            "audit_schema_version": audit.SCHEMA_VERSION,
            "status": "PASS",
            "surface_count": 4,
            "fixture": {"forbidden_value_labels": list(audit.FORBIDDEN_VALUES)},
        },
    )

    assert audit.main(["--summary"]) == 0
    assert (
        "ag_operator_review_workbench_privacy_regression=pass"
        in capsys.readouterr().out
    )

    monkeypatch.setattr(
        audit,
        "run_ag_operator_review_workbench_privacy_regression",
        lambda: {
            "audit_schema_version": audit.SCHEMA_VERSION,
            "status": "FAIL",
            "failure_code": "failed",
            "checks": {"no_forbidden_values": False},
        },
    )

    assert audit.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
