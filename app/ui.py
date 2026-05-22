from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
ADMIN_TEMPLATE = (STATIC_DIR / "index.html").read_text(encoding="utf-8")


def normalize_public_base_path(value: str | None) -> str:
    text = (value or "").strip()
    if not text or text == "/":
        return ""
    if not text.startswith("/"):
        text = f"/{text}"
    return text.rstrip("/")


@dataclass(frozen=True)
class AdminRuntimeConfig:
    base_path: str

    @classmethod
    def from_base_path(cls, value: str | None) -> "AdminRuntimeConfig":
        return cls(base_path=normalize_public_base_path(value))

    def static_path(self, asset: str) -> str:
        clean_asset = asset.lstrip("/")
        path = f"/static/{clean_asset}"
        return f"{self.base_path}{path}" if self.base_path else path

    def versioned_static_path(self, asset: str) -> str:
        clean_asset = asset.lstrip("/")
        version = static_asset_version(clean_asset)
        return f"{self.static_path(clean_asset)}?v={version}"

    def to_json(self) -> str:
        return json.dumps({"basePath": self.base_path}, ensure_ascii=False)


@lru_cache(maxsize=None)
def static_asset_version(asset: str) -> str:
    asset_path = STATIC_DIR / asset
    return hashlib.sha256(asset_path.read_bytes()).hexdigest()[:12]


def render_admin_html(base_path: str) -> str:
    config = AdminRuntimeConfig.from_base_path(base_path)
    return (
        ADMIN_TEMPLATE
        .replace("__STYLE_CSS_URL__", config.versioned_static_path("style.css"))
        .replace("__APP_JS_URL__", config.versioned_static_path("app.js"))
        .replace("__OAUTH_SLEEPER_RUNTIME_CONFIG__", config.to_json())
    )
