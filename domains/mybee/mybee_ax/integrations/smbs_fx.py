"""One-shot SMBS USD/KRW source admission through the canonical EOS API."""

from __future__ import annotations

import hashlib
import html
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from .finance_inputs import (
    ApprovedFinanceInputBundle,
    EosApiRequest,
    FinanceInputBundleError,
)

SMBS_PROVIDER_ID = "SMBS_TODAY_EXRATE"
SMBS_TODAY_URL = "http://www.smbs.co.kr/ExRate/TodayExRate.jsp"
SMBS_PARSER_PROFILE = "smbs-today-usd-krw.v1"

_SEARCH_DATE = re.compile(
    r"<input\b(?=[^>]*\bid=[\"']searchDate[\"'])[^>]*\bvalue=[\"']"
    r"(?P<value>\d{4}\.\d{2}\.\d{2})[\"'][^>]*>",
    re.IGNORECASE,
)
_TABLE_CAPTION = re.compile(r"<caption>\s*매매기준율표", re.IGNORECASE)
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_ROW = re.compile(r"<tr\b[^>]*>(?P<body>.*?)</tr>", re.IGNORECASE | re.DOTALL)
_CELL = re.compile(r"<td\b[^>]*>(?P<body>.*?)</td>", re.IGNORECASE | re.DOTALL)
_SCRIPT = re.compile(
    r"<script\b[^>]*>(?P<body>.*?)</script>", re.IGNORECASE | re.DOTALL
)
_TAG = re.compile(r"<[^>]+>")
_UNICODE_TOKEN = re.compile(r"%u_(?:[A-Z])?([0-9a-fA-F]{4})")
_BYTE_TOKEN = re.compile(r"%_(?:[A-Z])?([0-9a-fA-F]{2})")
_RATE = re.compile(r"(?<!\d)(\d{1,3}(?:,\d{3})*(?:\.\d+)?)(?!\d)")
_CHARSET = re.compile(rb"charset\s*=\s*[\"']?([A-Za-z0-9_-]+)", re.IGNORECASE)


class SmbsFxAdmissionError(FinanceInputBundleError):
    """Fail-closed source acquisition, parsing, or request construction error."""


@dataclass(frozen=True)
class SmbsSourceDocument:
    raw: bytes
    source_uri: str
    acquisition_mode: str
    transport_security: str
    captured_at: datetime


@dataclass(frozen=True)
class SmbsUsdKrwObservation:
    rate_date: date
    published_rate: Decimal
    quote_unit: Decimal
    source_sha256: str
    source_uri: str
    acquisition_mode: str
    transport_security: str
    captured_at: datetime
    published_at: datetime

    @property
    def source_record_id(self) -> str:
        return f"SMBS:{self.rate_date.isoformat()}:USD:KRW:FINAL"


def load_smbs_source_file(
    path: Path,
    *,
    source_uri: str = SMBS_TODAY_URL,
    captured_at: datetime | None = None,
) -> SmbsSourceDocument:
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise SmbsFxAdmissionError(
            "SMBS_SOURCE_FILE_UNREADABLE", "source file could not be read"
        ) from error
    if not raw:
        raise SmbsFxAdmissionError("SMBS_SOURCE_EMPTY", "source document is empty")
    return SmbsSourceDocument(
        raw=raw,
        source_uri=_source_uri(source_uri),
        acquisition_mode="OPERATOR_SOURCE_FILE",
        transport_security="OPERATOR_ATTESTED_FILE",
        captured_at=_aware_datetime("captured_at", captured_at or datetime.now(UTC)),
    )


