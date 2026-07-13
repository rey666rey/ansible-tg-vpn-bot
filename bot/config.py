from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_ids: frozenset[int]
    rollout_timeout_seconds: int
    database_path: Path
    xui_panel_scheme: str
    xui_panel_domain: str
    xui_panel_port: int
    xui_panel_base_path: str
    xui_subscription_port: int
    xui_subscription_path: str
    xui_clash_subscription_path: str
    xui_api_token: str
    xui_inbound_ids: tuple[int, ...]
    xui_client_flow: str
    admin_user: str
    admin_password: str
    project_root: Path = PROJECT_ROOT


def _parse_int_list(raw: str) -> tuple[int, ...]:
    values: list[int] = []
    for item in raw.replace(";", ",").split(","):
        value = item.strip()
        if not value:
            continue
        values.append(int(value))
    return tuple(values)


def _parse_admin_ids(raw: str) -> frozenset[int]:
    ids: set[int] = set()
    for item in raw.replace(";", ",").split(","):
        value = item.strip()
        if not value:
            continue
        ids.add(int(value))
    return frozenset(ids)


def load_settings() -> Settings:
    load_env_file(PROJECT_ROOT / ".env")

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token or token == "PASTE_TELEGRAM_BOT_TOKEN_HERE":
        raise RuntimeError("Set TELEGRAM_BOT_TOKEN in .env")

    admin_ids = _parse_admin_ids(os.getenv("TELEGRAM_ADMIN_IDS", "1249561776"))
    if not admin_ids:
        raise RuntimeError("Set TELEGRAM_ADMIN_IDS in .env")

    timeout = int(os.getenv("ROLLOUT_TIMEOUT_SECONDS", "3600"))
    database_path = _project_path(os.getenv("SQLITE_DB_PATH", "data/bot.sqlite3"))
    panel_scheme = os.getenv("XUI_PANEL_SCHEME", "https").strip().lower()
    panel_domain = os.getenv("XUI_PANEL_DOMAIN", "").strip().lower()
    panel_port = int(os.getenv("XUI_PANEL_PORT", "24444"))
    panel_base_path = os.getenv("XUI_PANEL_BASE_PATH", "").strip()
    subscription_port = int(os.getenv("XUI_SUBSCRIPTION_PORT", "2096"))
    subscription_path = os.getenv("XUI_SUBSCRIPTION_PATH", "/subrey/").strip()
    clash_subscription_path = os.getenv("XUI_CLASH_SUBSCRIPTION_PATH", "/clashrey/").strip()
    api_token = os.getenv("XUI_API_TOKEN", "").strip()
    if api_token == "PASTE_3X_UI_API_TOKEN_HERE":
        api_token = ""
    inbound_ids = _parse_int_list(os.getenv("XUI_INBOUND_IDS", "1,2,3"))
    client_flow = os.getenv("XUI_CLIENT_FLOW", "xtls-rprx-vision").strip()
    admin_user = os.getenv("ADMIN_USER", "rey").strip() or "rey"
    admin_password = os.getenv("ADMIN_USER_PASSWORD", "").strip()

    return Settings(
        bot_token=token,
        admin_ids=admin_ids,
        rollout_timeout_seconds=timeout,
        database_path=database_path,
        xui_panel_scheme=panel_scheme,
        xui_panel_domain=panel_domain,
        xui_panel_port=panel_port,
        xui_panel_base_path=panel_base_path,
        xui_subscription_port=subscription_port,
        xui_subscription_path=subscription_path,
        xui_clash_subscription_path=clash_subscription_path,
        xui_api_token=api_token,
        xui_inbound_ids=inbound_ids,
        xui_client_flow=client_flow,
        admin_user=admin_user,
        admin_password=admin_password,
    )


def _project_path(raw: str) -> Path:
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue

        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in {"'", '"'}
        ):
            value = value[1:-1]

        os.environ.setdefault(key, value)
