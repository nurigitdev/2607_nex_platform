import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

import {
  AE_WEB_VOUCHER_ATTACHMENT_PLAYWRIGHT_SCHEMA_VERSION,
  formatVoucherAttachmentSummary
} from "../scripts/runVoucherAttachmentPlaywrightSmoke.mjs";

const PACKAGE = JSON.parse(
  readFileSync(new URL("../package.json", import.meta.url), "utf-8")
);

describe("P8-S75G Voucher attachment Playwright contract", () => {
  it("registers the authenticated multiple-file smoke", () => {
    assert.equal(
      PACKAGE.scripts["smoke:voucher-attachment-playwright"],
      "node scripts/runVoucherAttachmentPlaywrightSmoke.mjs --summary"
    );
    assert.equal(
      AE_WEB_VOUCHER_ATTACHMENT_PLAYWRIGHT_SCHEMA_VERSION,
      "ae_web_voucher_attachment_playwright.p8.v1"
    );
  });

  it("formats metadata-only evidence", () => {
    assert.equal(
      formatVoucherAttachmentSummary({
        status: "PASS",
        observations: { selected_file_count: 3, locked_file_count: 3 },
        checks: { one: true, two: true }
      }),
      "p8_s75g_voucher_attachment_playwright=pass selected=3 locked=3 checks=2"
    );
    assert.match(
      formatVoucherAttachmentSummary({ status: "FAIL", observations: {}, checks: {} }),
      /playwright=fail/
    );
  });
});
