from __future__ import annotations

import json
import subprocess
from pathlib import Path

import check_p8_demo_compose as check
import pytest
import yaml
from nex_runtime import demo_compose
from nex_runtime.demo_compose import (
    DEMO_ADDED_SERVICE_IDS,
    DEMO_INSTALLED_PROCESS_IDS,
    DEMO_ROUTE_IDS,
    DemoComposeError,
    admit_demo_compose_sources,
    admit_rendered_demo_compose,
    image_environment_from_installed_runtime_reports,
    image_environment_from_release_report,
)

ROOT = Path(__file__).resolve().parents[1]


def _references() -> dict[str, str]:
    return {
        artifact_id: f"local/{artifact_id}@sha256:{index:064x}"
        for index, artifact_id in enumerate(
            (
                "nex-oa-runtime",
                "nex-ag-runtime",
                "nex-ae-runtime",
                "nex-cx-runtime",
                "nex-mo-runtime",
                "nex-wc-runtime",
                "nex-eos-runtime",
                "nex-ae-web",
            ),
            start=1,
        )
    }


def _release_report() -> dict:
    references = _references()
    return {
        "status": "PASS",
        "image_build": {
            "artifacts": [
                {
                    "artifact_id": key,
                    "image_reference": value,
                    "image_id": value.rsplit("@", 1)[1],
                    "manifest_digest": value.rsplit("@", 1)[1],
                    "local_tag": f"demo/{key}:current",
                }
                for key, value in references.items()
            ]
        },
        "release_manifest": {"release_set_digest": "sha256:" + "f" * 64},
    }


def _rendered() -> dict:
    references = _references()
    artifact_by_process = {
        "nex-oa": "nex-oa-runtime",
        "nex-ag": "nex-ag-runtime",
        "nex-ae-api": "nex-ae-runtime",
        "nex-cx": "nex-cx-runtime",
        "nex-mo": "nex-mo-runtime",
        "nex-wc": "nex-wc-runtime",
        "nex-eos": "nex-eos-runtime",
        "nex-ae-web": "nex-ae-web",
        "nex-ae-agent-runtime-worker": "nex-ae-runtime",
        "nex-wc-event-delivery-worker": "nex-wc-runtime",
        "nex-eos-outbox-publisher": "nex-eos-runtime",
    }
    services = {
        process_id: {
            "image": references[artifact_id],
            "restart": "unless-stopped",
        }
        for process_id, artifact_id in artifact_by_process.items()
    }
    services.update(
        {
            "openbao": {"image": "openbao"},
            "openbao-data-init": {"image": "openbao"},
            "traefik": {"image": "traefik"},
            "rustfs": {"image": "rustfs"},
        }
    )
    return {"name": "nex-platform-p8-demo", "services": services}


def test_demo_compose_sources_are_exact_and_secret_free() -> None:
    result = admit_demo_compose_sources(ROOT)

    assert result["status"] == "ADMITTED"
    assert result["added_service_count"] == len(DEMO_ADDED_SERVICE_IDS)
    assert result["installed_process_count"] == len(DEMO_INSTALLED_PROCESS_IDS)
    assert result["route_count"] == len(DEMO_ROUTE_IDS)
    assert result["wc_eos_tls_routes"] is True
    assert result["raw_secret_included"] is False


def test_rendered_compose_and_release_report_admission() -> None:
    references = _references()
    result = admit_rendered_demo_compose(
        _rendered(), image_references=references
    )
    environment = image_environment_from_release_report(_release_report())

    assert result["status"] == "PASS"
    assert result["installed_process_count"] == 11
    assert result["image_count"] == 8
    assert result["rendered_digest"].startswith("sha256:")
    assert environment["NEX_WC_RUNTIME_IMAGE"] == references["nex-wc-runtime"]


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (
            lambda value: {"services": {}},
            "installed process coverage",
        ),
        (
            lambda value: {
                **value,
                "services": {
                    key: item
                    for key, item in value["services"].items()
                    if key != "nex-eos"
                },
            },
            "installed process coverage",
        ),
        (
            lambda value: {
                **value,
                "services": {
                    **value["services"],
                    "nex-ae-agent-runtime-worker": {
                        **value["services"]["nex-ae-agent-runtime-worker"],
                        "restart": "no",
                    },
                },
            },
            "worker policy",
        ),
    ),
)
def test_rendered_compose_rejects_incomplete_runtime(mutation, message: str) -> None:
    with pytest.raises(DemoComposeError, match=message):
        admit_rendered_demo_compose(
            mutation(_rendered()), image_references=_references()
        )


