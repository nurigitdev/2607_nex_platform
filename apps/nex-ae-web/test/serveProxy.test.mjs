import assert from "node:assert/strict";
import { createServer } from "node:http";
import { once } from "node:events";
import { describe, it } from "node:test";

import {
  AE_API_PROXY_PREFIX,
  createAeWebServer,
  isProxyPath
} from "../scripts/serve.mjs";

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
    const server = createAeWebServer({ apiProxyTarget: "" });
    const port = await listen(server);
    try {
      const response = await fetch(`http://127.0.0.1:${port}/`);
      const body = await response.text();

      assert.equal(response.status, 200);
      assert.match(body, /credential-login-form/);
    } finally {
      await close(server);
    }
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