def fetch_smbs_source_once(
    *,
    url: str = SMBS_TODAY_URL,
    allow_insecure_http: bool = False,
    raw_output: Path,
    timeout_seconds: float = 20.0,
    captured_at: datetime | None = None,
) -> SmbsSourceDocument:
    normalized_url = _source_uri(url)
    if not allow_insecure_http:
        raise SmbsFxAdmissionError(
            "SMBS_HTTP_NOT_EXPLICITLY_ALLOWED",
            "the source is HTTP-only and requires explicit one-shot admission",
        )
    if timeout_seconds <= 0:
        raise SmbsFxAdmissionError("SMBS_TIMEOUT_INVALID", "timeout must be positive")
    if raw_output.exists() or not raw_output.parent.is_dir():
        raise SmbsFxAdmissionError(
            "SMBS_RAW_OUTPUT_INVALID",
            "raw output must be a new file under an existing directory",
        )
    request = Request(
        normalized_url,
        method="GET",
        headers={"User-Agent": "NeX-Platform-FX-Admission/1.0"},
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            final_url = response.geturl()
            content_type = response.headers.get_content_type()
            raw = response.read(2_000_001)
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        raise SmbsFxAdmissionError(
            "SMBS_SOURCE_UNAVAILABLE", "SMBS source could not be acquired"
        ) from error
    if final_url != normalized_url or content_type != "text/html":
        raise SmbsFxAdmissionError(
            "SMBS_SOURCE_RESPONSE_INVALID", "unexpected redirect or content type"
        )
    if not raw or len(raw) > 2_000_000:
        raise SmbsFxAdmissionError(
            "SMBS_SOURCE_SIZE_INVALID", "source response is empty or too large"
        )
    try:
        raw_output.write_bytes(raw)
    except OSError as error:
        raise SmbsFxAdmissionError(
            "SMBS_RAW_OUTPUT_UNWRITABLE", "raw source evidence could not be written"
        ) from error
    return SmbsSourceDocument(
        raw=raw,
        source_uri=normalized_url,
        acquisition_mode="OPERATOR_INITIATED_HTTP_CAPTURE",
        transport_security="HTTP_UNVERIFIED",
        captured_at=_aware_datetime("captured_at", captured_at or datetime.now(UTC)),
    )


def parse_smbs_usd_krw(
    document: SmbsSourceDocument,
    *,
    published_at: datetime,
) -> SmbsUsdKrwObservation:
    source = _decode_source(document.raw)
    source = _COMMENT.sub("", source)
    search_date = _SEARCH_DATE.search(source)
    if search_date is None:
        raise SmbsFxAdmissionError(
            "SMBS_RATE_DATE_MISSING", "source page does not expose searchDate"
        )
    rate_date = date.fromisoformat(search_date.group("value").replace(".", "-"))
    published_at = _aware_datetime("published_at", published_at)
    if published_at.astimezone(ZoneInfo("Asia/Seoul")).date() < rate_date:
        raise SmbsFxAdmissionError(
            "SMBS_PUBLICATION_TIME_INVALID",
            "published_at cannot precede the displayed Korean rate date",
        )

    caption = _TABLE_CAPTION.search(source)
    if caption is None:
        raise SmbsFxAdmissionError(
            "SMBS_RATE_TABLE_MISSING", "market-base rate table was not found"
        )
    table_start = source.rfind("<table", 0, caption.start())
    table_end = source.find("</table>", caption.end())
    if table_start < 0 or table_end < 0:
        raise SmbsFxAdmissionError(
            "SMBS_RATE_TABLE_INVALID", "market-base rate table is malformed"
        )
    matches: list[Decimal] = []
    for row in _ROW.finditer(source[table_start : table_end + len("</table>")]):
        cells = [
            _visible_cell(match.group("body"))
            for match in _CELL.finditer(row.group("body"))
        ]
        if len(cells) < 2 or "USD" not in cells[0]:
            continue
        rate_match = _RATE.search(cells[1])
        if rate_match is None:
            raise SmbsFxAdmissionError(
                "SMBS_USD_RATE_INVALID", "USD/KRW rate cell is not numeric"
            )
        matches.append(Decimal(rate_match.group(1).replace(",", "")))
    if len(matches) != 1 or matches[0] <= 0:
        raise SmbsFxAdmissionError(
            "SMBS_USD_RATE_AMBIGUOUS", "exactly one positive USD/KRW rate is required"
        )
    return SmbsUsdKrwObservation(
        rate_date=rate_date,
        published_rate=matches[0],
        quote_unit=Decimal(1),
        source_sha256=_sha256_hash_ref(document.raw),
        source_uri=document.source_uri,
        acquisition_mode=document.acquisition_mode,
        transport_security=document.transport_security,
        captured_at=document.captured_at,
        published_at=published_at,
    )


def build_smbs_fx_import_request(
    bundle: ApprovedFinanceInputBundle,
    observation: SmbsUsdKrwObservation,
    *,
    tenant_id: str,
    subject_id: str,
    company_id: str,
    policy_id: str,
    policy_version: int = 1,
) -> EosApiRequest:
    source = bundle.fx_policy["source"]
    if (
        source["provider_id"] != SMBS_PROVIDER_ID
        or source["source_uri"] != observation.source_uri
    ):
        raise SmbsFxAdmissionError(
            "SMBS_SOURCE_POLICY_MISMATCH", "observation does not match approved source"
        )
    if type(policy_version) is not int or policy_version < 1:
        raise SmbsFxAdmissionError(
            "SMBS_POLICY_VERSION_INVALID", "positive integer required"
        )
    tenant_id = _scoped_id("tenant_id", tenant_id)
    subject_id = _scoped_id("subject_id", subject_id)
    company_id = _uuid("company_id", company_id)
    policy_id = _uuid("policy_id", policy_id)
    source_record_id = observation.source_record_id
    snapshot_id = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            ":".join(
                (
                    tenant_id,
                    company_id,
                    policy_id,
                    str(policy_version),
                    source_record_id,
                )
            ),
        )
    )
    payload = {
        "snapshots": [
            {
                "company_id": company_id,
                "rate_snapshot_id": snapshot_id,
                "rate_policy_id": policy_id,
                "rate_policy_version": policy_version,
                "source_provider_id": SMBS_PROVIDER_ID,
                "base_currency": "USD",
                "quote_currency": "KRW",
                "quote_unit": _decimal_text(observation.quote_unit),
                "published_rate": _decimal_text(observation.published_rate),
                "desired_rate_date": observation.rate_date.isoformat(),
                "rate_date": observation.rate_date.isoformat(),
                "rate_as_of": observation.published_at.isoformat(),
                "published_at": observation.published_at.isoformat(),
                "publication_issue": "FINAL",
                "is_final": True,
                "source_record_id": source_record_id,
                "source_uri": observation.source_uri,
                "source_sha256": observation.source_sha256,
                "calendar_ref": source["calendar_ref"],
                "source_timezone": source["source_timezone"],
                "provenance": {
                    "parser_profile": SMBS_PARSER_PROFILE,
                    "acquisition_mode": observation.acquisition_mode,
                    "transport_security": observation.transport_security,
                    "captured_at": observation.captured_at.isoformat(),
                    "displayed_rate_date": observation.rate_date.isoformat(),
                    "raw_source_retained": True,
                    "operator_review_required": True,
                },
            }
        ]
    }
    return EosApiRequest(
        method="POST",
        path=bundle.fx_policy["runtime_boundaries"]["rate_import_endpoint"],
        tenant_id=tenant_id,
        subject_id=subject_id,
        payload=payload,
    )


