from __future__ import annotations

import asyncio
import html
import logging
import sys
from pathlib import Path
from urllib.parse import urlparse

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import FSInputFile, Message

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from bot.config import load_settings
    from bot.config import Settings
    from bot.database import ServerRepository
    from bot.keyboards import (
        BACK_BUTTON,
        BACKUP_BUTTON,
        CHECK_SERVERS_BUTTON,
        CLIENTS_BUTTON,
        GET_SUBSCRIPTION_BUTTON,
        ROLLOUT_BUTTON,
        SERVERS_BUTTON,
        main_keyboard,
        rollout_keyboard,
        subscription_keyboard,
    )
    from bot.middlewares import OwnerOnlyMiddleware
    from bot.rollout import RolloutRunner, parse_rollout_message
    from bot.xui_client import XuiApiError, XuiClientService, parse_bulk_subscription_message
else:
    from .config import load_settings
    from .config import Settings
    from .database import ServerRepository
    from .keyboards import (
        BACK_BUTTON,
        BACKUP_BUTTON,
        CHECK_SERVERS_BUTTON,
        CLIENTS_BUTTON,
        GET_SUBSCRIPTION_BUTTON,
        ROLLOUT_BUTTON,
        SERVERS_BUTTON,
        main_keyboard,
        rollout_keyboard,
        subscription_keyboard,
    )
    from .middlewares import OwnerOnlyMiddleware
    from .rollout import RolloutRunner, parse_rollout_message
    from .xui_client import XuiApiError, XuiClientService, parse_bulk_subscription_message


router = Router()


class RolloutStates(StatesGroup):
    waiting_payload = State()


class SubscriptionStates(StatesGroup):
    waiting_payload = State()


@router.message(CommandStart())
async def start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "💅 глянцевый пульт готов. выбирай, что будем полировать.",
        reply_markup=main_keyboard(),
    )


@router.message(F.text.in_({ROLLOUT_BUTTON, "раскатать сервер"}))
async def rollout_button(
    message: Message,
    state: FSMContext,
    rollout_runner: RolloutRunner,
) -> None:
    runner = rollout_runner
    if runner.busy:
        await message.answer("💎 раскатка уже идет. дай ей чуть блеска и времени.")
        return

    await state.set_state(RolloutStates.waiting_payload)
    await message.answer(
        "💎 пришли ip и домен. если user/password не указаны, возьму admin_user "
        "и admin_user_password из .env:\n"
        "<code>ip=203.0.113.10\n"
        "domain=fr.example.com</code>\n\n"
        "или явно:\n"
        "<code>ip=203.0.113.10\n"
        "user=rey\n"
        "password=ssh-password\n"
        "domain=fr.example.com</code>",
        reply_markup=rollout_keyboard(),
    )


@router.message(F.text.in_({BACK_BUTTON, "назад"}))
async def back_to_home(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "↩️ вернулись в сияющее меню.",
        reply_markup=main_keyboard(),
    )


@router.message(F.text.in_({SERVERS_BUTTON, "серверы"}))
async def servers_button(
    message: Message,
    server_repository: ServerRepository,
) -> None:
    servers = server_repository.list()
    if not servers:
        await message.answer(
            "🫙 пока ни одного сервера в шкатулке.",
            reply_markup=main_keyboard(),
        )
        return

    lines = ["🖥 серверы в базе:"]
    for server in servers:
        token = "🔐 token есть" if server.xui_api_token else "🕳 token нет"
        lines.append(
            f"{server.id}. <b>{html.escape(server.host)}</b> · {token}"
        )
    await message.answer("\n".join(lines), reply_markup=main_keyboard())


@router.message(F.text.in_({CHECK_SERVERS_BUTTON, "проверить серверы"}))
async def check_servers_button(
    message: Message,
    xui_client_service: XuiClientService,
) -> None:
    status_message = await message.answer(
        "🩺 проверяю серверы. маленький техно-глянец в процессе.",
        reply_markup=main_keyboard(),
    )
    results = await xui_client_service.check_all_servers()
    if not results:
        await status_message.answer("🫙 серверов пока нет.")
        return

    blocks: list[str] = []
    for item in results:
        marker = "✅ ok" if item.ok else "🚨 alarm"
        details = "\n".join(f"· {html.escape(detail)}" for detail in item.details)
        blocks.append(
            f"<b>{html.escape(item.server.host)}</b> · {marker}\n{details}"
        )
    for text in _chunk_message_blocks("🩺 проверка серверов:", blocks):
        await status_message.answer(text, reply_markup=main_keyboard())


