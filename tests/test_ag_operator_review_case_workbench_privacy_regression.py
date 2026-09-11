from __future__ import annotations

import json

import pytest

import run_ag_operator_review_case_workbench_privacy_regression as audit


def test_ag_operator_review_case_workbench_privacy_regression_passes() -> None:
    evidence = audit.run_ag_operator_review_case_workbench_privacy_regression()

    assert evidence["status"] == "PASS"
    assert evidence["audit_schema_version"] == audit.SCHEMA_VERSION
    assert evidence["slice"] == "0659"
    assert evidence["surface_count"] == 5
    assert all(evidence["checks"].values())
    assert all(not surface["leak_labels"] for surface in evidence["surfaces"])
    assert audit.summary_line(evidence) == (
        "ag_operator_review_case_workbench_privacy_regression=pass "
        "surfaces=5 forbidden_labels=11"
    )
    serialized = json.dumps(evidence, ensure_ascii=False)
    for forbidden in audit.FORBIDDEN_VALUES.values():
        assert forbidden not in serialized


def test_ag_operator_review_case_workbench_privacy_regression_detects_leak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        audit,
        "_collect_surface_payloads",
        lambda case_store, event_store, *, case_id: _surface_payloads_with_leak(),
    )

    evidence = audit.run_ag_operator_review_case_workbench_privacy_regression()

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == (
        "ag_operator_review_case_workbench_privacy_regression_failed"
    )
    assert evidence["checks"]["no_forbidden_values"] is False
    assert evidence["checks"]["raw_fields_absent"] is False
    assert evidence["surfaces"][0]["leak_labels"] == [
        "raw_action_comment_full_text",
        "raw_action_comment_sentinel",
    ]
    assert "no_forbidden_values" in audit.summary_line(evidence)


def test_ag_operator_review_case_workbench_privacy_regression_detects_bad_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        audit,
        "_collect_surface_payloads",
        lambda case_store, event_store, *, case_id: [
            audit.SurfacePayload("queue", 500, {"items": [], "redaction": {}}),
            audit.SurfacePayload("workbench_detail", 200, {"redaction": {}}),
            audit.SurfacePayload("timeline", 200, {"summary": {}, "redaction": {}}),
            audit.SurfacePayload("dashboard", 200, {"operator_review_cases": {}}),
            audit.SurfacePayload("issue_candidates", 200, {"issue_candidates": []}),
        ],
    )

    evidence = audit.run_ag_operator_review_case_workbench_privacy_regression()

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["all_routes_200"] is False
    assert evidence["checks"]["queue_action_material_safe"] is False
    assert evidence["checks"]["detail_action_material_safe"] is False
    assert evidence["checks"]["timeline_metadata_only"] is False
    assert evidence["checks"]["dashboard_case_section_safe"] is False
    assert evidence["checks"]["issue_candidates_reference_safe_cases"] is False


