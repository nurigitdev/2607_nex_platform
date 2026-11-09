import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { auditModernProductionImports } from "../../../scripts/auditModernProductionImports.mjs";

describe("modern production import boundary", () => {
  it("does not depend on legacy test fixtures or golden harnesses", async () => {
    const result = await auditModernProductionImports({
      sourceRoot: join(process.cwd(), "src"),
    });

    expect(result.filesScanned).toBeGreaterThan(25);
    expect(result.violations).toEqual([]);
  });
});
