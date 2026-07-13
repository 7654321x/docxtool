import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { after, test } from "node:test";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, "..");
const workerSource = await readFile(join(root, "resources", "frontend", "pages", "_worker.js"), "utf8");
const tempDir = await mkdtemp(join(tmpdir(), "docxtool-worker-"));
const workerModulePath = join(tempDir, "worker.mjs");

await writeFile(
  workerModulePath,
  `${workerSource}
export { backendPath, filterCookieHeader, isAdminProxyPath, isApiPath, methodAllowed, shouldProxyPath };
`,
  "utf8",
);

const worker = await import(pathToFileURL(workerModulePath).href);

after(async () => {
  await rm(tempDir, { force: true, recursive: true });
});

async function callWorker(pathname, options = {}) {
  const fetchCalls = [];
  const assetsCalls = [];
  const originalFetch = globalThis.fetch;
  const method = options.method || "GET";
  const requestInit = {
    headers: options.headers || {},
    method,
  };

  if (options.body !== undefined && method !== "GET" && method !== "HEAD") {
    requestInit.body = options.body;
  }

  const env = {
    ASSETS: {
      fetch: async (request) => {
        assetsCalls.push(request);
        return new Response(`asset:${new URL(request.url).pathname}`, { status: 203 });
      },
    },
    BACKEND_BASE_URL: "https://backend.example/base/",
    PROXY_SECRET: "worker-secret",
    ...options.env,
  };

  globalThis.fetch = async (target, init) => {
    fetchCalls.push({ init, target: String(target) });
    return new Response("proxied", { status: 209 });
  };

  try {
    const response = await worker.default.fetch(new Request(`https://front.example${pathname}`, requestInit), env);
    return { assetsCalls, fetchCalls, response };
  } finally {
    globalThis.fetch = originalFetch;
  }
}

async function responseJson(response) {
  return JSON.parse(await response.text());
}

test("path helpers only proxy api and exact admin routes", () => {
  assert.equal(worker.shouldProxyPath("/api/upload"), true);
  assert.equal(worker.shouldProxyPath("/api/unknown"), true);
  assert.equal(worker.shouldProxyPath("/monitor"), true);
  assert.equal(worker.shouldProxyPath("/log/task-id"), true);
  assert.equal(worker.shouldProxyPath("/monitor-evil"), false);
  assert.equal(worker.shouldProxyPath("/apiary"), false);
  assert.equal(worker.shouldProxyPath("/unknown"), false);

  assert.equal(worker.backendPath("/api/upload"), "/upload");
  assert.equal(worker.backendPath("/api/status/abc"), "/status/abc");
  assert.equal(worker.backendPath("/api/download/abc"), "/download/abc");
  assert.equal(worker.backendPath("/api/admin/session"), "/admin/session");
  assert.equal(worker.backendPath("/monitor"), "/monitor");
  assert.equal(worker.backendPath("/log/task-id"), "/log/task-id");
  assert.equal(worker.backendPath("/api/unknown"), "");
});

test("api upload proxies PUT and rejects other methods", async () => {
  const proxied = await callWorker("/api/upload?x=1", { body: "docx-bytes", method: "PUT" });

  assert.equal(proxied.response.status, 209);
  assert.equal(proxied.fetchCalls.length, 1);
  assert.equal(proxied.fetchCalls[0].target, "https://backend.example/base/upload?x=1");
  assert.equal(proxied.fetchCalls[0].init.method, "PUT");

  const rejected = await callWorker("/api/upload", { method: "GET" });
  assert.equal(rejected.response.status, 405);
  assert.deepEqual(await responseJson(rejected.response), {
    code: "METHOD_NOT_ALLOWED",
    error: "Method not allowed",
  });
  assert.equal(rejected.fetchCalls.length, 0);
});

