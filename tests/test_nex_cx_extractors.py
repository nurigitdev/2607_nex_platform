from __future__ import annotations

import pytest

from nex_cx.extractors import (
    ExtractionAdapterError,
    ExtractorInput,
    LocalMockTextExtractor,
    classify_source_format,
    decode_utf8_source,
    markdown_from_source_text,
    mock_binary_document_markdown,
)
from nex_cx.ingestion import sha256_bytes


def source(
    *,
    filename: str,
    content_type: str,
    body: bytes,
) -> ExtractorInput:
    return ExtractorInput(
        filename=filename,
        content_type=content_type,
        source_bytes=body,
        source_sha256=sha256_bytes(body),
    )


@pytest.mark.parametrize(
    ("filename", "content_type", "expected"),
    [
        ("source.md", "application/octet-stream", "markdown"),
        ("source.txt", "application/octet-stream", "plain_text"),
        ("source.csv", "text/csv; charset=utf-8", "plain_text"),
        ("source.pdf", "application/octet-stream", "pdf"),
        ("source.docx", "application/octet-stream", "docx"),
        ("source.pptx", "application/octet-stream", "pptx"),
        ("source.xlsx", "application/octet-stream", "xlsx"),
        ("source.bin", "application/octet-stream", "unsupported"),
    ],
)
def test_classify_source_format_uses_content_type_and_extension(
    filename: str,
    content_type: str,
    expected: str,
) -> None:
    assert classify_source_format(filename=filename, content_type=content_type) == expected


def test_local_mock_extractor_preserves_markdown() -> None:
    output = LocalMockTextExtractor().extract_markdown(
        source(
            filename="source.md",
            content_type="text/markdown",
            body=b"# Existing\n\nBody",
        )
    )

    assert output.markdown_text == "# Existing\n\nBody\n"
    assert output.mode == "markdown_to_markdown"
    assert output.source_format == "markdown"
    assert output.warnings == []


def test_local_mock_extractor_wraps_plain_text() -> None:
    output = LocalMockTextExtractor().extract_markdown(
        source(
            filename="source.txt",
            content_type="text/plain",
            body=b"Plain source",
        )
    )

    assert output.markdown_text == "# source.txt\n\nPlain source\n"
    assert output.mode == "plain_text_to_markdown"
    assert output.version == "slice-0072"


def test_local_mock_extractor_marks_binary_document_placeholder() -> None:
    output = LocalMockTextExtractor().extract_markdown(
        source(
            filename="source.pdf",
            content_type="application/pdf",
            body=b"%PDF-1.7\nprivate bytes",
        )
    )

    assert output.markdown_text == (
        "# source.pdf\n\n"
        "Mock extraction placeholder.\n\n"
        "- source_format: pdf\n"
        "- content_type: application/pdf\n"
    )
    assert output.mode == "binary_document_placeholder_to_markdown"
    assert output.warnings == ["mock_binary_extraction_placeholder:pdf"]
    assert "private bytes" not in output.markdown_text


def test_local_mock_extractor_rejects_unsupported_source_type() -> None:
    with pytest.raises(ExtractionAdapterError) as exc:
        LocalMockTextExtractor().extract_markdown(
            source(
                filename="source.bin",
                content_type="application/octet-stream",
                body=b"\x00\x01",
            )
        )

    assert exc.value.status_code == 415
    assert exc.value.error_code == "cx.extractor_source_type_unsupported"


def test_decode_utf8_source_rejects_non_utf8_text() -> None:
    with pytest.raises(ExtractionAdapterError) as exc:
        decode_utf8_source(b"\xff\xfe")

    assert exc.value.error_code == "cx.extractor_source_encoding_unsupported"


def test_markdown_helpers_are_deterministic() -> None:
    assert markdown_from_source_text("  ", filename="empty.md", content_type="text/markdown") == (
        "# empty.md\n\n"
    )
    assert mock_binary_document_markdown(
        filename="deck.pptx",
        content_type=(
            "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        ),
        source_format="pptx",
    ).startswith("# deck.pptx\n\nMock extraction placeholder.")
