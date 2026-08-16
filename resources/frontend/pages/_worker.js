const API_UPLOAD = "/api/upload";
const API_STATUS = "/api/status/";
const API_DOWNLOAD = "/api/download/";
const API_PRESETS = "/api/presets";
const API_ADMIN_SESSION = "/api/admin/session";
const API_AUTH_PREFIX = "/api/auth/";
const WPS_API_METHODS = new Map([
  ["/wps-api/v1/auth/register", new Set(["POST"])],
  ["/wps-api/v1/auth/login", new Set(["POST"])],
  ["/wps-api/v1/auth/me", new Set(["GET"])],
  ["/wps-api/v1/auth/logout", new Set(["POST"])],
  ["/wps-api/v1/heartbeat", new Set(["POST"])],
  ["/wps-api/v1/notifications/read", new Set(["POST"])],
  ["/wps-api/v1/format/authorize", new Set(["POST"])],
  ["/wps-api/v1/format/result", new Set(["POST"])],
]);
const ADMIN_EXACT_PATHS = new Set([
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
  "/presets",
]);
const ADMIN_LOG_PREFIX = "/log/";
const ADMIN_WORKSPACE_READ_PATHS = new Set([
  "/admin",
  "/admin/web",
  "/admin/web/tasks",
  "/admin/web/security",
  "/admin/web/runtime",
  "/admin/web/logs",
  "/admin/wps",
  "/admin/wps/users",
  "/admin/wps/devices",
  "/admin/wps/tasks",
]);
const WPS_ADMIN_RESOURCE_ID = /^[A-Za-z0-9._:-]{1,160}$/;

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
  if (pathname.startsWith(API_AUTH_PREFIX)) return pathname;
  if (pathname.startsWith("/api/admin/")) return "/admin/" + pathname.slice("/api/admin/".length);
  if (pathname === "/api/health") return "/health";
  if (pathname === "/api/ready") return "/ready";
  if (pathname === "/api/version") return "/version";
  if (isWpsPublicApiPath(pathname)) return pathname;
  if (isAdminProxyPath(pathname)) {
    return pathname;
  }
  return "";
}

function isApiPath(pathname) {
  return pathname.startsWith("/api/");
}

function isWpsPublicApiPath(pathname) {
  return WPS_API_METHODS.has(pathname);
}

function isAdminProxyPath(pathname) {
  return ADMIN_EXACT_PATHS.has(pathname)
    || ADMIN_WORKSPACE_READ_PATHS.has(pathname)
    || isWpsAdminUserDetailPath(pathname)
    || isWpsAdminMutationPath(pathname)
    || pathname === ADMIN_LOG_PREFIX
    || pathname.startsWith(ADMIN_LOG_PREFIX);
}

function isWpsAdminUserDetailPath(pathname) {
  const prefix = "/admin/wps/users/";
  if (!pathname.startsWith(prefix)) return false;
  const tail = pathname.slice(prefix.length);
  return WPS_ADMIN_RESOURCE_ID.test(tail);
}

function isWpsAdminMutationPath(pathname) {
  const userPrefix = "/admin/wps/users/";
  if (pathname.startsWith(userPrefix)) {
    const parts = pathname.slice(userPrefix.length).split("/");
    return parts.length === 2
      && WPS_ADMIN_RESOURCE_ID.test(parts[0])
      && new Set(["status", "password", "notifications", "delete"]).has(parts[1]);
  }
  const devicePrefix = "/admin/wps/devices/";
  if (pathname.startsWith(devicePrefix)) {
    const parts = pathname.slice(devicePrefix.length).split("/");
    return parts.length === 2
      && WPS_ADMIN_RESOURCE_ID.test(parts[0])
      && parts[1] === "status";
  }
  return false;
}

function shouldProxyPath(pathname) {
  return isApiPath(pathname) || isWpsPublicApiPath(pathname) || isAdminProxyPath(pathname);
}

function methodAllowed(pathname, method) {
  if (pathname === API_UPLOAD) return method === "PUT";
  if (pathname.startsWith(API_STATUS)) return method === "GET";
  if (pathname.startsWith(API_DOWNLOAD)) return method === "GET";
  if (pathname === API_PRESETS) return method === "GET" || method === "POST";
  if (pathname.startsWith(API_PRESETS + "/")) return method === "GET" || method === "PUT" || method === "DELETE";
  if (pathname === API_ADMIN_SESSION) return method === "GET";
  if (pathname === "/api/auth/me") return method === "GET";
  if (pathname === "/api/auth/register" || pathname === "/api/auth/login" || pathname === "/api/auth/logout") return method === "POST";
  if (pathname === "/admin/login") return method === "GET" || method === "POST";
  if (pathname === "/admin/logout") return method === "POST";
  if (pathname === "/admin/session") return method === "GET";
  if (ADMIN_WORKSPACE_READ_PATHS.has(pathname) || isWpsAdminUserDetailPath(pathname)) {
    return method === "GET";
  }
  if (isWpsAdminMutationPath(pathname)) return method === "POST";
  if (pathname === "/monitor" || pathname === "/stats" || pathname === "/ip" || pathname === "/log/" || pathname.startsWith("/log/")) {
    return method === "GET";
  }
  if (pathname === "/ban" || pathname === "/unban" || pathname === "/limit" || pathname === "/cleanup") {
    return method === "POST";
  }
  if (pathname === "/api/health" || pathname === "/api/ready" || pathname === "/api/version") {
    return method === "GET";
  }
  const wpsMethods = WPS_API_METHODS.get(pathname);
  if (wpsMethods) return wpsMethods.has(method);
  return false;
}

