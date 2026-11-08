import { describe, expect, it } from "vitest";

import viteConfig from "../../vite.config";

describe("modern Vite foundation", () => {
  it("builds the modern entry independently from the legacy application", () => {
    expect(viteConfig).toMatchObject({
      build: {
        outDir: "dist-v2",
        rollupOptions: {
          input: "modern.html",
        },
      },
    });
  });
});
