# -*- coding: utf-8 -*-
"""Тексты карточек записи для клиента и мастера."""
from __future__ import annotations

from datetime import date

from content import SALON, SERVICES, SIZES
from fmt import d_long, duration, esc, money

STATUS = {
    "pending": "ожидает подтверждения",
    "confirmed": "подтверждена",
    "declined": "отклонена",
    "cancelled": "отменена",
}


def service_title(b) -> str:
    return SERVICES.get(b["service"], {}).get("title", b["service"])


def size_title(b) -> str:
    return SIZES.get(b["size"], {}).get("title", "")


def pet_short(b) -> str:
    """Кличка без породы: «Бонни, той-терьер» → «Бонни»."""
    return (b["pet"] or "").split(",")[0].strip() or "питомец"


def client_card(b, with_status: bool = True) -> str:
    d = date.fromisoformat(b["day"])
    body = (
        f"<b>{esc(service_title(b))}</b>\n"
        f"{size_title(b)} собака · около {duration(b['duration'])}\n"
        f"{esc(b['pet'])}\n\n"
        f"{d_long(d)}\n"
        f"{b['start']} – {b['finish']}\n"
        f"Стоимость: {money(b['price'])}"
    )
    if b["note"]:
        body += f"\nОсобенности: {esc(b['note'])}"
    text = f"<blockquote>{body}</blockquote>"
    if with_status:
        text += f"\nСтатус: {STATUS.get(b['status'], b['status'])}"
    return text


def client_link(b) -> str:
    name = esc(b["first_name"] or "Клиент")
    link = f'<a href="tg://user?id={b["user_id"]}">{name}</a>'
    if b["username"]:
        link += f" (@{esc(b['username'])})"
    return link


def admin_card(b, title: str, with_status: bool = True) -> str:
    phone = esc(b["phone"]) if b["phone"] else "не указан"
    text = (
        f"<b>{esc(title)} № {b['id']}</b>\n"
        f"{client_card(b, with_status=False)}\n"
        f"Клиент: {client_link(b)}\n"
        f"Телефон: {phone}"
    )
    if with_status:
        text += f"\nСтатус: {STATUS.get(b['status'], b['status'])}"
    return text


def address_block() -> str:
    return f"{esc(SALON['address'])}\n{esc(SALON['phone'])}"
