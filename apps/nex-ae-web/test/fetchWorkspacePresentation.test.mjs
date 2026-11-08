import assert from "node:assert/strict";
import test from "node:test";

import {
  AE_WEB_FETCH_WORKSPACE_PRESENTATION_SCHEMA_VERSION,
  FetchWorkspacePresentationError,
  buildFetchWorkspacePresentation
} from "../src/fetchWorkspacePresentation.js";

test("fetch workspace starts without mock Chat/RAG presentation state", () => {
  const presentation = buildFetchWorkspacePresentation();

  assert.equal(
    presentation.presentationSchemaVersion,
    AE_WEB_FETCH_WORKSPACE_PRESENTATION_SCHEMA_VERSION
  );
  assert.deepEqual(presentation.documents, []);
  assert.equal(presentation.selectedDocumentId, null);
  assert.deepEqual(presentation.messages, []);
  assert.deepEqual(presentation.progressEvents, [
    ["workspace.ready", "READY_FOR_PROMPT", "READY"]
  ]);
  assert.equal(presentation.artifact.handoffStatus, "NOT_REQUIRED");
  assert.equal(presentation.audit.resultStatus, "NOT_STARTED");
});

test("fetch workspace preserves only explicitly bootstrapped documents", () => {
  const documents = [{ documentId: "doc-live-1", filename: "live.pdf" }];
  const presentation = buildFetchWorkspacePresentation({ documents });

  assert.deepEqual(presentation.documents, documents);
  assert.notEqual(presentation.documents, documents);
  assert.equal(presentation.selectedDocumentId, "doc-live-1");
});

test("fetch workspace rejects an invalid document bootstrap", () => {
  assert.throws(
    () => buildFetchWorkspacePresentation({ documents: {} }),
    error =>
      error instanceof FetchWorkspacePresentationError &&
      error.status === "FETCH_WORKSPACE_PRESENTATION_INVALID"
  );
});
