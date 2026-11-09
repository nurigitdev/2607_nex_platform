import { readFile } from "node:fs/promises";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

describe("design system style contract", () => {
  it("uses canonical tokens instead of component-local colors", async () => {
    const componentCss = await readFile(
      join(process.cwd(), "src/design-system/components/components.module.css"),
      "utf8",
    );
    const tokenCss = await readFile(
      join(process.cwd(), "src/design-system/tokens/tokens.css"),
      "utf8",
    );

    expect(componentCss).not.toMatch(/#[0-9a-f]{3,8}\b/i);
    expect(componentCss).not.toMatch(/\brgba?\(/i);
    expect(componentCss).toContain("var(--nex-accent)");
    expect(componentCss).toContain("var(--nex-border-focus)");
    expect(tokenCss).toContain(':root[data-theme="dark"]');
    expect(tokenCss).toContain("prefers-reduced-motion: reduce");
  });
});
