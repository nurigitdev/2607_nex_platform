#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.request import urlopen

from run_ae_web_static_browser_smoke import (
    start_dev_server,
    stop_process,
    wait_for_html,
)


ROOT_DIR = Path(__file__).resolve().parents[2]
APP_DIR = ROOT_DIR / "apps" / "nex-ae-web"
DEFAULT_PORT = 5320
DEFAULT_SLICE_LABEL = "Slice 0320"


@dataclass(frozen=True)
class SourceAnchor:
    relative_path: str
    anchor: str


@dataclass(frozen=True)
class GroundedResponseQualitySmokeResult:
    status: str
    slice_label: str
    url: str
    html_anchor_count: int
    source_anchor_count: int
    missing_html_anchors: tuple[str, ...] = ()
    missing_source_anchors: tuple[str, ...] = ()
    forbidden_fragments: tuple[str, ...] = ()
    error: str | None = None


def required_html_anchors() -> tuple[str, ...]:
    return (
        "grounded-response-quality",
        "message-list",
        "chat-status",
        "chat-title",
        "retrieval-quality-warnings",
    )


def required_source_anchors() -> tuple[SourceAnchor, ...]:
    return (
        SourceAnchor("src/groundedResponseQuality.js", "ae_web_grounded_response_quality_surface.v1"),
        SourceAnchor("src/groundedResponseQuality.js", "ae_chat_grounded_response_quality.v1"),
        SourceAnchor("src/groundedResponseQuality.js", "buildGroundedResponseQualitySurface"),
        SourceAnchor("src/groundedResponseQuality.js", "buildGroundedResponseQualitySummary"),
        SourceAnchor("src/groundedResponseQuality.js", "extractGroundedResponseQuality"),
        SourceAnchor("src/groundedResponseQuality.js", "PASS"),
        SourceAnchor("src/groundedResponseQuality.js", "WARN"),
        SourceAnchor("src/groundedResponseQuality.js", "FAIL"),
        SourceAnchor("src/groundedResponseQuality.js", "NOT_REQUIRED"),
        SourceAnchor("src/groundedResponseQuality.js", "UNKNOWN"),
        SourceAnchor("src/groundedResponseQuality.js", "rawOutputIncluded: false"),
        SourceAnchor("src/groundedResponseQuality.js", "evidenceTextIncluded: false"),
        SourceAnchor("src/groundedResponseQuality.js", "promptTextIncluded: false"),
        SourceAnchor("src/groundedResponseQuality.js", "providerDetailIncluded: false"),
        SourceAnchor("src/main.js", "renderGroundedResponseQualitySurface"),
        SourceAnchor("src/main.js", "renderMessageGroundedResponseQuality"),
        SourceAnchor("src/main.js", "groundedResponseQuality"),
        SourceAnchor("src/main.js", "grounded_response_quality"),
        SourceAnchor("src/main.js", "buildMockGroundedResponseQualityContract"),
        SourceAnchor("src/styles.css", ".grounded-response-quality-surface"),
        SourceAnchor("src/styles.css", ".grounded-response-quality-chip"),
    )


def forbidden_source_fragments() -> tuple[str, ...]:
    return (
        "raw_prompt",
        "source_text",
        "source_preview_text",
        "chunk_text",
        "content_text",
        "service_token",
        "api_key",
        "database_url",
        "provider_url",
        "/data/nex-platform",
        "private generated output",
        "private evidence text",
    )


def validate_html(html: str, anchors: tuple[str, ...] | None = None) -> tuple[str, ...]:
    expected = anchors or required_html_anchors()
    return tuple(anchor for anchor in expected if anchor not in html)


def validate_sources(
    *,
    app_dir: Path = APP_DIR,
    anchors: tuple[SourceAnchor, ...] | None = None,
    forbidden_fragments: tuple[str, ...] | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    expected = anchors or required_source_anchors()
    forbidden = forbidden_fragments or forbidden_source_fragments()
    source_cache: dict[str, str] = {}
    missing: list[str] = []
    forbidden_hits: list[str] = []

    for source_anchor in expected:
        text = source_cache.setdefault(
            source_anchor.relative_path,
            read_app_file(app_dir, source_anchor.relative_path),
        )
        if source_anchor.anchor not in text:
            missing.append(f"{source_anchor.relative_path}::{source_anchor.anchor}")

    for relative_path, text in source_cache.items():
        for fragment in forbidden:
            if fragment in text:
                forbidden_hits.append(f"{relative_path}::{fragment}")

    return tuple(missing), tuple(forbidden_hits)


def read_app_file(app_dir: Path, relative_path: str) -> str:
    return (app_dir / relative_path).read_text(encoding="utf-8")


def run_ae_web_grounded_response_quality_smoke(
    *,
    port: int = DEFAULT_PORT,
    slice_label: str = DEFAULT_SLICE_LABEL,
    timeout_seconds: float = 10.0,
    start_server: bool = True,
    opener: Callable[[str], object] = urlopen,
    popen: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
    sleeper: Callable[[float], None] = time.sleep,
    app_dir: Path = APP_DIR,
) -> GroundedResponseQualitySmokeResult:
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
        missing_html = validate_html(html)
        missing_source, forbidden_hits = validate_sources(app_dir=app_dir)
        status = (
            "pass"
            if not missing_html and not missing_source and not forbidden_hits
            else "failed"
        )
        return GroundedResponseQualitySmokeResult(
            status=status,
            slice_label=slice_label,
            url=url,
            html_anchor_count=len(required_html_anchors()),
            source_anchor_count=len(required_source_anchors()),
            missing_html_anchors=missing_html,
            missing_source_anchors=missing_source,
            forbidden_fragments=forbidden_hits,
        )
    except Exception as exc:
        return GroundedResponseQualitySmokeResult(
            status="failed",
            slice_label=slice_label,
            url=url,
            html_anchor_count=len(required_html_anchors()),
            source_anchor_count=len(required_source_anchors()),
            error=exc.__class__.__name__,
        )
    finally:
        if process is not None:
            stop_process(process)


def format_summary(result: GroundedResponseQualitySmokeResult) -> str:
    base = (
        "ae_web_grounded_response_quality_smoke="
        f"{result.status} slice={result.slice_label.replace(' ', '_')} "
        f"html_anchors={result.html_anchor_count} "
        f"source_anchors={result.source_anchor_count} url={result.url}"
    )
    if result.missing_html_anchors:
        return f"{base} missing_html={','.join(result.missing_html_anchors)}"
    if result.missing_source_anchors:
        return f"{base} missing_source={','.join(result.missing_source_anchors)}"
    if result.forbidden_fragments:
        return f"{base} forbidden={','.join(result.forbidden_fragments)}"
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

    result = run_ae_web_grounded_response_quality_smoke(
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
