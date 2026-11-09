import { access, readdir, readFile } from "node:fs/promises";
import { extname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const APP_ROOT = fileURLToPath(new URL("..", import.meta.url));
const RETIRED_PATHS = Object.freeze([
  "modern.html",
  "scripts/promoteModernBuild.mjs",
  "src/main.js",
  "src/styles.css",
  "src/approvalUi.js",
  "src/artifactCard.js",
  "src/voucherAttachmentUi.js",
]);
const RETIRED_SYMBOLS = Object.freeze([
  "renderInteractionAgentResult",
  "renderArtifactDownloadFormatSelector",
  "renderArtifactExportResultReadModel",
  "renderArtifactLibraryPanel",
  "renderArtifactPreviewPanel",
  "renderArtifactVersionPanel",
  "renderProjectMembershipBatchResult",
  "renderRepairedResponseReviewCard",
  "applyDocumentMessages",
  "viewFromLocationHash",
]);
const DIRECT_SERVICE_URL = /https?:\/\/(?:localhost|127\.0\.0\.1|0\.0\.0\.0|192\.168\.\d{1,3}\.\d{1,3})(?::\d+)?/i;

export async function auditLegacyUiRetirement({ appRoot = APP_ROOT } = {}) {
  const root = resolve(appRoot);
  const violations = [];

  for (const retiredPath of RETIRED_PATHS) {
    if (await exists(resolve(root, retiredPath))) {
      violations.push({ file: retiredPath, rule: "RETIRED_PATH_PRESENT" });
    }
  }

  const sourceRoot = resolve(root, "src");
  const sourceFiles = await collectSources(sourceRoot);
  for (const file of sourceFiles) {
    const source = await readFile(file, "utf8");
    for (const symbol of RETIRED_SYMBOLS) {
      if (source.includes(symbol)) {
        violations.push({ file: relative(root, file), rule: "RETIRED_RENDERER_REFERENCE", symbol });
      }
    }
  }

  const productionFiles = sourceFiles.filter(
    file => [".ts", ".tsx"].includes(extname(file)) && !file.includes(".test."),
  );
  for (const file of productionFiles) {
    const source = await readFile(file, "utf8");
    if (DIRECT_SERVICE_URL.test(source)) {
      violations.push({ file: relative(root, file), rule: "DIRECT_SERVICE_URL" });
    }
    if (/from\s+["'][^"']*(?:main\.js|styles\.css|approvalUi\.js|artifactCard\.js|voucherAttachmentUi\.js)["']/.test(source)) {
      violations.push({ file: relative(root, file), rule: "RETIRED_IMPORT" });
    }
  }

  const index = await readFile(resolve(root, "index.html"), "utf8");
  if (!index.includes('id="modern-root"') || !index.includes('/src/app/main.tsx')) {
    violations.push({ file: "index.html", rule: "REACT_ENTRY_REQUIRED" });
  }
  if (/credential-login-form|src\/main\.js|styles\.css/.test(index)) {
    violations.push({ file: "index.html", rule: "LEGACY_STATIC_MARKUP_PRESENT" });
  }
  if (!index.includes('"client_mode":"fetch"') || index.includes('"client_mode":"mock"')) {
    violations.push({ file: "index.html", rule: "IMPLICIT_MOCK_PRODUCTION" });
  }

  const packageJson = JSON.parse(await readFile(resolve(root, "package.json"), "utf8"));
  if (Object.hasOwn(packageJson.scripts ?? {}, "dev:legacy")) {
    violations.push({ file: "package.json", rule: "LEGACY_DEV_COMMAND_PRESENT" });
  }
  if ((packageJson.scripts?.["build:v2"] ?? "").includes("promoteModernBuild")) {
    violations.push({ file: "package.json", rule: "LEGACY_BUILD_PROMOTION_PRESENT" });
  }

  const viteConfig = await readFile(resolve(root, "vite.config.ts"), "utf8");
  if (!viteConfig.includes('input: "index.html"') || viteConfig.includes("modern.html")) {
    violations.push({ file: "vite.config.ts", rule: "NON_CANONICAL_VITE_ENTRY" });
  }

  return Object.freeze({
    filesScanned: sourceFiles.length + 3,
    violations: Object.freeze(violations),
  });
}

async function exists(path) {
  try {
    await access(path);
    return true;
  } catch {
    return false;
  }
}

async function collectSources(root) {
  const files = [];
  async function visit(directory) {
    const entries = await readdir(directory, { withFileTypes: true });
    for (const entry of entries) {
      const path = join(directory, entry.name);
      if (entry.isDirectory()) await visit(path);
      else if ([".js", ".ts", ".tsx"].includes(extname(entry.name)) && !entry.name.includes(".test.")) files.push(path);
    }
  }
  await visit(root);
  return files.sort();
}

async function main() {
  const result = await auditLegacyUiRetirement();
  if (result.violations.length > 0) {
    console.error(JSON.stringify(result, null, 2));
    process.exitCode = 1;
    return;
  }
  console.log(`legacy_ui_retirement_audit=pass files_scanned=${result.filesScanned}`);
}

if (process.argv[1] === fileURLToPath(import.meta.url)) await main();
