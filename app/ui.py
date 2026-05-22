from __future__ import annotations

import json
from dataclasses import dataclass
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

    def to_json(self) -> str:
        return json.dumps({"basePath": self.base_path}, ensure_ascii=False)


def render_admin_html(base_path: str) -> str:
    config = AdminRuntimeConfig.from_base_path(base_path)
    return (
        ADMIN_TEMPLATE
        .replace("__BASE_PATH__/static/style.css", config.static_path("style.css"))
        .replace("__BASE_PATH__/static/app.js", config.static_path("app.js"))
        .replace("__OAUTH_SLEEPER_RUNTIME_CONFIG__", config.to_json())
    )
