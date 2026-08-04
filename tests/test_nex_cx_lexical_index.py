from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import nex_cx.lexical_index as lexical_index
from nex_cx.chunking import build_and_store_chunk_set, register_chunking_routes
from nex_cx.ingestion import (
    ContentIngestionStore,
    CxStorageConfig,
    build_upload_registration,
    register_ingestion_routes,
    run_text_extraction_job,
)
from nex_cx.lexical_index import (
    LexicalIndexError,
    TokenizerUnavailable,
    build_and_store_lexical_index,
    build_lexical_index,
    build_postings,
    build_tokenizer_profile,
    dictionary_profile_for_tokenizer,
    korean_mixed_v1_tokens,
    ordered_chunk_texts,
    query_terms_for_lexical_index,
    register_lexical_index_routes,
    tokenize_with,
)
from nex_runtime import SERVICE_SPECS, build_service_app, issue_mock_service_token

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
REQUEST_ID = "0189f0ff-8f22-4f72-9b47-b481dc21bb21"


def auth_headers() -> dict[str, str]:
    issued = issue_mock_service_token(service_id="nex-ae-api", audience="nex-cx")
    return {
        "Authorization": f"Bearer {issued.access_token}",
        "X-Request-ID": REQUEST_ID,
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def storage_config(tmp_path: Path, *, tokenizer: str = "mecab_ko") -> CxStorageConfig:
    return CxStorageConfig(
        data_root=tmp_path,
        source_root=tmp_path / "cx" / "source-files",
        extracted_markdown_root=tmp_path / "cx" / "extracted-markdown",
        extraction_temp_root=tmp_path / "cx" / "extraction-temp",
        chunk_policy="chunk_1000_100",
        chunk_size=20,
        chunk_overlap=5,
        bm25_tokenizer=tokenizer,
        bm25_tokenizer_fallback="korean_mixed_v1",
    )


def build_store_with_chunks(
    tmp_path: Path,
    *,
    text: str = "안녕하세요 NeX platform trace trace",
    tokenizer: str = "mecab_ko",
) -> tuple[ContentIngestionStore, CxStorageConfig, dict[str, object]]:
    store = ContentIngestionStore()
    config = storage_config(tmp_path, tokenizer=tokenizer)
    document = build_upload_registration(
        {
            "filename": "source.txt",
            "content_type": "text/plain",
            "content_text": text,
        },
        storage_config=config,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    store.save_upload_registration(document, source_text=text)
    extraction = run_text_extraction_job(
        document["extraction"]["job_id"],
        store=store,
        storage_config=config,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    chunk_set = build_and_store_chunk_set(
        extraction["document_id"],
        store=store,
        storage_config=config,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    return store, config, chunk_set


def build_test_client(tmp_path: Path) -> tuple[TestClient, ContentIngestionStore]:
    app = build_service_app(SERVICE_SPECS["nex-cx"])
    store = ContentIngestionStore()
    config = storage_config(tmp_path)
    register_ingestion_routes(app, store=store, storage_config=config)
    register_chunking_routes(app, store=store, storage_config=config)
    register_lexical_index_routes(app, store=store, storage_config=config)
    return TestClient(app), store


def test_korean_mixed_v1_tokenizer_handles_korean_and_latin() -> None:
    assert korean_mixed_v1_tokens("안녕하세요 NeX-Platform 001!") == [
        "안녕하세요",
        "nex",
        "platform",
        "001",
    ]


def test_tokenize_with_rejects_unknown_tokenizer() -> None:
    with pytest.raises(TokenizerUnavailable):
        tokenize_with("unknown", "hello")


def test_tokenize_with_uses_mecab_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lexical_index, "_mecab_ko_tokens", lambda text: ["mecab", text])

    assert tokenize_with("mecab_ko", "토큰") == ["mecab", "토큰"]


def test_dictionary_profile_identifies_supported_tokenizers() -> None:
    assert dictionary_profile_for_tokenizer("mecab_ko") == "mecab-ko-dic"
    assert (
        dictionary_profile_for_tokenizer("korean_mixed_v1")
        == "none_regex_korean_mixed_v1"
    )
    assert dictionary_profile_for_tokenizer("unknown") == "unknown"


def test_build_tokenizer_profile_records_dictionary_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MECAB_DICDIR", "/opt/mecab/dic")

    profile = build_tokenizer_profile(
        tokenizer_requested="mecab_ko",
        tokenizer_used="mecab_ko",
        tokenizer_fallback="korean_mixed_v1",
        fallback_used=False,
    )

    assert profile["query_tokenizer_policy"] == "match_index_tokenizer_with_fallback"
    assert profile["dictionary_profile"] == "mecab-ko-dic"
    assert profile["dictionary_path_env"] == "MECAB_DICDIR"
    assert profile["dictionary_path_configured"] is True


def test_mecab_ko_tokens_parses_fake_mecab_output(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeTagger:
        def parse(self, text: str) -> str:
            return "NeX\tNNP\n플랫폼\tNNG\nEOS\n"

    class FakeMeCab:
        Tagger = FakeTagger

    monkeypatch.setitem(sys.modules, "MeCab", FakeMeCab)

    assert lexical_index._mecab_ko_tokens("NeX 플랫폼") == ["nex", "플랫폼"]


def test_mecab_ko_tokens_handles_empty_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeTagger:
        def parse(self, text: str) -> str:
            return ""

    class FakeMeCab:
        Tagger = FakeTagger

    monkeypatch.setitem(sys.modules, "MeCab", FakeMeCab)

    assert lexical_index._mecab_ko_tokens("") == []


def test_mecab_ko_tokens_skips_empty_terms(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeTagger:
        def parse(self, text: str) -> str:
            return "\tUNKNOWN\nNeX\tNNP\nEOS\n"

    class FakeMeCab:
        Tagger = FakeTagger

    monkeypatch.setitem(sys.modules, "MeCab", FakeMeCab)

    assert lexical_index._mecab_ko_tokens("NeX") == ["nex"]


def test_build_postings_counts_terms_per_chunk() -> None:
    postings = build_postings(
        [
            ({"chunk_id": "chunk-1", "ordinal": 0}, ["trace", "trace", "cx"]),
            ({"chunk_id": "chunk-2", "ordinal": 1}, ["trace"]),
        ]
    )

    assert postings == [
        {
            "term": "cx",
            "document_frequency": 1,
            "occurrences": [{"chunk_id": "chunk-1", "ordinal": 0, "count": 1}],
        },
        {
            "term": "trace",
            "document_frequency": 2,
            "occurrences": [
                {"chunk_id": "chunk-1", "ordinal": 0, "count": 2},
                {"chunk_id": "chunk-2", "ordinal": 1, "count": 1},
            ],
        },
    ]


def test_build_lexical_index_uses_requested_tokenizer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _, chunk_set = build_store_with_chunks(tmp_path)
    monkeypatch.delenv("MECAB_DICDIR", raising=False)
    monkeypatch.setattr(lexical_index, "_mecab_ko_tokens", lambda text: ["mecab", "trace"])

    record = build_lexical_index(
        document_id=chunk_set["document_id"],
        chunk_set=chunk_set,
        chunk_texts=ordered_chunk_texts(chunk_set, store),
        tokenizer_requested="mecab_ko",
        tokenizer_fallback="korean_mixed_v1",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert record["tokenizer_used"] == "mecab_ko"
    assert record["fallback_used"] is False
    assert record["tokenizer_profile"] == {
        "bm25_tokenizer_requested": "mecab_ko",
        "bm25_tokenizer": "mecab_ko",
        "bm25_tokenizer_fallback": "korean_mixed_v1",
        "fallback_used": False,
        "query_tokenizer_policy": "match_index_tokenizer_with_fallback",
        "dictionary_profile": "mecab-ko-dic",
        "dictionary_path_env": "MECAB_DICDIR",
        "dictionary_path_configured": False,
    }
    assert record["unique_token_count"] == 2


def test_build_lexical_index_falls_back_when_mecab_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _, chunk_set = build_store_with_chunks(tmp_path)

    def fail_mecab(text: str) -> list[str]:
        raise TokenizerUnavailable("missing")

    monkeypatch.setattr(lexical_index, "_mecab_ko_tokens", fail_mecab)

    record = build_lexical_index(
        document_id=chunk_set["document_id"],
        chunk_set=chunk_set,
        chunk_texts=ordered_chunk_texts(chunk_set, store),
        tokenizer_requested="mecab_ko",
        tokenizer_fallback="korean_mixed_v1",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert record["tokenizer_used"] == "korean_mixed_v1"
    assert record["fallback_used"] is True
    assert record["tokenizer_profile"]["dictionary_profile"] == (
        "none_regex_korean_mixed_v1"
    )
    assert record["tokenizer_profile"]["query_tokenizer_policy"] == (
        "match_index_tokenizer_with_fallback"
    )
    assert any(posting["term"] == "trace" for posting in record["postings"])


def test_query_terms_for_lexical_index_uses_recorded_tokenizer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lexical_index, "_mecab_ko_tokens", lambda text: ["mecab", text])

    terms = query_terms_for_lexical_index(
        {
            "tokenizer_used": "mecab_ko",
            "tokenizer_fallback": "korean_mixed_v1",
        },
        "질의",
    )

    assert terms == {"mecab", "질의"}


def test_query_terms_for_lexical_index_falls_back_to_index_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_mecab(text: str) -> list[str]:
        raise TokenizerUnavailable("missing")

    monkeypatch.setattr(lexical_index, "_mecab_ko_tokens", fail_mecab)

    terms = query_terms_for_lexical_index(
        {
            "tokenizer_used": "mecab_ko",
            "tokenizer_fallback": "korean_mixed_v1",
        },
        "NeX trace",
    )

    assert terms == {"nex", "trace"}


def test_query_terms_for_lexical_index_falls_back_to_builtin_default() -> None:
    terms = query_terms_for_lexical_index(
        {
            "tokenizer_used": "unsupported",
            "tokenizer_fallback": "also_unsupported",
        },
        "NeX trace",
    )

    assert terms == {"nex", "trace"}


def test_query_terms_for_lexical_index_defaults_missing_tokenizer_names() -> None:
    terms = query_terms_for_lexical_index({}, "NeX trace")

    assert terms == {"nex", "trace"}


def test_build_lexical_index_reports_no_available_tokenizer(tmp_path: Path) -> None:
    store, _, chunk_set = build_store_with_chunks(tmp_path)

    with pytest.raises(LexicalIndexError) as exc:
        build_lexical_index(
            document_id=chunk_set["document_id"],
            chunk_set=chunk_set,
            chunk_texts=ordered_chunk_texts(chunk_set, store),
            tokenizer_requested="unknown",
            tokenizer_fallback="also_unknown",
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert exc.value.status_code == 500
    assert exc.value.error_code == "cx.tokenizer_unavailable"


def test_ordered_chunk_texts_reports_missing_private_text(tmp_path: Path) -> None:
    store, _, chunk_set = build_store_with_chunks(tmp_path)
    store.chunk_texts.clear()

    with pytest.raises(LexicalIndexError) as exc:
        ordered_chunk_texts(chunk_set, store)

    assert exc.value.status_code == 409
    assert exc.value.error_code == "cx.chunk_text_unavailable"
    assert exc.value.retryable is True


def test_build_and_store_lexical_index_saves_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, config, chunk_set = build_store_with_chunks(tmp_path)

    def fail_mecab(text: str) -> list[str]:
        raise TokenizerUnavailable("missing")

    monkeypatch.setattr(lexical_index, "_mecab_ko_tokens", fail_mecab)

    record = build_and_store_lexical_index(
        chunk_set["document_id"],
        store=store,
        storage_config=config,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    assert record["lexical_index_schema_version"] == "cx_lexical_index.v1"
    assert store.get_lexical_index(chunk_set["document_id"]) == record


def test_build_and_store_lexical_index_reports_missing_chunk_set(tmp_path: Path) -> None:
    with pytest.raises(LexicalIndexError) as exc:
        build_and_store_lexical_index(
            "missing-doc",
            store=ContentIngestionStore(),
            storage_config=storage_config(tmp_path),
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert exc.value.error_code == "cx.chunk_set_not_found"


def test_lexical_index_endpoint_requires_service_claim(tmp_path: Path) -> None:
    client, _ = build_test_client(tmp_path)

    response = client.post("/api/v1/documents/missing/lexical-index/run")

    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"


def test_lexical_index_read_requires_service_claim(tmp_path: Path) -> None:
    client, _ = build_test_client(tmp_path)

    response = client.get("/api/v1/documents/missing/lexical-index")

    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTHORIZATION_HEADER_MISSING"


def test_lexical_index_endpoint_materializes_and_reads_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_mecab(text: str) -> list[str]:
        raise TokenizerUnavailable("missing")

    monkeypatch.setattr(lexical_index, "_mecab_ko_tokens", fail_mecab)
    client, _ = build_test_client(tmp_path)
    created = client.post(
        "/api/v1/documents/uploads",
        json={
            "filename": "source.txt",
            "content_type": "text/plain",
            "content_text": "안녕하세요 NeX platform trace",
        },
        headers=auth_headers(),
    ).json()
    client.post(f"/api/v1/jobs/{created['extraction']['job_id']}/run", headers=auth_headers())
    client.post(f"/api/v1/documents/{created['document_id']}/chunks/run", headers=auth_headers())

    run_response = client.post(
        f"/api/v1/documents/{created['document_id']}/lexical-index/run",
        headers=auth_headers(),
    )
    read_response = client.get(
        f"/api/v1/documents/{created['document_id']}/lexical-index",
        headers=auth_headers(),
    )

    assert run_response.status_code == 200
    payload = run_response.json()
    assert payload["fallback_used"] is True
    assert payload["tokenizer_used"] == "korean_mixed_v1"
    assert any(posting["term"] == "trace" for posting in payload["postings"])
    assert read_response.status_code == 200
    assert read_response.json()["unique_token_count"] == payload["unique_token_count"]


def test_lexical_index_endpoint_reports_missing_chunk_set(tmp_path: Path) -> None:
    client, _ = build_test_client(tmp_path)

    response = client.post(
        "/api/v1/documents/missing/lexical-index/run",
        headers=auth_headers(),
    )

    assert response.status_code == 404
    assert response.json()["error_code"] == "cx.chunk_set_not_found"


def test_lexical_index_read_reports_not_found(tmp_path: Path) -> None:
    client, _ = build_test_client(tmp_path)

    response = client.get(
        "/api/v1/documents/missing/lexical-index",
        headers=auth_headers(),
    )

    assert response.status_code == 404
    assert response.json()["error_code"] == "cx.lexical_index_not_found"