@router.message(F.text.in_({CLIENTS_BUTTON, "клиенты"}))
async def clients_button(
    message: Message,
    server_repository: ServerRepository,
) -> None:
    clients = server_repository.list_clients()
    if not clients:
        await message.answer(
            "👥 клиентов пока нет. витрина чистая.",
            reply_markup=main_keyboard(),
        )
        return

    blocks: list[str] = []
    for client in clients:
        blocks.append(
            f"<b>{html.escape(client.name)}</b>\n"
            f"🖥 сервер: <code>{html.escape(client.server_host)}</code>\n"
            f"🕒 обновлен: <code>{html.escape(client.updated_at or client.created_at)}</code>\n"
            f"🔗 sub: <code>{html.escape(client.subscription_url)}</code>\n"
            f"⚔️ clash: <code>{html.escape(client.clash_subscription_url)}</code>"
        )
    for text in _chunk_message_blocks("👥 клиенты в базе:", blocks):
        await message.answer(text, reply_markup=main_keyboard())


@router.message(F.text.in_({BACKUP_BUTTON, "бэкап"}))
async def backup_button(
    message: Message,
    settings: Settings,
) -> None:
    if not settings.database_path.exists():
        await message.answer("👜 sqlite-базы пока нет.", reply_markup=main_keyboard())
        return

    await message.answer_document(
        FSInputFile(settings.database_path, filename="bot.sqlite3"),
        caption="👜 бэкап базы. маленький сейф с блеском.",
        reply_markup=main_keyboard(),
    )


@router.message(F.text.in_({GET_SUBSCRIPTION_BUTTON, "добавить пользователя"}))
async def subscription_button(
    message: Message,
    state: FSMContext,
    server_repository: ServerRepository,
) -> None:
    await state.set_state(SubscriptionStates.waiting_payload)
    servers = server_repository.list()
    server_lines = "\n".join(
        f"{server.id}. {html.escape(server.host)}" for server in servers
    )
    servers_text = (
        f"\n\n🖥 серверы в базе:\n<code>{server_lines}</code>"
        if server_lines
        else "\n\n🫙 серверов в базе пока нет."
    )
    await message.answer(
        "✨ пришли имя клиента. создам его на всех серверах из базы:\n"
        "<code>client-name</code>\n\n"
        "или так, если нужны параметры:\n"
        "<code>client=client-name\n"
        "days=30\n"
        "gb=100</code>\n\n"
        "xui api token берется из базы каждого сервера после раскатки. "
        "если клиент уже есть, просто верну сабки."
        f"{servers_text}",
        reply_markup=subscription_keyboard(),
    )


@router.message(RolloutStates.waiting_payload)
async def rollout_payload(
    message: Message,
    state: FSMContext,
    rollout_runner: RolloutRunner,
    server_repository: ServerRepository,
    settings: Settings,
) -> None:
    runner = rollout_runner
    if message.text in {BACK_BUTTON, "назад"}:
        await back_to_home(message, state)
        return

    if runner.busy:
        await message.answer("💎 раскатка уже идет. дай ей чуть блеска и времени.")
        return

    try:
        request = parse_rollout_message(
            message.text or "",
            default_user=settings.admin_user,
            default_password=settings.admin_password,
        )
    except ValueError as exc:
        await message.answer(str(exc), reply_markup=rollout_keyboard())
        return

    try:
        await message.delete()
    except Exception:
        logging.info("Could not delete rollout payload message", exc_info=True)

    await state.clear()
    status_message = await message.answer(
        f"💎 начинаю раскатку <code>{html.escape(request.ip)}</code> "
        f"для <code>{html.escape(request.domain)}</code> "
        f"под <code>{html.escape(request.user)}</code>. "
        "отпишусь, когда ansible закончит.",
        reply_markup=main_keyboard(),
    )

    result = await runner.run(request)
    if result.ok:
        server, created = server_repository.add(request.domain)
        token_saved = False
        if result.xui_api_token:
            server = server_repository.save_xui_api_token(
                host=request.domain,
                token_name=result.xui_api_token_name,
                token=result.xui_api_token,
                auth_header=result.xui_api_auth_header,
            )
            token_saved = True
        server_status = "домен добавлен в базу." if created else "домен уже был в базе."
        token_status = (
            "xui api token сохранен в базе."
            if token_saved
            else "xui api token не нашелся в выводе ansible."
        )
        await status_message.answer(
            f"✅ готово: <code>{html.escape(request.domain)}</code> раскатан.\n"
            f"{server_status} id: <code>{server.id}</code>\n"
            f"{token_status}"
        )
        return

    details = result.stderr_tail or result.stdout_tail or "ansible не вернул вывод."
    details = html.escape(details)
    await status_message.answer(
        "🚨 раскатка упала.\n"
        f"код: <code>{result.returncode}</code>\n"
        f"<pre>{details}</pre>"
    )


