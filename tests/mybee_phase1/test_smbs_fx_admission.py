from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import URLError

import pytest
from mybee_ax.integrations.finance_inputs import load_approved_finance_input_bundle
from mybee_ax.integrations.smbs_fx import (
    SMBS_TODAY_URL,
    SmbsFxAdmissionError,
    SmbsSourceDocument,
    build_smbs_fx_import_request,
    fetch_smbs_source_once,
    load_smbs_source_file,
    parse_smbs_usd_krw,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/smbs_today_usd_krw_20261111.html"
TENANT_ID = "tenant-mybee"
SUBJECT_ID = "finance-owner"
COMPANY_ID = "81000000-0000-4000-8000-000000000001"
POLICY_ID = "81000000-0000-4000-8000-000000000002"
PUBLISHED_AT = datetime(2026, 11, 11, 9, 5, tzinfo=UTC)


def _document(raw: bytes | None = None) -> SmbsSourceDocument:
    return SmbsSourceDocument(
        raw=raw if raw is not None else FIXTURE.read_bytes(),
        source_uri=SMBS_TODAY_URL,
        acquisition_mode="OPERATOR_SOURCE_FILE",
        transport_security="OPERATOR_ATTESTED_FILE",
        captured_at=datetime(2026, 11, 11, 9, 10, tzinfo=UTC),
    )


def test_mb1_03a_parses_obfuscated_smbs_usd_krw_source() -> None:
    observation = parse_smbs_usd_krw(_document(), published_at=PUBLISHED_AT)

    assert observation.rate_date.isoformat() == "2026-11-11"
    assert str(observation.published_rate) == "1343.30"
    assert str(observation.quote_unit) == "1"
    assert observation.source_record_id == "SMBS:2026-11-11:USD:KRW:FINAL"
    assert observation.source_sha256.startswith("sha256:")


def test_mb1_03a_builds_deterministic_eos_import_request() -> None:
    observation = parse_smbs_usd_krw(_document(), published_at=PUBLISHED_AT)
    first = build_smbs_fx_import_request(
        load_approved_finance_input_bundle(ROOT),
        observation,
        tenant_id=TENANT_ID,
        subject_id=SUBJECT_ID,
        company_id=COMPANY_ID,
        policy_id=POLICY_ID,
    )
    second = build_smbs_fx_import_request(
        load_approved_finance_input_bundle(ROOT),
        observation,
        tenant_id=TENANT_ID,
        subject_id=SUBJECT_ID,
        company_id=COMPANY_ID,
        policy_id=POLICY_ID,
    )

    assert first == second
    assert first.path == "/internal/v2/finance/fx-rate-batches"
    snapshot = first.payload["snapshots"][0]
    assert snapshot["published_rate"] == "1343.30"
    assert snapshot["rate_date"] == "2026-11-11"
    assert snapshot["source_uri"] == SMBS_TODAY_URL
    assert snapshot["provenance"]["raw_source_retained"] is True
    assert snapshot["provenance"]["operator_review_required"] is True


def test_mb1_03a_source_file_is_primary_admission_path(tmp_path: Path) -> None:
    source = tmp_path / "smbs.html"
    source.write_bytes(FIXTURE.read_bytes())

    document = load_smbs_source_file(
        source, captured_at=datetime(2026, 11, 11, tzinfo=UTC)
    )

    assert document.acquisition_mode == "OPERATOR_SOURCE_FILE"
    assert document.transport_security == "OPERATOR_ATTESTED_FILE"


class _Headers:
    def __init__(self, content_type: str = "text/html") -> None:
        self._content_type = content_type

    def get_content_type(self) -> str:
        return self._content_type


class _Response:
    def __init__(
        self,
        raw: bytes,
        *,
        final_url: str = SMBS_TODAY_URL,
        content_type: str = "text/html",
    ) -> None:
        self._raw = raw
        self._final_url = final_url
        self.headers = _Headers(content_type)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def geturl(self) -> str:
        return self._final_url

    def read(self, _limit: int) -> bytes:
        return self._raw


def test_mb1_03a_explicit_http_capture_retains_raw_evidence(
    monkeypatch, tmp_path: Path
) -> None:
    raw = FIXTURE.read_bytes()
    monkeypatch.setattr(
        "mybee_ax.integrations.smbs_fx.urlopen",
        lambda *_args, **_kwargs: _Response(raw),
    )
    output = tmp_path / "captured.html"

    document = fetch_smbs_source_once(
        allow_insecure_http=True,
        raw_output=output,
        captured_at=datetime(2026, 11, 11, tzinfo=UTC),
    )

    assert output.read_bytes() == raw
    assert document.transport_security == "HTTP_UNVERIFIED"
    assert document.acquisition_mode == "OPERATOR_INITIATED_HTTP_CAPTURE"


@pytest.mark.parametrize(
    ("kwargs", "code"),
    (
        ({"allow_insecure_http": False}, "SMBS_HTTP_NOT_EXPLICITLY_ALLOWED"),
        ({"allow_insecure_http": True, "timeout_seconds": 0}, "SMBS_TIMEOUT_INVALID"),
    ),
)
def test_mb1_03a_http_capture_requires_explicit_bounded_execution(
    tmp_path: Path, kwargs: dict, code: str
) -> None:
    with pytest.raises(SmbsFxAdmissionError) as raised:
        fetch_smbs_source_once(raw_output=tmp_path / "raw.html", **kwargs)
    assert raised.value.code == code


def test_mb1_03a_http_capture_refuses_existing_raw_output(tmp_path: Path) -> None:
    output = tmp_path / "raw.html"
    output.write_bytes(b"existing evidence")
    with pytest.raises(SmbsFxAdmissionError) as raised:
        fetch_smbs_source_once(
            allow_insecure_http=True,
            raw_output=output,
        )
    assert raised.value.code == "SMBS_RAW_OUTPUT_INVALID"


def test_mb1_03a_http_capture_redacts_network_failure(
    monkeypatch, tmp_path: Path
) -> None:
    def fail(*_args, **_kwargs):
        raise URLError("sensitive upstream detail")

    monkeypatch.setattr("mybee_ax.integrations.smbs_fx.urlopen", fail)

    with pytest.raises(SmbsFxAdmissionError) as raised:
        fetch_smbs_source_once(
            allow_insecure_http=True, raw_output=tmp_path / "raw.html"
        )
    assert raised.value.code == "SMBS_SOURCE_UNAVAILABLE"
    assert "sensitive" not in str(raised.value)


@pytest.mark.parametrize(
    ("response", "code"),
    (
        (
            _Response(b"content", final_url="http://www.smbs.co.kr/other"),
            "SMBS_SOURCE_RESPONSE_INVALID",
        ),
        (
            _Response(b"content", content_type="application/json"),
            "SMBS_SOURCE_RESPONSE_INVALID",
        ),
        (_Response(b""), "SMBS_SOURCE_SIZE_INVALID"),
        (_Response(b"x" * 2_000_001), "SMBS_SOURCE_SIZE_INVALID"),
    ),
)
def test_mb1_03a_http_response_guards(
    monkeypatch, tmp_path: Path, response: _Response, code: str
) -> None:
    monkeypatch.setattr(
        "mybee_ax.integrations.smbs_fx.urlopen",
        lambda *_args, **_kwargs: response,
    )
    with pytest.raises(SmbsFxAdmissionError) as raised:
        fetch_smbs_source_once(
            allow_insecure_http=True, raw_output=tmp_path / "raw.html"
        )
    assert raised.value.code == code


def test_mb1_03a_raw_evidence_write_failure_is_fail_closed(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "mybee_ax.integrations.smbs_fx.urlopen",
        lambda *_args, **_kwargs: _Response(FIXTURE.read_bytes()),
    )

    def fail_write(_path, _raw):
        raise OSError("private path")

    monkeypatch.setattr(Path, "write_bytes", fail_write)
    with pytest.raises(SmbsFxAdmissionError) as raised:
        fetch_smbs_source_once(
            allow_insecure_http=True, raw_output=tmp_path / "raw.html"
        )
    assert raised.value.code == "SMBS_RAW_OUTPUT_UNWRITABLE"


def test_mb1_03a_source_file_and_uri_guards(tmp_path: Path) -> None:
    with pytest.raises(SmbsFxAdmissionError) as missing:
        load_smbs_source_file(tmp_path / "missing.html")
    assert missing.value.code == "SMBS_SOURCE_FILE_UNREADABLE"
    empty = tmp_path / "empty.html"
    empty.write_bytes(b"")
    with pytest.raises(SmbsFxAdmissionError) as empty_error:
        load_smbs_source_file(empty)
    assert empty_error.value.code == "SMBS_SOURCE_EMPTY"
    with pytest.raises(SmbsFxAdmissionError) as invalid_uri:
        load_smbs_source_file(FIXTURE, source_uri="https://www.smbs.co.kr/")
    assert invalid_uri.value.code == "SMBS_SOURCE_URI_INVALID"


@pytest.mark.parametrize(
    ("mutate", "code"),
    (
        (
            lambda text: text.replace('id="searchDate"', 'id="other"'),
            "SMBS_RATE_DATE_MISSING",
        ),
        (
            lambda text: text.replace("매매기준율표", "다른 표"),
            "SMBS_RATE_TABLE_MISSING",
        ),
        (
            lambda text: text.replace(
                "%_D31%_D2c%_D33%_D34%_D33%_D2e%_D33%_D30", "BAD"
            ),
            "SMBS_USD_RATE_INVALID",
        ),
        (
            lambda text: text.replace("%_C55%_C53%_C44", "%_C45%_C55%_C52"),
            "SMBS_USD_RATE_AMBIGUOUS",
        ),
    ),
)
def test_mb1_03a_parser_drift_fails_closed(mutate, code: str) -> None:
    raw = mutate(FIXTURE.read_text(encoding="utf-8")).encode("utf-8")
    with pytest.raises(SmbsFxAdmissionError) as raised:
        parse_smbs_usd_krw(_document(raw), published_at=PUBLISHED_AT)
    assert raised.value.code == code


def test_mb1_03a_parser_accepts_declared_euc_kr_source() -> None:
    text = FIXTURE.read_text(encoding="utf-8").replace("UTF-8", "EUC-KR")
    observation = parse_smbs_usd_krw(
        _document(text.encode("euc-kr")), published_at=PUBLISHED_AT
    )
    assert observation.published_rate.is_finite()


def test_mb1_03a_parser_rejects_untrusted_time_table_and_encoding() -> None:
    with pytest.raises(SmbsFxAdmissionError) as publication:
        parse_smbs_usd_krw(
            _document(), published_at=datetime(2026, 11, 10, 0, tzinfo=UTC)
        )
    assert publication.value.code == "SMBS_PUBLICATION_TIME_INVALID"

    malformed = FIXTURE.read_text().replace("</table>", "")
    with pytest.raises(SmbsFxAdmissionError) as table:
        parse_smbs_usd_krw(_document(malformed.encode()), published_at=PUBLISHED_AT)
    assert table.value.code == "SMBS_RATE_TABLE_INVALID"

    duplicate = FIXTURE.read_text().replace(
        "</tbody>",
        FIXTURE.read_text().split("<tbody>", 1)[1].split("</tbody>", 1)[0] + "</tbody>",
    )
    with pytest.raises(SmbsFxAdmissionError) as ambiguous:
        parse_smbs_usd_krw(_document(duplicate.encode()), published_at=PUBLISHED_AT)
    assert ambiguous.value.code == "SMBS_USD_RATE_AMBIGUOUS"

    with pytest.raises(SmbsFxAdmissionError) as encoding:
        parse_smbs_usd_krw(_document(b"\xff\xfe\xff"), published_at=PUBLISHED_AT)
    assert encoding.value.code == "SMBS_SOURCE_ENCODING_INVALID"


@pytest.mark.parametrize(
    ("mutate", "code"),
    (
        (
            lambda document, observation: (
                document,
                observation,
                {"policy_version": 0},
            ),
            "SMBS_POLICY_VERSION_INVALID",
        ),
        (
            lambda document, observation: (
                document,
                observation,
                {"tenant_id": "bad tenant"},
            ),
            "SMBS_TENANT_ID_INVALID",
        ),
        (
            lambda document, observation: (
                document,
                observation,
                {"company_id": "bad"},
            ),
            "SMBS_COMPANY_ID_INVALID",
        ),
    ),
)
def test_mb1_03a_request_binding_rejections(mutate, code: str) -> None:
    observation = parse_smbs_usd_krw(_document(), published_at=PUBLISHED_AT)
    _, observation, overrides = mutate(_document(), observation)
    values = {
        "tenant_id": TENANT_ID,
        "subject_id": SUBJECT_ID,
        "company_id": COMPANY_ID,
        "policy_id": POLICY_ID,
    }
    values.update(overrides)
    with pytest.raises(SmbsFxAdmissionError) as raised:
        build_smbs_fx_import_request(
            load_approved_finance_input_bundle(ROOT), observation, **values
        )
    assert raised.value.code == code


def test_mb1_03a_request_rejects_source_policy_and_naive_time() -> None:
    observation = parse_smbs_usd_krw(_document(), published_at=PUBLISHED_AT)
    with pytest.raises(SmbsFxAdmissionError) as mismatch:
        build_smbs_fx_import_request(
            load_approved_finance_input_bundle(ROOT),
            replace(observation, source_uri="http://www.smbs.co.kr/other"),
            tenant_id=TENANT_ID,
            subject_id=SUBJECT_ID,
            company_id=COMPANY_ID,
            policy_id=POLICY_ID,
        )
    assert mismatch.value.code == "SMBS_SOURCE_POLICY_MISMATCH"

    with pytest.raises(SmbsFxAdmissionError) as naive:
        parse_smbs_usd_krw(
            _document(),
            published_at=datetime(2026, 11, 11),  # noqa: DTZ001 - rejection case
        )
    assert naive.value.code == "SMBS_PUBLISHED_AT_INVALID"


def test_mb1_03a_config_keeps_automatic_fetch_disabled() -> None:
    policy = json.loads(
        (ROOT / "domains/mybee/config/fx/approved_rate_source_policy.json").read_text()
    )
    assert policy["source"]["source_uri"] == SMBS_TODAY_URL
    assert policy["source"]["automatic_fetch_enabled"] is False
