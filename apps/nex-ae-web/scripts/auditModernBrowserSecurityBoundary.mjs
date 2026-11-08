import { readdir, readFile } from "node:fs/promises";
import { extname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const SOURCE_EXTENSIONS = new Set([".ts", ".tsx"]);
const FORBIDDEN_PATTERNS = Object.freeze([
  {
    id: "DIRECT_INTERNAL_SERVICE_URL",
    pattern: /https?:\/\/(?:localhost|127\.0\.0\.1|0\.0\.0\.0|192\.168\.\d{1,3}\.\d{1,3})(?::\d+)?/i,
  },
  {
    id: "DIRECT_PLATFORM_SERVICE_PORT",
    pattern: /:(?:8101|8102|8103|8104|8105)(?:\b|\/)/,
  },
  {
    id: "BROWSER_SERVICE_TOKEN_CONFIG",
    pattern: /(?:NEX_[A-Z0-9_]*SERVICE_TOKEN|service_token\s*[=:]\s*["'])/i,
  },
  {
    id: "BROWSER_API_KEY_CONFIG",
    pattern: /(?:NEX_[A-Z0-9_]*API_KEY|api_key\s*[=:]\s*["'])/i,
  },
]);

export async function auditModernBrowserSecurityBoundary({
  sourceRoot,
  htmlPath,
} = {}) {
  const root = sourceRoot ?? fileURLToPath(new URL("../src", import.meta.url));
  const entry = htmlPath ?? fileURLToPath(new URL("../index.html", import.meta.url));
  const files = await collectProductionSources(root);
  files.push(entry);
  const violations = [];

  for (const file of files) {
    const source = await readFile(file, "utf8");
    for (const rule of FORBIDDEN_PATTERNS) {
      if (rule.pattern.test(source)) {
        violations.push({
          file: file === entry ? "index.html" : relative(root, file),
          rule: rule.id,
        });
      }
    }
  }

  const html = await readFile(entry, "utf8");
  if (!html.includes('"client_mode":"fetch"')) {
    violations.push({ file: "index.html", rule: "FETCH_MODE_REQUIRED" });
  }
  if (!html.includes('"ae_base_url":"/ae-api"')) {
    violations.push({ file: "index.html", rule: "AE_FACADE_REQUIRED" });
  }
  if (!html.includes('"fetch_clients_enabled":true')) {
    violations.push({ file: "index.html", rule: "FETCH_FLAG_REQUIRED" });
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
      if (entry.isDirectory()) await visit(path);
      else if (SOURCE_EXTENSIONS.has(extname(entry.name)) && !entry.name.includes(".test.")) {
        files.push(path);
      }
    }
  }
  await visit(root);
  return files.sort();
}

async function main() {
  const result = await auditModernBrowserSecurityBoundary();
  if (result.violations.length > 0) {
    console.error(JSON.stringify(result, null, 2));
    process.exitCode = 1;
    return;
  }
  console.log(`modern_browser_security_audit=pass files_scanned=${result.filesScanned}`);
}

if (process.argv[1] === fileURLToPath(import.meta.url)) await main();
