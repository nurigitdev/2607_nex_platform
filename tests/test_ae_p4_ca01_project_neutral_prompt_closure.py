from __future__ import annotations

import json
from pathlib import Path
import runpy

import pytest

import run_p4_ca01_project_neutral_prompt_closure as closure


def test_repository_p4_ca01_closure_passes() -> None:
    result = closure.run_p4_ca01_project_neutral_prompt_closure()

    assert result["status"] == "PASS"
    assert result["admission_gate"] == "OPEN_FOR_P4_SOURCE_IMPLEMENTATION"
    assert result["validation_scope"] == "FOCUSED_CONTRACT_IMPACT_PROBE"
    assert all(result["checks"].values())
    assert result["summary"]["probe_count"] == 9
    assert result["summary"]["passed_probe_count"] == 9
    assert result["summary"]["manifest_entry_count"] >= 8
    assert result["summary"]["valid_manifest_entry_count"] == result["summary"][
        "manifest_entry_count"
    ]


def test_probe_matrix_keeps_prompt_project_neutral_without_weakening_claims() -> None:
    result = closure.run_p4_ca01_project_neutral_prompt_closure()
    probes = {item["name"]: item for item in result["probe_results"]}

    assert probes["prompt_ia_null_project"]["schema_accepted"] is True
    assert probes["prompt_ia_null_project"]["protocol_accepted"] is True
    assert probes["prompt_ia_resolved_project"]["passed"] is True
    assert probes["claimed_workitem_pa_project"]["passed"] is True
    assert probes["prompt_pa_rejected"]["schema_accepted"] is False
    assert probes["claimed_null_project_rejected"]["protocol_accepted"] is False
    assert probes["claimed_ia_rejected"]["passed"] is True
    assert probes["tenant_missing_rejected"]["passed"] is True
    assert probes["blank_project_rejected"]["passed"] is True
    assert probes["invalid_claim_generation_rejected"]["passed"] is True


def test_protocol_rejects_unsupported_source_and_invalid_required_text() -> None:
    protocol = closure._load_protocol(closure.ROOT / closure.CANDIDATE_PROTOCOL)
    payload = closure._prompt_payload()
    payload["source_type"] = "UNSUPPORTED"
    assert closure._protocol_accepts(protocol, payload) is False

    payload = closure._prompt_payload()
    payload["source_ref"] = " "
    assert closure._protocol_accepts(protocol, payload) is False

    payload = closure._prompt_payload()
    payload["project_id"] = 42
    assert closure._protocol_accepts(protocol, payload) is False


def test_contract_loaders_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    non_object = tmp_path / "non-object.json"
    non_object.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="expected JSON object"):
        closure._load_json(non_object)

    monkeypatch.setattr(
        closure.importlib.util,
        "spec_from_file_location",
        lambda *_args, **_kwargs: None,
    )
    with pytest.raises(ImportError, match="cannot load protocol"):
        closure._load_protocol(tmp_path / "missing.py")


def test_closure_fails_closed_for_malformed_amended_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        closure,
        "_load_json",
        lambda _path: (_ for _ in ()).throw(ValueError("malformed")),
    )

    result = closure.run_p4_ca01_project_neutral_prompt_closure()

    assert result["status"] == "FAIL"
    assert result["checks"]["amended_schema_is_valid_draft_2020_12"] is False
    assert result["summary"]["probe_count"] == 0


def test_closure_fails_closed_for_missing_assets(tmp_path: Path) -> None:
    result = closure.run_p4_ca01_project_neutral_prompt_closure(tmp_path)

    assert result["status"] == "FAIL"
    assert result["admission_gate"] == "BLOCKED"
    assert result["summary"] == {
        "probe_count": 0,
        "passed_probe_count": 0,
        "manifest_entry_count": 0,
        "valid_manifest_entry_count": 0,
    }
    assert result["checks"]["controlled_assets_present"] is False
    assert result["checks"]["amendment_manifest_hashes_valid"] is False


def test_closure_fails_when_frozen_hash_history_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_sha256 = closure._sha256

    def changed_hash(path: Path) -> str:
        if path.name == "execution-trigger-v2.1.schema.json" and "frozen" in path.parts:
            return "0" * 64
        return real_sha256(path)

    monkeypatch.setattr(closure, "_sha256", changed_hash)
    result = closure.run_p4_ca01_project_neutral_prompt_closure()

    assert result["status"] == "FAIL"
    assert result["checks"]["frozen_hash_history_unchanged"] is False


def test_manifest_validation_rejects_empty_or_tampered_manifest(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / closure.MANIFEST
    manifest.parent.mkdir(parents=True)
    manifest.write_text("path,bytes,sha256,role\n", encoding="utf-8")
    rows, valid = closure._manifest_results(tmp_path)
    assert rows == []
    assert valid is False

    asset = tmp_path / "asset.txt"
    asset.write_text("actual", encoding="utf-8")
    manifest.write_text(
        "path,bytes,sha256,role\nasset.txt,6," + "0" * 64 + ",test\n",
        encoding="utf-8",
    )
    rows, valid = closure._manifest_results(tmp_path)
    assert rows[0]["present"] is True
    assert rows[0]["hash_and_size_match"] is False
    assert valid is False


def test_summary_and_main_paths(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    passing = closure.run_p4_ca01_project_neutral_prompt_closure()
    assert closure.summary_line(passing).startswith(
        "p4_ca01_project_neutral_prompt_closure=pass probes=9/9"
    )

    monkeypatch.setattr(
        closure,
        "run_p4_ca01_project_neutral_prompt_closure",
        lambda: passing,
    )
    output = tmp_path / "evidence.json"
    assert closure.main(["--summary", "--output", str(output)]) == 0
    assert "closure=pass" in capsys.readouterr().out
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "PASS"

    failed = {"status": "FAIL", "admission_gate": "BLOCKED", "summary": {}}
    monkeypatch.setattr(
        closure,
        "run_p4_ca01_project_neutral_prompt_closure",
        lambda: failed,
    )
    assert closure.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"


def test_script_entrypoint_exits_successfully(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(closure.sys, "argv", [closure.__file__])
    with pytest.raises(SystemExit) as raised:
        runpy.run_path(str(closure.ROOT / closure.__file__), run_name="__main__")

    assert raised.value.code == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"
