from __future__ import annotations

import json
import shutil
from copy import deepcopy
from pathlib import Path

import pytest
import run_s144_staging_trust_rehearsal as runner
import yaml
from nex_runtime.s144_staging import (
    OIDC_CALLBACK,
    S144StagingError,
    configure_openbao_s144_trust,
    refresh_openbao_s144_transit_credentials,
    validate_s144_compose_assets,
)

ROOT = Path(__file__).resolve().parents[1]


class FakeClient:
    def __init__(self) -> None:
        self.requests = []
        self.key_data = {
            "type": "rsa-3072",
            "latest_version": 1,
            "derived": False,
            "exportable": False,
            "allow_plaintext_backup": False,
        }
        self.client_data = {
            "client_id": "GSDTnn3KaOrLpNlVGlYLS9TVsZgOTweO",
            "client_secret": "client-" + "credential-" + "x" * 32,
            "client_type": "confidential",
            "redirect_uris": [OIDC_CALLBACK],
            "assignments": ["allow_all"],
        }
        self.kv_version: object = 1
        self.provider_client_ids = [self.client_data["client_id"]]

    def request(self, method, path, *, token=None, payload=None):
        self.requests.append((method, path, token, deepcopy(payload)))
        if path == "/v1/transit/keys/oa-signing" and method == "GET":
            return {"data": deepcopy(self.key_data)}
        if (
            path == "/v1/identity/oidc/client/nex-platform-oa-staging"
            and method == "GET"
        ):
            return {"data": deepcopy(self.client_data)}
        if path.endswith("NEX_OA_OIDC_CLIENT_SECRET"):
            return {"data": {"version": self.kv_version}}
        if path == "/v1/identity/oidc/provider/nex-platform" and method == "GET":
            return {"data": {"allowed_client_ids": self.provider_client_ids}}
        if path.endswith("/role-id"):
            return {"data": {"role_id": "transit-role-id-12345678"}}
        if path.endswith("/secret-id"):
            return {"data": {"secret_id": "transit-secret-id-12345678"}}
        return {}


def _copy_compose(tmp_path: Path) -> Path:
    target = tmp_path / "root/deployment/compose"
    target.parent.mkdir(parents=True)
    shutil.copytree(ROOT / "deployment/compose", target)
    return tmp_path / "root"


def test_s144_compose_override_is_value_free_and_single_host() -> None:
    result = validate_s144_compose_assets(ROOT)

    assert result == {
        "schema_version": "s144_staging_trust_federation.v1",
        "status": "VALID",
        "base_schema_version": "s143_external_staging.v1",
        "orchestrator": "docker-compose-single-host",
        "override_service_count": 3,
        "tls_route_count": 10,
        "oidc_secret_reference_count": 1,
        "transit_runtime_secret_count": 2,
        "openbao_ui_enabled": True,
        "identity_network_internal": True,
        "host_software_install_required": False,
        "raw_secret_values_included": False,
    }


