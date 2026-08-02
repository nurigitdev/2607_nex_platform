from __future__ import annotations

import json
from pathlib import Path


WEB_ROOT = Path(__file__).parents[1] / "apps" / "nex-ae-web"


def read_web_file(relative_path: str) -> str:
    return (WEB_ROOT / relative_path).read_text(encoding="utf-8")


def test_ae_web_shell_exposes_mvp_workspace_surfaces() -> None:
    html = read_web_file("index.html")

    for required_id in [
        "workspace-summary",
        "message-list",
        "progress-timeline",
        "document-list",
        "artifact-panel",
        "audit-panel",
        "retrieval-toggle",
        "format-select",
    ]:
        assert f'id="{required_id}"' in html
    assert "Slice 0040" in html
    assert "lang=\"ko\"" in html


def test_ae_web_mock_state_links_generation_artifact_and_audit_contracts() -> None:
    javascript = read_web_file("src/main.js")

    for expected in [
        "generation.retrieval.ready",
        "generation.citation.validating",
        "READY_FOR_RENDERING",
        "compat-grounded-answer-v1",
        "handoff-local",
        "general-llm-default",
    ]:
        assert expected in javascript
    assert "raw_prompt" not in javascript
    assert "provider_url" not in javascript
    assert "/data/nex-platform" not in javascript


def test_ae_web_styles_keep_responsive_operational_layout() -> None:
    styles = read_web_file("src/styles.css")

    assert "grid-template-columns: minmax(220px, 260px) minmax(0, 1fr)" in styles
    assert "@media (max-width: 620px)" in styles
    assert "overflow-wrap: anywhere" in styles
    assert "letter-spacing: 0" in styles
    assert "letter-spacing: -" not in styles
    assert "linear-gradient" not in styles


def test_ae_web_package_version_tracks_slice_0040() -> None:
    package = json.loads(read_web_file("package.json"))

    assert package["name"] == "nex-ae-web"
    assert package["version"] == "0.0.0-slice0040"
    assert package["scripts"]["dev"] == "node scripts/serve.mjs"
