"""Route orchestration for server-rendered administrator workspace Web pages."""

from __future__ import annotations

from urllib.parse import parse_qs, urlencode


_WEB_SECTIONS = frozenset({"tasks", "security", "runtime", "logs"})
_WEB_TASK_PATHS = frozenset({"/admin/web", "/admin/web/tasks"})
_WPS_LIST_PATHS = frozenset(
    {"/admin/wps/users", "/admin/wps/devices", "/admin/wps/tasks"}
)


def _first(values: dict[str, list[str]], key: str, default: str = "") -> str:
    """Return one bounded query value without trusting browser input for later validation."""
    return str((values.get(key) or [default])[0])


def _bounded_query_values(
    parsed, fields: tuple[tuple[str, int], ...]
) -> dict[str, str]:
    """Keep only explicitly supported, bounded query state during a session handoff."""
    values = parse_qs(str(getattr(parsed, "query", "") or ""), keep_blank_values=True)
    result: dict[str, str] = {}
    for key, limit in fields:
        value = _first(values, key).strip()[:limit]
        if value:
            result[key] = value
    return result


def workspace_session_target(parsed) -> str:
    """Build a safe canonical workspace target after stripping a legacy credential query."""
    path = str(getattr(parsed, "path", "") or "/admin")
    fields: tuple[tuple[str, int], ...]
    if path in _WEB_TASK_PATHS:
        fields = (("q", 80), ("status", 20), ("page", 16), ("page_size", 16))
    elif path == "/admin/web/security":
        fields = (("ip", 80),)
    elif path == "/admin/web/logs":
        fields = (("task_id", 128),)
    elif path in _WPS_LIST_PATHS:
        fields = (
            ("q", 80),
            ("status", 20),
            ("online", 20),
            ("version", 40),
            ("page", 16),
            ("page_size", 16),
        )
    elif path.startswith("/admin/wps/users/") and "/" not in path[len("/admin/wps/users/"):]:
        fields = (("tab", 20), ("page", 16), ("page_size", 16))
    elif path in {"/admin", "/admin/wps", "/admin/web/runtime"}:
        fields = ()
    else:
        return "/admin"
    suffix = urlencode(_bounded_query_values(parsed, fields))
    return path + (f"?{suffix}" if suffix else "")


def _admin_web_url(section: str, **params: object) -> str:
    """Build a canonical Web-workspace URL from allow-listed, already-normalized values."""
    values: dict[str, str] = {}
    for key, value in params.items():
        text = str(value or "").strip()
        if not text:
            continue
        if key == "page" and text == "1":
            continue
        if key == "page_size" and text == "20":
            continue
        values[key] = text
    suffix = urlencode(values)
    return f"/admin/web/{section}" + (f"?{suffix}" if suffix else "")


def monitor_compat_target(parsed, *, monitor_query_from) -> str:
    """Map legacy monitor filters to the canonical task-center URL without echoing arbitrary query keys."""
    query = monitor_query_from(parsed)
    return _admin_web_url(
        "tasks",
        q=str(query.get("task_q") or "")[:80],
        status=str(query.get("task_status") or "")[:20],
        page=query.get("recent_page", 1),
        page_size=query.get("recent_size", 20),
    )


def ip_compat_target(ip: str) -> str:
    """Return the canonical security-detail URL for one legacy IP target."""
    return _admin_web_url("security", ip=str(ip or "").strip())


def log_compat_target(task_id: str) -> str:
    """Return the canonical logs-detail URL for one legacy task identifier."""
    return _admin_web_url("logs", task_id=str(task_id or "").strip()[:128])


def task_id_from_query(parsed) -> str:
    """Extract the bounded task-log detail selector from a canonical logs-page request."""
    values = parse_qs(parsed.query, keep_blank_values=True)
    return _first(values, "task_id").strip()[:128]


def handle_web_page(
    handler,
    parsed,
    section: str,
    *,
    require_admin,
    monitor_query_from,
    web_stats,
    readiness,
    runtime,
    limit_settings,
    csrf_input,
    render_page,
) -> None:
    """Query the existing Web statistics source and render one workspace subsection."""
    if not require_admin(parsed):
        return
    section = section if section in _WEB_SECTIONS else "tasks"
    values = parse_qs(parsed.query, keep_blank_values=True)
    query = dict(monitor_query_from(parsed))
    query["task_q"] = _first(values, "q")[:80]
    query["task_status"] = _first(values, "status")[:20]
    query["recent_page"] = _first(values, "page", str(query.get("recent_page", 1)))
    query["recent_size"] = _first(values, "page_size", str(query.get("recent_size", 20)))
    stats = web_stats(query)
    handler._text(
        render_page(
            section=section,
            stats=stats,
            query=stats["query"],
            readiness=readiness(),
            runtime=runtime(),
            limit=limit_settings(),
            csrf_input=csrf_input(handler._admin_csrf_token(parsed)),
        ),
        "text/html; charset=utf-8",
    )
