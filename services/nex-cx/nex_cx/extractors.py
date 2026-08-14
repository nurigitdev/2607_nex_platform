from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Protocol


MARKDOWN_CONTENT_TYPES = {"text/markdown", "text/x-markdown"}
PLAIN_TEXT_CONTENT_TYPES = {
    "application/json",
    "application/xml",
    "text/csv",
    "text/plain",
}
BINARY_DOCUMENT_CONTENT_TYPES = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
}
BINARY_DOCUMENT_EXTENSIONS = {
    ".docx": "docx",
    ".pdf": "pdf",
    ".pptx": "pptx",
    ".xlsx": "xlsx",
}
MARKDOWN_EXTENSIONS = {".markdown", ".md"}
PLAIN_TEXT_EXTENSIONS = {".csv", ".json", ".log", ".txt", ".xml"}
TEXT_SOURCE_FORMATS = ("markdown", "plain_text")
BINARY_SOURCE_FORMATS = ("pdf", "docx", "pptx", "xlsx")
SOURCE_FORMATS = (*TEXT_SOURCE_FORMATS, *BINARY_SOURCE_FORMATS)
PDF_EXTRACTION_MODE = "pdf_to_markdown"
PLACEHOLDER_BINARY_MODE = "binary_document_placeholder_to_markdown"
PLACEHOLDER_BINARY_WARNING_PREFIX = "mock_binary_extraction_placeholder"


@dataclass(frozen=True)
class ExtractorInput:
    filename: str
    content_type: str
    source_bytes: bytes
    source_sha256: str


@dataclass(frozen=True)
class ExtractorOutput:
    markdown_text: str
    provider: str
    mode: str
    version: str
    source_format: str
    warnings: list[str]


@dataclass(frozen=True)
class ExtractorBackendCapability:
    source_format: str
    current_backend: str
    current_version: str
    current_mode: str
    status: str
    real_extraction: bool
    content_types: tuple[str, ...]
    extensions: tuple[str, ...]
    warning: str | None
    next_slice: str | None


@dataclass(frozen=True)
class ExtractionAdapterError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False


class TextExtractor(Protocol):
    def extract_markdown(self, source: ExtractorInput) -> ExtractorOutput:
        ...


@dataclass(frozen=True)
class LocalMockTextExtractor:
    provider: str = "local_mock"
    version: str = "slice-0072"

    def extract_markdown(self, source: ExtractorInput) -> ExtractorOutput:
        source_format = classify_source_format(
            filename=source.filename,
            content_type=source.content_type,
        )
        if source_format in TEXT_SOURCE_FORMATS:
            source_text = decode_utf8_source(source.source_bytes)
            return ExtractorOutput(
                markdown_text=markdown_from_source_text(
                    source_text,
                    filename=source.filename,
                    content_type=source.content_type,
                ),
                provider=self.provider,
                mode=f"{source_format}_to_markdown",
                version=self.version,
                source_format=source_format,
                warnings=[],
            )
        if source_format == "pdf":
            return extract_pdf_markdown(source, provider=self.provider, version=self.version)
        if source_format in BINARY_SOURCE_FORMATS:
            return ExtractorOutput(
                markdown_text=mock_binary_document_markdown(
                    filename=source.filename,
                    content_type=source.content_type,
                    source_format=source_format,
                ),
                provider=self.provider,
                mode=PLACEHOLDER_BINARY_MODE,
                version=self.version,
                source_format=source_format,
                warnings=[f"{PLACEHOLDER_BINARY_WARNING_PREFIX}:{source_format}"],
            )
        raise ExtractionAdapterError(
            status_code=415,
            error_code="cx.extractor_source_type_unsupported",
            detail=f"No extractor is registered for source type: {source.content_type}",
        )


def classify_source_format(*, filename: str, content_type: str) -> str:
    normalized_content_type = content_type.split(";", maxsplit=1)[0].strip().lower()
    suffix = Path(filename).suffix.lower()
    if normalized_content_type in MARKDOWN_CONTENT_TYPES or suffix in MARKDOWN_EXTENSIONS:
        return "markdown"
    if (
        normalized_content_type in PLAIN_TEXT_CONTENT_TYPES
        or normalized_content_type.startswith("text/")
        or suffix in PLAIN_TEXT_EXTENSIONS
    ):
        return "plain_text"
    if normalized_content_type in BINARY_DOCUMENT_CONTENT_TYPES:
        return BINARY_DOCUMENT_CONTENT_TYPES[normalized_content_type]
    if suffix in BINARY_DOCUMENT_EXTENSIONS:
        return BINARY_DOCUMENT_EXTENSIONS[suffix]
    return "unsupported"


def extractor_backend_catalog(
    *,
    provider: str = "local_mock",
    version: str = "slice-0072",
) -> tuple[ExtractorBackendCapability, ...]:
    return (
        ExtractorBackendCapability(
            source_format="markdown",
            current_backend=provider,
            current_version=version,
            current_mode="markdown_to_markdown",
            status="implemented",
            real_extraction=True,
            content_types=tuple(sorted(MARKDOWN_CONTENT_TYPES)),
            extensions=tuple(sorted(MARKDOWN_EXTENSIONS)),
            warning=None,
            next_slice=None,
        ),
        ExtractorBackendCapability(
            source_format="plain_text",
            current_backend=provider,
            current_version=version,
            current_mode="plain_text_to_markdown",
            status="implemented",
            real_extraction=True,
            content_types=tuple(sorted(PLAIN_TEXT_CONTENT_TYPES)),
            extensions=tuple(sorted(PLAIN_TEXT_EXTENSIONS)),
            warning=None,
            next_slice=None,
        ),
        *(
            binary_extractor_capability(
                source_format,
                provider=provider,
                version=version,
            )
            for source_format in BINARY_SOURCE_FORMATS
        ),
    )


