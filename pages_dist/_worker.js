const API_UPLOAD = "/api/upload";
const API_STATUS = "/api/status/";
const API_DOWNLOAD = "/api/download/";
const API_PRESETS = "/api/presets";
const API_ADMIN_SESSION = "/api/admin/session";
const ADMIN_PATHS = [
  "/admin/login",
  "/admin/logout",
  "/admin/session",
  "/monitor",
  "/stats",
  "/ip",
  "/ban",
  "/unban",
  "/limit",
  "/cleanup",
  "/log/",
  "/presets",
];
const DEFAULT_PROXY_SECRET = "docxtool-proxy-20260601-9ec0d6e2443a4f5f9784f0f04bb62917";

function jsonError(code, error, status) {
  return new Response(JSON.stringify({ code, error }), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

function backendPath(pathname) {
  if (pathname === API_UPLOAD) return "/upload";
  if (pathname.startsWith(API_STATUS)) return "/status/" + pathname.slice(API_STATUS.length);
  if (pathname.startsWith(API_DOWNLOAD)) return "/download/" + pathname.slice(API_DOWNLOAD.length);
  if (pathname === API_PRESETS) return "/presets";
  if (pathname.startsWith(API_PRESETS + "/")) return "/presets/" + pathname.slice((API_PRESETS + "/").length);
  if (pathname === API_ADMIN_SESSION) return "/admin/session";
  if (pathname.startsWith("/api/admin/")) return "/admin/" + pathname.slice("/api/admin/".length);
  if (pathname === "/api/health") return "/health";
  if (pathname === "/api/ready") return "/ready";
  if (pathname === "/api/version") return "/version";
  if (ADMIN_PATHS.some((prefix) => pathname === prefix || pathname.startsWith(prefix + "/"))) {
    return pathname;
  }
  return "";
}

function methodAllowed(pathname, method) {
  if (pathname === API_UPLOAD) return method === "PUT";
  if (pathname.startsWith(API_STATUS)) return method === "GET";
  if (pathname.startsWith(API_DOWNLOAD)) return method === "GET";
  if (pathname === API_PRESETS) return method === "GET" || method === "POST";
  if (pathname.startsWith(API_PRESETS + "/")) return method === "GET" || method === "PUT" || method === "DELETE";
  if (pathname === API_ADMIN_SESSION) return method === "GET";
  if (pathname === "/admin/login") return method === "GET" || method === "POST";
  if (pathname === "/admin/logout") return method === "POST";
  if (pathname === "/monitor" || pathname === "/stats" || pathname === "/ip" || pathname === "/log/" || pathname.startsWith("/log/")) {
    return method === "GET";
  }
  if (pathname === "/ban" || pathname === "/unban" || pathname === "/limit" || pathname === "/cleanup") {
    return method === "POST";
  }
  if (pathname === "/api/health" || pathname === "/api/ready" || pathname === "/api/version") {
    return method === "GET";
  }
  return false;
}

function filterCookieHeader(cookieHeader) {
  const allowed = [];
  for (const part of String(cookieHeader || "").split(";")) {
    const trimmed = part.trim();
    if (!trimmed) continue;
    if (trimmed.startsWith("docxtool_admin_session=")) allowed.push(trimmed);
  }
  return allowed.join("; ");
}

async function proxyApi(request, env, url) {
  try {
    if (request.method === "OPTIONS") return new Response(null, { status: 204 });

    const path = backendPath(url.pathname);
    if (!path) return jsonError("API_NOT_FOUND", "API not found", 404);
    if (!methodAllowed(url.pathname, request.method)) {
      return jsonError("METHOD_NOT_ALLOWED", "Method not allowed", 405);
    }

    const backendBase = String(env.BACKEND_BASE_URL || "").trim().replace(/\/+$/, "");
    const proxySecret = String(env.PROXY_SECRET || "").trim();
    if (!backendBase) {
      return jsonError("BACKEND_NOT_CONFIGURED", "Cloudflare Pages env BACKEND_BASE_URL is not configured", 500);
    }
    if (!proxySecret) {
      return jsonError("PROXY_SECRET_NOT_CONFIGURED", "Cloudflare Pages env PROXY_SECRET is not configured", 500);
    }

    const target = new URL(backendBase + path);
    target.search = url.search;

    const headers = new Headers(request.headers);
    const clientIp = request.headers.get("CF-Connecting-IP") || "";
    for (const key of [
      "Host",
      "Forwarded",
      "X-Proxy-Secret",
      "X-Docxtool-Proxy",
      "X-Forwarded-For",
      "X-Real-IP",
      "X-Forwarded-Host",
      "X-Forwarded-Proto",
      "CF-Connecting-IP",
      "X-Admin-Token",
      "Cookie",
      "Authorization",
      "Proxy-Authorization",
    ]) {
      headers.delete(key);
    }
    const cookieHeader = filterCookieHeader(request.headers.get("Cookie"));
    if (cookieHeader) {
      headers.set("Cookie", cookieHeader);
    } else {
      headers.delete("Cookie");
    }
    headers.set("X-Proxy-Secret", proxySecret);
    headers.set("X-Docxtool-Proxy", "cloudflare-pages");
    headers.set("X-Forwarded-Host", url.host);
    headers.set("X-Forwarded-Proto", "https");
    if (clientIp) {
      headers.set("CF-Connecting-IP", clientIp);
      headers.set("X-Forwarded-For", clientIp);
      headers.set("X-Real-IP", clientIp);
    }

    const init = {
      method: request.method,
      headers,
      redirect: "manual",
    };
    if (request.method !== "GET" && request.method !== "HEAD") {
      init.body = request.body;
    }

    return fetch(target, init);
  } catch (error) {
    return jsonError("PROXY_WORKER_ERROR", error && error.message ? error.message : "Worker proxy failed", 502);
  }
}

export default {
  async fetch(request, env) {
    try {
      const url = new URL(request.url);
      if (url.pathname.startsWith("/api/")) {
        return proxyApi(request, env, url);
      }
      return env.ASSETS.fetch(request);
    } catch (error) {
      return jsonError("WORKER_ERROR", error && error.message ? error.message : "Worker failed", 500);
    }
  },
};
