# -*- coding: utf-8 -*-
"""Панель мастера: записи, подтверждение, закрытие времени."""
from __future__ import annotations

import logging
from contextlib import suppress
from datetime import date, timedelta

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import config
import db
import notify
import ui
from cards import admin_card, pet_short, service_title
from content import HORIZON_DAYS, SLOT_STEP
from fmt import d_btn, d_date, d_long, d_short, esc, plural
from handlers.common import ack, mid_of
from keyboards import grid, kb
from slots import day_hours, to_hhmm, to_min

log = logging.getLogger(__name__)

router = Router()
# Все обработчики этого роутера доступны только мастеру.
router.message.filter(F.chat.type == "private", F.from_user.id.in_(config.ADMIN_IDS))
router.callback_query.filter(F.from_user.id.in_(config.ADMIN_IDS))

PANEL = [("← Панель", "adm")]


async def respond(call: CallbackQuery, bot: Bot, text: str, markup) -> None:
    """
    Обновляет сообщение, на котором нажата кнопка. Если это главный экран чата —
    через общий механизм экранов, если это уведомление — редактируем его напрямую.
    """
    chat_id, mid = call.message.chat.id, call.message.message_id
    if ui.SCREENS.get(chat_id) == mid:
        await ui.show(bot, chat_id, text, markup, message_id=mid)
        return
    with suppress(TelegramAPIError):
        await bot.edit_message_text(text, chat_id=chat_id, message_id=mid, reply_markup=markup)


def booking_id(call: CallbackQuery, prefix: str) -> int | None:
    arg = call.data[len(prefix):]
    return int(arg) if arg.isdigit() else None


# ── Панель ───────────────────────────────────────────────────────────────────

async def s_panel(bot: Bot, chat_id: int, mid: int | None = None) -> None:
    now = config.now_local()
    today = now.date()
    n_today = len(db.day_bookings(today.isoformat()))
    n_tomorrow = len(db.day_bookings((today + timedelta(days=1)).isoformat()))
    pending = db.pending_count(now)
    text = (
        "<b>Панель мастера</b>\n\n"
        f"Сегодня: {plural(n_today, 'запись', 'записи', 'записей')}\n"
        f"Завтра: {plural(n_tomorrow, 'запись', 'записи', 'записей')}\n"
        f"Ждут подтверждения: {pending}"
    )
    rows = [
        [("Сегодня", "adm_list:today"), ("Завтра", "adm_list:tomorrow")],
        [("Ближайшие записи", "adm_list:next")],
        [("Закрыть время", "adm_close"), ("Снять закрытие", "adm_blocks")],
        [("← В меню", "menu")],
    ]
    await ui.show(bot, chat_id, text, kb(*rows), message_id=mid)


@router.message(Command("admin"))
async def cmd_admin(msg: Message, state: FSMContext, bot: Bot) -> None:
    await ui.quiet_delete(msg)
    await state.clear()
    await s_panel(bot, msg.chat.id)