def test_rendered_compose_rejects_mutable_drift_and_forbidden_values() -> None:
    references = _references()
    with pytest.raises(DemoComposeError, match="incomplete or mutable"):
        admit_rendered_demo_compose(
            _rendered(), image_references={**references, "extra": "latest"}
        )
    rendered = _rendered()
    rendered["services"]["nex-oa"]["image"] = "drift"
    with pytest.raises(DemoComposeError, match="references drift"):
        admit_rendered_demo_compose(rendered, image_references=references)
    rendered = _rendered()
    rendered["environment"] = {"NEX_OA_TEST_DATABASE_URL": "nuri1004"}
    with pytest.raises(DemoComposeError, match="forbidden database"):
        admit_rendered_demo_compose(rendered, image_references=references)


def test_release_report_rejects_failure_and_coverage_drift() -> None:
    with pytest.raises(DemoComposeError, match="not passing"):
        image_environment_from_release_report({"status": "FAIL"})
    report = _release_report()
    report["image_build"]["artifacts"].pop()
    with pytest.raises(DemoComposeError, match="coverage drift"):
        image_environment_from_release_report(report)


def test_installed_runtime_report_replaces_only_the_ae_image() -> None:
    image_id = "sha256:" + "a" * 64
    report = {
        "status": "PASS",
        "slice": "P8-DEMO-S10B",
        "base_image": "demo/nex-ae-runtime:current",
        "output_image": "demo/nex-ae-runtime:p8-demo-s10b",
        "bundle": {"status": "PASS"},
        "image": {
            "image_id": image_id,
            "repo_digests": [f"demo/nex-ae-runtime@{image_id}"],
        },
    }

    environment = image_environment_from_installed_runtime_reports(
        _release_report(), report
    )

    assert environment["NEX_AE_RUNTIME_IMAGE"] == (
        f"demo/nex-ae-runtime@{image_id}"
    )
    wc_digest = _references()["nex-wc-runtime"].rsplit("@", 1)[1]
    assert environment["NEX_WC_RUNTIME_IMAGE"] == f"demo/nex-wc-runtime@{wc_digest}"


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (lambda value: {**value, "status": "FAIL"}, "not passing"),
        (lambda value: {**value, "bundle": {"status": "FAIL"}}, "not admitted"),
        (lambda value: {**value, "base_image": "wrong"}, "base image drift"),
        (
            lambda value: {
                **value,
                "image": {**value["image"], "repo_digests": ["latest"]},
            },
            "mutable",
        ),
    ),
)
def test_installed_runtime_report_rejects_provenance_drift(mutation, message: str) -> None:
    image_id = "sha256:" + "a" * 64
    report = {
        "status": "PASS",
        "slice": "P8-DEMO-S10B",
        "base_image": "demo/nex-ae-runtime:current",
        "output_image": "demo/nex-ae-runtime:p8-demo-s10b",
        "bundle": {"status": "PASS"},
        "image": {
            "image_id": image_id,
            "repo_digests": [f"demo/nex-ae-runtime@{image_id}"],
        },
    }

    with pytest.raises(DemoComposeError, match=message):
        image_environment_from_installed_runtime_reports(
            _release_report(), mutation(report)
        )


def test_source_admission_contains_yaml_and_policy_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = demo_compose._read_text
    monkeypatch.setattr(
        demo_compose,
        "_read_text",
        lambda path: "[invalid" if path.name == "p8-demo.override.yaml" else original(path),
    )
    with pytest.raises(DemoComposeError, match="invalid YAML"):
        admit_demo_compose_sources(ROOT)

    monkeypatch.setattr(demo_compose, "_read_text", original)
    with pytest.raises(DemoComposeError, match="missing"):
        admit_demo_compose_sources(ROOT, overlay_path="missing.yaml")


