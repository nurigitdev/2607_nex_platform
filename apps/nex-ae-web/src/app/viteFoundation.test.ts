import { describe, expect, it } from "vitest";

import viteConfig from "../../vite.config";

describe("modern Vite foundation", () => {
  it("builds the React production entry into the canonical distribution", () => {
    expect(viteConfig).toMatchObject({
      build: {
        outDir: "dist",
        rollupOptions: {
          input: "index.html",
        },
      },
    });
  });
});
