#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.error import URLError
from urllib.request import urlopen


ROOT_DIR = Path(__file__).resolve().parents[2]
APP_DIR = ROOT_DIR / "apps" / "nex-ae-web"
DEFAULT_PORT = 5227
DEFAULT_SLICE_LABEL = "Slice 0227"


@dataclass(frozen=True)
class BrowserSmokeResult:
    status: str
    slice_label: str
    url: str
    anchor_count: int
    missing_anchors: tuple[str, ...] = ()
    error: str | None = None


def required_anchors(slice_label: str = DEFAULT_SLICE_LABEL) -> tuple[str, ...]:
    return (
        slice_label,
        "ae-web-runtime-config",
        "runtime-diagnostics-panel",
        "runtime-diagnostics-preview",
        "upload-feedback",
        "upload-retry-button",
        "document-detail-feedback",
        "document-detail-retry-button",
        "retrieval-feedback",
        "retrieval-retry-button",
        "retrieval-client-summary",
    )


def validate_html(
    html: str,
    anchors: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    expected = anchors or required_anchors()
    return tuple(anchor for anchor in expected if anchor not in html)


def run_static_browser_smoke(
    *,
    port: int = DEFAULT_PORT,
    slice_label: str = DEFAULT_SLICE_LABEL,
    timeout_seconds: float = 10.0,
    start_server: bool = True,
    opener: Callable[[str], object] = urlopen,
    popen: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
    sleeper: Callable[[float], None] = time.sleep,
) -> BrowserSmokeResult:
    url = f"http://127.0.0.1:{port}/"
    process = None
    try:
        if start_server:
            process = start_dev_server(port=port, popen=popen)
        html = wait_for_html(
            url,
            timeout_seconds=timeout_seconds,
            opener=opener,
            sleeper=sleeper,
        )
        missing = validate_html(html, required_anchors(slice_label))
        if missing:
            return BrowserSmokeResult(
                status="failed",
                slice_label=slice_label,
                url=url,
                anchor_count=len(required_anchors(slice_label)),
                missing_anchors=missing,
            )
        return BrowserSmokeResult(
            status="pass",
            slice_label=slice_label,
            url=url,
            anchor_count=len(required_anchors(slice_label)),
        )
    except Exception as exc:
        return BrowserSmokeResult(
            status="failed",
            slice_label=slice_label,
            url=url,
            anchor_count=len(required_anchors(slice_label)),
            error=exc.__class__.__name__,
        )
    finally:
        if process is not None:
            stop_process(process)


def start_dev_server(
    *,
    port: int,
    popen: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
) -> subprocess.Popen[bytes]:
    env = dict(os.environ)
    env["PORT"] = str(port)
    return popen(
        ["npm", "--prefix", str(APP_DIR), "run", "dev"],
        cwd=ROOT_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def wait_for_html(
    url: str,
    *,
    timeout_seconds: float,
    opener: Callable[[str], object] = urlopen,
    sleeper: Callable[[float], None] = time.sleep,
) -> str:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with opener(url) as response:
                return response.read().decode("utf-8")
        except URLError as exc:
            last_error = exc
            sleeper(0.1)
    raise TimeoutError(f"Timed out waiting for AE Web smoke URL: {last_error}")


def stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


def format_summary(result: BrowserSmokeResult) -> str:
    base = (
        "ae_web_static_browser_smoke="
        f"{result.status} slice={result.slice_label.replace(' ', '_')} "
        f"anchors={result.anchor_count} url={result.url}"
    )
    if result.missing_anchors:
        return f"{base} missing={','.join(result.missing_anchors)}"
    if result.error:
        return f"{base} error={result.error}"
    return base


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--slice-label", default=DEFAULT_SLICE_LABEL)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--no-start-server", action="store_true")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)

    result = run_static_browser_smoke(
        port=args.port,
        slice_label=args.slice_label,
        timeout_seconds=args.timeout,
        start_server=not args.no_start_server,
    )
    output = format_summary(result) if args.summary else result
    print(output)
    return 0 if result.status == "pass" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
