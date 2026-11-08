import { defineConfig } from "vitest/config";

export default defineConfig({
  server: process.env.AE_API_PROXY_TARGET
    ? {
        proxy: {
          "/ae-api": {
            target: process.env.AE_API_PROXY_TARGET,
            changeOrigin: true,
            rewrite: path => path.replace(/^\/ae-api/, ""),
          },
        },
      }
    : undefined,
  build: {
    emptyOutDir: true,
    outDir: "dist-v2",
    rollupOptions: {
      input: "modern.html",
    },
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    setupFiles: ["src/design-system/test/setup.ts"],
  },
});
