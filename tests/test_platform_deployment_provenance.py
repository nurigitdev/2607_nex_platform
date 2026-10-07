from __future__ import annotations

import subprocess

import pytest

import run_platform_deployment_provenance as smoke


def test_deployment_provenance_evidence_passes() -> None:
    result = smoke.run_platform_deployment_provenance()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert result["summary"] == {
        "artifact_count": 6,
        "provenance_digest_count": 6,
        "image_digest_count": 0,
        "synthetic_complete_set_proof_count": 1,
    }
    assert result["decision"]["image_build_performed"] is False


def test_synthetic_image_references_are_complete_and_unique() -> None:
    references = smoke._synthetic_image_references()

    assert len(references) == 6
    assert len(set(references.values())) == 6
    assert all("@sha256:" in value for value in references.values())


def test_git_metadata_fails_closed(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        smoke.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            subprocess.CalledProcessError(1, "git")
        ),
    )

    with pytest.raises(ValueError, match="Git source metadata is unavailable"):
        smoke._git_metadata(tmp_path)


def test_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = smoke.run_platform_deployment_provenance()
    assert smoke.summary_line(passing) == (
        "platform_deployment_provenance=pass artifacts=6 provenance=6 "
        "images=0 complete_set_proofs=1 next=1420"
    )
    assert smoke.summary_line({"status": "FAIL", "issues": [1]}) == (
        "platform_deployment_provenance=fail issues=1"
    )

    monkeypatch.setattr(smoke, "run_platform_deployment_provenance", lambda: passing)
    assert smoke.main(["--summary"]) == 0
    assert "provenance=pass" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_platform_deployment_provenance",
        lambda: (_ for _ in ()).throw(ValueError("bad provenance")),
    )
    assert smoke.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
