#!/usr/bin/env node
import { readFile, rename, rm } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const APP_ROOT = fileURLToPath(new URL("..", import.meta.url));

export async function promoteModernBuild({ rootDir = APP_ROOT } = {}) {
  const outputDir = resolve(rootDir, "dist");
  const modernPath = resolve(outputDir, "modern.html");
  const indexPath = resolve(outputDir, "index.html");
  const html = await readFile(modernPath, "utf8");
  if (!html.includes('"client_mode":"fetch"') || !html.includes('"ae_base_url":"/ae-api"')) {
    throw new Error("Production browser config must use fetch mode through /ae-api");
  }
  if (!html.includes('id="modern-root"') || /credential-login-form|src\/main\.js/.test(html)) {
    throw new Error("Production build does not contain the admitted React root");
  }
  await rm(indexPath, { force: true });
  await rename(modernPath, indexPath);
  return Object.freeze({ outputDir, indexPath, modernPathRemoved: true });
}

export async function main(output = console.log) {
  try {
    const result = await promoteModernBuild();
    output(`modern_build_promotion=pass output=${result.indexPath}`);
    return 0;
  } catch (error) {
    output(`modern_build_promotion=fail error=${error?.constructor?.name ?? "Error"}`);
    return 1;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exitCode = await main();
}
