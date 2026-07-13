from __future__ import annotations

import ipaddress
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


DOMAIN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


@dataclass(frozen=True)
class Server:
    id: int
    host: str
    panel_host: str | None = None
    subscription_host: str | None = None
    panel_base_path: str | None = None
    xui_api_token_name: str | None = None
    xui_api_token: str | None = None
    xui_api_auth_header: str | None = None


@dataclass(frozen=True)
class Client:
    id: int
    name: str
    server_host: str
    subscription_url: str
    clash_subscription_url: str
    created_at: str
    updated_at: str | None = None


class ServerRepository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS servers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    host TEXT NOT NULL UNIQUE,
                    panel_host TEXT,
                    subscription_host TEXT,
                    panel_base_path TEXT,
                    xui_api_token_name TEXT,
                    xui_api_token TEXT,
                    xui_api_auth_header TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS clients (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    server_host TEXT NOT NULL,
                    subscription_url TEXT NOT NULL,
                    clash_subscription_url TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(name, server_host)
                )
                """
            )
            self._ensure_columns(conn)

    def add(
        self,
        host: str,
        panel_host: str | None = None,
        subscription_host: str | None = None,
        panel_base_path: str | None = None,
    ) -> tuple[Server, bool]:
        normalized_host = normalize_server_host(host)
        normalized_panel_host = normalize_server_host(panel_host) if panel_host else None
        normalized_subscription_host = (
            normalize_server_host(subscription_host) if subscription_host else normalized_host
        )
        normalized_panel_base_path = normalize_panel_base_path(panel_base_path)
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO servers(
                    host,
                    panel_host,
                    subscription_host,
                    panel_base_path
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    normalized_host,
                    normalized_panel_host,
                    normalized_subscription_host,
                    normalized_panel_base_path,
                ),
            )
            created = cursor.rowcount > 0
            if not created:
                conn.execute(
                    """
                    UPDATE servers
                    SET panel_host = COALESCE(?, panel_host),
                        subscription_host = COALESCE(?, subscription_host, host),
                        panel_base_path = COALESCE(?, panel_base_path),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE host = ?
                    """,
                    (
                        normalized_panel_host,
                        normalized_subscription_host,
                        normalized_panel_base_path,
                        normalized_host,
                    ),
                )
            row = conn.execute(
                """
                SELECT id, host, panel_host, subscription_host,
                       panel_base_path, xui_api_token_name,
                       xui_api_token, xui_api_auth_header
                FROM servers
                WHERE host = ?
                """,
                (normalized_host,),
            ).fetchone()

        if row is None:
            raise RuntimeError("Could not save server.")
        return _row_to_server(row), created

    def save_xui_api_token(
        self,
        host: str,
        token_name: str | None,
        token: str,
        auth_header: str | None,
        panel_host: str | None = None,
        subscription_host: str | None = None,
        panel_base_path: str | None = None,
    ) -> Server:
        normalized_host = normalize_server_host(host)
        normalized_panel_host = normalize_server_host(panel_host) if panel_host else None
        normalized_subscription_host = (
            normalize_server_host(subscription_host) if subscription_host else None
        )
        normalized_panel_base_path = normalize_panel_base_path(panel_base_path)
        normalized_token_name = (token_name or "").strip() or None
        normalized_auth_header = (auth_header or "").strip() or None
        token = token.strip()
        if not token:
            raise ValueError("XUI API token is empty.")

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO servers(
                    host,
                    panel_host,
                    subscription_host,
                    panel_base_path,
                    xui_api_token_name,
                    xui_api_token,
                    xui_api_auth_header,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(host) DO UPDATE SET
                    panel_host = COALESCE(excluded.panel_host, servers.panel_host),
                    subscription_host = COALESCE(excluded.subscription_host, servers.subscription_host, servers.host),
                    panel_base_path = COALESCE(excluded.panel_base_path, servers.panel_base_path),
                    xui_api_token_name = excluded.xui_api_token_name,
                    xui_api_token = excluded.xui_api_token,
                    xui_api_auth_header = excluded.xui_api_auth_header,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    normalized_host,
                    normalized_panel_host,
                    normalized_subscription_host,
                    normalized_panel_base_path,
                    normalized_token_name,
                    token,
                    normalized_auth_header,
                ),
            )
            row = conn.execute(
                """
                SELECT id, host, panel_host, subscription_host,
                       panel_base_path, xui_api_token_name,
                       xui_api_token, xui_api_auth_header
                FROM servers
                WHERE host = ?
                """,
                (normalized_host,),
            ).fetchone()

        if row is None:
            raise RuntimeError("Could not save server token.")
        return _row_to_server(row)

    def get(self, value: str) -> Server | None:
        value = value.strip()
        if not value:
            return None

        with self._connect() as conn:
            if value.isdigit():
                row = conn.execute(
                    """
                    SELECT id, host, panel_host, subscription_host,
                           panel_base_path, xui_api_token_name,
                           xui_api_token, xui_api_auth_header
                    FROM servers
                    WHERE id = ?
                    """,
                    (int(value),),
                ).fetchone()
            else:
                try:
                    host = normalize_server_host(value)
                except ValueError:
                    return None
                row = conn.execute(
                    """
                    SELECT id, host, panel_host, subscription_host,
                           panel_base_path, xui_api_token_name,
                           xui_api_token, xui_api_auth_header
                    FROM servers
                    WHERE host = ? OR panel_host = ? OR subscription_host = ?
                    """,
                    (host, host, host),
                ).fetchone()

        if row is None:
            return None
        return _row_to_server(row)

    def list(self) -> list[Server]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, host, panel_host, subscription_host,
                       panel_base_path, xui_api_token_name,
                       xui_api_token, xui_api_auth_header
                FROM servers
                ORDER BY id
                """
            ).fetchall()
        return [_row_to_server(row) for row in rows]

    def save_client(
        self,
        name: str,
        server_host: str,
        subscription_url: str,
        clash_subscription_url: str,
    ) -> Client:
        normalized_name = name.strip()
        normalized_host = normalize_server_host(server_host)
        if not normalized_name:
            raise ValueError("Client name is empty.")

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO clients(
                    name,
                    server_host,
                    subscription_url,
                    clash_subscription_url,
                    updated_at
                )
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(name, server_host) DO UPDATE SET
                    subscription_url = excluded.subscription_url,
                    clash_subscription_url = excluded.clash_subscription_url,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    normalized_name,
                    normalized_host,
                    subscription_url,
                    clash_subscription_url,
                ),
            )
            row = conn.execute(
                """
                SELECT id, name, server_host, subscription_url, clash_subscription_url,
                       created_at, updated_at
                FROM clients
                WHERE name = ? AND server_host = ?
                """,
                (normalized_name, normalized_host),
            ).fetchone()

        if row is None:
            raise RuntimeError("Could not save client.")
        return _row_to_client(row)

    def list_clients(self) -> list[Client]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, name, server_host, subscription_url, clash_subscription_url,
                       created_at, updated_at
                FROM clients
                ORDER BY lower(name), lower(server_host)
                """
            ).fetchall()
        return [_row_to_client(row) for row in rows]

    def delete_client_records(self, name: str) -> int:
        normalized_name = name.strip()
        if not normalized_name:
            return 0
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM clients WHERE lower(name) = lower(?)",
                (normalized_name,),
            )
            return int(cursor.rowcount)

    def _ensure_columns(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute("PRAGMA table_info(servers)").fetchall()
        columns = {str(row["name"]) for row in rows}
        migrations = {
            "xui_api_token_name": "ALTER TABLE servers ADD COLUMN xui_api_token_name TEXT",
            "xui_api_token": "ALTER TABLE servers ADD COLUMN xui_api_token TEXT",
            "xui_api_auth_header": "ALTER TABLE servers ADD COLUMN xui_api_auth_header TEXT",
            "panel_host": "ALTER TABLE servers ADD COLUMN panel_host TEXT",
            "subscription_host": "ALTER TABLE servers ADD COLUMN subscription_host TEXT",
            "panel_base_path": "ALTER TABLE servers ADD COLUMN panel_base_path TEXT",
            "updated_at": "ALTER TABLE servers ADD COLUMN updated_at TEXT",
        }
        for column, statement in migrations.items():
            if column not in columns:
                conn.execute(statement)

        client_rows = conn.execute("PRAGMA table_info(clients)").fetchall()
        client_columns = {str(row["name"]) for row in client_rows}
        client_migrations = {
            "updated_at": "ALTER TABLE clients ADD COLUMN updated_at TEXT",
        }
        for column, statement in client_migrations.items():
            if column not in client_columns:
                conn.execute(statement)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn


def parse_add_server_message(text: str) -> str:
    line = text.strip()
    if not line:
        raise ValueError("пришли ip или домен сервера.")

    if "=" in line:
        values: dict[str, str] = {}
        for raw_line in line.splitlines():
            item = raw_line.strip()
            if not item:
                continue
            if "=" not in item:
                raise ValueError("каждая строка должна быть в формате key=value.")
            key, value = item.split("=", 1)
            values[key.strip().upper()] = value.strip()
        line = values.get("SERVER") or values.get("HOST") or values.get("IP") or values.get("DOMAIN") or ""

    return normalize_server_host(line)


def _row_to_server(row: sqlite3.Row) -> Server:
    return Server(
        id=int(row["id"]),
        host=str(row["host"]),
        panel_host=row["panel_host"],
        subscription_host=row["subscription_host"],
        panel_base_path=row["panel_base_path"],
        xui_api_token_name=row["xui_api_token_name"],
        xui_api_token=row["xui_api_token"],
        xui_api_auth_header=row["xui_api_auth_header"],
    )


def _row_to_client(row: sqlite3.Row) -> Client:
    return Client(
        id=int(row["id"]),
        name=str(row["name"]),
        server_host=str(row["server_host"]),
        subscription_url=str(row["subscription_url"]),
        clash_subscription_url=str(row["clash_subscription_url"]),
        created_at=str(row["created_at"]),
        updated_at=row["updated_at"],
    )


def normalize_server_host(value: str) -> str:
    host = value.strip().lower().rstrip("/")
    if not host:
        raise ValueError("пришли ip или домен сервера.")

    if "://" in host:
        parsed = urlparse(host)
        host = parsed.hostname or ""

    if not host:
        raise ValueError("не смог прочитать ip или домен.")

    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        pass

    host = host.rstrip(".")
    if not _is_valid_domain(host):
        raise ValueError("это не похоже на ip или домен.")
    return host


def normalize_panel_base_path(value: str | None) -> str | None:
    path = (value or "").strip()
    if not path:
        return None
    path = path.strip("/")
    if not path:
        return None
    if "/" in path or not re.fullmatch(r"[A-Za-z0-9._~-]+", path):
        raise ValueError("panel_base_path должен быть одним url-сегментом без slash.")
    if path == "panel":
        raise ValueError("panel_base_path не должен быть равен panel.")
    return "/" + path


def _is_valid_domain(host: str) -> bool:
    if len(host) > 253 or "." not in host:
        return False
    labels = host.split(".")
    return all(DOMAIN_RE.fullmatch(label) for label in labels)
