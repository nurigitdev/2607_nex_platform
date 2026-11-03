from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import run_gb2_s20qk_embedding_revision_ab as smoke
from test_nex_cx_retrieval_embedding_revision_ab import (
    REVISION_A,
    REVISION_B,
    _artifact,
    _profile,
    _source,
)


def _write(path: Path, value: object) -> str:
    text = f"{json.dumps(value, indent=2, sort_keys=True)}\n"
    path.write_text(text, encoding="utf-8")
    return smoke._text_hash(text)


def _requester(method: str, url: str, **kwargs: object) -> httpx.Response:
    assert method == "POST"
    assert url == "http://embedding.example/v1/embeddings"
    assert kwargs["json"] == {
        "model": "embedding-a",
        "input": [
            "프로젝트 비용 전표의 승인 근거를 조회한다.",
            "사내 식당의 오늘 메뉴를 조회한다.",
        ],
    }
    return httpx.Response(
        200,
        json={
            "object": "list",
            "data": [
                {"index": 0, "embedding": [0.1, 0.2]},
                {"index": 1, "embedding": [0.3, 0.4]},
            ],
        },
    )


def _profile_env(tmp_path: Path, *, slot: str = "A") -> dict[str, str]:
    revision = REVISION_A if slot == "A" else REVISION_B
    model = f"embedding-{slot.lower()}"
    source_path = tmp_path / f"source-{slot}.json"
    artifact_path = tmp_path / f"artifact-{slot}.json"
    _write(source_path, _source(revision))
    _write(artifact_path, _artifact(revision))
    return {
        smoke.SMOKE_ENV: "1",
        smoke.MODE_ENV: "PROFILE",
        smoke.SLOT_ENV: slot,
        smoke.SOURCE_PATH_ENV: str(source_path),
        smoke.ARTIFACT_PATH_ENV: str(artifact_path),
        "NEX_MO_REMOTE_EMBEDDING_URL": (
            "http://embedding.example/v1/embeddings"
        ),
        "NEX_MO_REMOTE_EMBEDDING_REQUEST_SHAPE": "openai_embeddings",
        "NEX_MO_REMOTE_EMBEDDING_MODEL": model,
        "NEX_MO_REMOTE_EMBEDDING_MODEL_REVISION": revision,
        "NEX_MO_REMOTE_EMBEDDING_DEPLOYMENT_ID": f"deployment-{model}",
        "NEX_MO_REMOTE_EMBEDDING_API_KEY": "test-only-key",
        "NEX_MO_REMOTE_EMBEDDING_RETRY_MAX_ATTEMPTS": "1",
    }


def test_skip_profile_and_compare_modes(tmp_path: Path) -> None:
    skipped = smoke.run_gb2_s20qk_embedding_revision_ab({})
    assert skipped["status"] == "SKIPPED"
    assert "=skipped" in smoke.summary_line(skipped)

    env = _profile_env(tmp_path)
    profile_result = smoke.run_gb2_s20qk_embedding_revision_ab(
        env,
        requester=_requester,
    )
    assert profile_result["status"] == "PASS"
    assert profile_result["result"]["slot"] == "A"
    assert profile_result["result"]["embedding_binding"]["vector_dimension"] == 2
    assert "dimension=2" in smoke.summary_line(profile_result)
    assert "test-only-key" not in json.dumps(profile_result)
    assert "data" not in profile_result["result"]
    assert "embedding" not in profile_result["result"]["evidence"]

    profile_a = tmp_path / "profile-a.json"
    profile_b = tmp_path / "profile-b.json"
    _write(
        profile_a,
        {
            "evidence_schema_version": smoke.SCHEMA_VERSION,
            "status": "PASS",
            "mode": "PROFILE",
            "result": _profile(
                "A", revision=REVISION_A, model="embedding-a", dimension=2560
            ),
        },
    )
    _write(
        profile_b,
        {
            "evidence_schema_version": smoke.SCHEMA_VERSION,
            "status": "PASS",
            "mode": "PROFILE",
            "result": _profile(
                "B", revision=REVISION_B, model="embedding-b", dimension=4096
            ),
        },
    )
    compared = smoke.run_gb2_s20qk_embedding_revision_ab(
        {
            smoke.SMOKE_ENV: "1",
            smoke.MODE_ENV: "COMPARE",
            smoke.PROFILE_A_PATH_ENV: str(profile_a),
            smoke.PROFILE_B_PATH_ENV: str(profile_b),
        }
    )
    assert compared["status"] == "PASS"
    assert compared["result"]["decision"]["status"] == "NO_ADMISSIBLE_REVISION"
    assert "mode=compare" in smoke.summary_line(compared)


