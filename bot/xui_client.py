from __future__ import annotations

import asyncio
import http.client
import json
import secrets
import ssl
import time
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import ParseResult, quote, urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen

from .config import Settings
from .database import Server, ServerRepository, normalize_server_host


@dataclass(frozen=True)
class XuiAddClientRequest:
    server_ref: str
    api_token: str
    inbound_ids: tuple[int, ...]
    email: str
    total_gb: Decimal
    days: int
    sub_base_url: str | None
    sub_path: str | None
    clash_path: str | None
    flow: str
    limit_ip: int
    tg_id: int
    comment: str
    tls_verify: bool
    sub_id: str | None = None


@dataclass(frozen=True)
class XuiAddClientResult:
    email: str
    sub_id: str
    subscription_url: str
    clash_subscription_url: str


@dataclass(frozen=True)
class XuiSubscriptionRequest:
    server_ref: str
    client_name: str
    sub_base_url: str | None
    sub_path: str | None
    clash_path: str | None
    api_token: str | None
    inbound_ids: tuple[int, ...] | None
    total_gb: Decimal
    days: int
    flow: str | None
    limit_ip: int
    tg_id: int
    comment: str
    tls_verify: bool


@dataclass(frozen=True)
class XuiBulkSubscriptionRequest:
    client_name: str
    sub_path: str | None
    clash_path: str | None
    inbound_ids: tuple[int, ...] | None
    total_gb: Decimal
    days: int
    flow: str | None
    limit_ip: int
    tg_id: int
    comment: str
    tls_verify: bool


@dataclass(frozen=True)
class XuiSubscriptionResult:
    client_name: str
    subscription_url: str
    clash_subscription_url: str
    created: bool
    inbound_ids: tuple[int, ...]


@dataclass(frozen=True)
class XuiServerSubscriptionResult:
    server: Server
    result: XuiSubscriptionResult | None
    error: str | None
    validation_errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class XuiServerCheckResult:
    server: Server
    ok: bool
    details: tuple[str, ...]


class XuiApiError(RuntimeError):
    pass


MANAGED_INBOUND_TAGS = (
    "in-vless-reality-8443",
    "in-vless-xhttp-tls-443",
    "in-hysteria2-443",
)


def parse_bulk_subscription_message(text: str) -> XuiBulkSubscriptionRequest:
    if "=" in text:
        values = _parse_key_values(text)
        client_name = (
            values.get("CLIENT")
            or values.get("EMAIL")
            or values.get("NAME")
            or values.get("SUB_ID")
        )
        inbound_ids_raw = (
            values.get("INBOUND_IDS")
            or values.get("INBOUNDS")
            or values.get("INBOUND_ID")
        )
    else:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        client_name = lines[0] if lines else None
        inbound_ids_raw = None
        values = {}

    if not client_name:
        raise ValueError("пришли имя клиента.")

    client_name = client_name.strip()
    if not client_name:
        raise ValueError("имя клиента не должно быть пустым.")

    return XuiBulkSubscriptionRequest(
        client_name=client_name,
        sub_path=_empty_to_none(values.get("SUB_PATH")),
        clash_path=_empty_to_none(values.get("CLASH_PATH")),
        inbound_ids=(
            _parse_inbound_ids(inbound_ids_raw)
            if inbound_ids_raw
            else None
        ),
        total_gb=_parse_decimal(values.get("GB") or values.get("TOTAL_GB") or "0", "GB"),
        days=_parse_int(values.get("DAYS") or "0", "DAYS", minimum=0),
        flow=_empty_to_none(values.get("FLOW")),
        limit_ip=_parse_int(values.get("LIMIT_IP") or "0", "LIMIT_IP", minimum=0),
        tg_id=_parse_int(values.get("TG_ID") or "0", "TG_ID", minimum=0),
        comment=(values.get("COMMENT") or "").strip(),
        tls_verify=_parse_bool(values.get("TLS_VERIFY") or "true"),
    )