def test_source_admission_reports_all_security_and_route_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    overlay = yaml.safe_load(
        (ROOT / "deployment/compose/p8-demo.override.yaml").read_text(encoding="utf-8")
    )
    dynamic = yaml.safe_load(
        (ROOT / "deployment/compose/traefik/p8-demo-dynamic.yaml").read_text(
            encoding="utf-8"
        )
    )
    overlay["name"] = "wrong"
    service = overlay["services"]["nex-wc"]
    service.update(
        {
            "restart": "no",
            "read_only": False,
            "cap_drop": [],
            "ports": ["8106:8106"],
            "command": ["bad"],
            "image": "missing",
        }
    )
    overlay["services"]["nex-eos"]["image"] = "missing"
    overlay["services"]["nex-wc-event-delivery-worker"].update(
        {"image": "missing", "command": ["bad"]}
    )
    overlay["services"]["nex-eos-outbox-publisher"]["image"] = "missing"
    overlay["secrets"] = {}
    overlay["NEX_OA_TEST_DATABASE_URL"] = "nuri1004"
    wc_router = dynamic["http"]["routers"].pop("wc")
    wc_router.update({"service": "bad", "tls": None})
    dynamic["http"]["routers"]["wc"] = wc_router
    dynamic["http"]["services"]["wc"] = {
        "loadBalancer": {"servers": [{"url": "http://wrong:1"}]}
    }

    def source(path: Path) -> str:
        value = overlay if path.name == "p8-demo.override.yaml" else dynamic
        return yaml.safe_dump(value, sort_keys=False)

    monkeypatch.setattr(demo_compose, "_read_text", source)
    with pytest.raises(DemoComposeError) as raised:
        admit_demo_compose_sources(ROOT)

    detail = str(raised.value)
    for message in (
        "project name drift",
        "restart policy drift",
        "read-only policy drift",
        "capability policy drift",
        "host port is forbidden",
        "worker command drift",
        "image input missing",
        "owner secret missing",
        "raw database credential",
        "route coverage or order drift",
        "TLS route drift",
        "upstream drift",
    ):
        assert message in detail


def test_mapping_helpers_fail_closed() -> None:
    with pytest.raises(DemoComposeError, match="must be an object"):
        demo_compose._mapping([], "object")
    with pytest.raises(DemoComposeError, match="must be an array"):
        demo_compose._mapping({}, "array", sequence=True)


def test_protected_render_runner_with_fake_compose(
    tmp_path: Path,
) -> None:
    image_report = tmp_path / "images.json"
    image_report.write_text(json.dumps(_release_report()), encoding="utf-8")

    def execute(command, **kwargs):
        assert command[:2] == ("docker", "compose")
        assert kwargs["env"]["NEX_WC_RUNTIME_IMAGE"].startswith("local/")
        return subprocess.CompletedProcess(
            command, 0, yaml.safe_dump(_rendered()), ""
        )

    source = check.check_p8_demo_compose({}, execute=False, root=ROOT)
    result = check.check_p8_demo_compose(
        {check.EXECUTION_ENV: "1"},
        execute=True,
        root=ROOT,
        image_report_path=image_report,
        executor=execute,
    )

    assert source["status"] == "SOURCE_ADMITTED"
    assert result["status"] == "PASS"
    assert result["render"]["service_count"] == 15
    assert result["secret_included"] is False


def test_render_runner_contains_failures_and_cli(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    image_report = tmp_path / "images.json"
    image_report.write_text("{}", encoding="utf-8")
    result = check.check_p8_demo_compose(
        {check.EXECUTION_ENV: "1"},
        execute=True,
        root=ROOT,
        image_report_path=image_report,
    )
    assert result["status"] == "FAIL"
    assert result["secret_included"] is False
    assert "p8_demo_compose=fail" in check.summary_line(result)

    passing_images = tmp_path / "passing-images.json"
    passing_images.write_text(json.dumps(_release_report()), encoding="utf-8")
    failed_render = check.check_p8_demo_compose(
        {check.EXECUTION_ENV: "1"},
        execute=True,
        root=ROOT,
        image_report_path=passing_images,
        executor=lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 1, "", "blocked"
        ),
    )
    assert failed_render["status"] == "FAIL"

    passing = {
        "status": "PASS",
        "rendered": True,
        "render": {"service_count": 15, "image_count": 8},
    }
    monkeypatch.setattr(check, "check_p8_demo_compose", lambda **_kwargs: passing)
    report = tmp_path / "report.json"
    assert check.main(["--report", str(report), "--summary"]) == 0
    assert "p8_demo_compose=pass" in capsys.readouterr().out
    assert json.loads(report.read_text(encoding="utf-8")) == passing
