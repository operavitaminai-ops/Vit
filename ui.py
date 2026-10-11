# -*- coding: utf-8 -*-
"""
Вывод «экранов». Бот держит в чате одно главное сообщение и редактирует его
по ходу диалога, поэтому переписка выглядит как мини-приложение.
"""
from __future__ import annotations

import logging
from contextlib import suppress
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import (
    FSInputFile,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Message,
    ReplyKeyboardRemove,
)

log = logging.getLogger(__name__)

# chat_id → id главного сообщения («экрана») в этом чате
SCREENS: dict[int, int] = {}
# путь к картинке → file_id в Telegram (чтобы не загружать файл каждый раз)
_FILE_IDS: dict[str, str] = {}


def _media(photo: Path | None):
    if photo is None or not photo.exists():
        return None
    return _FILE_IDS.get(str(photo)) or FSInputFile(photo)


def _remember(photo: Path | None, sent) -> None:
    if photo is not None and isinstance(sent, Message) and sent.photo:
        _FILE_IDS[str(photo)] = sent.photo[-1].file_id


async def show(
    bot: Bot,
    chat_id: int,
    text: str,
    kb: InlineKeyboardMarkup | None = None,
    photo: Path | None = None,
    message_id: int | None = None,
) -> int:
    """
    Показывает экран: редактирует текущее сообщение, а если тип сообщения
    не позволяет (текст ↔ фото) — отправляет новое и удаляет старое.
    Возвращает id сообщения с экраном.
    """
    mid = message_id or SCREENS.get(chat_id)
    media = _media(photo)

    if mid:
        try:
            if media:
                sent = await bot.edit_message_media(
                    media=InputMediaPhoto(media=media, caption=text, parse_mode="HTML"),
                    chat_id=chat_id,
                    message_id=mid,
                    reply_markup=kb,
                )
                _remember(photo, sent)
            else:
                await bot.edit_message_text(
                    text, chat_id=chat_id, message_id=mid, reply_markup=kb
                )
            SCREENS[chat_id] = mid
            return mid
        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                SCREENS[chat_id] = mid
                return mid
            log.debug("Не удалось отредактировать экран (%s), отправляю новый", e)

    if media:
        sent = await bot.send_photo(chat_id, media, caption=text, reply_markup=kb)
        _remember(photo, sent)
    else:
        sent = await bot.send_message(chat_id, text, reply_markup=kb)
    if mid:
        with suppress(TelegramAPIError):
            await bot.delete_message(chat_id, mid)
    SCREENS[chat_id] = sent.message_id
    return sent.message_id


async def drop_screen(bot: Bot, chat_id: int) -> None:
    """Удаляет текущий экран (например, при повторном /start)."""
    mid = SCREENS.pop(chat_id, None)
    if mid:
        with suppress(TelegramAPIError):
            await bot.delete_message(chat_id, mid)


async def quiet_delete(msg: Message) -> None:
    """Удаляет сообщение пользователя, чтобы чат оставался чистым."""
    with suppress(TelegramAPIError):
        await msg.delete()


async def delete_by_id(bot: Bot, chat_id: int, message_id: int | None) -> None:
    if message_id:
        with suppress(TelegramAPIError):
            await bot.delete_message(chat_id, message_id)


async def clear_reply_keyboard(bot: Bot, chat_id: int) -> None:
    """Убирает обычную клавиатуру (кнопку «Поделиться номером») из чата."""
    with suppress(TelegramAPIError):
        tmp = await bot.send_message(chat_id, "·", reply_markup=ReplyKeyboardRemove())
        await bot.delete_message(chat_id, tmp.message_id)
