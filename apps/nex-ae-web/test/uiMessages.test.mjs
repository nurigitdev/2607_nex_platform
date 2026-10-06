import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  DEFAULT_LOCALE,
  applyDocumentMessages,
  message,
  normalizeLocale,
  statusMessage,
  validateCatalogParity
} from "../src/locales/messages.js";

describe("AE Web UI message contract", () => {
  it("uses Korean by default and keeps Korean and English catalogs in parity", () => {
    const parity = validateCatalogParity();

    assert.equal(DEFAULT_LOCALE, "ko");
    assert.equal(parity.valid, true);
    assert.ok(parity.keyCount >= 80);
    assert.deepEqual(parity.missingByLocale, { ko: [], en: [] });
    assert.deepEqual(parity.extraByLocale, { ko: [], en: [] });
    assert.equal(message("action.send"), "전송");
    assert.equal(message("action.send", { locale: "en-US" }), "Send");
  });

  it("normalizes supported locales and falls back to Korean", () => {
    assert.equal(normalizeLocale("ko-KR"), "ko");
    assert.equal(normalizeLocale("en_US"), "en");
    assert.equal(normalizeLocale("ja-JP"), "ko");
    assert.equal(normalizeLocale(), "ko");
  });

  it("formats values and preserves unresolved placeholders and unknown keys", () => {
    assert.equal(message("timeline.event_count", { values: { count: 3 } }), "3개 이벤트");
    assert.equal(
      message("timeline.event_count", { locale: "en", values: {} }),
      "{count} events"
    );
    assert.equal(
      message("missing.message", { values: { count: 3 } }),
      "missing.message"
    );
  });

  it("translates known statuses while preserving provider-safe unknown values", () => {
    assert.equal(statusMessage("READY_FOR_HANDOFF"), "전달 준비");
    assert.equal(statusMessage("FAILED", "en"), "Failed");
    assert.equal(statusMessage("PROVIDER_CUSTOM_STATE"), "PROVIDER_CUSTOM_STATE");
    assert.equal(statusMessage(""), "알 수 없음");
  });

  it("reports missing and extra locale keys", () => {
    const parity = validateCatalogParity({
      ko: { a: "가", b: "나" },
      en: { a: "A", c: "C" }
    });

    assert.equal(parity.valid, false);
    assert.deepEqual(parity.missingByLocale.en, ["b"]);
    assert.deepEqual(parity.extraByLocale.en, ["c"]);
  });

  it("applies text and accessible labels to a document-like root", () => {
    const textNode = fakeNode({ i18n: "nav.workspace" });
    const ariaNode = fakeNode({ i18nAriaLabel: "summary.label" });
    const titleNode = fakeNode({ i18nTitle: "action.refresh" });
    const nodes = new Map([
      ["[data-i18n]", [textNode]],
      ["[data-i18n-aria-label]", [ariaNode]],
      ["[data-i18n-title]", [titleNode]]
    ]);
    const root = {
      documentElement: { lang: "", dataset: {} },
      querySelectorAll: selector => nodes.get(selector) || []
    };

    const result = applyDocumentMessages(root, "en-US");

    assert.equal(result.locale, "en");
    assert.equal(result.catalog.valid, true);
    assert.equal(root.documentElement.lang, "en");
    assert.equal(root.documentElement.dataset.locale, "en");
    assert.equal(textNode.textContent, "Workspace");
    assert.equal(ariaNode.attributes["aria-label"], "Workspace status");
    assert.equal(titleNode.attributes.title, "Refresh");
  });

  it("accepts an absent or partial document root", () => {
    const result = applyDocumentMessages(null, "unsupported");
    assert.equal(result.locale, "ko");
    assert.equal(result.catalog.valid, true);

    const root = { querySelectorAll: () => [{ dataset: {} }] };
    assert.equal(applyDocumentMessages(root).locale, "ko");
  });
});

function fakeNode(dataset) {
  return {
    dataset,
    textContent: "",
    attributes: {},
    setAttribute(name, value) {
      this.attributes[name] = value;
    }
  };
}
