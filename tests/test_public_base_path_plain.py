from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import Settings
from app.ui import AdminRuntimeConfig, normalize_public_base_path, render_admin_html

APP_JS = ROOT / "app" / "static" / "app.js"


def assert_equal(actual, expected, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_contains(text: str, expected: str, label: str) -> None:
    if expected not in text:
        raise AssertionError(f"{label}: expected to find {expected!r}")


def assert_not_contains(text: str, unexpected: str, label: str) -> None:
    if unexpected in text:
        raise AssertionError(f"{label}: did not expect to find {unexpected!r}")


def test_normalize_public_base_path() -> None:
    cases = [
        ("", ""),
        (None, ""),
        ("/", ""),
        ("custom/oauth-sleeper", "/custom/oauth-sleeper"),
        ("/custom/oauth-sleeper/", "/custom/oauth-sleeper"),
        ("  /custom/oauth-sleeper//  ", "/custom/oauth-sleeper"),
    ]
    for raw, expected in cases:
        assert_equal(normalize_public_base_path(raw), expected, f"normalize {raw!r}")


def test_settings_delegates_public_base_path_canonicalization() -> None:
    settings = Settings(DATABASE_URL="postgresql://example/db", PUBLIC_BASE_PATH="custom/oauth-sleeper/")
    assert_equal(settings.public_base_path_prefix, "/custom/oauth-sleeper", "settings canonical prefix")


def test_admin_runtime_config_for_direct_access() -> None:
    config = AdminRuntimeConfig.from_base_path("")
    assert_equal(config.base_path, "", "direct base path")
    assert_equal(config.static_path("style.css?v=1"), "/static/style.css?v=1", "direct static path")
    assert_equal(config.to_json(), '{"basePath": ""}', "direct runtime json")


def test_admin_runtime_config_for_path_mount() -> None:
    config = AdminRuntimeConfig.from_base_path("/custom/oauth-sleeper/")
    assert_equal(config.base_path, "/custom/oauth-sleeper", "mounted base path")
    assert_equal(
        config.static_path("app.js?v=1"),
        "/custom/oauth-sleeper/static/app.js?v=1",
        "mounted static path",
    )
    assert_equal(config.to_json(), '{"basePath": "/custom/oauth-sleeper"}', "mounted runtime json")


def test_render_admin_html_for_direct_access() -> None:
    html = render_admin_html("")
    assert_contains(html, 'href="/static/style.css', "direct css path")
    assert_contains(html, 'src="/static/app.js', "direct js path")
    assert_contains(html, 'window.__OAUTH_SLEEPER_CONFIG__ = {"basePath": ""};', "direct config assignment")
    assert_not_contains(html, "__BASE_PATH__", "base path placeholder replaced")
    assert_not_contains(html, "__OAUTH_SLEEPER_RUNTIME_CONFIG__", "runtime placeholder replaced")


def test_render_admin_html_for_path_mount() -> None:
    html = render_admin_html("/custom/oauth-sleeper")
    assert_contains(html, 'href="/custom/oauth-sleeper/static/style.css', "mounted css path")
    assert_contains(html, 'src="/custom/oauth-sleeper/static/app.js', "mounted js path")
    assert_contains(
        html,
        'window.__OAUTH_SLEEPER_CONFIG__ = {"basePath": "/custom/oauth-sleeper"};',
        "mounted config assignment",
    )
    assert_not_contains(html, "__BASE_PATH__", "base path placeholder replaced")
    assert_not_contains(html, "__OAUTH_SLEEPER_RUNTIME_CONFIG__", "runtime placeholder replaced")


def test_frontend_source_uses_runtime_base_path() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    assert_not_contains(source, "/custom/oauth-sleeper/", "hardcoded browser prefix removed")
    assert_contains(source, "window.__OAUTH_SLEEPER_CONFIG__", "runtime config access")
    assert_contains(source, "joinBasePath(", "base-path join helper")
    assert_contains(source, "api/accounts?page=", "accounts api uses relative runtime path")
    assert_contains(source, "api/whitelist/", "whitelist api uses relative runtime path")


if __name__ == "__main__":
    tests = [
        test_normalize_public_base_path,
        test_settings_delegates_public_base_path_canonicalization,
        test_admin_runtime_config_for_direct_access,
        test_admin_runtime_config_for_path_mount,
        test_render_admin_html_for_direct_access,
        test_render_admin_html_for_path_mount,
        test_frontend_source_uses_runtime_base_path,
    ]
    for test in tests:
        try:
            test()
        except Exception as exc:
            print(f"FAIL {test.__name__}: {exc}")
            raise
        else:
            print(f"PASS {test.__name__}")
