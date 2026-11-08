import { defineConfig } from "vitest/config";

export default defineConfig({
  build: {
    emptyOutDir: true,
    outDir: "dist-v2",
    rollupOptions: {
      input: "modern.html",
    },
  },
  test: {
    environment: "jsdom",
    include: ["src/app/**/*.test.ts", "src/app/**/*.test.tsx"],
  },
});
