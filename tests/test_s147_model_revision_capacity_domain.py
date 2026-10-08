from __future__ import annotations

import run_s147_model_revision_capacity_domain as smoke


def test_model_revision_capacity_domain_passes() -> None:
    result = smoke.run_model_revision_capacity_domain()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "capability_count": 3,
        "identity_count": 3,
        "node_count": 3,
        "gpu_count": 3,
        "check_count": 9,
    }
    assert len(set(result["identity_fingerprints"])) == 3
    assert result["next_slice"] == "1465"


def test_helpers_summary_and_main(monkeypatch, capsys) -> None:
    result = smoke.run_model_revision_capacity_domain()
    assert smoke.summary_line(result) == (
        "model_revision_capacity_domain=pass capabilities=3 identities=3 "
        "nodes=3 checks=9/9 next=1465"
    )
    monkeypatch.setattr(smoke, "run_model_revision_capacity_domain", lambda: result)
    assert smoke.main(["--summary"]) == 0
    assert "next=1465" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    failed = {"status": "FAIL", "summary": {}, "next_slice": "blocked"}
    monkeypatch.setattr(smoke, "run_model_revision_capacity_domain", lambda: failed)
    assert smoke.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
