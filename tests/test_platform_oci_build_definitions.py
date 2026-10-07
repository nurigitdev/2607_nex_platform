from __future__ import annotations

import run_platform_oci_build_definitions as smoke


def test_repository_oci_build_evidence_is_complete() -> None:
    result = smoke.run_platform_oci_build_definitions()

    assert result["status"] == "PASS"
    assert result["summary"]["artifact_count"] == 6
    assert result["summary"]["target_count"] == 6
    assert result["summary"]["context_file_count"] > 700
    assert result["summary"]["context_byte_count"] > 0
    assert result["summary"]["digest_pinned_base_count"] == 6
    assert result["summary"]["digest_pinned_builder_count"] == 10
    assert result["summary"]["unique_builder_image_count"] == 2
    assert result["decision"] == {
        "repository_root_build_context_allowed": False,
        "owner_allowlist_context_required": True,
        "non_root_runtime_required": True,
        "docker_daemon_required_for_this_evidence": False,
        "production_connection_required": False,
        "next_slice": "1416",
    }


def test_summary_and_main_branches(monkeypatch, capsys) -> None:
    passing = smoke.run_platform_oci_build_definitions()
    assert smoke.summary_line(passing).startswith(
        "platform_oci_build_definitions=pass artifacts=6 targets=6"
    )
    assert smoke.summary_line({"status": "FAIL"}) == (
        "platform_oci_build_definitions=fail"
    )

    monkeypatch.setattr(smoke, "run_platform_oci_build_definitions", lambda: passing)
    assert smoke.main(["--summary"]) == 0
    assert "definitions=pass" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_platform_oci_build_definitions",
        lambda: (_ for _ in ()).throw(ValueError("bad build")),
    )
    assert smoke.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
