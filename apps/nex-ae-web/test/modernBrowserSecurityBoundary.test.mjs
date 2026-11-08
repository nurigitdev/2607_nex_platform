import assert from "node:assert/strict";
import test from "node:test";

import { auditModernBrowserSecurityBoundary } from "../scripts/auditModernBrowserSecurityBoundary.mjs";

test("modern production sources preserve the same-origin browser security boundary", async () => {
  const result = await auditModernBrowserSecurityBoundary();
  assert.equal(result.violations.length, 0, JSON.stringify(result.violations));
  assert.ok(result.filesScanned > 0);
});