def parse_subscription_message(text: str) -> XuiSubscriptionRequest:
    if "=" in text:
        values = _parse_key_values(text)
        server_ref = (
            values.get("SERVER")
            or values.get("HOST")
            or values.get("IP")
            or values.get("DOMAIN")
            or values.get("PANEL_URL")
            or values.get("URL")
        )
        client_name = (
            values.get("CLIENT")
            or values.get("EMAIL")
            or values.get("NAME")
            or values.get("SUB_ID")
        )
        api_token = _empty_to_none(values.get("API_TOKEN") or values.get("TOKEN"))
        inbound_ids_raw = (
            values.get("INBOUND_IDS")
            or values.get("INBOUNDS")
            or values.get("INBOUND_ID")
        )
    else:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        server_ref = lines[0] if len(lines) >= 1 else None
        client_name = lines[1] if len(lines) >= 2 else None
        api_token = None
        inbound_ids_raw = None
        values = {}

    missing = [
        name
        for name, value in (
            ("IP или домен сервера", server_ref),
            ("имя клиента", client_name),
        )
        if not value
    ]
    if missing:
        raise ValueError("не хватает полей: " + ", ".join(missing) + ".")

    server_ref = server_ref.strip()
    parsed_url = urlparse(server_ref)
    if parsed_url.scheme and parsed_url.scheme not in {"http", "https"}:
        raise ValueError("url должен начинаться с http:// или https://.")
    if not parsed_url.scheme and not server_ref.isdigit():
        normalize_server_host(server_ref)

    client_name = client_name.strip()
    if not client_name:
        raise ValueError("имя клиента не должно быть пустым.")

    return XuiSubscriptionRequest(
        server_ref=server_ref,
        client_name=client_name,
        sub_base_url=_empty_to_none(values.get("SUB_BASE_URL") or values.get("SUB_URL")),
        sub_path=_empty_to_none(values.get("SUB_PATH")),
        clash_path=_empty_to_none(values.get("CLASH_PATH")),
        api_token=api_token,
        inbound_ids=(
            _parse_inbound_ids(inbound_ids_raw)
            if inbound_ids_raw
            else None
        ),
        total_gb=_parse_decimal(values.get("GB") or values.get("TOTAL_GB") or "0", "GB"),
        days=_parse_int(values.get("DAYS") or "0", "DAYS", minimum=0),
        flow=_empty_to_none(values.get("FLOW")),
        limit_ip=_parse_int(values.get("LIMIT_IP") or "0", "LIMIT_IP", minimum=0),
        tg_id=_parse_int(values.get("TG_ID") or "0", "TG_ID", minimum=0),
        comment=(values.get("COMMENT") or "").strip(),
        tls_verify=_parse_bool(values.get("TLS_VERIFY") or "true"),
    )


def parse_add_client_message(text: str) -> XuiAddClientRequest:
    values = _parse_key_values(text)

    server_ref = values.get("PANEL_URL") or values.get("SERVER") or values.get("URL")
    api_token = values.get("API_TOKEN") or values.get("TOKEN")
    inbound_ids_raw = values.get("INBOUND_IDS") or values.get("INBOUNDS") or values.get("INBOUND_ID")
    email = values.get("EMAIL") or values.get("CLIENT")

    missing = [
        name
        for name, value in (
            ("SERVER или PANEL_URL", server_ref),
            ("API_TOKEN", api_token),
            ("INBOUND_IDS", inbound_ids_raw),
            ("EMAIL", email),
        )
        if not value
    ]
    if missing:
        raise ValueError("не хватает полей: " + ", ".join(missing) + ".")

    server_ref = server_ref.strip()
    parsed_url = urlparse(server_ref)
    if parsed_url.scheme and parsed_url.scheme not in {"http", "https"}:
        raise ValueError("panel_url должен начинаться с http:// или https://.")
    if not parsed_url.scheme and not server_ref.isdigit():
        normalize_server_host(server_ref)

    inbound_ids = _parse_inbound_ids(inbound_ids_raw)
    total_gb = _parse_decimal(values.get("GB") or values.get("TOTAL_GB") or "0", "GB")
    days = _parse_int(values.get("DAYS") or "0", "DAYS", minimum=0)
    limit_ip = _parse_int(values.get("LIMIT_IP") or "0", "LIMIT_IP", minimum=0)
    tg_id = _parse_int(values.get("TG_ID") or "0", "TG_ID", minimum=0)
    tls_verify = _parse_bool(values.get("TLS_VERIFY") or "true")

    return XuiAddClientRequest(
        server_ref=server_ref,
        api_token=api_token.strip(),
        inbound_ids=inbound_ids,
        email=email.strip(),
        total_gb=total_gb,
        days=days,
        sub_base_url=_empty_to_none(values.get("SUB_BASE_URL") or values.get("SUB_URL")),
        sub_path=_empty_to_none(values.get("SUB_PATH")),
        clash_path=_empty_to_none(values.get("CLASH_PATH")),
        flow=(values.get("FLOW") or "xtls-rprx-vision").strip(),
        limit_ip=limit_ip,
        tg_id=tg_id,
        comment=(values.get("COMMENT") or "").strip(),
        tls_verify=tls_verify,
    )