def test_ag_operator_review_case_workbench_privacy_helpers() -> None:
    assert audit._leak_labels(
        f"prefix {audit.RAW_PROMPT} suffix",
        audit.FORBIDDEN_VALUES,
    ) == ["raw_prompt"]
    assert audit._contains_forbidden_keys(
        {"items": [{"storage_path": "/tmp/raw"}]},
        {"storage_path"},
    )
    assert not audit._contains_forbidden_keys(["safe", {"safe": True}], {"raw"})
    assert audit._previews_are_bounded({"latest_action": {"safe": "hash_only"}})
    assert audit._previews_are_bounded(
        {"resolution_preview": "bounded safe preview"}
    )
    assert not audit._previews_are_bounded(
        {"action_comment_preview": audit.RAW_ACTION_SENTINEL}
    )
    assert audit._action_material_safe({"action_comment_hash": "a" * 64})
    assert not audit._action_material_safe({"action_comment_hash": "not-a-hash"})
    assert audit._collect_hash_values(
        [{"action_comment_hash": "a" * 64}, {"resolution_hash": None}]
    ) == ["a" * 64]
    assert audit._is_sha256_hex("f" * 64)
    assert not audit._is_sha256_hex("g" * 64)
    assert audit._timeline_metadata_only(
        {
            "summary": {
                "timeline_status": "READY",
                "case_recorded_event_count": 1,
                "case_action_event_count": 1,
            },
            "redaction": _safe_redaction(),
        }
    )
    assert not audit._timeline_metadata_only({"summary": "bad"})
    assert audit._redaction_flags_safe({"redaction": _safe_redaction()})
    assert not audit._redaction_flags_safe({"redaction": "bad"})
    assert audit._dashboard_case_section_safe(
        {
            "operator_review_cases": {
                "summary": {"case_count": 1},
                "attention": [{"case_id": "case"}],
                "redaction": _safe_redaction(),
            }
        }
    )
    assert not audit._dashboard_case_section_safe({"operator_review_cases": "bad"})
    assert audit._issue_candidates_safe(
        {
            "issue_candidates": [
                {
                    "rule_id": "operator_review_case_attention_required.v1",
                    "signal": {"source_type": "operator_review_case"},
                }
            ]
        }
    )
    assert not audit._issue_candidates_safe({"issue_candidates": "bad"})


def test_ag_operator_review_case_workbench_privacy_evidence_redaction_guard() -> None:
    with pytest.raises(ValueError, match="raw_prompt"):
        audit.assert_privacy_evidence_redacted(audit.RAW_PROMPT)
    audit.assert_privacy_evidence_redacted("only labels are safe")


def test_ag_operator_review_case_workbench_privacy_main(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        audit,
        "run_ag_operator_review_case_workbench_privacy_regression",
        lambda: {
            "audit_schema_version": audit.SCHEMA_VERSION,
            "status": "PASS",
            "surface_count": 5,
            "fixture": {"forbidden_value_labels": list(audit.FORBIDDEN_VALUES)},
        },
    )

    assert audit.main(["--summary"]) == 0
    assert (
        "ag_operator_review_case_workbench_privacy_regression=pass"
        in capsys.readouterr().out
    )

    monkeypatch.setattr(
        audit,
        "run_ag_operator_review_case_workbench_privacy_regression",
        lambda: {
            "audit_schema_version": audit.SCHEMA_VERSION,
            "status": "FAIL",
            "failure_code": "failed",
            "checks": {"no_forbidden_values": False},
        },
    )

    assert audit.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out


def _surface_payloads_with_leak() -> list[audit.SurfacePayload]:
    return [
        audit.SurfacePayload(
            "queue",
            200,
            {
                "items": [
                    {
                        "latest_action": {
                            "action_comment_hash": "a" * 64,
                            "raw_action_comment": audit.RAW_ACTION_COMMENT,
                        }
                    }
                ],
                "redaction": _safe_redaction(),
            },
        ),
        audit.SurfacePayload(
            "workbench_detail",
            200,
            {
                "latest_action": {"action_comment_hash": "b" * 64},
                "redaction": _safe_redaction(),
            },
        ),
        audit.SurfacePayload(
            "timeline",
            200,
            {
                "summary": {
                    "timeline_status": "READY",
                    "case_recorded_event_count": 1,
                    "case_action_event_count": 1,
                },
                "redaction": _safe_redaction(),
            },
        ),
        audit.SurfacePayload(
            "dashboard",
            200,
            {
                "operator_review_cases": {
                    "summary": {"case_count": 1},
                    "attention": [{"case_id": "case"}],
                    "redaction": _safe_redaction(),
                }
            },
        ),
        audit.SurfacePayload(
            "issue_candidates",
            200,
            {
                "issue_candidates": [
                    {
                        "rule_id": "operator_review_case_attention_required.v1",
                        "signal": {"source_type": "operator_review_case"},
                    }
                ]
            },
        ),
    ]


def _safe_redaction() -> dict[str, bool]:
    return {key: False for key in audit.CASE_REDACTION_FLAGS}
