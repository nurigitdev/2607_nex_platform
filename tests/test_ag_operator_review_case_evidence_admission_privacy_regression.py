from __future__ import annotations

import json

import pytest

import run_ag_operator_review_case_evidence_admission_privacy_regression as audit


def test_ag_operator_review_case_evidence_admission_privacy_regression_passes() -> None:
    evidence = audit.run_ag_operator_review_case_evidence_admission_privacy_regression()

    assert evidence["status"] == "PASS"
    assert evidence["audit_schema_version"] == audit.SCHEMA_VERSION
    assert evidence["slice"] == "0669"
    assert evidence["surface_count"] == 3
    assert all(evidence["checks"].values())
    assert all(not surface["leak_labels"] for surface in evidence["surfaces"])
    assert audit.summary_line(evidence) == (
        "ag_operator_review_case_evidence_admission_privacy_regression=pass "
        "surfaces=3 forbidden_labels=11"
    )
    serialized = json.dumps(evidence, ensure_ascii=False)
    for forbidden in audit.FORBIDDEN_VALUES.values():
        assert forbidden not in serialized


def test_ag_operator_review_case_evidence_admission_privacy_regression_detects_leak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        audit,
        "_collect_surface_payloads",
        lambda case_store, note_store, export_store, *, case_id: _surface_payloads_with_leak(),
    )

    evidence = audit.run_ag_operator_review_case_evidence_admission_privacy_regression()

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == (
        "ag_operator_review_case_evidence_admission_privacy_regression_failed"
    )
    assert evidence["checks"]["no_forbidden_values"] is False
    assert evidence["checks"]["raw_fields_absent"] is False
    assert evidence["surfaces"][1]["leak_labels"] == ["raw_operator_note"]
    assert "no_forbidden_values" in audit.summary_line(evidence)


def test_ag_operator_review_case_evidence_admission_privacy_regression_detects_bad_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        audit,
        "_collect_surface_payloads",
        lambda case_store, note_store, export_store, *, case_id: [
            audit.SurfacePayload("workbench_detail", 500, {"redaction": {}}),
            audit.SurfacePayload("evidence_links", 200, {"redaction": {}}),
            audit.SurfacePayload("action_admission", 200, {"redaction": {}}),
        ],
    )

    evidence = audit.run_ag_operator_review_case_evidence_admission_privacy_regression()

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["all_routes_200"] is False
    assert evidence["checks"]["workbench_detail_summary_only"] is False
    assert evidence["checks"]["evidence_links_safe"] is False
    assert evidence["checks"]["evidence_item_redaction_safe"] is False
    assert evidence["checks"]["action_admission_safe"] is False


def test_ag_operator_review_case_evidence_admission_helpers() -> None:
    assert audit._leak_labels(
        f"prefix {audit.RAW_PROMPT} suffix",
        audit.FORBIDDEN_VALUES,
    ) == ["raw_prompt"]
    assert audit._contains_forbidden_keys(
        {"items": [{"storage_path": "/tmp/raw"}]},
        {"storage_path"},
    )
    assert not audit._contains_forbidden_keys(["safe", {"safe": True}], {"raw"})
    assert audit._workbench_detail_summary_only(_safe_detail_payload())
    assert not audit._workbench_detail_summary_only({"evidence_links": []})
    assert audit._evidence_links_safe(_safe_evidence_payload())
    assert not audit._evidence_links_safe({"summary": {}, "items": "bad"})
    assert audit._action_admission_safe(_safe_admission_payload())
    assert not audit._action_admission_safe({"summary": {}, "requested_action": {}})
    assert audit._admission_item_safe(_safe_admission_payload()["items"][0])
    assert not audit._admission_item_safe("bad")
    assert audit._evidence_item_redaction_safe(_safe_evidence_payload())
    bad_item = _safe_evidence_payload()
    bad_item["items"][0]["redaction"] = {"raw_operator_note_included": True}
    assert not audit._evidence_item_redaction_safe(bad_item)
    assert not audit._evidence_item_redaction_safe({"items": "bad"})
    assert audit._redaction_flags_safe(
        {"redaction": _safe_flags(audit.ADMISSION_REDACTION_FLAGS)},
        audit.ADMISSION_REDACTION_FLAGS,
    )
    assert not audit._redaction_flags_safe({"redaction": "bad"}, ("flag",))
    assert audit._collect_hash_values(
        [{"operator_note_hash": "a" * 64}, {"evidence_hash": None}]
    ) == ["a" * 64]
    assert audit._collect_preview_values({"operator_note_preview": "safe"}) == ["safe"]
    assert audit._is_sha256_hex("f" * 64)
    assert not audit._is_sha256_hex("g" * 64)
    assert len(audit._sha256_text("value")) == 64
    assert audit._case_payload()["target_ref"]["target_id"] == audit.TARGET_ID
    assert audit._unsafe_note_record()["raw_operator_note"] == audit.RAW_OPERATOR_NOTE
    assert audit._unsafe_export_record()["metadata"]["raw_evidence_body"] == (
        audit.RAW_EVIDENCE_BODY
    )


