import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  AE_CHAT_RETRIEVAL_QUALITY_WARNING_SCHEMA_VERSION,
  AE_WEB_RETRIEVAL_QUALITY_WARNING_SURFACE_SCHEMA_VERSION,
  RetrievalQualityWarningSurfaceError,
  buildRetrievalQualityWarningSummary,
  buildRetrievalQualityWarningSurface,
  extractRetrievalQualityWarnings
} from "../src/retrievalQualityWarnings.js";

function structuredWarnings(overrides = {}) {
  return {
    contract_schema_version: "ae_chat_retrieval_quality_warning.v1",
    warning_count: 1,
    warning_kinds: ["tokenizer_fallback_used"],
    quality_flag_count: 1,
    quality_flag_kinds: ["debug_checked"],
    low_confidence_threshold: 0.2,
    best_score_below_threshold: false,
    status_caveat_required: true,
    recommended_action: "proceed_with_caveat",
    raw_warning_details_included: false,
    ...overrides
  };
}

describe("AE Web retrieval quality warning surface", () => {
  it("maps structured AE chat warning contracts to safe visible UI state", () => {
    const surface = buildRetrievalQualityWarningSurface({
      retrieval: {
        quality_warnings: structuredWarnings({
          warning_kinds: ["tokenizer_fallback_used:private-doc"],
          quality_flag_kinds: ["debug_checked:private-doc"]
        })
      }
    });
    const summary = buildRetrievalQualityWarningSummary(surface);

    assert.equal(
      surface.warning_surface_schema_version,
      AE_WEB_RETRIEVAL_QUALITY_WARNING_SURFACE_SCHEMA_VERSION
    );
    assert.equal(surface.source_schema_version, AE_CHAT_RETRIEVAL_QUALITY_WARNING_SCHEMA_VERSION);
    assert.equal(surface.visible, true);
    assert.equal(surface.severity, "warning");
    assert.equal(surface.recommended_action, "proceed_with_caveat");
    assert.deepEqual(surface.warning_kinds, ["tokenizer_fallback_used"]);
    assert.deepEqual(surface.quality_flag_kinds, ["debug_checked"]);
    assert.equal(summary.metadata.rawWarningDetailsIncluded, false);
    assert.doesNotMatch(JSON.stringify(surface), /private-doc|source_text|raw_prompt|service_token|provider_url/);
  });

  it("normalizes each recommended action into deterministic severity", () => {
    const proceed = buildRetrievalQualityWarningSurface(
      structuredWarnings({
        recommended_action: "proceed",
        warning_count: 0,
        warning_kinds: [],
        quality_flag_count: 0,
        quality_flag_kinds: [],
        status_caveat_required: false
      })
    );
    const ask = buildRetrievalQualityWarningSurface(
      structuredWarnings({ recommended_action: "ask_confirmation", best_score_below_threshold: true })
    );
    const noAnswer = buildRetrievalQualityWarningSurface({
      cxStatus: "NO_ANSWER"
    });
    const blocked = buildRetrievalQualityWarningSurface({
      status: "UNAVAILABLE"
    });

    assert.equal(proceed.visible, false);
    assert.equal(proceed.severity, "success");
    assert.equal(ask.visible, true);
    assert.equal(ask.severity, "warning");
    assert.equal(noAnswer.recommended_action, "show_no_answer");
    assert.equal(noAnswer.severity, "pending");
    assert.equal(blocked.recommended_action, "show_error");
    assert.equal(blocked.severity, "danger");
  });

  it("builds fallback caveats from legacy warning arrays", () => {
    const qualityWarnings = extractRetrievalQualityWarnings({
      warnings: [
        "source_summary_missing:private-doc",
        "source_summary_missing:private-doc",
        7
      ]
    });
    const surface = buildRetrievalQualityWarningSurface({
      warnings: ["source_summary_missing:private-doc"]
    });

    assert.equal(qualityWarnings.recommended_action, "proceed_with_caveat");
    assert.deepEqual(qualityWarnings.warning_kinds, ["source_summary_missing"]);
    assert.equal(surface.status_caveat_required, true);
    assert.equal(surface.warning_count, 1);
    assert.doesNotMatch(JSON.stringify(surface), /private-doc/);
  });

  it("keeps sparse or invalid inputs safe and rejects invalid summaries", () => {
    const empty = buildRetrievalQualityWarningSurface(null);
    const sparse = buildRetrievalQualityWarningSurface({
      quality_warnings: {
        recommended_action: "unknown",
        warning_count: -1,
        warning_kinds: ["", "permission_filtered:private-doc", 2],
        quality_flag_count: "many",
        quality_flag_kinds: ["low_source_confidence:private-doc"],
        low_confidence_threshold: true,
        raw_warning_details_included: true
      }
    });

    assert.equal(empty.recommended_action, "proceed");
    assert.equal(empty.visible, false);
    assert.equal(sparse.recommended_action, "proceed");
    assert.equal(sparse.warning_count, 1);
    assert.deepEqual(sparse.warning_kinds, ["permission_filtered"]);
    assert.equal(sparse.quality_flag_count, 1);
    assert.equal(sparse.low_confidence_threshold, null);
    assert.equal(sparse.metadata.rawWarningDetailsIncluded, false);
    assert.throws(
      () => buildRetrievalQualityWarningSummary({}),
      error =>
        error instanceof RetrievalQualityWarningSurfaceError &&
        error.status === "RETRIEVAL_QUALITY_WARNING_SUMMARY_INVALID"
    );
  });
});