function filterCookieHeader(cookieHeader) {
  const allowed = [];
  for (const part of String(cookieHeader || "").split(";")) {
    const trimmed = part.trim();
    if (!trimmed) continue;
    if (
      trimmed.startsWith("docxtool_admin_session=") ||
      trimmed.startsWith("docxtool_anon_user=")
      || trimmed.startsWith("docxtool_user_session=")
    ) allowed.push(trimmed);
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
    const accessClientId = String(env.CF_ACCESS_CLIENT_ID || "").trim();
    const accessClientSecret = String(env.CF_ACCESS_CLIENT_SECRET || "").trim();
    if (!backendBase) {
      return jsonError("BACKEND_NOT_CONFIGURED", "Cloudflare Pages env BACKEND_BASE_URL is not configured", 500);
    }
    if (!proxySecret) {
      return jsonError("PROXY_SECRET_NOT_CONFIGURED", "Cloudflare Pages env PROXY_SECRET is not configured", 500);
    }
    if (!accessClientId) {
      return jsonError("CF_ACCESS_CLIENT_ID_NOT_CONFIGURED", "Cloudflare Pages env CF_ACCESS_CLIENT_ID is not configured", 500);
    }
    if (!accessClientSecret) {
      return jsonError("CF_ACCESS_CLIENT_SECRET_NOT_CONFIGURED", "Cloudflare Pages env CF_ACCESS_CLIENT_SECRET is not configured", 500);
    }

    let backendOrigin;
    try {
      backendOrigin = new URL(backendBase);
    } catch (_) {
      return jsonError("BACKEND_URL_INVALID", "Cloudflare Pages env BACKEND_BASE_URL must be an HTTPS hostname origin", 500);
    }
    if (
      backendOrigin.protocol !== "https:"
      || !backendOrigin.hostname
      || backendOrigin.username
      || backendOrigin.password
      || backendOrigin.pathname !== "/"
      || backendOrigin.search
      || backendOrigin.hash
      || isIpLiteralHost(backendOrigin.hostname)
    ) {
      return jsonError("BACKEND_URL_INVALID", "Cloudflare Pages env BACKEND_BASE_URL must be an HTTPS hostname origin", 500);
    }

    const target = new URL(path, backendOrigin);
    target.search = url.search;

    const headers = new Headers(request.headers);
    const clientIp = request.headers.get("CF-Connecting-IP") || "";
    const protectedHeaders = [
      "Host",
      "Forwarded",
      "X-Proxy-Secret",
      "X-Docxtool-Proxy",
      "CF-Access-Client-Id",
      "CF-Access-Client-Secret",
      "X-Forwarded-For",
      "X-Real-IP",
      "X-Forwarded-Host",
      "X-Forwarded-Proto",
      "CF-Connecting-IP",
      "X-Admin-Token",
      "Cookie",
      "Proxy-Authorization",
    ];
    if (!isWpsPublicApiPath(url.pathname)) {
      protectedHeaders.push("Authorization");
    }
    for (const key of protectedHeaders) {
      headers.delete(key);
    }
    if (!isWpsPublicApiPath(url.pathname)) {
      const cookieHeader = filterCookieHeader(request.headers.get("Cookie"));
      if (cookieHeader) {
        headers.set("Cookie", cookieHeader);
      } else {
        headers.delete("Cookie");
      }
    }
    headers.set("X-Proxy-Secret", proxySecret);
    headers.set("X-Docxtool-Proxy", "cloudflare-pages");
    headers.set("CF-Access-Client-Id", accessClientId);
    headers.set("CF-Access-Client-Secret", accessClientSecret);
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
  } catch (_) {
    return jsonError("PROXY_WORKER_ERROR", "Worker proxy failed", 502);
  }
}

function isIpLiteralHost(hostname) {
  return /^\d{1,3}(?:\.\d{1,3}){3}$/.test(hostname) || hostname.includes(":");
}

export default {
  async fetch(request, env) {
    try {
      const url = new URL(request.url);
      if (shouldProxyPath(url.pathname)) {
        return proxyApi(request, env, url);
      }
      return env.ASSETS.fetch(request);
    } catch (_) {
      return jsonError("WORKER_ERROR", "Worker failed", 500);
    }
  },
};
