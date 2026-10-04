from __future__ import annotations

import run_platform_runtime_manifest_domain as smoke


def test_domain_evidence_passes() -> None:
    result = smoke.build_domain_evidence()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["decision"]["secret_values_allowed_in_projection"] is False
    assert result["decision"]["next_slice"] == "1314"


def test_summary_and_main(monkeypatch, capsys) -> None:
    passing = smoke.build_domain_evidence()
    assert smoke.summary_line(passing) == (
        "platform_runtime_manifest_domain=pass profile=local_mock "
        "endpoints=1 processes=1 next=1314"
    )
    assert smoke.summary_line({"status": "FAIL", "issues": [1]}) == (
        "platform_runtime_manifest_domain=fail issues=1"
    )

    monkeypatch.setattr(smoke, "build_domain_evidence", lambda: passing)
    assert smoke.main(["--summary"]) == 0
    assert "domain=pass" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        smoke, "build_domain_evidence", lambda: {"status": "FAIL", "issues": []}
    )
    assert smoke.main([]) == 1