@pytest.mark.parametrize(
    ("path", "old", "new", "message"),
    (
        (
            "deployment/compose/s144-staging.override.yaml",
            "  identity:\n    internal: true",
            "  identity:\n    internal: false",
            "identity network",
        ),
        (
            "deployment/compose/s144-staging.override.yaml",
            "NEX_OA_TRANSIT_ROLE_ID_FILE: /run/secrets/openbao_transit_role_id",
            "NEX_OA_TRANSIT_ROLE_ID_FILE: /run/secrets/missing",
            "OA trust",
        ),
        (
            "deployment/compose/s144-staging.override.yaml",
            "NEX_OA_SIGNING_PROVIDER: OPENBAO_TRANSIT",
            "NEX_OA_SIGNING_PROVIDER: UNAVAILABLE",
            "OA trust",
        ),
        (
            "deployment/compose/s144-staging.override.yaml",
            "id.nex-staging.test",
            "other.nex-staging.test",
            "identity route",
        ),
        (
            "deployment/compose/s144-staging.override.yaml",
            "  openbao:\n    volumes:",
            "  openbao:\n    privileged: true\n    volumes:",
            "privilege",
        ),
        (
            "deployment/compose/s144-staging.override.yaml",
            "../compose/openbao/s144-config.hcl:/openbao/config/config.hcl:ro",
            "../compose/openbao/config.hcl:/openbao/config/config.hcl:ro",
            "configuration override",
        ),
        (
            "deployment/compose/s144-staging.override.yaml",
            "${NEX_S144_OIDC_CLIENT_ID:?OpenBao generated OIDC client id is required}",
            "fixed-client-id",
            "generated OIDC client id",
        ),
        (
            "deployment/compose/s144-staging.override.yaml",
            "secret://openbao/nex-platform/staging/nex-oa/",
            "secret://other/nex-platform/staging/nex-oa/",
            "secret reference",
        ),
        (
            "deployment/compose/openbao/s144-config.hcl",
            "ui = true",
            "ui = false",
            "UI",
        ),
        (
            "deployment/compose/traefik/s144-dynamic.yaml",
            "rootCAs: [/run/secrets/openbao_ca]",
            "rootCAs: []",
            "managed identity",
        ),
    ),
)
def test_s144_compose_assets_reject_drift(tmp_path, path, old, new, message) -> None:
    root = _copy_compose(tmp_path)
    target = root / path
    value = target.read_text(encoding="utf-8")
    assert old in value
    target.write_text(value.replace(old, new, 1), encoding="utf-8")

    with pytest.raises(S144StagingError, match=message):
        validate_s144_compose_assets(root)


def test_openbao_trust_configuration_is_policy_isolated_and_value_free() -> None:
    client = FakeClient()
    result = configure_openbao_s144_trust(
        client,
        root_token="root-" + "x" * 24,
    )

    assert result["status"] == "CONFIGURED"
    assert result["transit_key_version"] == 1
    assert result["transit_role_name"] == "nex-oa-transit-staging"
    assert result["oidc_secret_version"] == 1
    assert result["oidc_client_secret_included"] is False
    assert result["oidc_client_secret_reference_included"] is False
    assert client.client_data["client_secret"] not in json.dumps(result)
    policy_request = next(
        item for item in client.requests if item[1].endswith("nex-oa-transit-staging")
    )
    policy = policy_request[3]["policy"]
    assert 'path "transit/sign/oa-signing/sha2-256"' in policy
    assert 'capabilities = ["update"]' in policy
    assert "transit/keys/oa-signing/rotate" not in policy
    assert "kv/data/" not in policy
    role_request = next(
        item
        for item in client.requests
        if item[1].endswith("role/nex-oa-transit-staging")
    )
    assert role_request[3]["secret_id_num_uses"] == 0
    assert role_request[3]["secret_id_ttl"] == "24h"
    client_request = next(
        item
        for item in client.requests
        if item[1].endswith("client/nex-platform-oa-staging") and item[0] == "POST"
    )
    assert client_request[3]["redirect_uris"] == [OIDC_CALLBACK]
    assert client_request[3]["client_type"] == "confidential"


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (lambda client: client.key_data.update(type="rsa-2048"), "Transit"),
        (lambda client: setattr(client, "key_data", []), "Transit key response"),
        (lambda client: client.client_data.update(client_secret=""), "OIDC client"),
        (lambda client: setattr(client, "kv_version", True), "secret version"),
        (lambda client: setattr(client, "provider_client_ids", ["other"]), "binding"),
    ),
)
def test_openbao_trust_configuration_rejects_invalid_responses(
    mutation, message
) -> None:
    client = FakeClient()
    mutation(client)
    with pytest.raises(S144StagingError, match=message):
        configure_openbao_s144_trust(client, root_token="root-" + "x" * 24)


