import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  AE_WEB_REPAIRED_RESPONSE_DECISION_STATE_SCHEMA_VERSION,
  buildRepairedResponseDecisionStateSummary,
  createRepairedResponseDecisionState,
  markRepairedResponseDecisionFailed,
  markRepairedResponseDecisionRecorded,
  markRepairedResponseDecisionSubmitting
} from "../src/repairedResponseDecisionState.js";

describe("AE Web repaired response decision UI state", () => {
  it("creates a safe ready state summary", () => {
    const state = createRepairedResponseDecisionState();
    const summary = buildRepairedResponseDecisionStateSummary(state);

    assert.equal(
      state.decision_state_schema_version,
      AE_WEB_REPAIRED_RESPONSE_DECISION_STATE_SCHEMA_VERSION
    );
    assert.equal(summary.status, "READY_FOR_DECISION");
    assert.equal(summary.action, null);
    assert.equal(summary.metadata.rawPromptRendered, false);
    assert.doesNotMatch(
      JSON.stringify(summary),
      /raw_prompt|raw_generation_output|source_text|service_token/
    );
  });

  it("moves through submitting and recorded states", () => {
    const ready = createRepairedResponseDecisionState({ clientMode: "fetch" });
    const submitting = markRepairedResponseDecisionSubmitting(
      ready,
      "accept_repair"
    );
    const recorded = markRepairedResponseDecisionRecorded(submitting, {
      action: "accept_repair",
      repairedResponseDecisionId: "decision-001",
      clientMode: "fetch"
    });

    assert.equal(submitting.status, "SUBMITTING");
    assert.equal(submitting.action, "accept_repair");
    assert.equal(submitting.clientMode, "fetch");
    assert.equal(recorded.status, "RECORDED");
    assert.equal(recorded.decisionId, "decision-001");
    assert.equal(recorded.errorStatus, null);
  });

  it("records failed states without losing retry context", () => {
    const ready = createRepairedResponseDecisionState();
    const failed = markRepairedResponseDecisionFailed(
      ready,
      "keep_original",
      { status: "NETWORK_ERROR" },
      "mock"
    );
    const fallback = markRepairedResponseDecisionFailed(ready, "archive", null);

    assert.equal(failed.status, "FAILED");
    assert.equal(failed.action, "keep_original");
    assert.equal(failed.errorStatus, "NETWORK_ERROR");
    assert.equal(fallback.action, null);
    assert.equal(
      fallback.errorStatus,
      "REPAIRED_RESPONSE_DECISION_FAILED"
    );
  });

  it("normalizes unsupported values and rejects invalid state summaries", () => {
    const normalized = createRepairedResponseDecisionState({
      status: "UNKNOWN",
      action: "archive",
      clientMode: "live"
    });

    assert.equal(normalized.status, "READY_FOR_DECISION");
    assert.equal(normalized.action, null);
    assert.equal(normalized.clientMode, "mock");
    assert.throws(
      () => buildRepairedResponseDecisionStateSummary({}),
      /decision state is invalid/
    );
  });
});
