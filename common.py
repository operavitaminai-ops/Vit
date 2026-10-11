# -*- coding: utf-8 -*-
"""Общие помощники для обработчиков."""
from __future__ import annotations

from contextlib import suppress

from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery

import ui


async def ack(call: CallbackQuery, text: str | None = None, alert: bool = False) -> None:
    """Отвечает на нажатие кнопки (убирает «часики»). Ошибки устаревших нажатий игнорируются."""
    with suppress(TelegramAPIError):
        await call.answer(text, show_alert=alert)


def mid_of(call: CallbackQuery) -> int:
    """Какое сообщение редактировать: текущий экран чата или то, где нажата кнопка."""
    return ui.SCREENS.get(call.message.chat.id) or call.message.message_id