def test_openbao_trust_configuration_rejects_invalid_root_credential() -> None:
    with pytest.raises(S144StagingError, match="root credential"):
        configure_openbao_s144_trust(FakeClient(), root_token="short")
    with pytest.raises(S144StagingError, match="root credential"):
        configure_openbao_s144_trust(
            FakeClient(),
            root_token="x" * 4097,
        )


def test_transit_runtime_credentials_are_written_without_secret_projection(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime"
    (runtime / "credentials").mkdir(parents=True)
    client = FakeClient()

    result = refresh_openbao_s144_transit_credentials(
        client,
        root_token="root-" + "x" * 24,
        runtime_dir=runtime,
    )

    assert result["status"] == "REFRESHED"
    assert result["secret_id_included"] is False
    assert "transit-secret-id" not in json.dumps(result)
    assert (runtime / "credentials/nex-oa-transit.role-id").read_text().strip() == (
        "transit-role-id-12345678"
    )
    assert (runtime / "credentials/nex-oa-transit.secret-id").read_text().strip() == (
        "transit-secret-id-12345678"
    )
    assert (runtime / "credentials/nex-oa-transit.secret-id").stat().st_mode & 0o777 == 0o644


def test_transit_runtime_credentials_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(S144StagingError, match="root credential"):
        refresh_openbao_s144_transit_credentials(
            FakeClient(), root_token="short", runtime_dir=tmp_path
        )
    with pytest.raises(S144StagingError, match="directory"):
        refresh_openbao_s144_transit_credentials(
            FakeClient(), root_token="root-" + "x" * 24, runtime_dir=tmp_path
        )

    runtime = tmp_path / "runtime"
    (runtime / "credentials").mkdir(parents=True)

    class InvalidClient(FakeClient):
        def request(self, method, path, *, token=None, payload=None):
            if path.endswith("/secret-id"):
                return {"data": {"secret_id": "short"}}
            return super().request(method, path, token=token, payload=payload)

    with pytest.raises(S144StagingError, match="AppRole credential"):
        refresh_openbao_s144_transit_credentials(
            InvalidClient(),
            root_token="root-" + "x" * 24,
            runtime_dir=runtime,
        )


def test_rehearsal_runner_and_cli(monkeypatch, capsys) -> None:
    result = runner.run_s144_staging_trust_rehearsal()
    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["decision"]["topology"] == "docker-compose-single-host"
    assert runner.summary_line(result).startswith(
        "s144_staging_trust_rehearsal=pass checks=17/17"
    )

    monkeypatch.setattr(runner, "run_s144_staging_trust_rehearsal", lambda: result)
    assert runner.main(["--summary"]) == 0
    assert "next=1441" in capsys.readouterr().out

    failed = {**result, "status": "FAIL", "issues": ["x"]}
    assert runner.summary_line(failed) == "s144_staging_trust_rehearsal=fail issues=1"
    monkeypatch.setattr(
        runner,
        "run_s144_staging_trust_rehearsal",
        lambda: failed,
    )
    assert runner.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out


def test_s144_invalid_yaml_is_rejected(tmp_path) -> None:
    root = _copy_compose(tmp_path)
    (root / "deployment/compose/s144-staging.override.yaml").write_text(
        "services: [",
        encoding="utf-8",
    )
    with pytest.raises(S144StagingError, match="unreadable"):
        validate_s144_compose_assets(root)


def test_s144_invalid_service_document_is_rejected(tmp_path) -> None:
    root = _copy_compose(tmp_path)
    path = root / "deployment/compose/s144-staging.override.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["services"].pop("nex-oa")
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    with pytest.raises(S144StagingError, match="coverage"):
        validate_s144_compose_assets(root)


def test_s144_non_mapping_dynamic_document_is_rejected(tmp_path) -> None:
    root = _copy_compose(tmp_path)
    (root / "deployment/compose/traefik/s144-dynamic.yaml").write_text(
        "[]\n",
        encoding="utf-8",
    )
    with pytest.raises(S144StagingError, match="invalid"):
        validate_s144_compose_assets(root)