def _decode_source(raw: bytes) -> str:
    match = _CHARSET.search(raw[:8192])
    encodings = [match.group(1).decode("ascii")] if match is not None else []
    encodings.extend(("euc-kr", "utf-8"))
    for encoding in dict.fromkeys(encodings):
        try:
            return raw.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    raise SmbsFxAdmissionError(
        "SMBS_SOURCE_ENCODING_INVALID", "source encoding is not admitted"
    )


def _visible_cell(value: str) -> str:
    replaced = _SCRIPT.sub(
        lambda match: _decode_script_tokens(match.group("body")), value
    )
    return " ".join(html.unescape(_TAG.sub(" ", replaced)).split())


def _decode_script_tokens(value: str) -> str:
    unicode_text = _UNICODE_TOKEN.sub(lambda match: chr(int(match.group(1), 16)), value)
    decoded = _BYTE_TOKEN.sub(lambda match: chr(int(match.group(1), 16)), unicode_text)
    argument = re.search(r"d[1-5]\(\s*['\"](?P<value>.*?)['\"]\s*\)", decoded)
    return argument.group("value") if argument is not None else ""


def _source_uri(value: str) -> str:
    if value != SMBS_TODAY_URL:
        raise SmbsFxAdmissionError(
            "SMBS_SOURCE_URI_INVALID", "canonical SMBS TodayExRate HTTP URL required"
        )
    return value


def _aware_datetime(field: str, value: datetime) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise SmbsFxAdmissionError(
            f"SMBS_{field.upper()}_INVALID", "timezone-aware datetime required"
        )
    return value


def _uuid(field: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as error:
        raise SmbsFxAdmissionError(
            f"SMBS_{field.upper()}_INVALID", "UUID required"
        ) from error


def _scoped_id(field: str, value: object) -> str:
    normalized = str(value).strip() if value is not None else ""
    if (
        not normalized
        or len(normalized) > 128
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", normalized) is None
    ):
        raise SmbsFxAdmissionError(
            f"SMBS_{field.upper()}_INVALID", "stable scoped identifier required"
        )
    return normalized


def _sha256_hash_ref(raw: bytes) -> str:
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")
