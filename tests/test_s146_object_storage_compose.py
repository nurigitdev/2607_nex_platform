from pathlib import Path

import run_s146_object_storage_compose as audit


def test_repository_object_storage_compose_audit_passes() -> None:
    result = audit.run_object_storage_compose()
    assert result["status"] == "PASS"
    assert result["slice"] == "1460"
    assert result["next_slice"] == "1461"
    assert all(result["checks"].values())
    assert result["raw_secret_values_included"] is False
    assert audit.summary_line(result) == (
        "object_storage_compose=pass checks=10/10 buckets=2 "
        "credentials=2 host_ports=0 next=1461"
    )


def test_object_storage_compose_audit_reports_failure(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        audit,
        "validate_s146_compose_assets",
        lambda _root: {
            "orchestrator": "other",
            "rustfs_image": "mutable",
            "runtime_user": "0:0",
            "tls_route_count": 0,
            "host_port_count": 1,
            "console_enabled": True,
            "application_bucket_count": 1,
            "application_credential_pair_count": 1,
            "secret_reference_count": 0,
            "durable_volume_count": 0,
        },
    )
    result = audit.run_object_storage_compose(tmp_path)
    assert result["status"] == "FAIL"
    assert result["next_slice"] == "blocked"
    assert "object_storage_compose=fail" in audit.summary_line(result)


def test_object_storage_compose_cli_outputs_summary_and_json(monkeypatch, capsys) -> None:
    passing = audit.run_object_storage_compose()
    monkeypatch.setattr(audit, "run_object_storage_compose", lambda: passing)
    assert audit.main(["--summary"]) == 0
    assert "object_storage_compose=pass" in capsys.readouterr().out
    assert audit.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    failing = {**passing, "status": "FAIL", "next_slice": "blocked"}
    monkeypatch.setattr(audit, "run_object_storage_compose", lambda: failing)
    assert audit.main(["--summary"]) == 1
    assert "object_storage_compose=fail" in capsys.readouterr().out
