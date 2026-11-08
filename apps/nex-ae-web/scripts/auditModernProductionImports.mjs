import { readdir, readFile } from "node:fs/promises";
import { extname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const FORBIDDEN_PRODUCTION_IMPORTS = Object.freeze([
  "artifactMockRecord.js",
  "credentialLoginHarness.js",
  "deterministicGoldenJourney.js",
  "fetchModeHarness.js",
  "goldenJourneyArtifact.js",
  "goldenJourneyGrounding.js",
  "goldenJourneyIngestion.js",
  "goldenJourneyState.js",
  "goldenJourneyViewport.js",
]);

const SOURCE_EXTENSIONS = new Set([".ts", ".tsx"]);

export async function auditModernProductionImports({ sourceRoot } = {}) {
  const root = sourceRoot ?? fileURLToPath(new URL("../src", import.meta.url));
  const files = await collectProductionSources(root);
  const violations = [];

  for (const file of files) {
    const source = await readFile(file, "utf8");
    for (const forbiddenImport of FORBIDDEN_PRODUCTION_IMPORTS) {
      if (source.includes(forbiddenImport)) {
        violations.push({
          file: relative(root, file),
          forbiddenImport,
        });
      }
    }
  }

  return Object.freeze({
    filesScanned: files.length,
    violations: Object.freeze(violations),
  });
}

async function collectProductionSources(root) {
  const files = [];

  async function visit(directory) {
    const entries = await readdir(directory, { withFileTypes: true });
    for (const entry of entries) {
      const path = join(directory, entry.name);
      if (entry.isDirectory()) {
        await visit(path);
      } else if (
        SOURCE_EXTENSIONS.has(extname(entry.name)) &&
        !entry.name.includes(".test.")
      ) {
        files.push(path);
      }
    }
  }

  await visit(root);
  return files.sort();
}

async function main() {
  const result = await auditModernProductionImports();
  if (result.violations.length > 0) {
    console.error(JSON.stringify(result, null, 2));
    process.exitCode = 1;
    return;
  }
  console.log(
    `modern_production_import_audit=pass files_scanned=${result.filesScanned}`,
  );
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  await main();
}