def test_ag_operator_review_case_evidence_admission_privacy_evidence_redaction_guard() -> None:
    with pytest.raises(ValueError, match="raw_prompt"):
        audit.assert_privacy_evidence_redacted(audit.RAW_PROMPT)
    audit.assert_privacy_evidence_redacted("only labels are safe")


def test_ag_operator_review_case_evidence_admission_privacy_main(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        audit,
        "run_ag_operator_review_case_evidence_admission_privacy_regression",
        lambda: {
            "audit_schema_version": audit.SCHEMA_VERSION,
            "status": "PASS",
            "surface_count": 3,
            "fixture": {"forbidden_value_labels": list(audit.FORBIDDEN_VALUES)},
        },
    )

    assert audit.main(["--summary"]) == 0
    assert (
        "ag_operator_review_case_evidence_admission_privacy_regression=pass"
        in capsys.readouterr().out
    )

    monkeypatch.setattr(
        audit,
        "run_ag_operator_review_case_evidence_admission_privacy_regression",
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
        audit.SurfacePayload("workbench_detail", 200, _safe_detail_payload()),
        audit.SurfacePayload(
            "evidence_links",
            200,
            {
                **_safe_evidence_payload(),
                "items": [
                    {
                        **_safe_evidence_payload()["items"][0],
                        "raw_operator_note": audit.RAW_OPERATOR_NOTE,
                    }
                ],
            },
        ),
        audit.SurfacePayload("action_admission", 200, _safe_admission_payload()),
    ]


def _safe_detail_payload() -> dict[str, object]:
    return {
        "evidence_links": {
            "inline_items_included": False,
            "summary": {
                "evidence_source_status": "READY",
                "total_link_count": 2,
            },
        },
        "action_admission": {
            "inline_items_included": False,
            "summary": {"preflight_only": True},
        },
        "redaction": _safe_flags(audit.DETAIL_REDACTION_FLAGS),
    }


def _safe_evidence_payload() -> dict[str, object]:
    return {
        "summary": {
            "evidence_source_status": "READY",
            "operator_note_count": 1,
            "redacted_evidence_export_count": 1,
            "returned_link_count": 2,
        },
        "items": [
            {
                "link_type": "operator_review_note",
                "operator_note_hash": "a" * 64,
                "operator_note_preview": "Bounded safe note preview.",
                "redaction": {
                    "raw_operator_note_included": False,
                    "storage_paths_included": False,
                    "idempotency_keys_included": False,
                },
            },
            {
                "link_type": "redacted_evidence_export",
                "evidence_hash": "b" * 64,
                "redaction": {
                    "raw_evidence_body_included": False,
                    "storage_paths_included": False,
                    "idempotency_keys_included": False,
                },
            },
        ],
        "redaction": _safe_flags(audit.EVIDENCE_REDACTION_FLAGS),
    }


def _safe_admission_payload() -> dict[str, object]:
    return {
        "summary": {
            "requested_action_type": "RESOLVE",
            "requested_action_admitted": True,
            "preflight_only": True,
        },
        "requested_action": {
            "action_type": "RESOLVE",
            "current_status": "OPEN",
            "target_status": "RESOLVED",
            "admitted": True,
            "requires_resolution_comment": True,
            "mutation_route_authoritative": True,
            "preflight_only": True,
        },
        "items": [
            {
                "action_type": "RESOLVE",
                "current_status": "OPEN",
                "target_status": "RESOLVED",
                "admitted": True,
                "mutation_route_authoritative": True,
                "preflight_only": True,
            }
        ],
        "redaction": _safe_flags(audit.ADMISSION_REDACTION_FLAGS),
    }


def _safe_flags(flags: tuple[str, ...]) -> dict[str, bool]:
    return {key: False for key in flags}
