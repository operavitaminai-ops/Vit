# -*- coding: utf-8 -*-
"""Построение инлайн-клавиатур."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

Row = list[tuple[str, str]]


def kb(*rows: Row) -> InlineKeyboardMarkup:
    """kb([("Текст", "data"), ...], [...]) — по одному списку на строку кнопок."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=text, callback_data=data) for text, data in row]
            for row in rows
        ]
    )


def grid(items: Row, per_row: int) -> list[Row]:
    """Раскладывает кнопки по per_row штук в строке."""
    return [items[i:i + per_row] for i in range(0, len(items), per_row)]