def test_invalid_mode_paths_json_profile_and_provider_fail_closed(
    tmp_path: Path,
) -> None:
    invalid = smoke.run_gb2_s20qk_embedding_revision_ab(
        {smoke.SMOKE_ENV: "1", smoke.MODE_ENV: "OTHER"}
    )
    assert invalid["failure_code"] == "S20QK_MODE_INVALID"

    missing = smoke.run_gb2_s20qk_embedding_revision_ab(
        {smoke.SMOKE_ENV: "1", smoke.MODE_ENV: "PROFILE"}
    )
    assert missing["failure_code"].endswith("_REQUIRED")

    malformed = tmp_path / "malformed.json"
    malformed.write_text("[]", encoding="utf-8")
    failed = smoke.run_gb2_s20qk_embedding_revision_ab(
        {
            smoke.SMOKE_ENV: "1",
            smoke.MODE_ENV: "COMPARE",
            smoke.PROFILE_A_PATH_ENV: str(malformed),
            smoke.PROFILE_B_PATH_ENV: str(malformed),
        }
    )
    assert failed["status"] == "FAIL"
    assert failed["detail"] == "TypeError"

    env = _profile_env(tmp_path)
    env.pop("NEX_MO_REMOTE_EMBEDDING_URL")
    unconfigured = smoke.run_gb2_s20qk_embedding_revision_ab(env)
    assert unconfigured["failure_code"] == "S20QK_EMBEDDING_PROVIDER_NOT_CONFIGURED"

    def rejected(*_args: object, **_kwargs: object) -> httpx.Response:
        return httpx.Response(401, json={"detail": "denied"})

    provider_failed = smoke.run_gb2_s20qk_embedding_revision_ab(
        _profile_env(tmp_path), requester=rejected
    )
    assert provider_failed["status"] == "FAIL"
    assert provider_failed["detail"] in {"ProviderRouteError", "HTTPStatusError"}


@pytest.mark.parametrize(
    "response,error_code",
    [
        ({"data": []}, "S20QK_EMBEDDING_RESPONSE_INVALID"),
        ({"data": ["bad", "bad"]}, "S20QK_EMBEDDING_RESPONSE_INVALID"),
        (
            {
                "data": [
                    {"index": True, "embedding": [0.1]},
                    {"index": 1, "embedding": [0.2]},
                ]
            },
            "S20QK_EMBEDDING_RESPONSE_INVALID",
        ),
        (
            {
                "data": [
                    {"index": 0, "embedding": []},
                    {"index": 1, "embedding": [0.2]},
                ]
            },
            "S20QK_EMBEDDING_RESPONSE_INVALID",
        ),
    ],
)
def test_probe_rejects_malformed_normalized_response(
    monkeypatch, response: dict, error_code: str
) -> None:
    monkeypatch.setattr(smoke, "execute_remote_embedding_request", lambda *_a, **_k: response)
    with pytest.raises(smoke.EmbeddingRevisionABError, match=error_code):
        smoke._probe_embedding(
            {
                "NEX_MO_REMOTE_EMBEDDING_URL": "http://embedding.example",
                "NEX_MO_REMOTE_EMBEDDING_MODEL": "embedding-a",
            },
            requester=None,
        )


def test_probe_projects_nonfinite_and_inconsistent_dimension(monkeypatch) -> None:
    monkeypatch.setattr(
        smoke,
        "execute_remote_embedding_request",
        lambda *_a, **_k: {
            "model_revision": REVISION_A,
            "deployment_id": "deployment-embedding-a",
            "data": [
                {"index": 0, "embedding": [float("nan"), 0.1]},
                {"index": 1, "embedding": [0.2]},
            ],
        },
    )
    projected = smoke._probe_embedding(
        {
            "NEX_MO_REMOTE_EMBEDDING_URL": "http://embedding.example",
            "NEX_MO_REMOTE_EMBEDDING_MODEL": "embedding-a",
            "NEX_MO_REMOTE_EMBEDDING_MODEL_REVISION": REVISION_A,
            "NEX_MO_REMOTE_EMBEDDING_DEPLOYMENT_ID": "deployment-embedding-a",
        },
        requester=None,
    )
    assert projected["finite_vectors"] is False
    assert projected["consistent_dimension"] is False
    assert "data" not in projected


def test_profile_payload_redaction_helpers_summary_and_main(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    raw = {"profile_schema_version": "raw"}
    assert smoke._profile_payload(raw) is raw
    with pytest.raises(smoke.EmbeddingRevisionABError, match="NOT_ADMITTED"):
        smoke._profile_payload(
            {
                "evidence_schema_version": smoke.SCHEMA_VERSION,
                "status": "FAIL",
                "mode": "PROFILE",
                "result": {},
            }
        )
    with pytest.raises(ValueError, match="protected"):
        smoke._assert_redacted(
            {"leak": "private-key"},
            {"NEX_MO_REMOTE_EMBEDDING_API_KEY": "private-key"},
        )
    assert smoke.summary_line({}).endswith("error=unknown")
    assert "decision=unknown" in smoke.summary_line(
        {"status": "PASS", "mode": "COMPARE", "result": []}
    )
    assert "decision=unknown" in smoke.summary_line(
        {"status": "PASS", "mode": "PROFILE", "result": {"slot": "A"}}
    )

    captured: dict[str, str] = {}
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qk_embedding_revision_ab",
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
                "--artifact",
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
    assert captured[smoke.ARTIFACT_PATH_ENV] == str(output)

    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qk_embedding_revision_ab",
        lambda _env: {"status": "FAIL", "failure_code": "blocked"},
    )
    assert smoke.main([]) == 1
