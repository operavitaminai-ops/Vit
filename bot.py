# -*- coding: utf-8 -*-
"""Точка входа. Запуск: python bot.py"""
from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import suppress

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeChat

import config
import db
import reminders
from content import SALON
from handlers import admin, client

log = logging.getLogger("bot")


async def setup_profile(bot: Bot) -> None:
    """Команды и тексты, которые Telegram показывает в профиле бота."""
    name = SALON["name"]
    with suppress(TelegramAPIError):
        await bot.set_my_commands([BotCommand(command="start", description="Главное меню")])
    for admin_id in config.ADMIN_IDS:
        with suppress(TelegramAPIError):
            await bot.set_my_commands(
                [
                    BotCommand(command="start", description="Главное меню"),
                    BotCommand(command="admin", description="Панель мастера"),
                ],
                scope=BotCommandScopeChat(chat_id=admin_id),
            )
    with suppress(TelegramAPIError):
        await bot.set_my_short_description(f"Онлайн-запись в груминг-студию «{name}»")
        await bot.set_my_description(
            f"Запись в груминг-студию «{name}»: выберите услугу, день и время за минуту. "
            "Напоминания о визите, перенос и отмена записи — прямо в чате."
        )


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    if not config.BOT_TOKEN:
        sys.exit(
            "Не задан BOT_TOKEN. Скопируйте .env.example в .env и вставьте токен от @BotFather."
        )
    if not config.ADMIN_IDS:
        log.warning(
            "ADMIN_IDS пуст: уведомления мастеру не отправляются, записи подтверждаются "
            "автоматически. Укажите свой Telegram ID в .env."
        )

    db.init()
    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(admin.router)   # сначала мастер: его команды не должны попасть в клиентский fallback
    dp.include_router(client.router)

    await setup_profile(bot)
    reminder_task = asyncio.create_task(reminders.loop(bot))
    try:
        await bot.delete_webhook(drop_pending_updates=False)
        me = await bot.get_me()
        log.info("Бот запущен: @%s", me.username)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        reminder_task.cancel()
        with suppress(asyncio.CancelledError):
            await reminder_task
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
