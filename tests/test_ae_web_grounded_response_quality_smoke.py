from __future__ import annotations

from pathlib import Path
from urllib.error import URLError

import pytest

import run_ae_web_grounded_response_quality_smoke as smoke


class FakeResponse:
    def __init__(self, html: str) -> None:
        self.html = html

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def read(self) -> bytes:
        return self.html.encode("utf-8")


class FakeProcess:
    def __init__(self, *, running: bool = True, wait_timeout: bool = False) -> None:
        self.running = running
        self.wait_timeout = wait_timeout
        self.terminated = False
        self.killed = False
        self.wait_calls = 0

    def poll(self) -> int | None:
        return None if self.running else 0

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: int) -> None:
        self.wait_calls += 1
        if self.wait_timeout and self.wait_calls == 1:
            raise smoke.subprocess.TimeoutExpired("npm", timeout)
        self.running = False

    def kill(self) -> None:
        self.killed = True
        self.running = False


def full_html() -> str:
    return "\n".join(smoke.required_html_anchors())


def write_source_tree(root: Path, *, forbidden: bool = False) -> Path:
    app_dir = root / "apps" / "nex-ae-web"
    (app_dir / "src").mkdir(parents=True)
    files: dict[str, str] = {
        "src/groundedResponseQuality.js": "\n".join(
            [
                "ae_web_grounded_response_quality_surface.v1",
                "ae_chat_grounded_response_quality.v1",
                "buildGroundedResponseQualitySurface",
                "buildGroundedResponseQualitySummary",
                "extractGroundedResponseQuality",
                "PASS",
                "WARN",
                "FAIL",
                "NOT_REQUIRED",
                "UNKNOWN",
                "rawOutputIncluded: false",
                "evidenceTextIncluded: false",
                "promptTextIncluded: false",
                "providerDetailIncluded: false",
            ]
        ),
        "src/main.js": "\n".join(
            [
                "renderGroundedResponseQualitySurface",
                "renderMessageGroundedResponseQuality",
                "groundedResponseQuality",
                "grounded_response_quality",
                "buildMockGroundedResponseQualityContract",
            ]
        ),
        "src/styles.css": "\n".join(
            [".grounded-response-quality-surface", ".grounded-response-quality-chip"]
        ),
    }
    if forbidden:
        files["src/main.js"] += "\nraw_prompt"
    for relative_path, text in files.items():
        (app_dir / relative_path).write_text(text, encoding="utf-8")
    return app_dir


def test_validate_html_reports_missing_grounded_quality_anchor() -> None:
    missing = smoke.validate_html("message-list")

    assert "grounded-response-quality" in missing
    assert "message-list" not in missing


def test_validate_sources_reports_missing_and_forbidden_fragments(
    tmp_path: Path,
) -> None:
    app_dir = write_source_tree(tmp_path, forbidden=True)
    (app_dir / "src" / "groundedResponseQuality.js").write_text(
        "ae_web_grounded_response_quality_surface.v1",
        encoding="utf-8",
    )

    missing, forbidden = smoke.validate_sources(app_dir=app_dir)

    assert (
        "src/groundedResponseQuality.js::buildGroundedResponseQualitySurface"
        in missing
    )
    assert "src/main.js::raw_prompt" in forbidden


def test_run_grounded_quality_smoke_passes_with_fake_server_and_sources(
    tmp_path: Path,
) -> None:
    app_dir = write_source_tree(tmp_path)
    started: list[FakeProcess] = []

    def fake_popen(*args: object, **kwargs: object) -> FakeProcess:
        process = FakeProcess()
        started.append(process)
        return process

    result = smoke.run_ae_web_grounded_response_quality_smoke(
        opener=lambda url: FakeResponse(full_html()),
        popen=fake_popen,
        sleeper=lambda seconds: None,
        app_dir=app_dir,
    )

    assert result.status == "pass"
    assert result.html_anchor_count == len(smoke.required_html_anchors())
    assert result.source_anchor_count == len(smoke.required_source_anchors())
    assert started[0].terminated is True
    assert started[0].killed is False
    assert "ae_web_grounded_response_quality_smoke=pass" in smoke.format_summary(
        result
    )


def test_run_grounded_quality_smoke_reports_missing_html_without_server(
    tmp_path: Path,
) -> None:
    app_dir = write_source_tree(tmp_path)

    result = smoke.run_ae_web_grounded_response_quality_smoke(
        start_server=False,
        opener=lambda url: FakeResponse("message-list"),
        sleeper=lambda seconds: None,
        app_dir=app_dir,
    )

    assert result.status == "failed"
    assert "grounded-response-quality" in result.missing_html_anchors
    assert "missing_html=grounded-response-quality" in smoke.format_summary(result)