def extractor_backend_gap_summary(
    catalog: tuple[ExtractorBackendCapability, ...] | None = None,
) -> dict[str, object]:
    capabilities = catalog if catalog is not None else extractor_backend_catalog()
    implemented = [item for item in capabilities if item.real_extraction]
    gaps = [item for item in capabilities if not item.real_extraction]
    return {
        "schema_version": "cx_extractor_backend_gap_summary.v1",
        "source_format_count": len(capabilities),
        "implemented_real_extraction_count": len(implemented),
        "gap_placeholder_count": len(gaps),
        "gap_source_formats": [item.source_format for item in gaps],
        "next_slices": [
            item.next_slice for item in gaps if item.next_slice is not None
        ],
    }


def content_types_for_source_format(source_format: str) -> tuple[str, ...]:
    if source_format == "markdown":
        return tuple(sorted(MARKDOWN_CONTENT_TYPES))
    if source_format == "plain_text":
        return tuple(sorted(PLAIN_TEXT_CONTENT_TYPES))
    return tuple(
        sorted(
            content_type
            for content_type, mapped_format in BINARY_DOCUMENT_CONTENT_TYPES.items()
            if mapped_format == source_format
        )
    )


def extensions_for_source_format(source_format: str) -> tuple[str, ...]:
    if source_format == "markdown":
        return tuple(sorted(MARKDOWN_EXTENSIONS))
    if source_format == "plain_text":
        return tuple(sorted(PLAIN_TEXT_EXTENSIONS))
    return tuple(
        sorted(
            extension
            for extension, mapped_format in BINARY_DOCUMENT_EXTENSIONS.items()
            if mapped_format == source_format
        )
    )


def next_slice_for_binary_source_format(source_format: str) -> str:
    if source_format == "pdf":
        return "Slice 0285"
    if source_format == "docx":
        return "Slice 0286"
    return "Slice 0287"


def binary_extractor_capability(
    source_format: str,
    *,
    provider: str,
    version: str,
) -> ExtractorBackendCapability:
    if source_format == "pdf":
        return ExtractorBackendCapability(
            source_format=source_format,
            current_backend=provider,
            current_version=version,
            current_mode=PDF_EXTRACTION_MODE,
            status="implemented",
            real_extraction=True,
            content_types=content_types_for_source_format(source_format),
            extensions=extensions_for_source_format(source_format),
            warning=None,
            next_slice=None,
        )
    return ExtractorBackendCapability(
        source_format=source_format,
        current_backend=provider,
        current_version=version,
        current_mode=PLACEHOLDER_BINARY_MODE,
        status="gap_placeholder",
        real_extraction=False,
        content_types=content_types_for_source_format(source_format),
        extensions=extensions_for_source_format(source_format),
        warning=f"{PLACEHOLDER_BINARY_WARNING_PREFIX}:{source_format}",
        next_slice=next_slice_for_binary_source_format(source_format),
    )


def decode_utf8_source(source_bytes: bytes) -> str:
    try:
        return source_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ExtractionAdapterError(
            status_code=415,
            error_code="cx.extractor_source_encoding_unsupported",
            detail="Text source bytes must be UTF-8 encoded.",
        ) from exc


def markdown_from_source_text(
    source_text: str,
    *,
    filename: str,
    content_type: str,
) -> str:
    stripped = source_text.strip()
    if not stripped:
        return f"# {filename}\n\n"
    if filename.lower().endswith(".md") or content_type == "text/markdown":
        return _ensure_trailing_newline(stripped)
    return _ensure_trailing_newline(f"# {filename}\n\n{stripped}")


def mock_binary_document_markdown(
    *,
    filename: str,
    content_type: str,
    source_format: str,
) -> str:
    return (
        f"# {filename}\n\n"
        "Mock extraction placeholder.\n\n"
        f"- source_format: {source_format}\n"
        f"- content_type: {content_type}\n"
    )


def extract_pdf_markdown(
    source: ExtractorInput,
    *,
    provider: str,
    version: str,
) -> ExtractorOutput:
    try:
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(source.source_bytes))
    except Exception as exc:
        raise ExtractionAdapterError(
            status_code=422,
            error_code="cx.extractor_pdf_parse_failed",
            detail="PDF source could not be parsed.",
        ) from exc

    page_sections: list[str] = []
    warnings: list[str] = []
    for page_number, page in enumerate(reader.pages, start=1):
        try:
            page_text = page.extract_text() or ""
        except Exception as exc:
            raise ExtractionAdapterError(
                status_code=422,
                error_code="cx.extractor_pdf_page_text_failed",
                detail=f"PDF page text extraction failed: page {page_number}.",
            ) from exc
        normalized = page_text.strip()
        if not normalized:
            warnings.append(f"pdf_page_text_empty:{page_number}")
            continue
        page_sections.append(f"## Page {page_number}\n\n{normalized}")
    if not page_sections:
        raise ExtractionAdapterError(
            status_code=422,
            error_code="cx.extractor_pdf_text_unavailable",
            detail="PDF source did not contain extractable text.",
        )
    return ExtractorOutput(
        markdown_text=_ensure_trailing_newline(
            f"# {source.filename}\n\n" + "\n\n".join(page_sections)
        ),
        provider=provider,
        mode=PDF_EXTRACTION_MODE,
        version=version,
        source_format="pdf",
        warnings=warnings,
    )


def _ensure_trailing_newline(value: str) -> str:
    if value.endswith("\n"):
        return value
    return f"{value}\n"
