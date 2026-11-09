import { readFile } from "node:fs/promises";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  contrastRatio,
  generateDesignTokenCss,
  resolveSemanticColor,
  validateDesignTokens,
} from "../../../scripts/designTokens.mjs";

async function loadTokens() {
  return JSON.parse(
    await readFile(
      join(process.cwd(), "src/design-system/tokens/tokens.json"),
      "utf8",
    ),
  );
}

describe("NeX design token v1", () => {
  it("validates canonical structure, references, and unique variables", async () => {
    const result = validateDesignTokens(await loadTokens());

    expect(result).toEqual({
      primitiveCount: 63,
      semanticCount: 38,
      cssVariableCount: 146,
      componentCount: 15,
    });
  });

  it("reproduces application and admitted CSS without drift", async () => {
    const tokens = await loadTokens();
    const generated = generateDesignTokenCss(tokens);
    const applicationCss = await readFile(
      join(process.cwd(), "src/design-system/tokens/tokens.css"),
      "utf8",
    );
    const admittedCss = await readFile(
      join(process.cwd(), "../../docs/transition/UIUX/tokens.css"),
      "utf8",
    );

    expect(applicationCss).toBe(generated);
    expect(admittedCss).toBe(generated);
  });

  it.each(["light", "dark"])(
    "meets WCAG AA text contrast for the %s semantic palette",
    async theme => {
      const tokens = await loadTokens();
      const combinations = [
        ["text-primary", "bg-surface"],
        ["text-secondary", "bg-surface"],
        ["accent-text", "accent-subtle"],
        ["success-fg", "success-bg"],
        ["warning-fg", "warning-bg"],
        ["danger-fg", "danger-bg"],
        ["info-fg", "info-bg"],
        ["pending-fg", "pending-bg"],
      ];

      for (const [foreground, background] of combinations) {
        expect(
          contrastRatio(
            resolveSemanticColor(tokens, foreground, theme),
            resolveSemanticColor(tokens, background, theme),
          ),
          `${foreground} on ${background}`,
        ).toBeGreaterThanOrEqual(4.5);
      }
    },
  );

  it("rejects unresolved references, drift, duplicates, and malformed dimensions", async () => {
    const source = await loadTokens();

    const unresolved = structuredClone(source);
    unresolved.semantic.accent.ref.light = "missing-blue";
    expect(() => validateDesignTokens(unresolved)).toThrow(
      "references an unknown primitive",
    );

    const drifted = structuredClone(source);
    drifted.semantic.accent.light = "#FFFFFF";
    expect(() => validateDesignTokens(drifted)).toThrow(
      "does not match its primitive",
    );

    const duplicate = structuredClone(source);
    duplicate.component.push(structuredClone(duplicate.component[0]));
    expect(() => validateDesignTokens(duplicate)).toThrow(
      "Duplicate component token",
    );

    const malformed = structuredClone(source);
    malformed.layout["sidebar-width"] = "wide";
    expect(() => validateDesignTokens(malformed)).toThrow(
      "layout.sidebar-width is invalid",
    );

    expect(() => resolveSemanticColor(source, "unknown", "light")).toThrow(
      "Unknown semantic color request",
    );
  });
});