@router.message(SubscriptionStates.waiting_payload)
async def subscription_payload(
    message: Message,
    state: FSMContext,
    xui_client_service: XuiClientService,
) -> None:
    if message.text in {BACK_BUTTON, "назад"}:
        await back_to_home(message, state)
        return

    try:
        request = parse_bulk_subscription_message(message.text or "")
    except ValueError as exc:
        await message.answer(str(exc), reply_markup=subscription_keyboard())
        return

    try:
        await message.delete()
    except Exception:
        logging.info("Could not delete subscription payload message", exc_info=True)

    status_message = await message.answer(
        f"✨ создаю <code>{html.escape(request.client_name)}</code> на всех серверах.",
        reply_markup=subscription_keyboard(),
    )

    try:
        results = await xui_client_service.ensure_client_subscription_on_all_servers(request)
    except XuiApiError as exc:
        await status_message.answer(
            "🚨 не смог создать клиента или получить сабку:\n"
            f"<pre>{html.escape(str(exc))}</pre>",
            reply_markup=subscription_keyboard(),
        )
        return

    await state.clear()
    for item in results:
        if item.result is None:
            continue
        server_repository.save_client(
            name=item.result.client_name,
            server_host=item.server.host,
            subscription_url=item.result.subscription_url,
            clash_subscription_url=item.result.clash_subscription_url,
        )
    for index, text in enumerate(
        _format_bulk_subscription_messages(request.client_name, results),
        start=1,
    ):
        await status_message.answer(
            text,
            reply_markup=main_keyboard() if index == 1 else None,
        )


@router.message()
async def fallback(message: Message) -> None:
    await message.answer(
        "✨ выбери действие в меню. блеск сам себя не наведет.",
        reply_markup=main_keyboard(),
    )


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = load_settings()

    bot = Bot(
        settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    access = OwnerOnlyMiddleware(settings.admin_ids)
    router.message.middleware(access)
    router.callback_query.middleware(access)

    server_repository = ServerRepository(settings.database_path)
    server_repository.init_db()

    dp = Dispatcher(
        settings=settings,
        rollout_runner=RolloutRunner(settings),
        xui_client_service=XuiClientService(settings, server_repository),
        server_repository=server_repository,
    )
    dp.include_router(router)

    await dp.start_polling(bot)


def _format_bulk_subscription_messages(client_name: str, results: list) -> list[str]:
    blocks: list[str] = []
    for item in results:
        if item.result is None:
            host = html.escape(item.server.host)
            blocks.append(
                f"<b>{host}</b>\n"
                "🚨 ошибка:\n"
                f"<pre>{html.escape(_short_error(item.error))}</pre>"
            )
            continue

        host = html.escape(_subscription_host(item.result.subscription_url, item.server.host))
        status = "создан" if item.result.created else "уже был"
        validation_text = (
            "\nпроверка: " + "; ".join(html.escape(value) for value in item.validation_errors)
            if item.validation_errors
            else "\nпроверка: mihomo выглядит ок"
        )
        inbound_text = (
            "\n"
            f"inbounds: <code>{html.escape(','.join(str(value) for value in item.result.inbound_ids))}</code>"
            if item.result.inbound_ids
            else ""
        )
        blocks.append(
            f"<b>{host}</b>\n"
            f"👤 клиент: <code>{html.escape(item.result.client_name)}</code> ({status})"
            f"{inbound_text}"
            f"{validation_text}\n\n"
            "🔗 обычная сабка:\n"
            f"<code>{html.escape(item.result.subscription_url)}</code>\n\n"
            "⚔️ clash:\n"
            f"<code>{html.escape(item.result.clash_subscription_url)}</code>"
        )

    header_name = html.escape(client_name)
    header = f"✅ готово для <code>{header_name}</code>. блеск нанесен тонким слоем."
    return _chunk_message_blocks(header, blocks)


def _chunk_message_blocks(header: str, blocks: list[str], limit: int = 3600) -> list[str]:
    messages: list[str] = []
    current = header
    for block in blocks:
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            messages.append(current)
        current = block
    if current:
        messages.append(current)
    return messages or [header]


def _subscription_host(subscription_url: str, fallback: str) -> str:
    parsed = urlparse(subscription_url)
    return parsed.hostname or fallback


def _short_error(error: str | None, limit: int = 1200) -> str:
    text = error or "неизвестная ошибка"
    if len(text) <= limit:
        return text
    return text[-limit:]


if __name__ == "__main__":
    asyncio.run(main())
