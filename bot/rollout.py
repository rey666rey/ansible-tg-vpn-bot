from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import re
import secrets
import string
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .config import Settings
from .database import normalize_panel_base_path, normalize_server_host


@dataclass(frozen=True)
class RolloutRequest:
    ip: str
    user: str
    password: str
    domain: str
    panel_domain: str | None = None
    panel_base_path: str | None = None


@dataclass(frozen=True)
class RolloutResult:
    ok: bool
    returncode: int | None
    stdout_tail: str
    stderr_tail: str
    hint: str | None = None
    xui_api_token_name: str | None = None
    xui_api_token: str | None = None
    xui_api_auth_header: str | None = None


def parse_rollout_message(
    text: str,
    default_user: str = "root",
    default_password: str = "",
) -> RolloutRequest:
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if "=" not in line:
            raise ValueError("каждая строка должна быть в формате key=value.")

        key, value = line.split("=", 1)
        key = key.strip().upper()
        value = value.strip()
        if key in {
            "IP",
            "USER",
            "PASSWORD",
            "DOMAIN",
            "PANEL_DOMAIN",
            "PANEL_HOST",
            "PANEL_BASE_PATH",
        }:
            values[key] = value

    ip = values.get("IP", "")
    explicit_user = "USER" in values
    explicit_password = "PASSWORD" in values
    user = values.get("USER", "")
    password = values.get("PASSWORD", "")
    domain = values.get("DOMAIN", "")
    panel_domain = values.get("PANEL_DOMAIN") or values.get("PANEL_HOST") or ""
    panel_base_path = values.get("PANEL_BASE_PATH") or ""

    if explicit_user != explicit_password:
        raise ValueError("user и password нужно указывать вместе или не указывать оба.")

    if not explicit_user and not explicit_password:
        user = default_user
        password = default_password

    if not ip or not password or not domain:
        raise ValueError(
            "нужны ip=... и domain=..., а user/password можно не указывать, "
            "если admin_user и admin_user_password заданы в .env."
        )
    if not user:
        raise ValueError("user не должен быть пустым.")

    try:
        ipaddress.ip_address(ip)
    except ValueError as exc:
        raise ValueError("ip выглядит некорректно.") from exc

    try:
        domain = normalize_server_host(domain)
    except ValueError as exc:
        raise ValueError("domain выглядит некорректно.") from exc

    if panel_domain:
        try:
            panel_domain = normalize_server_host(panel_domain)
        except ValueError as exc:
            raise ValueError("panel_domain выглядит некорректно.") from exc

    return RolloutRequest(
        ip=ip,
        user=user,
        password=password,
        domain=domain,
        panel_domain=panel_domain or None,
        panel_base_path=normalize_panel_base_path(panel_base_path),
    )


def generate_secret_path(length: int = 18) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "/" + "".join(secrets.choice(alphabet) for _ in range(length))


