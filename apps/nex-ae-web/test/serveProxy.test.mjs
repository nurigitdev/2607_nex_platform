import assert from "node:assert/strict";
import { createServer } from "node:http";
import { once } from "node:events";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, it } from "node:test";

import {
  AE_API_PROXY_PREFIX,
  createAeWebServer,
  cacheControlFor,
  isProxyPath
} from "../scripts/serve.mjs";

async function staticFixture() {
  const root = await mkdtemp(join(tmpdir(), "ae-web-static-"));
  await mkdir(join(root, "assets"));
  await writeFile(join(root, "index.html"), '<div id="modern-root"></div>', "utf8");
  await writeFile(join(root, "assets", "app-abc123.js"), "export {};", "utf8");
  return root;
}

async function listen(server) {
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  return server.address().port;
}

async function close(server) {
  server.close();
  await once(server, "close");
}

describe("AE Web dev server same-origin proxy", () => {
  it("keeps proxy path matching explicit to /ae-api", () => {
    assert.equal(AE_API_PROXY_PREFIX, "/ae-api");
    assert.equal(isProxyPath("/ae-api"), true);
    assert.equal(isProxyPath("/ae-api/api/v1/auth/session"), true);
    assert.equal(isProxyPath("/not-ae-api/api/v1/auth/session"), false);
  });

  it("serves static files when proxy target is not configured", async () => {
    const rootDir = await staticFixture();
    const server = createAeWebServer({ rootDir, apiProxyTarget: "" });
    const port = await listen(server);
    try {
      const response = await fetch(`http://127.0.0.1:${port}/`);
      const body = await response.text();

      assert.equal(response.status, 200);
      assert.match(body, /modern-root/);
      assert.equal(response.headers.get("cache-control"), "no-cache, no-store, must-revalidate");
    } finally {
      await close(server);
      await rm(rootDir, { recursive: true, force: true });
    }
  });

  it("supports SPA fallback, modern redirect, immutable assets, and API fail-closed", async () => {
    const rootDir = await staticFixture();
    const server = createAeWebServer({ rootDir, apiProxyTarget: "" });
    const port = await listen(server);
    try {
      const navigation = await fetch(`http://127.0.0.1:${port}/approvals`);
      assert.match(await navigation.text(), /modern-root/);

      const redirect = await fetch(`http://127.0.0.1:${port}/modern.html`, { redirect: "manual" });
      assert.equal(redirect.status, 308);
      assert.equal(redirect.headers.get("location"), "/");

      const asset = await fetch(`http://127.0.0.1:${port}/assets/app-abc123.js`);
      assert.equal(asset.headers.get("cache-control"), "public, max-age=31536000, immutable");
      assert.equal(asset.headers.get("content-type"), "text/javascript; charset=utf-8");

      const unavailable = await fetch(`http://127.0.0.1:${port}/ae-api/api/v1/auth/session`);
      assert.equal(unavailable.status, 503);
      assert.deepEqual(await unavailable.json(), { error_code: "ae_web_proxy_target_unavailable" });
    } finally {
      await close(server);
      await rm(rootDir, { recursive: true, force: true });
    }
  });

  it("freezes safe cache classification", () => {
    assert.equal(cacheControlFor("/app/dist/index.html"), "no-cache, no-store, must-revalidate");
    assert.equal(cacheControlFor("/app/dist/assets/app.js"), "public, max-age=31536000, immutable");
    assert.equal(cacheControlFor("/app/dist/favicon.ico"), "public, max-age=300");
  });

  it("proxies /ae-api requests to the configured backend target", async () => {
    const backendCalls = [];
    const backend = createServer((request, response) => {
      const bodyChunks = [];
      request.on("data", chunk => bodyChunks.push(chunk));
      request.on("end", () => {
        backendCalls.push({
          method: request.method,
          url: request.url,
          host: request.headers.host,
          cookie: request.headers.cookie,
          body: Buffer.concat(bodyChunks).toString("utf8")
        });
        response.writeHead(200, {
          "content-type": "application/json",
          "set-cookie": "nex_ae_session=opaque; HttpOnly; Path=/"
        });
        response.end(JSON.stringify({ ok: true }));
      });
    });
    const backendPort = await listen(backend);
    const aeWeb = createAeWebServer({
      apiProxyTarget: `http://127.0.0.1:${backendPort}`
    });
    const aeWebPort = await listen(aeWeb);

    try {
      const response = await fetch(
        `http://127.0.0.1:${aeWebPort}/ae-api/api/v1/auth/session/login?trace=1`,
        {
          method: "POST",
          headers: {
            "content-type": "application/json",
            cookie: "nex_ae_session=old"
          },
          body: JSON.stringify({ tenant_id: "tenant", password: "redacted" })
        }
      );
      const payload = await response.json();

      assert.deepEqual(payload, { ok: true });
      assert.equal(response.headers.get("set-cookie"), "nex_ae_session=opaque; HttpOnly; Path=/");
      assert.deepEqual(backendCalls, [
        {
          method: "POST",
          url: "/api/v1/auth/session/login?trace=1",
          host: `127.0.0.1:${backendPort}`,
          cookie: "nex_ae_session=old",
          body: JSON.stringify({ tenant_id: "tenant", password: "redacted" })
        }
      ]);
    } finally {
      await close(aeWeb);
      await close(backend);
    }
  });

  it("returns a proxy error for unsupported targets", async () => {
    const server = createAeWebServer({ apiProxyTarget: "file:///tmp/backend" });
    const port = await listen(server);
    try {
      const response = await fetch(`http://127.0.0.1:${port}/ae-api/health`);
      const payload = await response.json();

      assert.equal(response.status, 502);
      assert.equal(payload.error_code, "ae_web_proxy_protocol_invalid");
    } finally {
      await close(server);
    }
  });
});
