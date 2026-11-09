import assert from "node:assert/strict";
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import test from "node:test";

import { auditLegacyUiRetirement } from "../scripts/auditLegacyUiRetirement.mjs";

test("React is the sole AE Web production UI", async () => {
  const result = await auditLegacyUiRetirement();
  assert.equal(result.violations.length, 0, JSON.stringify(result.violations));
  assert.ok(result.filesScanned > 0);
});

test("legacy UI retirement audit rejects retired files and renderer references", async () => {
  const appRoot = await mkdtemp(join(tmpdir(), "nex-ae-web-legacy-audit-"));
  try {
    await mkdir(join(appRoot, "src", "app"), { recursive: true });
    await writeFile(join(appRoot, "src", "app", "main.tsx"), "renderArtifactLibraryPanel();\n", "utf8");
    await writeFile(join(appRoot, "src", "main.js"), "legacy();\n", "utf8");
    await writeFile(join(appRoot, "index.html"), '<div id="modern-root"></div><script src="/src/app/main.tsx"></script>', "utf8");
    await writeFile(join(appRoot, "package.json"), JSON.stringify({ scripts: { "build:v2": "vite build" } }), "utf8");
    await writeFile(join(appRoot, "vite.config.ts"), 'input: resolve(APP_ROOT, "index.html")', "utf8");

    const result = await auditLegacyUiRetirement({ appRoot });
    assert.ok(result.violations.some(item => item.rule === "RETIRED_PATH_PRESENT"));
    assert.ok(result.violations.some(item => item.rule === "RETIRED_RENDERER_REFERENCE"));
  } finally {
    await rm(appRoot, { recursive: true, force: true });
  }
});
