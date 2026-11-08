import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  AE_WEB_SESSION_IDENTITY_PRESENTATION_SCHEMA_VERSION,
  buildSessionIdentityPresentation
} from "../src/sessionIdentityPresentation.js";

describe("AE Web current-session identity presentation", () => {
  it("uses the credential account for an authenticated session", () => {
    const presentation = buildSessionIdentityPresentation({
      sessionState: {
        status: "authenticated",
        subjectRef: { type: "oa.user", id: "employee-1001" }
      },
      employeeId: " 1001 "
    });

    assert.deepEqual(presentation, {
      session_identity_presentation_schema_version:
        AE_WEB_SESSION_IDENTITY_PRESENTATION_SCHEMA_VERSION,
      visible: true,
      account: "1001",
      subjectRef: "employee-1001"
    });
  });

  it("falls back to the OA subject after a browser reload", () => {
    const presentation = buildSessionIdentityPresentation({
      sessionState: {
        status: "authenticated",
        subjectRef: { type: "oa.user", id: "employee-1001" }
      }
    });

    assert.equal(presentation.visible, true);
    assert.equal(presentation.account, "employee-1001");
  });

  it("does not expose an identity for anonymous sessions", () => {
    const presentation = buildSessionIdentityPresentation({
      sessionState: {
        status: "anonymous",
        subjectRef: { type: "oa.user", id: "must-not-render" }
      },
      employeeId: "1001"
    });

    assert.equal(presentation.visible, false);
    assert.equal(presentation.account, "");
    assert.equal(presentation.subjectRef, "");
  });
});
