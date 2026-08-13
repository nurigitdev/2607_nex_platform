import { createReadStream, existsSync, statSync } from "node:fs";
import { createServer, request as httpRequest } from "node:http";
import { request as httpsRequest } from "node:https";
import { extname, join, normalize, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const root = resolve(new URL("..", import.meta.url).pathname);
const port = Number(process.env.PORT || 5173);
const host = process.env.HOST || "127.0.0.1";
const aeApiProxyTarget = process.env.AE_API_PROXY_TARGET || "";
export const AE_API_PROXY_PREFIX = "/ae-api";

const mimeTypes = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8"
};

export function createAeWebServer({
  rootDir = root,
  apiProxyTarget = aeApiProxyTarget,
  apiProxyPrefix = AE_API_PROXY_PREFIX
} = {}) {
  return createServer((request, response) => {
    const url = new URL(request.url || "/", `http://${request.headers.host}`);
    if (apiProxyTarget && isProxyPath(url.pathname, apiProxyPrefix)) {
      proxyApiRequest({
        request,
        response,
        url,
        apiProxyTarget,
        apiProxyPrefix
      });
      return;
    }

    const requestedPath = normalize(decodeURIComponent(url.pathname));
    const filePath = resolve(join(rootDir, requestedPath === "/" ? "index.html" : requestedPath));

    if (!filePath.startsWith(rootDir) || !existsSync(filePath) || statSync(filePath).isDirectory()) {
      response.writeHead(404, { "content-type": "text/plain; charset=utf-8" });
      response.end("Not found");
      return;
    }

    response.writeHead(200, {
      "content-type": mimeTypes[extname(filePath)] || "application/octet-stream"
    });
    createReadStream(filePath).pipe(response);
  });
}

export function isProxyPath(pathname, apiProxyPrefix = AE_API_PROXY_PREFIX) {
  return pathname === apiProxyPrefix || pathname.startsWith(`${apiProxyPrefix}/`);
}

function proxyApiRequest({
  request,
  response,
  url,
  apiProxyTarget,
  apiProxyPrefix
}) {
  let targetBase;
  try {
    targetBase = new URL(apiProxyTarget);
  } catch {
    response.writeHead(502, { "content-type": "application/json; charset=utf-8" });
    response.end(JSON.stringify({ error_code: "ae_web_proxy_target_invalid" }));
    return;
  }
  if (!["http:", "https:"].includes(targetBase.protocol)) {
    response.writeHead(502, { "content-type": "application/json; charset=utf-8" });
    response.end(JSON.stringify({ error_code: "ae_web_proxy_protocol_invalid" }));
    return;
  }

  const proxiedPath = url.pathname.slice(apiProxyPrefix.length) || "/";
  const targetUrl = new URL(`${proxiedPath}${url.search}`, targetBase);
  const proxyRequest = (targetUrl.protocol === "https:" ? httpsRequest : httpRequest)(
    targetUrl,
    {
      method: request.method,
      headers: proxyRequestHeaders(request.headers, targetUrl)
    },
    proxyResponse => {
      response.writeHead(
        proxyResponse.statusCode || 502,
        proxyResponse.statusMessage,
        proxyResponse.headers
      );
      proxyResponse.pipe(response);
    }
  );
  proxyRequest.on("error", () => {
    if (!response.headersSent) {
      response.writeHead(502, { "content-type": "application/json; charset=utf-8" });
    }
    response.end(JSON.stringify({ error_code: "ae_web_proxy_request_failed" }));
  });
  request.pipe(proxyRequest);
}

function proxyRequestHeaders(headers, targetUrl) {
  const forwarded = { ...headers };
  delete forwarded.host;
  delete forwarded.connection;
  forwarded.host = targetUrl.host;
  return forwarded;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  createAeWebServer().listen(port, host, () => {
    console.log(`nex-ae-web listening at http://${host}:${port}`);
  });
}
