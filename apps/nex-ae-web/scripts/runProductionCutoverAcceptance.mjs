#!/usr/bin/env node
import { readdir, readFile } from "node:fs/promises";
import { once } from "node:events";
import { resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { createAeWebServer } from "./serve.mjs";

export const PRODUCTION_CUTOVER_SCHEMA_VERSION = "ae_web_production_cutover.uxm_s20.v1";
const APP_ROOT = fileURLToPath(new URL("..", import.meta.url));
const ROOT = resolve(APP_ROOT, "../..");

export async function runProductionCutoverAcceptance({ appRoot = APP_ROOT, root = ROOT } = {}) {
  const dist = resolve(appRoot, "dist");
  const index = await readFile(resolve(dist, "index.html"), "utf8");
  const assets = await readdir(resolve(dist, "assets"));
  const containerfile = await readFile(resolve(root, "deployment/oci/ae-web.Containerfile"), "utf8");
  const server = createAeWebServer({ rootDir: dist, apiProxyTarget: "" });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const port = server.address().port;
  try {
    const base = `http://127.0.0.1:${port}`;
    const rootResponse = await fetch(`${base}/`);
    const rootHtml = await rootResponse.text();
    const routeResponse = await fetch(`${base}/approvals`);
    const modernResponse = await fetch(`${base}/modern.html`, { redirect: "manual" });
    const apiResponse = await fetch(`${base}/ae-api/api/v1/auth/session`);
    const checks = Object.freeze({
      dist_index_is_react: index.includes('id="modern-root"') && !index.includes("credential-login-form"),
      production_fetch_mode: index.includes('"client_mode":"fetch"') && index.includes('"ae_base_url":"/ae-api"'),
      root_serves_react: rootResponse.status === 200 && rootHtml === index,
      spa_fallback_serves_react: routeResponse.status === 200 && await routeResponse.text() === index,
      modern_route_redirected: modernResponse.status === 308 && modernResponse.headers.get("location") === "/",
      api_without_target_fails_closed: apiResponse.status === 503,
      hashed_assets_present: assets.some(name => /-[A-Za-z0-9_-]+\.(?:js|css)$/.test(name)),
      container_is_multistage: containerfile.includes("AS ae-web-build") && containerfile.includes("COPY --from=ae-web-build"),
      runtime_contains_dist_only: containerfile.includes("/build/apps/nex-ae-web/dist ./dist") && !containerfile.includes("apps/nex-ae-web/index.html ./index.html"),
      runtime_is_non_root: containerfile.includes("USER node") && containerfile.includes('CMD ["node", "scripts/serve.mjs"]'),
    });
    return Object.freeze({
      schemaVersion: PRODUCTION_CUTOVER_SCHEMA_VERSION,
      status: Object.values(checks).every(Boolean) ? "PASS" : "FAIL",
      observations: Object.freeze({ assetCount: assets.length, routeCount: 4 }),
      checks,
    });
  } finally {
    server.close();
    await once(server, "close");
  }
}

export function formatSummary(result) {
  return result.status === "PASS"
    ? `production_cutover_acceptance=pass assets=${result.observations.assetCount} checks=${Object.keys(result.checks).length}`
    : "production_cutover_acceptance=fail reason=checks_failed";
}

export async function main(argv = process.argv.slice(2), output = console.log) {
  try {
    const result = await runProductionCutoverAcceptance();
    output(argv.includes("--summary") ? formatSummary(result) : JSON.stringify(result, null, 2));
    return result.status === "PASS" ? 0 : 1;
  } catch (error) {
    output(`production_cutover_acceptance=fail error=${error?.constructor?.name ?? "Error"}`);
    return 1;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exitCode = await main();
}
