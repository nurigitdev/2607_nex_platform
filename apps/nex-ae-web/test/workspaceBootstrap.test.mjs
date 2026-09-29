import test from "node:test";
import assert from "node:assert/strict";

import {
  AE_WEB_WORKSPACE_BOOTSTRAP_SCHEMA_VERSION,
  WorkspaceBootstrapError,
  loadWorkspaceBootstrap
} from "../src/workspaceBootstrap.js";

function fixture(overrides = {}) {
  return {
    schema_version: AE_WEB_WORKSPACE_BOOTSTRAP_SCHEMA_VERSION,
    workspace_id: "7f4c34be-6d3f-4296-884d-b823904cf5df",
    chat_document_id: "6ba55095-00c3-42c5-9f67-f0699dd99617",
    ...overrides
  };
}

test("loads safe durable workspace lineage", () => {
  const result = loadWorkspaceBootstrap({
    windowRef: { __NEX_AE_WEB_WORKSPACE_BOOTSTRAP__: fixture() }
  });
  assert.equal(result.workspaceId, fixture().workspace_id);
  assert.equal(result.chatDocumentId, fixture().chat_document_id);
  assert.equal(result.metadata.ownerIdentityIncluded, false);
});

test("is optional and rejects unsupported or incomplete metadata", () => {
  assert.equal(loadWorkspaceBootstrap({ windowRef: {} }), null);
  assert.throws(
    () => loadWorkspaceBootstrap({
      windowRef: {
        __NEX_AE_WEB_WORKSPACE_BOOTSTRAP__: fixture({ database_url: "hidden" })
      }
    }),
    error => error instanceof WorkspaceBootstrapError &&
      error.status === "WORKSPACE_BOOTSTRAP_FIELD_UNSUPPORTED"
  );
  assert.throws(
    () => loadWorkspaceBootstrap({
      windowRef: {
        __NEX_AE_WEB_WORKSPACE_BOOTSTRAP__: fixture({ workspace_id: "" })
      }
    }),
    /required/
  );
});