@router.callback_query(F.data == "adm")
async def cb_panel(call: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await ack(call)
    await state.clear()
    await s_panel(bot, call.message.chat.id, mid_of(call))


# ── Списки записей ───────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("adm_list:"))
async def cb_list(call: CallbackQuery, bot: Bot) -> None:
    await ack(call)
    which = call.data[9:]
    now = config.now_local()
    today = now.date()
    if which == "today":
        rows_db, title, show_date = db.day_bookings(today.isoformat()), f"Сегодня, {d_short(today)}", False
    elif which == "tomorrow":
        tomorrow = today + timedelta(days=1)
        rows_db, title, show_date = db.day_bookings(tomorrow.isoformat()), f"Завтра, {d_short(tomorrow)}", False
    else:
        rows_db, title, show_date = db.upcoming_all(now, 12), "Ближайшие записи", True

    lines = [f"<b>{title}</b>"]
    buttons = []
    if not rows_db:
        lines.append("\nЗаписей нет.")
    for b in rows_db:
        d = date.fromisoformat(b["day"])
        when = f"{d_short(d)}, {b['start']}" if show_date else f"{b['start']}–{b['finish']}"
        mark = "" if b["status"] == "confirmed" else " · ждёт подтверждения"
        lines.append(
            f"\n<b>{when}</b> · {esc(b['pet'])}\n{esc(service_title(b))}{mark}"
        )
        label = f"{d_short(d)} {b['start']}" if show_date else b["start"]
        buttons.append([(f"{label} · {pet_short(b)}", f"adm_b:{b['id']}")])
    await ui.show(
        bot, call.message.chat.id, "\n".join(lines), kb(*buttons, PANEL), message_id=mid_of(call)
    )


def card_markup(b):
    rows = []
    if b["status"] == "pending":
        rows.append([("Принять", f"adm_acc:{b['id']}"), ("Отклонить", f"adm_dec:{b['id']}")])
    if b["status"] in ("pending", "confirmed"):
        rows.append([("Отменить запись", f"adm_cx:{b['id']}")])
    rows.append(PANEL)
    return kb(*rows)


@router.callback_query(F.data.startswith("adm_b:"))
async def cb_booking(call: CallbackQuery, bot: Bot) -> None:
    await ack(call)
    bid = booking_id(call, "adm_b:")
    b = db.get_booking(bid) if bid else None
    if b is None:
        await respond(call, bot, "Запись не найдена.", kb(PANEL))
        return
    await respond(call, bot, admin_card(b, "Запись"), card_markup(b))


# ── Решения по записи ────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("adm_acc:"))
async def cb_accept(call: CallbackQuery, bot: Bot) -> None:
    bid = booking_id(call, "adm_acc:")
    b = db.get_booking(bid) if bid else None
    if b is None:
        await ack(call, "Запись не найдена", alert=True)
        return
    if b["status"] != "pending":
        await ack(call, "Эта запись уже обработана", alert=True)
        await respond(call, bot, admin_card(b, "Запись"), card_markup(b))
        return
    db.set_status(b["id"], "confirmed")
    b = db.get_booking(b["id"])
    await ack(call, "Запись подтверждена")
    await respond(call, bot, admin_card(b, "Запись"), card_markup(b))
    await notify.client_confirmed(bot, b)


@router.callback_query(F.data.startswith("adm_dec:"))
async def cb_decline(call: CallbackQuery, bot: Bot) -> None:
    bid = booking_id(call, "adm_dec:")
    b = db.get_booking(bid) if bid else None
    if b is None:
        await ack(call, "Запись не найдена", alert=True)
        return
    if b["status"] != "pending":
        await ack(call, "Эта запись уже обработана", alert=True)
        await respond(call, bot, admin_card(b, "Запись"), card_markup(b))
        return
    db.set_status(b["id"], "declined")
    b = db.get_booking(b["id"])
    await ack(call, "Запись отклонена")
    await respond(call, bot, admin_card(b, "Запись"), card_markup(b))
    await notify.client_declined(bot, b)


@router.callback_query(F.data.startswith("adm_cx:"))
async def cb_cancel_ask(call: CallbackQuery, bot: Bot) -> None:
    await ack(call)
    bid = booking_id(call, "adm_cx:")
    b = db.get_booking(bid) if bid else None
    if b is None or b["status"] not in ("pending", "confirmed"):
        await respond(call, bot, "Запись уже неактивна.", kb(PANEL))
        return
    text = f"<b>Отменить запись?</b>\nКлиент получит уведомление.\n\n{admin_card(b, 'Запись')}"
    await respond(
        call, bot, text,
        kb([("Да, отменить", f"adm_cxy:{b['id']}")], [("Нет", f"adm_b:{b['id']}")]),
    )


@router.callback_query(F.data.startswith("adm_cxy:"))
async def cb_cancel_do(call: CallbackQuery, bot: Bot) -> None:
    bid = booking_id(call, "adm_cxy:")
    b = db.get_booking(bid) if bid else None
    if b is None or b["status"] not in ("pending", "confirmed"):
        await ack(call, "Запись уже неактивна", alert=True)
        return
    db.set_status(b["id"], "cancelled")
    b = db.get_booking(b["id"])
    await ack(call, "Запись отменена")
    await respond(call, bot, admin_card(b, "Запись"), card_markup(b))
    await notify.client_cancelled(bot, b)


# ── Закрытие времени ─────────────────────────────────────────────────────────

def working_dates(today: date) -> list[date]:
    return [
        d for d in (today + timedelta(days=i) for i in range(HORIZON_DAYS)) if day_hours(d)
    ]


@router.callback_query(F.data == "adm_close")
async def cb_close(call: CallbackQuery, bot: Bot) -> None:
    await ack(call)
    today = config.now_local().date()
    buttons = []
    for d in working_dates(today):
        delta = (d - today).days
        label = "Сегодня" if delta == 0 else "Завтра" if delta == 1 else d_btn(d)
        buttons.append((label, f"adm_cd:{d.isoformat()}"))
    await ui.show(
        bot, call.message.chat.id,
        "<b>Закрыть время</b>\n\nВыберите день. Закрытое время клиентам не показывается.",
        kb(*grid(buttons, 3), PANEL), message_id=mid_of(call),
    )


def parse_day(raw: str) -> date | None:
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


@router.callback_query(F.data.startswith("adm_cd:"))
async def cb_close_day(call: CallbackQuery, bot: Bot) -> None:
    await ack(call)
    d = parse_day(call.data[7:])
    if d is None or not day_hours(d):
        return
    iso = d.isoformat()
    await ui.show(
        bot, call.message.chat.id, f"<b>{d_long(d)}</b>\n\nЧто закрыть?",
        kb([("Весь день", f"adm_cday:{iso}")], [("Часть дня", f"adm_cpart:{iso}")],
           [("← Назад", "adm_close")]),
        message_id=mid_of(call),
    )


@router.callback_query(F.data.startswith("adm_cday:"))
async def cb_close_whole(call: CallbackQuery, bot: Bot) -> None:
    await ack(call)
    d = parse_day(call.data[9:])
    if d is None:
        return
    db.add_block(d.isoformat())
    existing = len(db.day_bookings(d.isoformat()))
    text = f"<b>День закрыт</b>\n\n{d_long(d)} больше не доступен для записи."
    if existing:
        text += (
            f"\n\nНа этот день уже {plural(existing, 'запись', 'записи', 'записей')}. "
            "Они сохранены: при необходимости отмените их в списке."
        )
    await ui.show(bot, call.message.chat.id, text, kb(PANEL), message_id=mid_of(call))


@router.callback_query(F.data.startswith("adm_cpart:"))
async def cb_close_part(call: CallbackQuery, bot: Bot) -> None:
    await ack(call)
    d = parse_day(call.data[10:])
    hours = day_hours(d) if d else None
    if d is None or hours is None:
        return
    iso = d.isoformat()
    times = [to_hhmm(t) for t in range(hours[0], hours[1], SLOT_STEP)]
    buttons = [(t, f"adm_cs:{iso}|{t}") for t in times]
    await ui.show(
        bot, call.message.chat.id,
        f"<b>{d_long(d)}</b>\n\nС какого времени закрыть?",
        kb(*grid(buttons, 4), [("← Назад", f"adm_cd:{iso}")]),
        message_id=mid_of(call),
    )


@router.callback_query(F.data.startswith("adm_cs:"))
async def cb_close_start(call: CallbackQuery, bot: Bot) -> None:
    await ack(call)
    parts = call.data[7:].split("|")
    d = parse_day(parts[0]) if len(parts) == 2 else None
    if d is None:
        return
    iso, t = parts
    rows = [
        [("1 час", f"adm_cl:{iso}|{t}|60"), ("2 часа", f"adm_cl:{iso}|{t}|120")],
        [("3 часа", f"adm_cl:{iso}|{t}|180"), ("До конца дня", f"adm_cl:{iso}|{t}|0")],
        [("← Назад", f"adm_cpart:{iso}")],
    ]
    await ui.show(
        bot, call.message.chat.id,
        f"<b>{d_long(d)}</b>\nС {t}\n\nНа сколько закрыть?",
        kb(*rows), message_id=mid_of(call),
    )


@router.callback_query(F.data.startswith("adm_cl:"))
async def cb_close_done(call: CallbackQuery, bot: Bot) -> None:
    await ack(call)
    parts = call.data[7:].split("|")
    d = parse_day(parts[0]) if len(parts) == 3 else None
    hours = day_hours(d) if d else None
    if d is None or hours is None or not parts[2].isdigit():
        return
    iso, t, mins = parts[0], parts[1], int(parts[2])
    end = hours[1] if mins == 0 else min(to_min(t) + mins, hours[1])
    db.add_block(iso, t, to_hhmm(end))
    await ui.show(
        bot, call.message.chat.id,
        f"<b>Время закрыто</b>\n\n{d_long(d)}, {t}–{to_hhmm(end)}.",
        kb(PANEL), message_id=mid_of(call),
    )


async def s_blocks(bot: Bot, chat_id: int, mid: int | None) -> None:
    blocks = db.list_blocks(config.now_local().date().isoformat())
    if not blocks:
        text, rows = "<b>Закрытое время</b>\n\nСейчас ничего не закрыто.", [PANEL]
    else:
        text = "<b>Закрытое время</b>\n\nНажмите, чтобы снова открыть."
        rows = []
        for blk in blocks:
            when = "весь день" if blk["start"] is None else f"{blk['start']}–{blk['finish']}"
            d = date.fromisoformat(blk["day"])
            rows.append([(f"{d_date(d)} · {when}  ✕", f"adm_ub:{blk['id']}")])
        rows.append(PANEL)
    await ui.show(bot, chat_id, text, kb(*rows), message_id=mid)


@router.callback_query(F.data == "adm_blocks")
async def cb_blocks(call: CallbackQuery, bot: Bot) -> None:
    await ack(call)
    await s_blocks(bot, call.message.chat.id, mid_of(call))


@router.callback_query(F.data.startswith("adm_ub:"))
async def cb_unblock(call: CallbackQuery, bot: Bot) -> None:
    await ack(call)
    arg = call.data[7:]
    if arg.isdigit():
        db.remove_block(int(arg))
    await s_blocks(bot, call.message.chat.id, mid_of(call))
