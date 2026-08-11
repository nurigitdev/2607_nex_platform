from __future__ import annotations

from urllib.error import URLError

import pytest

import run_ae_web_static_browser_smoke as ae_web_smoke


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
            raise ae_web_smoke.subprocess.TimeoutExpired("npm", timeout)
        self.running = False

    def kill(self) -> None:
        self.killed = True
        self.running = False


def full_html(slice_label: str = ae_web_smoke.DEFAULT_SLICE_LABEL) -> str:
    return "\n".join(ae_web_smoke.required_anchors(slice_label))


def test_validate_html_reports_missing_anchors() -> None:
    missing = ae_web_smoke.validate_html("Slice 0227", ("Slice 0227", "missing"))

    assert missing == ("missing",)


def test_run_static_browser_smoke_passes_with_fake_server() -> None:
    started: list[FakeProcess] = []

    def fake_popen(*args: object, **kwargs: object) -> FakeProcess:
        process = FakeProcess()
        started.append(process)
        return process

    result = ae_web_smoke.run_static_browser_smoke(
        opener=lambda url: FakeResponse(full_html()),
        popen=fake_popen,
        sleeper=lambda seconds: None,
    )

    assert result.status == "pass"
    assert result.anchor_count == len(ae_web_smoke.required_anchors())
    assert started[0].terminated is True
    assert started[0].killed is False


def test_run_static_browser_smoke_reports_missing_anchor_without_server() -> None:
    result = ae_web_smoke.run_static_browser_smoke(
        start_server=False,
        opener=lambda url: FakeResponse("Slice 0227"),
        sleeper=lambda seconds: None,
    )

    assert result.status == "failed"
    assert "runtime-diagnostics-panel" in result.missing_anchors
    assert "missing=ae-web-runtime-config" in ae_web_smoke.format_summary(result)


def test_wait_for_html_retries_until_available() -> None:
    calls = {"count": 0}

    def flaky_opener(url: str) -> FakeResponse:
        calls["count"] += 1
        if calls["count"] == 1:
            raise URLError("not ready")
        return FakeResponse(full_html())

    html = ae_web_smoke.wait_for_html(
        "http://127.0.0.1:5227/",
        timeout_seconds=1,
        opener=flaky_opener,
        sleeper=lambda seconds: None,
    )

    assert "runtime-diagnostics-panel" in html
    assert calls["count"] == 2


def test_run_static_browser_smoke_reports_timeout_error() -> None:
    result = ae_web_smoke.run_static_browser_smoke(
        start_server=False,
        timeout_seconds=0,
        opener=lambda url: FakeResponse("never used"),
        sleeper=lambda seconds: None,
    )

    assert result.status == "failed"
    assert result.error == "TimeoutError"
    assert "error=TimeoutError" in ae_web_smoke.format_summary(result)


def test_stop_process_handles_exited_and_stuck_processes() -> None:
    exited = FakeProcess(running=False)
    stuck = FakeProcess(wait_timeout=True)

    ae_web_smoke.stop_process(exited)
    ae_web_smoke.stop_process(stuck)

    assert exited.terminated is False
    assert stuck.terminated is True
    assert stuck.killed is True


def test_main_outputs_summary_for_fetch_only_smoke(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        ae_web_smoke,
        "run_static_browser_smoke",
        lambda **kwargs: ae_web_smoke.BrowserSmokeResult(
            status="pass",
            slice_label=kwargs["slice_label"],
            url=f"http://127.0.0.1:{kwargs['port']}/",
            anchor_count=11,
        ),
    )

    assert ae_web_smoke.main(["--summary", "--no-start-server"]) == 0
    assert "ae_web_static_browser_smoke=pass" in capsys.readouterr().out


def test_main_returns_failure_without_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        ae_web_smoke,
        "run_static_browser_smoke",
        lambda **kwargs: ae_web_smoke.BrowserSmokeResult(
            status="failed",
            slice_label=kwargs["slice_label"],
            url=f"http://127.0.0.1:{kwargs['port']}/",
            anchor_count=11,
            error="TimeoutError",
        ),
    )

    assert ae_web_smoke.main(["--no-start-server"]) == 1
    assert "BrowserSmokeResult" in capsys.readouterr().out
