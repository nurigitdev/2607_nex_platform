import assert from "node:assert/strict";
import test from "node:test";

import {
  AE_WEB_DEFAULT_VIEW,
  allowedApplicationViews,
  buildApplicationShellSummary,
  canAccessOperations,
  resolveApplicationShell,
  viewFromLocationHash
} from "../src/applicationShell.js";

function session(status = "authenticated", roles = ["employee"]) {
  return { status, roles };
}

test("anonymous and expired sessions expose only the authentication shell", () => {
  for (const status of ["anonymous", "expired"]) {
    const shell = resolveApplicationShell({
      sessionState: session(status),
      requestedView: "operations"
    });
    assert.equal(shell.authenticationVisible, true);
    assert.equal(shell.applicationVisible, false);
    assert.equal(shell.activeView, null);
    assert.deepEqual(shell.allowedViews, []);
  }
});

test("employee sessions default to workspace and cannot enter operations", () => {
  const shell = resolveApplicationShell({
    sessionState: session("authenticated", ["employee"]),
    requestedView: "operations"
  });
  assert.equal(shell.activeView, AE_WEB_DEFAULT_VIEW);
  assert.equal(shell.operationsVisible, false);
  assert.equal(shell.allowedViews.includes("approvals"), true);
  assert.equal(shell.allowedViews.includes("operations"), false);
});

test("admin and operator roles can enter the operations view case-insensitively", () => {
  for (const role of ["admin", "OPERATOR"]) {
    const state = session("authenticated", [role]);
    assert.equal(canAccessOperations(state), true);
    assert.equal(allowedApplicationViews(state).includes("operations"), true);
    assert.equal(
      resolveApplicationShell({ sessionState: state, requestedView: "operations" })
        .activeView,
      "operations"
    );
  }
});

test("unknown views fall back to workspace without broadening access", () => {
  const shell = resolveApplicationShell({
    sessionState: session(),
    requestedView: "internal-service-map"
  });
  assert.equal(shell.activeView, "workspace");
  assert.equal(shell.operationsVisible, false);
});

test("hash parsing accepts only canonical application views", () => {
  assert.equal(viewFromLocationHash("#documents"), "documents");
  assert.equal(viewFromLocationHash("#OPERATIONS"), "operations");
  assert.equal(viewFromLocationHash("#credential-login-panel"), null);
  assert.equal(viewFromLocationHash(""), null);
});

test("shell summary contains routing metadata but no roles or identity", () => {
  const shell = resolveApplicationShell({
    sessionState: session("authenticated", ["admin"]),
    requestedView: "operations"
  });
  assert.deepEqual(buildApplicationShellSummary(shell), {
    application_shell_schema_version: "ae_web_application_shell.p8_s42a.v1",
    authenticated: true,
    active_view: "operations",
    allowed_view_count: 7,
    operations_visible: true,
    session_status: "authenticated"
  });
});
