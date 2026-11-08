from __future__ import annotations

import json
from pathlib import Path

import pytest
import run_gb2_s20qj_reranker_revision_ab as smoke
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from test_nex_cx_retrieval_reranker_revision_ab import (
    REVISION_A,
    REVISION_B,
    _profile,
    _repeatability,
    _revision,
    _source,
)


def _write(path: Path, value: object) -> str:
    text = f"{json.dumps(value, indent=2, sort_keys=True)}\n"
    path.write_text(text, encoding="utf-8")
    return smoke._text_hash(text)


def _profile_files(tmp_path: Path, *, slot: str = "A") -> dict[str, str]:
    model = f"model-{slot.lower()}"
    revision_value = REVISION_A if slot == "A" else REVISION_B
    repeatability_path = tmp_path / f"repeatability-{slot}.json"
    revision_path = tmp_path / f"revision-{slot}.json"
    source_path = tmp_path / f"source-{slot}.json"
    repeatability_hash = _write(repeatability_path, _repeatability(model))
    revision_hash = _write(revision_path, _revision(revision_value, model))
    source = _source(revision_value, model)
    source["provenance"].update(
        repeatability_evidence_sha256=repeatability_hash,
        revision_evidence_sha256=revision_hash,
    )
    _write(source_path, source)
    return {
        smoke.SMOKE_ENV: "1",
        smoke.MODE_ENV: "PROFILE",
        smoke.SLOT_ENV: slot,
        smoke.SOURCE_PATH_ENV: str(source_path),
        smoke.REPEATABILITY_PATH_ENV: str(repeatability_path),
        smoke.REVISION_PATH_ENV: str(revision_path),
    }


def test_skip_profile_and_compare_modes(tmp_path: Path) -> None:
    assert smoke.run_gb2_s20qj_reranker_revision_ab({})["status"] == "SKIPPED"

    profile_result = smoke.run_gb2_s20qj_reranker_revision_ab(_profile_files(tmp_path))
    assert profile_result["status"] == "PASS"
    assert profile_result["result"]["slot"] == "A"
    assert "mode=profile slot=A" in smoke.summary_line(profile_result)

    profile_a = tmp_path / "profile-a.json"
    profile_b = tmp_path / "profile-b.json"
    _write(
        profile_a,
        {
            "evidence_schema_version": smoke.SCHEMA_VERSION,
            "status": "PASS",
            "mode": "PROFILE",
            "result": _profile("A", revision=REVISION_A, model="model-a"),
        },
    )
    _write(
        profile_b,
        {
            "evidence_schema_version": smoke.SCHEMA_VERSION,
            "status": "PASS",
            "mode": "PROFILE",
            "result": _profile("B", revision=REVISION_B, model="model-b"),
        },
    )
    compared = smoke.run_gb2_s20qj_reranker_revision_ab(
        {
            smoke.SMOKE_ENV: "1",
            smoke.MODE_ENV: "COMPARE",
            smoke.PROFILE_A_PATH_ENV: str(profile_a),
            smoke.PROFILE_B_PATH_ENV: str(profile_b),
        }
    )
    assert compared["status"] == "PASS"
    assert compared["result"]["decision"]["status"] == "NO_ADMISSIBLE_REVISION"
    assert "mode=compare decision=NO_ADMISSIBLE_REVISION" in smoke.summary_line(
        compared
    )


def test_invalid_mode_missing_path_json_and_profile_fail_safely(
    tmp_path: Path,
) -> None:
    invalid_mode = smoke.run_gb2_s20qj_reranker_revision_ab(
        {smoke.SMOKE_ENV: "1", smoke.MODE_ENV: "OTHER"}
    )
    assert invalid_mode["failure_code"] == "S20QJ_MODE_INVALID"

    missing = smoke.run_gb2_s20qj_reranker_revision_ab(
        {smoke.SMOKE_ENV: "1", smoke.MODE_ENV: "PROFILE"}
    )
    assert missing["failure_code"].endswith("_REQUIRED")

    malformed = tmp_path / "malformed.json"
    malformed.write_text("[]", encoding="utf-8")
    failed = smoke.run_gb2_s20qj_reranker_revision_ab(
        {
            smoke.SMOKE_ENV: "1",
            smoke.MODE_ENV: "COMPARE",
            smoke.PROFILE_A_PATH_ENV: str(malformed),
            smoke.PROFILE_B_PATH_ENV: str(malformed),
        }
    )
    assert failed["failure_code"] == "S20QJ_EXECUTION_FAILED"
    assert failed["detail"] == "TypeError"

    with pytest.raises(smoke.RerankerRevisionABError, match="NOT_ADMITTED"):
        smoke._profile_payload(
            {
                "evidence_schema_version": smoke.SCHEMA_VERSION,
                "status": "FAIL",
                "mode": "PROFILE",
                "result": {},
            }
        )
    raw = {"profile_schema_version": "raw"}
    assert smoke._profile_payload(raw) is raw


def test_redaction_guard_helpers_and_main(monkeypatch, tmp_path: Path, capsys) -> None:
    with pytest.raises(ValueError, match="protected"):
        smoke._assert_redacted(
            {"leak": "private-key"},
            {"NEX_MO_REMOTE_RERANKER_API_KEY": "private-key"},
        )
    assert smoke._read_json(_json_object(tmp_path / "object.json"))[1] == {"ok": True}
    assert smoke._text_hash("abc").startswith("sha256:")
    assert smoke.summary_line({}).endswith("error=unknown")
    assert "=skipped" in smoke.summary_line({"status": "SKIPPED"})
    assert "decision=unknown" in smoke.summary_line(
        {"status": "PASS", "mode": "PROFILE", "result": {"slot": "A"}}
    )
    assert "decision=unknown" in smoke.summary_line(
        {"status": "PASS", "mode": "COMPARE", "result": []}
    )

    captured: dict[str, str] = {}
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qj_reranker_revision_ab",
        lambda env: (
            captured.update(env)
            or {
                "status": "PASS",
                "mode": "COMPARE",
                "result": {"decision": {"status": "REVISION_A_SELECTED"}},
            }
        ),
    )
    output = tmp_path / "output.json"
    assert (
        smoke.main(
            [
                "--mode",
                "PROFILE",
                "--slot",
                "B",
                "--source",
                str(output),
                "--repeatability",
                str(output),
                "--revision",
                str(output),
                "--profile-a",
                str(output),
                "--profile-b",
                str(output),
                "--output",
                str(output),
                "--summary",
            ]
        )
        == 0
    )
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "PASS"
    assert "REVISION_A_SELECTED" in capsys.readouterr().out
    assert captured[smoke.SLOT_ENV] == "B"
    assert captured[smoke.PROFILE_B_PATH_ENV] == str(output)

    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qj_reranker_revision_ab",
        lambda _env: {"status": "FAIL", "failure_code": "blocked"},
    )
    assert smoke.main([]) == 1


def _json_object(path: Path) -> Path:
    path.write_text('{"ok": true}', encoding="utf-8")
    return path


def test_comparison_profile_hash_is_not_recomputed_from_file_format(
    tmp_path: Path,
) -> None:
    profile = _profile("A", revision=REVISION_A, model="model-a")
    path = tmp_path / "profile.json"
    _write(path, profile)
    _, loaded = smoke._read_json(path)
    unsigned = dict(loaded)
    profile_hash = unsigned.pop("profile_hash")
    assert profile_hash == semantic_sha256_hash_ref(unsigned)
