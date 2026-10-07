from __future__ import annotations

import run_oa_openbao_transit_rotation_checkpoint as runner


def test_rotation_checkpoint_passes_without_protected_contact() -> None:
    result = runner.run_oa_openbao_transit_rotation_checkpoint()

    assert result["status"] == "PASS"
    assert result["summary"] == {
        "check_count": 14,
        "key_count": 2,
        "active_key_count": 1,
        "jwks_key_count": 2,
        "restart_count": 1,
    }
    assert all(result["checks"].values())
    assert result["decision"]["atomic_rotation_required"] is True
    assert result["decision"]["live_openbao_contacted"] is False


def test_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = runner.run_oa_openbao_transit_rotation_checkpoint()
    assert runner.summary_line(passing) == (
        "oa_transit_rotation_checkpoint=pass checks=14/14 keys=2 active=1 "
        "jwks=2 restarts=1 next=1438"
    )
    assert runner.summary_line({"status": "FAIL", "issues": ["x"]}) == (
        "oa_transit_rotation_checkpoint=fail issues=1"
    )

    monkeypatch.setattr(
        runner,
        "run_oa_openbao_transit_rotation_checkpoint",
        lambda: passing,
    )
    assert runner.main(["--summary"]) == 0
    assert "oa_transit_rotation_checkpoint=pass" in capsys.readouterr().out

    failing = {**passing, "status": "FAIL"}
    monkeypatch.setattr(
        runner,
        "run_oa_openbao_transit_rotation_checkpoint",
        lambda: failing,
    )
    assert runner.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out


def test_transit_double_key_creation_is_idempotent() -> None:
    transport = runner._TransitLifecycleTransport()
    path = f"/v1/transit/keys/{runner.KEY_NAME}"

    transport.request("POST", path, token="operator-token", payload={})
    first_key = transport.keys[1]
    transport.request("POST", path, token="operator-token", payload={})

    assert transport.keys == {1: first_key}
