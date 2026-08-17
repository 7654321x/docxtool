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
    BACKEND_BASE_URL: "https://backend.example",
    PROXY_SECRET: "worker-secret",
    ...options.env,
  };

  globalThis.fetch = async (target, init) => {
    fetchCalls.push({ init, target: String(target) });
    return new Response("proxied", { headers: options.backendHeaders || {}, status: 209 });
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

test("path helpers only proxy api and allow-listed admin routes", () => {
  assert.equal(worker.shouldProxyPath("/api/upload"), true);
  assert.equal(worker.shouldProxyPath("/api/unknown"), true);
  assert.equal(worker.shouldProxyPath("/monitor"), true);
  assert.equal(worker.shouldProxyPath("/log/task-id"), true);
  assert.equal(worker.shouldProxyPath("/admin"), true);
  assert.equal(worker.shouldProxyPath("/admin/web/tasks"), true);
  assert.equal(worker.shouldProxyPath("/admin/wps/users/wusr_1"), true);
  assert.equal(worker.shouldProxyPath("/admin/wps/users/wusr_1/password"), true);
  assert.equal(worker.shouldProxyPath("/admin/wps/users/wusr_1/notifications"), true);
  assert.equal(worker.shouldProxyPath("/admin/wps/users/wusr_1/unexpected"), false);
  assert.equal(worker.shouldProxyPath("/wps-api/v1/auth/me"), true);
  assert.equal(worker.shouldProxyPath("/wps-api/v1/unknown"), false);
  assert.equal(worker.shouldProxyPath("/monitor-evil"), false);
  assert.equal(worker.shouldProxyPath("/apiary"), false);
  assert.equal(worker.shouldProxyPath("/unknown"), false);

  assert.equal(worker.backendPath("/api/upload"), "/upload");
  assert.equal(worker.backendPath("/api/status/abc"), "/status/abc");
  assert.equal(worker.backendPath("/api/download/abc"), "/download/abc");
  assert.equal(worker.backendPath("/api/admin/session"), "/admin/session");
  assert.equal(worker.backendPath("/monitor"), "/monitor");
  assert.equal(worker.backendPath("/log/task-id"), "/log/task-id");
  assert.equal(worker.backendPath("/admin/wps/users/wusr_1"), "/admin/wps/users/wusr_1");
  assert.equal(worker.backendPath("/wps-api/v1/auth/me"), "/wps-api/v1/auth/me");
  assert.equal(worker.backendPath("/api/unknown"), "");
});

test("api upload proxies PUT and rejects other methods", async () => {
  const proxied = await callWorker("/api/upload?x=1", { body: "docx-bytes", method: "PUT" });

  assert.equal(proxied.response.status, 209);
  assert.equal(proxied.fetchCalls.length, 1);
  assert.equal(proxied.fetchCalls[0].target, "https://backend.example/upload?x=1");
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
    ["/admin", "GET", "/admin"],
    ["/admin/web/tasks", "GET", "/admin/web/tasks"],
    ["/admin/wps", "GET", "/admin/wps"],
    ["/admin/wps/users/wusr_1", "GET", "/admin/wps/users/wusr_1"],
    ["/admin/wps/users/wusr_1/status", "POST", "/admin/wps/users/wusr_1/status"],
    ["/admin/wps/users/wusr_1/password", "POST", "/admin/wps/users/wusr_1/password"],
    ["/admin/wps/users/wusr_1/notifications", "POST", "/admin/wps/users/wusr_1/notifications"],
    ["/admin/wps/users/wusr_1/delete", "POST", "/admin/wps/users/wusr_1/delete"],
    ["/admin/wps/devices/wdev_1/status", "POST", "/admin/wps/devices/wdev_1/status"],
    ["/ban?ip=203.0.113.10", "POST", "/ban?ip=203.0.113.10"],
    ["/unban?ip=203.0.113.10", "POST", "/unban?ip=203.0.113.10"],
    ["/limit", "POST", "/limit"],
    ["/cleanup", "POST", "/cleanup"],
    ["/log/task-id", "GET", "/log/task-id"],
  ];

  for (const [pathname, method, targetPath] of routes) {
    const result = await callWorker(pathname, { method });
    assert.equal(result.response.status, 209, `${method} ${pathname}`);
    assert.equal(result.fetchCalls[0].target, `https://backend.example${targetPath}`);
  }

  const rejected = await callWorker("/ban?ip=203.0.113.10", { method: "GET" });
  assert.equal(rejected.response.status, 405);
  assert.equal(rejected.fetchCalls.length, 0);

  const wrongMethod = await callWorker("/admin/wps/users/wusr_1/status", { method: "GET" });
  assert.equal(wrongMethod.response.status, 405);
  assert.equal(wrongMethod.fetchCalls.length, 0);
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

test("two Pages variables are sufficient for API proxying", async () => {
  const result = await callWorker("/api/health", {
    env: {
      BACKEND_BASE_URL: "https://backend.example",
      PROXY_SECRET: "worker-secret",
    },
  });
  const headers = result.fetchCalls[0].init.headers;

  assert.equal(result.response.status, 209);
  assert.equal(result.fetchCalls[0].target, "https://backend.example/health");
  assert.equal(headers.get("X-Proxy-Secret"), "worker-secret");
  assert.equal(headers.get("X-Docxtool-Proxy"), "cloudflare-pages");
  assert.equal(headers.has("CF-Access-Client-Id"), false);
  assert.equal(headers.has("CF-Access-Client-Secret"), false);
});

test("worker source keeps origin deployment details out of the public proxy", () => {
  assert.equal(workerSource.includes("origin.toolpp.cn"), false);
  assert.equal(workerSource.includes("43.130.232.115"), false);
  assert.equal(workerSource.includes("cloudflared"), false);
  assert.equal(workerSource.includes("env.BACKEND_BASE_URL"), true);
  assert.equal(workerSource.includes("env.PROXY_SECRET"), true);
});

test("proxy rejects non-HTTPS, direct-IP, and path-bearing backend origins", async () => {
  for (const backendBase of [
    "http://backend.example",
    "https://203.0.113.9",
    "https://backend.example/private",
  ]) {
    const result = await callWorker("/api/presets", {
      env: { BACKEND_BASE_URL: backendBase },
    });
    assert.equal(result.response.status, 500, backendBase);
    assert.deepEqual(await responseJson(result.response), {
      code: "BACKEND_URL_INVALID",
      error: "Cloudflare Pages env BACKEND_BASE_URL must be an HTTPS hostname origin",
    });
    assert.equal(result.fetchCalls.length, 0, backendBase);
  }
});

test("proxy strips sensitive inbound headers and forwards only allowed cookies", async () => {
  const result = await callWorker("/api/upload", {
    body: "docx-bytes",
    headers: {
      Authorization: "Bearer user-secret",
      "CF-Access-Client-Id": "attacker-client-id",
      "CF-Access-Client-Secret": "attacker-client-secret",
      "CF-Connecting-IP": "203.0.113.5",
      Cookie: "docxtool_admin_session=session-id; docxtool_anon_user=v1.token; docxtool_user_session=user-token; other=value",
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
  assert.equal(headers.has("CF-Access-Client-Id"), false);
  assert.equal(headers.has("CF-Access-Client-Secret"), false);
  assert.equal(headers.get("X-Forwarded-Host"), "front.example");
  assert.equal(headers.get("X-Forwarded-Proto"), "https");
  assert.equal(headers.get("CF-Connecting-IP"), "203.0.113.5");
  assert.equal(headers.get("X-Forwarded-For"), "203.0.113.5");
  assert.equal(headers.get("X-Real-IP"), "203.0.113.5");
  assert.equal(headers.get("Cookie"), "docxtool_admin_session=session-id; docxtool_anon_user=v1.token; docxtool_user_session=user-token");
  assert.equal(headers.get("X-Custom"), "kept");
  assert.equal(headers.has("Authorization"), false);
  assert.equal(headers.has("X-Admin-Token"), false);
});

test("WPS public routes preserve only their Bearer session and no browser cookies", async () => {
  const result = await callWorker("/wps-api/v1/auth/me", {
    headers: {
      Authorization: "Bearer wps-session-token",
      Cookie: "docxtool_admin_session=admin; other=value",
      "CF-Access-Client-Id": "attacker-client-id",
      "CF-Access-Client-Secret": "attacker-client-secret",
      "X-Proxy-Secret": "attacker-secret",
    },
  });
  const headers = result.fetchCalls[0].init.headers;

  assert.equal(result.response.status, 209);
  assert.equal(result.fetchCalls[0].target, "https://backend.example/wps-api/v1/auth/me");
  assert.equal(headers.get("Authorization"), "Bearer wps-session-token");
  assert.equal(headers.has("Cookie"), false);
  assert.equal(headers.get("X-Proxy-Secret"), "worker-secret");
  assert.equal(headers.has("CF-Access-Client-Id"), false);
  assert.equal(headers.has("CF-Access-Client-Secret"), false);

  assert.equal((await callWorker("/wps-api/v1/auth/me", { method: "POST" })).response.status, 405);
  assert.equal((await callWorker("/wps-api/v1/heartbeat", { method: "POST", body: "{}" })).response.status, 209);
});

test("user auth routes proxy only their allowed methods", async () => {
  assert.equal((await callWorker("/api/auth/me", { method: "GET" })).response.status, 209);
  assert.equal((await callWorker("/api/auth/me", { method: "POST" })).response.status, 405);
  for (const path of ["/api/auth/register", "/api/auth/login", "/api/auth/logout"]) {
    assert.equal((await callWorker(path, { method: "POST", body: "{}" })).response.status, 209, path);
    assert.equal((await callWorker(path, { method: "GET" })).response.status, 405, path);
  }
});

test("proxy preserves anonymous Set-Cookie from backend", async () => {
  const result = await callWorker("/api/presets", {
    backendHeaders: {
      "Set-Cookie": "docxtool_anon_user=v1.token; HttpOnly; SameSite=Lax; Secure",
    },
  });

  assert.equal(
    result.response.headers.get("Set-Cookie"),
    "docxtool_anon_user=v1.token; HttpOnly; SameSite=Lax; Secure",
  );
});

test("admin login preserves backend relative redirects and secure session cookies", async () => {
  const result = await callWorker("/admin/login", {
    backendHeaders: {
      Location: "/admin",
      "Set-Cookie": "docxtool_admin_session=session-id; HttpOnly; SameSite=Strict; Secure; Path=/",
    },
    body: "token=admin-token",
    method: "POST",
  });

  assert.equal(result.response.headers.get("Location"), "/admin");
  assert.equal(
    result.response.headers.get("Set-Cookie"),
    "docxtool_admin_session=session-id; HttpOnly; SameSite=Strict; Secure; Path=/",
  );
});
