from docxtool.web.routing import match_get_route, match_post_route


def test_wps_public_routes_are_explicit():
    assert match_get_route("/wps-api/v1/auth/me").action == "wps_auth_me"
    expected = {
        "/wps-api/v1/auth/register": "wps_auth_register",
        "/wps-api/v1/auth/login": "wps_auth_login",
        "/wps-api/v1/auth/logout": "wps_auth_logout",
        "/wps-api/v1/heartbeat": "wps_heartbeat",
        "/wps-api/v1/format/authorize": "wps_format_authorize",
        "/wps-api/v1/format/result": "wps_format_result",
    }
    assert {path: match_post_route(path).action for path in expected} == expected
