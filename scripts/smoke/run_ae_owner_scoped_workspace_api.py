#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "services" / "nex-ae-api", ROOT / "services" / "_shared"):
    sys.path.insert(0, str(path))

from fastapi.testclient import TestClient  # noqa: E402
from nex_ae_api.workspace import WorkspaceStateStore, register_workspace_routes  # noqa: E402
from nex_runtime import (  # noqa: E402
    SERVICE_SPECS,
    build_service_app,
    issue_mock_user_token,
)


def run_owner_scoped_workspace_api_smoke() -> dict[str, Any]:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    store = WorkspaceStateStore()
    register_workspace_routes(app, store=store)
    client = TestClient(app)
    owner = _headers("tenant-a", "user-a")
    other = _headers("tenant-a", "user-b")

    created = client.post(
        "/api/v1/workspaces",
        json={"title": "Private workspace"},
        headers=owner,
    )
    body = created.json()
    workspace_id = body.get("workspace_id", "missing")
    owner_read = client.get(f"/api/v1/workspaces/{workspace_id}", headers=owner)
    owner_activity = client.get(
        f"/api/v1/workspaces/{workspace_id}/activity",
        headers=owner,
    )
    cross_owner_read = client.get(
        f"/api/v1/workspaces/{workspace_id}",
        headers=other,
    )
    mismatch = client.post(
        "/api/v1/workspaces",
        json={"title": "Mismatch", "owner_user_id": "user-b"},
        headers=owner,
    )
    checks = {
        "create_accepted": created.status_code == 200,
        "claim_tenant_applied": body.get("tenant_id") == "tenant-a",
        "claim_owner_applied": body.get("owner_user_id") == "user-a",
        "owner_read_accepted": owner_read.status_code == 200,
        "owner_activity_ordered": owner_activity.status_code == 200
        and owner_activity.json()["activities"][0]["activity_type"]
        == "workspace.created",
        "cross_owner_hidden": cross_owner_read.status_code == 404,
        "payload_mismatch_rejected": mismatch.status_code == 403,
        "app_store_exposed": app.state.ae_workspace_store is store,
    }
    return {
        "smoke_schema_version": "ae_owner_scoped_workspace_api_smoke.v1",
        "slice": "1016",
        "requirement": "S102",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "workspace_count": len(store.workspaces),
        "activity_count": len(store.activities_by_workspace.get(workspace_id, [])),
        "private_content_included": False,
        "postgres_required": False,
    }


def summary_line(result: Mapping[str, Any]) -> str:
    passed = sum(bool(value) for value in result.get("checks", {}).values())
    total = len(result.get("checks", {}))
    return (
        "ae_owner_scoped_workspace_api="
        f"{str(result.get('status', 'FAIL')).lower()} checks={passed}/{total} "
        f"workspaces={result.get('workspace_count', 0)} "
        f"activities={result.get('activity_count', 0)}"
    )


def _headers(tenant_id: str, user_id: str) -> dict[str, str]:
    issued = issue_mock_user_token(tenant_id=tenant_id, user_id=user_id)
    return {"Authorization": f"Bearer {issued.access_token}"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_owner_scoped_workspace_api_smoke()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