class XuiClientService:
    def __init__(self, settings: Settings, server_repository: ServerRepository) -> None:
        self.settings = settings
        self.server_repository = server_repository

    def get_subscription(
        self,
        request: XuiSubscriptionRequest,
    ) -> XuiSubscriptionResult:
        panel_url = self._resolve_panel_url(request.server_ref)
        return self._subscription_result(panel_url, request, created=False, inbound_ids=())

    async def ensure_client_subscription(
        self,
        request: XuiSubscriptionRequest,
    ) -> XuiSubscriptionResult:
        server = self._resolve_server_record(request.server_ref)
        api_token = (
            request.api_token
            or (server.xui_api_token if server else None)
            or self.settings.xui_api_token
        )
        if not api_token:
            raise XuiApiError(
                "у этого сервера нет xui api token в базе. "
                "сначала раскатай сервер или передай api_token вручную."
            )

        panel_url = self._resolve_panel_url(request.server_ref)
        inbound_ids = await self._resolve_inbound_ids(
            panel_url=panel_url,
            requested_ids=request.inbound_ids,
            api_token=api_token,
            tls_verify=request.tls_verify,
        )
        if not inbound_ids:
            raise XuiApiError("задай xui_inbound_ids в .env.")

        add_request = XuiAddClientRequest(
            server_ref=request.server_ref,
            api_token=api_token,
            inbound_ids=inbound_ids,
            email=request.client_name,
            total_gb=request.total_gb,
            days=request.days,
            sub_base_url=request.sub_base_url,
            sub_path=request.sub_path,
            clash_path=request.clash_path,
            flow=request.flow or self.settings.xui_client_flow,
            limit_ip=request.limit_ip,
            tg_id=request.tg_id,
            comment=request.comment,
            tls_verify=request.tls_verify,
            sub_id=request.client_name,
        )

        try:
            await self.add_client(add_request)
        except XuiApiError as exc:
            if not _looks_like_existing_client(str(exc)):
                raise
            return self._subscription_result(
                panel_url,
                request,
                created=False,
                inbound_ids=inbound_ids,
            )

        return self._subscription_result(
            panel_url,
            request,
            created=True,
            inbound_ids=inbound_ids,
        )

    async def ensure_client_subscription_on_all_servers(
        self,
        request: XuiBulkSubscriptionRequest,
    ) -> list[XuiServerSubscriptionResult]:
        servers = self.server_repository.list()
        if not servers:
            raise XuiApiError("в базе пока нет серверов. сначала раскатай сервер.")

        tasks = [
            self._ensure_client_subscription_on_server(server, request)
            for server in servers
        ]
        return await asyncio.gather(*tasks)

    async def _ensure_client_subscription_on_server(
        self,
        server: Server,
        request: XuiBulkSubscriptionRequest,
    ) -> XuiServerSubscriptionResult:
        server_request = XuiSubscriptionRequest(
            server_ref=server.host,
            client_name=request.client_name,
            sub_base_url=None,
            sub_path=request.sub_path,
            clash_path=request.clash_path,
            api_token=None,
            inbound_ids=request.inbound_ids,
            total_gb=request.total_gb,
            days=request.days,
            flow=request.flow,
            limit_ip=request.limit_ip,
            tg_id=request.tg_id,
            comment=request.comment,
            tls_verify=request.tls_verify,
        )
        try:
            result = await self.ensure_client_subscription(server_request)
            validation_errors = await self.validate_clash_subscription(
                result.clash_subscription_url
            )
        except XuiApiError as exc:
            return XuiServerSubscriptionResult(
                server=server,
                result=None,
                error=str(exc),
            )
        except Exception as exc:
            return XuiServerSubscriptionResult(
                server=server,
                result=None,
                error=f"неожиданная ошибка: {exc}",
            )
        return XuiServerSubscriptionResult(
            server=server,
            result=result,
            error=None,
            validation_errors=tuple(validation_errors),
        )

    async def check_all_servers(self) -> list[XuiServerCheckResult]:
        servers = self.server_repository.list()
        tasks = [self.check_server(server) for server in servers]
        return await asyncio.gather(*tasks) if tasks else []

    async def check_server(self, server: Server) -> XuiServerCheckResult:
        details: list[str] = []
        if not server.xui_api_token:
            return XuiServerCheckResult(
                server=server,
                ok=False,
                details=("нет xui api token в базе",),
            )

        panel_url = self._resolve_panel_url(server.host)
        try:
            response = await asyncio.to_thread(
                self._get_json_with_scheme_fallback,
                _api_url(panel_url, "/panel/api/inbounds/list"),
                server.xui_api_token,
                True,
            )
        except XuiApiError as exc:
            return XuiServerCheckResult(
                server=server,
                ok=False,
                details=(f"api не отвечает: {exc}",),
            )

        if not response.get("success", False):
            return XuiServerCheckResult(
                server=server,
                ok=False,
                details=("api ответил, но success=false",),
            )

        rows = response.get("obj")
        if not isinstance(rows, list):
            return XuiServerCheckResult(
                server=server,
                ok=False,
                details=("api вернул странный список inbound-ов",),
            )

        tags = {
            str(row.get("tag") or "").strip()
            for row in rows
            if isinstance(row, dict)
        }
        remarks = {
            str(row.get("remark") or "").strip()
            for row in rows
            if isinstance(row, dict)
        }
        missing = [
            tag
            for tag in MANAGED_INBOUND_TAGS
            if tag not in tags and tag.removeprefix("in-") not in remarks
        ]
        if missing:
            details.append("не найдены inbound-ы: " + ", ".join(missing))
        else:
            details.append("managed inbound-ы на месте")

        details.append(f"api token: {server.xui_api_token_name or 'без имени'}")
        return XuiServerCheckResult(
            server=server,
            ok=not missing,
            details=tuple(details),
        )

    async def validate_clash_subscription(self, clash_url: str) -> list[str]:
        try:
            text = await asyncio.to_thread(self._get_text, clash_url, True)
        except XuiApiError as exc:
            return [f"clash-сабка не скачалась: {exc}"]

        return _validate_mihomo_subscription_text(text)

    async def _resolve_inbound_ids(
        self,
        panel_url: str,
        requested_ids: tuple[int, ...] | None,
        api_token: str,
        tls_verify: bool,
    ) -> tuple[int, ...]:
        if requested_ids:
            return requested_ids

        try:
            response = await asyncio.to_thread(
                self._get_json_with_scheme_fallback,
                _api_url(panel_url, "/panel/api/inbounds/list"),
                api_token,
                tls_verify,
            )
        except XuiApiError:
            return self.settings.xui_inbound_ids

        if not response.get("success", False):
            return self.settings.xui_inbound_ids

        rows = response.get("obj")
        if not isinstance(rows, list):
            return self.settings.xui_inbound_ids

        by_tag: dict[str, int] = {}
        by_remark: dict[str, int] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                inbound_id = int(row["id"])
            except (KeyError, TypeError, ValueError):
                continue
            tag = str(row.get("tag") or "").strip()
            remark = str(row.get("remark") or "").strip()
            if tag:
                by_tag[tag] = inbound_id
            if remark:
                by_remark[remark] = inbound_id

        ids = tuple(
            by_tag.get(tag) or by_remark.get(tag.removeprefix("in-"))
            for tag in MANAGED_INBOUND_TAGS
        )
        if all(ids):
            return tuple(int(item) for item in ids)

        return self.settings.xui_inbound_ids

    async def add_client(self, request: XuiAddClientRequest) -> XuiAddClientResult:
        panel_url = self._resolve_panel_url(request.server_ref)
        sub_id = request.sub_id or secrets.token_urlsafe(8)
        payload = {
            "client": {
                "id": str(uuid.uuid4()),
                "email": request.email,
                "security": "auto",
                "flow": request.flow,
                "limitIp": request.limit_ip,
                "totalGB": _gb_to_bytes(request.total_gb),
                "expiryTime": _expiry_time_ms(request.days),
                "enable": True,
                "tgId": request.tg_id,
                "subId": sub_id,
                "comment": request.comment,
                "reset": 0,
            },
            "inboundIds": list(request.inbound_ids),
        }

        response = await asyncio.to_thread(
            self._post_json_with_scheme_fallback,
            _api_url(panel_url, "/panel/api/clients/add"),
            request.api_token,
            payload,
            request.tls_verify,
        )
        if not response.get("success", False):
            message = response.get("msg") or response.get("message") or "3x-ui вернул ошибку."
            raise XuiApiError(str(message))

        sub_base_url = request.sub_base_url or _default_sub_base_url(
            panel_url,
            self.settings.xui_subscription_port,
        )
        return XuiAddClientResult(
            email=request.email,
            sub_id=sub_id,
            subscription_url=_subscription_url(
                sub_base_url,
                request.sub_path or self.settings.xui_subscription_path,
                sub_id,
            ),
            clash_subscription_url=_subscription_url(
                sub_base_url,
                request.clash_path or self.settings.xui_clash_subscription_path,
                sub_id,
            ),
        )

    def _subscription_result(
        self,
        panel_url: str,
        request: XuiSubscriptionRequest,
        created: bool,
        inbound_ids: tuple[int, ...],
    ) -> XuiSubscriptionResult:
        sub_base_url = request.sub_base_url or _default_sub_base_url(
            panel_url,
            self.settings.xui_subscription_port,
        )
        return XuiSubscriptionResult(
            client_name=request.client_name,
            subscription_url=_subscription_url(
                sub_base_url,
                request.sub_path or self.settings.xui_subscription_path,
                request.client_name,
            ),
            clash_subscription_url=_subscription_url(
                sub_base_url,
                request.clash_path or self.settings.xui_clash_subscription_path,
                request.client_name,
            ),
            created=created,
            inbound_ids=inbound_ids,
        )

    def _post_json(
        self,
        url: str,
        api_token: str,
        payload: dict[str, Any],
        tls_verify: bool,
    ) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        req = Request(
            url,
            data=body,
            headers={
                "Authorization": f"Bearer {api_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        return self._open_json(req, tls_verify)

    def _open_json(self, req: Request, tls_verify: bool) -> dict[str, Any]:
        context = None if tls_verify else ssl._create_unverified_context()
        try:
            with urlopen(req, timeout=30, context=context) as resp:
                raw = resp.read()
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace").strip()
            raise XuiApiError(f"HTTP {exc.code}: {raw or exc.reason}") from exc
        except ssl.SSLError as exc:
            raise XuiApiError(str(exc)) from exc
        except URLError as exc:
            raise XuiApiError(str(exc.reason)) from exc
        except http.client.RemoteDisconnected as exc:
            raise XuiApiError(str(exc)) from exc
        except http.client.HTTPException as exc:
            raise XuiApiError(str(exc)) from exc
        except OSError as exc:
            raise XuiApiError(str(exc)) from exc

        try:
            data = json.loads(raw.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            raise XuiApiError("3x-ui вернул не json.") from exc
        if not isinstance(data, dict):
            raise XuiApiError("3x-ui вернул неожиданный ответ.")
        return data

    def _post_json_with_scheme_fallback(
        self,
        url: str,
        api_token: str,
        payload: dict[str, Any],
        tls_verify: bool,
    ) -> dict[str, Any]:
        try:
            return self._post_json(url, api_token, payload, tls_verify)
        except XuiApiError as exc:
            if not _looks_like_https_to_http_error(str(exc)):
                raise

            retry_url = _replace_url_scheme(url, "http")
            if retry_url == url:
                raise

            try:
                return self._post_json(retry_url, api_token, payload, tls_verify)
            except XuiApiError as retry_exc:
                raise XuiApiError(
                    "3x-ui api не ответил ни по https, ни по http. "
                    f"https: {exc}; http: {retry_exc}"
                ) from retry_exc

    def _get_json_with_scheme_fallback(
        self,
        url: str,
        api_token: str,
        tls_verify: bool,
    ) -> dict[str, Any]:
        try:
            return self._get_json(url, api_token, tls_verify)
        except XuiApiError as exc:
            if not _looks_like_https_to_http_error(str(exc)):
                raise

            retry_url = _replace_url_scheme(url, "http")
            if retry_url == url:
                raise

            try:
                return self._get_json(retry_url, api_token, tls_verify)
            except XuiApiError as retry_exc:
                raise XuiApiError(
                    "3x-ui api не ответил ни по https, ни по http. "
                    f"https: {exc}; http: {retry_exc}"
                ) from retry_exc

    def _get_json(
        self,
        url: str,
        api_token: str,
        tls_verify: bool,
    ) -> dict[str, Any]:
        req = Request(
            url,
            headers={
                "Authorization": f"Bearer {api_token}",
                "Accept": "application/json",
            },
            method="GET",
        )
        return self._open_json(req, tls_verify)

    def _get_text(self, url: str, tls_verify: bool) -> str:
        req = Request(url, headers={"Accept": "text/plain, application/yaml, */*"})
        context = None if tls_verify else ssl._create_unverified_context()
        try:
            with urlopen(req, timeout=30, context=context) as resp:
                raw = resp.read()
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace").strip()
            raise XuiApiError(f"HTTP {exc.code}: {raw or exc.reason}") from exc
        except ssl.SSLError as exc:
            raise XuiApiError(str(exc)) from exc
        except URLError as exc:
            raise XuiApiError(str(exc.reason)) from exc
        except http.client.HTTPException as exc:
            raise XuiApiError(str(exc)) from exc
        except OSError as exc:
            raise XuiApiError(str(exc)) from exc
        return raw.decode("utf-8", errors="replace")

    def _resolve_panel_url(self, server_ref: str) -> str:
        parsed_url = urlparse(server_ref)
        if parsed_url.scheme:
            if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
                raise XuiApiError("panel_url должен быть полным url.")
            return server_ref.rstrip("/")

        server = self.server_repository.get(server_ref)
        if server is None:
            try:
                host = normalize_server_host(server_ref)
            except ValueError as exc:
                raise XuiApiError("сервер не найден в базе.") from exc
        else:
            host = server.host

        return _build_panel_url(
            scheme=self.settings.xui_panel_scheme,
            host=host,
            port=self.settings.xui_panel_port,
            base_path=self.settings.xui_panel_base_path,
        )

    def _resolve_server_record(self, server_ref: str) -> Server | None:
        parsed_url = urlparse(server_ref)
        if parsed_url.scheme:
            host = parsed_url.hostname
            if not host:
                return None
            return self.server_repository.get(host)
        return self.server_repository.get(server_ref)


def _parse_key_values(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if "=" not in line:
            raise ValueError("каждая строка должна быть в формате key=value.")
        key, value = line.split("=", 1)
        key = key.strip().upper()
        if key:
            values[key] = value.strip()
    return values


def _parse_inbound_ids(raw: str) -> tuple[int, ...]:
    ids: list[int] = []
    for item in raw.replace(";", ",").split(","):
        value = item.strip()
        if not value:
            continue
        ids.append(_parse_int(value, "INBOUND_IDS", minimum=1))
    if not ids:
        raise ValueError("inbound_ids должен содержать хотя бы один id.")
    return tuple(ids)


def _parse_int(raw: str, field: str, minimum: int) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{field} должен быть целым числом.") from exc
    if value < minimum:
        raise ValueError(f"{field} должен быть не меньше {minimum}.")
    return value


def _parse_decimal(raw: str, field: str) -> Decimal:
    try:
        value = Decimal(raw.replace(",", "."))
    except InvalidOperation as exc:
        raise ValueError(f"{field} должен быть числом.") from exc
    if value < 0:
        raise ValueError(f"{field} должен быть не меньше 0.")
    return value


def _parse_bool(raw: str) -> bool:
    return raw.strip().lower() not in {"0", "false", "no", "off", "нет"}


def _looks_like_existing_client(message: str) -> bool:
    normalized = message.lower()
    patterns = (
        "already",
        "duplicate",
        "same email",
        "email already",
        "client already",
    )
    return any(pattern in normalized for pattern in patterns)


def _empty_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _gb_to_bytes(value: Decimal) -> int:
    if value == 0:
        return 0
    return int(value * Decimal(1024**3))


def _expiry_time_ms(days: int) -> int:
    if days == 0:
        return 0
    return int((time.time() + days * 86400) * 1000)


def _api_url(panel_url: str, api_path: str) -> str:
    base = panel_url.rstrip("/") + "/"
    return urljoin(base, api_path.lstrip("/"))


def _looks_like_https_to_http_error(message: str) -> bool:
    normalized = message.lower()
    return (
        "unexpected_eof_while_reading" in normalized
        or "wrong version number" in normalized
        or "ssl" in normalized and "eof occurred" in normalized
    )


def _replace_url_scheme(url: str, scheme: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme:
        return url
    return urlunparse(
        ParseResult(
            scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )


def _build_panel_url(scheme: str, host: str, port: int, base_path: str) -> str:
    netloc_host = f"[{host}]" if ":" in host else host
    path = "/" + base_path.strip("/")
    return urlunparse(ParseResult(scheme, f"{netloc_host}:{port}", path, "", "", ""))


def _default_sub_base_url(panel_url: str, port: int) -> str:
    parsed = urlparse(panel_url)
    host = parsed.hostname or parsed.netloc
    if parsed.hostname and ":" in parsed.hostname:
        host = f"[{parsed.hostname}]"
    netloc = f"{host}:{port}"
    return urlunparse(ParseResult(parsed.scheme, netloc, "", "", "", ""))


def _subscription_url(base_url: str, path: str, sub_id: str) -> str:
    normalized_path = "/" + path.strip("/")
    return base_url.rstrip("/") + normalized_path + "/" + quote(sub_id.strip(), safe="")


def _validate_mihomo_subscription_text(text: str) -> list[str]:
    errors: list[str] = []
    normalized = text.lower()
    if "reality-opts" in normalized and "public-key:" not in normalized:
        errors.append("reality-нода без reality-opts.public-key")
    if "network: xhttp" in normalized and "xhttp-opts" not in normalized:
        errors.append("xhttp-нода без xhttp-opts")
    if "type: hysteria2" in normalized and "password:" not in normalized:
        errors.append("hysteria2-нода без password")
    if "proxies:" not in normalized and "- name:" not in normalized:
        errors.append("mihomo/clash yaml выглядит пустым")
    return errors
