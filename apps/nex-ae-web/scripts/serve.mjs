import { createReadStream, existsSync, statSync } from "node:fs";
import { createServer, request as httpRequest } from "node:http";
import { request as httpsRequest } from "node:https";
import { extname, join, normalize, resolve, sep } from "node:path";
import { pathToFileURL } from "node:url";

const sourceRoot = resolve(new URL("..", import.meta.url).pathname);
const staticRoot = resolve(process.env.NEX_AE_WEB_STATIC_ROOT || join(sourceRoot, "dist"));
const webBaseUrl = optionalHttpUrl(process.env.NEX_AE_WEB_BASE_URL);
const port = Number(process.env.PORT || webBaseUrl?.port || defaultPort(webBaseUrl) || 5173);
const host = process.env.HOST || webBaseUrl?.hostname || "127.0.0.1";
const aeApiProxyTarget = process.env.AE_API_PROXY_TARGET || process.env.NEX_AE_API_BASE_URL || "";
export const AE_API_PROXY_PREFIX = "/ae-api";

function optionalHttpUrl(value) {
  if (!value) return null;
  const parsed = new URL(value);
  if (!["http:", "https:"].includes(parsed.protocol)) {
    throw new Error("NEX_AE_WEB_BASE_URL must use http or https");
  }
  return parsed;
}

function defaultPort(url) {
  if (!url) return null;
  return url.protocol === "https:" ? 443 : 80;
}

const mimeTypes = {
  ".css": "text/css; charset=utf-8",
  ".gif": "image/gif",
  ".html": "text/html; charset=utf-8",
  ".ico": "image/x-icon",
  ".jpeg": "image/jpeg",
  ".js": "text/javascript; charset=utf-8",
  ".jpg": "image/jpeg",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".webp": "image/webp",
  ".woff": "font/woff",
  ".woff2": "font/woff2"
};

export function createAeWebServer({
  rootDir = staticRoot,
  apiProxyTarget = aeApiProxyTarget,
  apiProxyPrefix = AE_API_PROXY_PREFIX
} = {}) {
  return createServer((request, response) => {
    const url = new URL(request.url || "/", `http://${request.headers.host}`);
    if (isProxyPath(url.pathname, apiProxyPrefix)) {
      if (apiProxyTarget) {
        proxyApiRequest({ request, response, url, apiProxyTarget, apiProxyPrefix });
      } else {
        response.writeHead(503, { "content-type": "application/json; charset=utf-8" });
        response.end(JSON.stringify({ error_code: "ae_web_proxy_target_unavailable" }));
      }
      return;
    }

    if (url.pathname === "/modern.html") {
      response.writeHead(308, { location: "/", "cache-control": "no-store" });
      response.end();
      return;
    }

    const requestedPath = normalize(decodeURIComponent(url.pathname));
    const requestedFile = requestedPath === "/" ? "index.html" : requestedPath;
    let filePath = resolve(join(rootDir, requestedFile));
    const withinRoot = filePath === rootDir || filePath.startsWith(`${rootDir}${sep}`);
    const missing = !withinRoot || !existsSync(filePath) || statSync(filePath).isDirectory();

    if (missing && isSpaNavigation(request, requestedPath)) {
      filePath = resolve(rootDir, "index.html");
    }

    if (!withinRoot || !existsSync(filePath) || statSync(filePath).isDirectory()) {
      response.writeHead(404, { "content-type": "text/plain; charset=utf-8" });
      response.end("Not found");
      return;
    }

    response.writeHead(200, {
      "content-type": mimeTypes[extname(filePath)] || "application/octet-stream",
      "cache-control": cacheControlFor(filePath),
      "x-content-type-options": "nosniff",
      "referrer-policy": "same-origin"
    });
    if (request.method === "HEAD") response.end();
    else createReadStream(filePath).pipe(response);
  });
}

export function isProxyPath(pathname, apiProxyPrefix = AE_API_PROXY_PREFIX) {
  return pathname === apiProxyPrefix || pathname.startsWith(`${apiProxyPrefix}/`);
}

export function isSpaNavigation(request, pathname) {
  return ["GET", "HEAD"].includes(request.method || "GET") && extname(pathname) === "";
}

export function cacheControlFor(filePath) {
  if (extname(filePath) === ".html") return "no-cache, no-store, must-revalidate";
  if (filePath.includes(`${sep}assets${sep}`)) return "public, max-age=31536000, immutable";
  return "public, max-age=300";
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