test("admin and log routes proxy with strict method rules", async () => {
  const routes = [
    ["/monitor", "GET", "/monitor"],
    ["/stats", "GET", "/stats"],
    ["/ip", "GET", "/ip"],
    ["/admin/login", "GET", "/admin/login"],
    ["/admin/login", "POST", "/admin/login"],
    ["/admin/logout", "POST", "/admin/logout"],
    ["/admin/session", "GET", "/admin/session"],
    ["/ban?ip=203.0.113.10", "POST", "/ban?ip=203.0.113.10"],
    ["/unban?ip=203.0.113.10", "POST", "/unban?ip=203.0.113.10"],
    ["/limit", "POST", "/limit"],
    ["/cleanup", "POST", "/cleanup"],
    ["/log/task-id", "GET", "/log/task-id"],
  ];

  for (const [pathname, method, targetPath] of routes) {
    const result = await callWorker(pathname, { method });
    assert.equal(result.response.status, 209, `${method} ${pathname}`);
    assert.equal(result.fetchCalls[0].target, `https://backend.example/base${targetPath}`);
  }

  const rejected = await callWorker("/ban?ip=203.0.113.10", { method: "GET" });
  assert.equal(rejected.response.status, 405);
  assert.equal(rejected.fetchCalls.length, 0);
});

test("root and static assets fall through to pages assets", async () => {
  for (const pathname of ["/", "/index.html", "/assets/app.css"]) {
    const result = await callWorker(pathname);
    assert.equal(result.response.status, 203, pathname);
    assert.equal(await result.response.text(), `asset:${pathname}`, pathname);
    assert.equal(result.fetchCalls.length, 0, pathname);
    assert.equal(result.assetsCalls.length, 1, pathname);
  }
});

test("similar non-proxy paths fall through to static assets", async () => {
  for (const pathname of ["/monitor-evil", "/apiary", "/unknown"]) {
    const result = await callWorker(pathname);
    assert.equal(result.response.status, 203, pathname);
    assert.equal(result.fetchCalls.length, 0, pathname);
    assert.equal(result.assetsCalls.length, 1, pathname);
  }
});

test("unknown api paths return api not found without hitting assets", async () => {
  const result = await callWorker("/api/unknown", { method: "GET" });

  assert.equal(result.response.status, 404);
  assert.deepEqual(await responseJson(result.response), {
    code: "API_NOT_FOUND",
    error: "API not found",
  });
  assert.equal(result.fetchCalls.length, 0);
  assert.equal(result.assetsCalls.length, 0);
});

test("missing proxy configuration returns clear errors", async () => {
  const missingBackend = await callWorker("/api/upload", {
    body: "docx-bytes",
    env: { BACKEND_BASE_URL: "" },
    method: "PUT",
  });
  assert.equal(missingBackend.response.status, 500);
  assert.deepEqual(await responseJson(missingBackend.response), {
    code: "BACKEND_NOT_CONFIGURED",
    error: "Cloudflare Pages env BACKEND_BASE_URL is not configured",
  });

  const missingSecret = await callWorker("/api/upload", {
    body: "docx-bytes",
    env: { PROXY_SECRET: "" },
    method: "PUT",
  });
  assert.equal(missingSecret.response.status, 500);
  assert.deepEqual(await responseJson(missingSecret.response), {
    code: "PROXY_SECRET_NOT_CONFIGURED",
    error: "Cloudflare Pages env PROXY_SECRET is not configured",
  });
});

test("proxy strips sensitive inbound headers and forwards only allowed cookies", async () => {
  const result = await callWorker("/api/upload", {
    body: "docx-bytes",
    headers: {
      Authorization: "Bearer user-secret",
      "CF-Connecting-IP": "203.0.113.5",
      Cookie: "docxtool_admin_session=session-id; other=value",
      "X-Admin-Token": "admin-secret",
      "X-Custom": "kept",
      "X-Forwarded-For": "198.51.100.1",
      "X-Proxy-Secret": "attacker-secret",
    },
    method: "PUT",
  });
  const headers = result.fetchCalls[0].init.headers;

  assert.equal(headers.get("X-Proxy-Secret"), "worker-secret");
  assert.equal(headers.get("X-Docxtool-Proxy"), "cloudflare-pages");
  assert.equal(headers.get("X-Forwarded-Host"), "front.example");
  assert.equal(headers.get("X-Forwarded-Proto"), "https");
  assert.equal(headers.get("CF-Connecting-IP"), "203.0.113.5");
  assert.equal(headers.get("X-Forwarded-For"), "203.0.113.5");
  assert.equal(headers.get("X-Real-IP"), "203.0.113.5");
  assert.equal(headers.get("Cookie"), "docxtool_admin_session=session-id");
  assert.equal(headers.get("X-Custom"), "kept");
  assert.equal(headers.has("Authorization"), false);
  assert.equal(headers.has("X-Admin-Token"), false);
});