class RolloutRunner:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = asyncio.Lock()

    @property
    def busy(self) -> bool:
        return self._lock.locked()

    async def run(self, request: RolloutRequest) -> RolloutResult:
        async with self._lock:
            return await self._run_locked(request)

    async def _run_locked(self, request: RolloutRequest) -> RolloutResult:
        with tempfile.TemporaryDirectory(prefix="tg-rollout-") as tmpdir:
            inventory_path = Path(tmpdir) / "inventory.yml"
            inventory_path.write_text(
                json.dumps(
                    {
                        "all": {
                            "children": {
                                "xui_servers": {
                                    "hosts": {
                                        "server1": {
                                            "ansible_host": request.ip,
                                            "ansible_user": request.user,
                                            "ansible_port": 22,
                                            "ansible_password": request.password,
                                        }
                                    },
                                    "vars": {
                                        "ansible_become": True,
                                        "ansible_python_interpreter": "/usr/bin/python3",
                                    },
                                }
                            }
                        }
                    },
                    ensure_ascii=True,
                    indent=2,
                ),
                encoding="utf-8",
            )
            inventory_path.chmod(0o600)

            env = os.environ.copy()
            if not env.get("ANSIBLE_LOCAL_TEMP") or env["ANSIBLE_LOCAL_TEMP"].startswith("/private/"):
                env["ANSIBLE_LOCAL_TEMP"] = "/tmp/ansible-local"
            env.setdefault("ANSIBLE_HOST_KEY_CHECKING", "False")
            env["XUI_TLS_DOMAIN"] = request.domain
            if request.panel_domain:
                env["XUI_PANEL_DOMAIN"] = request.panel_domain
            else:
                env.setdefault("XUI_PANEL_DOMAIN", request.domain)
            if request.panel_base_path:
                env["XUI_PANEL_BASE_PATH"] = request.panel_base_path

            proc = await asyncio.create_subprocess_exec(
                "ansible-playbook",
                "-i",
                str(inventory_path),
                "server_tuning.yml",
                cwd=self.settings.project_root,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

            try:
                stdout_raw, stderr_raw = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=self.settings.rollout_timeout_seconds,
                )
            except TimeoutError:
                proc.kill()
                stdout_raw, stderr_raw = await proc.communicate()
                return RolloutResult(
                    ok=False,
                    returncode=None,
                    stdout_tail=_tail(stdout_raw),
                    stderr_tail="раскатка остановлена по таймауту.",
                    hint="ansible не успел закончить за отведенное время.",
                )

            stdout_tail = _tail(stdout_raw)
            stderr_tail = _tail(stderr_raw)
            return RolloutResult(
                ok=proc.returncode == 0,
                returncode=proc.returncode,
                stdout_tail=stdout_tail,
                stderr_tail=stderr_tail,
                hint=classify_rollout_failure(stdout_tail, stderr_tail),
                **parse_xui_api_token(stdout_raw),
            )


def _tail(raw: bytes, limit: int = 3500) -> str:
    text = raw.decode("utf-8", errors="replace").strip()
    if len(text) <= limit:
        return text
    return text[-limit:]


def classify_rollout_failure(stdout_tail: str, stderr_tail: str) -> str | None:
    text = f"{stdout_tail}\n{stderr_tail}".lower()
    if "invalid/incorrect password" in text or "permission denied" in text:
        return (
            "ssh не пустил на сервер: неверный user/password или root-login уже отключен. "
            "после reinstall обычно нужно указать user=root и новый root password от провайдера."
        )
    if "remote host identification has changed" in text or "offending" in text and "known_hosts" in text:
        return (
            "ssh host key изменился. такое нормально после reinstall vps. "
            "удали старый ключ командой ssh-keygen -R <ip> на машине, где крутится бот, "
            "или зайди в боте в 🧨 удалить сервер и раскатай заново."
        )
    if "using a ssh password instead of a key is not possible" in text:
        return (
            "ansible не может идти по паролю при включенной проверке host key. "
            "для первого входа поставь ANSIBLE_HOST_KEY_CHECKING=False или используй ssh-ключ."
        )
    if "no such file or directory" in text and "ansible-playbook" in text:
        return "на машине с ботом не установлен ansible-playbook."
    if "sshpass" in text and ("not found" in text or "to use the 'ssh' connection type with passwords" in text):
        return "для ssh-пароля на машине с ботом нужен пакет sshpass."
    if "connection timed out" in text or "operation timed out" in text:
        return "сервер недоступен по ssh: проверь ip, порт 22, firewall/security group и что vps уже загрузился."
    return None


def parse_xui_api_token(raw: bytes | str) -> dict[str, str | None]:
    text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
    normalized = text.replace("\\n", "\n").replace("\\r", "\r")
    return {
        "xui_api_token_name": _extract_token_value(normalized, "XUI_API_TOKEN_NAME"),
        "xui_api_token": _extract_token_value(normalized, "XUI_API_TOKEN"),
        "xui_api_auth_header": _extract_token_value(normalized, "XUI_API_AUTH_HEADER"),
    }


def _extract_token_value(text: str, key: str) -> str | None:
    match = re.search(rf"(?:^|\n)\s*{re.escape(key)}=([^\r\n\"]+)", text)
    if not match:
        return None
    value = match.group(1).strip()
    return value or None