def test_run_grounded_quality_smoke_reports_missing_source_and_forbidden(
    tmp_path: Path,
) -> None:
    app_dir = write_source_tree(tmp_path, forbidden=True)
    (app_dir / "src" / "styles.css").write_text("", encoding="utf-8")

    missing_source = smoke.run_ae_web_grounded_response_quality_smoke(
        start_server=False,
        opener=lambda url: FakeResponse(full_html()),
        sleeper=lambda seconds: None,
        app_dir=app_dir,
    )
    assert missing_source.status == "failed"
    assert (
        "src/styles.css::.grounded-response-quality-surface"
        in missing_source.missing_source_anchors
    )
    assert (
        "missing_source=src/styles.css::.grounded-response-quality-surface"
        in smoke.format_summary(missing_source)
    )

    forbidden_app_dir = write_source_tree(tmp_path / "forbidden", forbidden=True)
    forbidden_result = smoke.run_ae_web_grounded_response_quality_smoke(
        start_server=False,
        opener=lambda url: FakeResponse(full_html()),
        sleeper=lambda seconds: None,
        app_dir=forbidden_app_dir,
    )
    assert forbidden_result.status == "failed"
    assert "src/main.js::raw_prompt" in forbidden_result.forbidden_fragments
    assert "forbidden=src/main.js::raw_prompt" in smoke.format_summary(
        forbidden_result
    )


def test_run_grounded_quality_smoke_reports_timeout_and_stops_stuck_server() -> None:
    started: list[FakeProcess] = []

    def fake_popen(*args: object, **kwargs: object) -> FakeProcess:
        process = FakeProcess(wait_timeout=True)
        started.append(process)
        return process

    result = smoke.run_ae_web_grounded_response_quality_smoke(
        timeout_seconds=0,
        opener=lambda url: FakeResponse("never used"),
        popen=fake_popen,
        sleeper=lambda seconds: None,
    )

    assert result.status == "failed"
    assert result.error == "TimeoutError"
    assert started[0].terminated is True
    assert started[0].killed is True
    assert "error=TimeoutError" in smoke.format_summary(result)


def test_run_grounded_quality_smoke_retries_until_html_is_available(
    tmp_path: Path,
) -> None:
    app_dir = write_source_tree(tmp_path)
    calls = {"count": 0}

    def flaky_opener(url: str) -> FakeResponse:
        calls["count"] += 1
        if calls["count"] == 1:
            raise URLError("not ready")
        return FakeResponse(full_html())

    result = smoke.run_ae_web_grounded_response_quality_smoke(
        start_server=False,
        opener=flaky_opener,
        sleeper=lambda seconds: None,
        app_dir=app_dir,
    )

    assert result.status == "pass"
    assert calls["count"] == 2


def test_main_outputs_summary_and_failure_modes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_ae_web_grounded_response_quality_smoke",
        lambda **kwargs: smoke.GroundedResponseQualitySmokeResult(
            status="pass",
            slice_label=kwargs["slice_label"],
            url=f"http://127.0.0.1:{kwargs['port']}/",
            html_anchor_count=5,
            source_anchor_count=21,
        ),
    )
    assert smoke.main(["--summary", "--no-start-server"]) == 0
    assert "ae_web_grounded_response_quality_smoke=pass" in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_ae_web_grounded_response_quality_smoke",
        lambda **kwargs: smoke.GroundedResponseQualitySmokeResult(
            status="failed",
            slice_label=kwargs["slice_label"],
            url=f"http://127.0.0.1:{kwargs['port']}/",
            html_anchor_count=5,
            source_anchor_count=21,
            error="TimeoutError",
        ),
    )
    assert smoke.main(["--no-start-server"]) == 1
    assert "GroundedResponseQualitySmokeResult" in capsys.readouterr().out


def test_grounded_quality_smoke_quality_gate_and_docs_are_wired() -> None:
    root = Path(__file__).parents[1]
    quality_gate = (root / "scripts" / "quality" / "run_quality_gate.sh").read_text(
        encoding="utf-8"
    )
    docs_index = (root / "docs" / "README.md").read_text(encoding="utf-8")
    slice_doc = (
        root
        / "docs"
        / "slices"
        / "0320_ae_web_grounded_response_quality_smoke_evidence.md"
    )

    assert "run_ae_web_grounded_response_quality_smoke.py --summary" in quality_gate
    assert "0320_ae_web_grounded_response_quality_smoke_evidence.md" in docs_index
    assert slice_doc.exists()
