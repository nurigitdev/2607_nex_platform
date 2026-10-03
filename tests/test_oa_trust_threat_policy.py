from __future__ import annotations

import pytest

from nex_oa.trust_threat_policy import (
    TRUST_THREAT_POLICIES,
    build_trust_threat_evidence,
    evidence_privacy_violations,
)


def test_threat_matrix_is_complete_and_privacy_safe() -> None:
    evidence = build_trust_threat_evidence(evaluated_at="2026-10-03T12:00:00Z")

    assert set(TRUST_THREAT_POLICIES) == {
        "algorithm_confusion",
        "kid_injection",
        "audience_confusion",
        "token_replay",
        "stale_authorization",
        "key_or_credential_disclosure",
        "trust_dependency_outage",
        "raw_token_logging",
    }
    assert evidence["summary"] == {
        "threat_count": 8,
        "critical_count": 2,
        "high_count": 6,
        "privacy_violation_count": 0,
    }
    assert evidence_privacy_violations(evidence) == ()
    assert evidence["threats"]["algorithm_confusion"]["severity"] == "CRITICAL"


@pytest.mark.parametrize("evaluated_at", [None, "", "2026-10-03T12:00:00+00:00"])
def test_invalid_evaluation_time_is_rejected(evaluated_at: object) -> None:
    with pytest.raises(ValueError, match="ending in Z"):
        build_trust_threat_evidence(evaluated_at=evaluated_at)  # type: ignore[arg-type]


def test_privacy_scanner_finds_fields_values_and_nested_sequences() -> None:
    payload = {
        "access_token": "redacted",
        "items": [
            {"safe": "Bearer test-only"},
            ("nex-mock-service.payload", "-----BEGIN PRIVATE KEY-----"),
        ],
        "count": 1,
    }

    assert evidence_privacy_violations(payload) == (
        "forbidden_field:access_token",
        "forbidden_value:items[0].safe",
        "forbidden_value:items[1][0]",
        "forbidden_value:items[1][1]",
    )
