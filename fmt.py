# -*- coding: utf-8 -*-
"""Форматирование дат, денег и текста для сообщений."""
from __future__ import annotations

import html
import re
from datetime import date

WD_SHORT = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
WD_FULL = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
MONTH_GEN = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]
MONTH_SHORT = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]

NBSP = " "


def esc(value) -> str:
    """Экранирование пользовательского текста для HTML-разметки Telegram."""
    return html.escape("" if value is None else str(value), quote=False)


def cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def money(value: int) -> str:
    return f"{value:,}".replace(",", NBSP) + NBSP + "₽"


def d_long(d: date) -> str:
    """Пятница, 9 октября"""
    return cap(f"{WD_FULL[d.weekday()]}, {d.day} {MONTH_GEN[d.month - 1]}")


def d_date(d: date) -> str:
    """9 октября"""
    return f"{d.day} {MONTH_GEN[d.month - 1]}"


def d_short(d: date) -> str:
    """9 окт"""
    return f"{d.day} {MONTH_SHORT[d.month - 1]}"


def d_btn(d: date) -> str:
    """пт 9 окт"""
    return f"{WD_SHORT[d.weekday()]} {d.day} {MONTH_SHORT[d.month - 1]}"


def duration(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} мин"
    h, m = divmod(minutes, 60)
    if m == 0:
        return f"{h} ч"
    if m == 30:
        return f"{h},5 ч"
    return f"{h} ч {m} мин"


def plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(n)
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} {one}"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} {few}"
    return f"{n} {many}"


def schedule_text(schedule: dict) -> str:
    """Собирает строки вида «Пн–Пт: 10:00–19:00» из расписания."""
    groups: list[list] = []
    for i in range(7):
        hours = schedule.get(i)
        if groups and groups[-1][1] == i - 1 and groups[-1][2] == hours:
            groups[-1][1] = i
        else:
            groups.append([i, i, hours])
    lines = []
    for a, b, hours in groups:
        days = cap(WD_SHORT[a]) if a == b else f"{cap(WD_SHORT[a])}–{cap(WD_SHORT[b])}"
        lines.append(f"{days}: {hours[0]}–{hours[1]}" if hours else f"{days}: выходной")
    return "\n".join(lines)


def normalize_phone(raw: str) -> str | None:
    """Приводит номер к виду +7 (900) 123-45-67 или +<цифры>. Если не номер — None."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 10:
        digits = "7" + digits
    if len(digits) == 11 and digits[0] in "78":
        digits = "7" + digits[1:]
        return f"+7 ({digits[1:4]}) {digits[4:7]}-{digits[7:9]}-{digits[9:11]}"
    if 11 <= len(digits) <= 15:
        return "+" + digits
    return None
