# -*- coding: utf-8 -*-
"""Клиентская часть бота: меню, информация, запись, «Мои записи»."""
from __future__ import annotations

import logging
from datetime import date

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, KeyboardButton, Message, ReplyKeyboardMarkup

import config
import db
import notify
import ui
from cards import address_block, client_card, pet_short, service_title
from content import (
    MASTER, MAX_ACTIVE_BOOKINGS, NOTE_OPTIONS, SALON, SCHEDULE, SERVICES, SIZES,
)
from fmt import (
    d_btn, d_date, d_long, duration, esc, money, normalize_phone, schedule_text,
)
from handlers.common import ack, mid_of
from keyboards import grid, kb
from slots import to_hhmm, to_min

log = logging.getLogger(__name__)

router = Router()
router.message.filter(F.chat.type == "private")

TOTAL_STEPS = 6


class Book(StatesGroup):
    pet = State()      # ждём кличку и породу
    note = State()     # ждём свою заметку
    phone = State()    # ждём номер телефона


# ── Вспомогательное ──────────────────────────────────────────────────────────

def head(step: int | None, title: str) -> str:
    text = f"<b>{title}</b>"
    if step:
        text += f"\n<i>Шаг {step} из {TOTAL_STEPS}</i>"
    return text + "\n\n"


def is_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


def need(data: dict, *keys: str) -> bool:
    return all(data.get(k) is not None for k in keys)


def compose_note(data: dict) -> str:
    parts = [NOTE_OPTIONS[i] for i in (data.get("notes") or []) if 0 <= i < len(NOTE_OPTIONS)]
    if data.get("note_text"):
        parts.append(data["note_text"])
    return "; ".join(parts)


async def reset_kb(bot: Bot, state: FSMContext, chat_id: int) -> None:
    """Убирает кнопку «Поделиться номером», если она была показана."""
    data = await state.get_data()
    kid = data.get("reply_kb")
    if kid:
        await state.update_data(reply_kb=None)
        await ui.clear_reply_keyboard(bot, chat_id)
        await ui.delete_by_id(bot, chat_id, kid)


async def expired(call: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    """Данные записи потерялись (например, бот перезапускали): начинаем сначала."""
    await state.clear()
    await ack(call, "Сессия устарела, начнём заново")
    await s_menu(bot, call.message.chat.id, call.from_user, mid_of(call))


# ── Главное меню ─────────────────────────────────────────────────────────────

def menu_text(name: str) -> str:
    return (
        f"<b>{esc(SALON['name'])}</b>\n"
        f"{esc(SALON['tagline'])} · {esc(SALON['city'])}\n\n"
        f"{esc(name)}, добро пожаловать.\n"
        "Бережно ухаживаем за собаками любых размеров и пород: без спешки и лишнего стресса. "
        "Запись занимает около минуты.\n\n"
        f"Ваш мастер — {esc(MASTER['short'])}."
    )


def menu_kb(user_id: int):
    rows = [
        [("Записаться", "book")],
        [("Услуги и цены", "services"), ("О специалисте", "master")],
        [("Мои записи", "my"), ("Контакты", "contacts")],
    ]
    if is_admin(user_id):
        rows.append([("Панель мастера", "adm")])
    return kb(*rows)


async def s_menu(bot: Bot, chat_id: int, user, mid: int | None = None) -> None:
    await ui.show(
        bot, chat_id, menu_text(user.first_name or "Здравствуйте"), menu_kb(user.id),
        photo=config.WELCOME_PHOTO, message_id=mid,
    )


@router.message(Command("start", "menu"))
async def cmd_start(msg: Message, state: FSMContext, bot: Bot) -> None:
    await reset_kb(bot, state, msg.chat.id)
    await state.clear()
    db.upsert_user(msg.from_user)
    await ui.quiet_delete(msg)
    await ui.drop_screen(bot, msg.chat.id)
    await s_menu(bot, msg.chat.id, msg.from_user)


@router.callback_query(F.data == "menu")
async def cb_menu(call: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await ack(call)
    await reset_kb(bot, state, call.message.chat.id)
    await state.clear()
    await s_menu(bot, call.message.chat.id, call.from_user, mid_of(call))


# ── Информационные экраны ────────────────────────────────────────────────────

@router.callback_query(F.data == "services")
async def cb_services_info(call: CallbackQuery, bot: Bot) -> None:
    await ack(call)
    parts = ["<b>Услуги и цены</b>"]
    for s in SERVICES.values():
        prices = " · ".join(f"{SIZES[k]['title']} {money(v)}" for k, v in s["price"].items())
        parts.append(f"<b>{esc(s['title'])}</b>\n{esc(s['desc'])}\n{prices}")
    sizes = ", ".join(f"{z['title'].lower()} — {z['hint']}" for z in SIZES.values())
    parts.append(
        f"<i>Размер: {sizes}. Если шерсть сильно запутана, мастер уточнит стоимость на месте.</i>"
    )
    await ui.show(
        bot, call.message.chat.id, "\n\n".join(parts),
        kb([("Записаться", "book")], [("← Назад", "menu")]),
        message_id=mid_of(call),
    )


@router.callback_query(F.data == "master")
async def cb_master(call: CallbackQuery, bot: Bot) -> None:
    await ack(call)
    text = (
        f"<b>{esc(MASTER['name'])}</b>\n{esc(MASTER['title'])}\n\n"
        f"{esc(MASTER['facts'])}\n\n"
        f"{esc(MASTER['bio'])}\n\n"
        f"<b>Подход к работе</b>\n{esc(MASTER['approach'])}"
    )
    await ui.show(
        bot, call.message.chat.id, text,
        kb([("Записаться", "book")], [("← Назад", "menu")]),
        photo=config.MASTER_PHOTO, message_id=mid_of(call),
    )


@router.callback_query(F.data == "contacts")
async def cb_contacts(call: CallbackQuery, bot: Bot) -> None:
    await ack(call)
    text = (
        "<b>Контакты</b>\n\n"
        f"{esc(SALON['name'])}\n{esc(SALON['address'])}\n{esc(SALON['how_to_get'])}\n\n"
        f"<b>Часы работы</b>\n{schedule_text(SCHEDULE)}\n\n"
        f"<b>Телефон</b>\n{esc(SALON['phone'])}\n\n"
        "<i>Запись через бота доступна круглосуточно.</i>"
    )
    await ui.show(
        bot, call.message.chat.id, text,
        kb([("Записаться", "book")], [("← Назад", "menu")]),
        message_id=mid_of(call),
    )


# ── Запись, шаг 1: услуга ────────────────────────────────────────────────────

async def s_services(bot: Bot, chat_id: int, mid: int | None) -> None:
    parts = [head(1, "Выберите услугу")]
    for s in SERVICES.values():
        parts.append(f"<b>{esc(s['title'])}</b>\n{esc(s['desc'])}\n\n")
    rows = [
        [(f"{s['title']} · от {money(min(s['price'].values()))}", f"svc:{k}")]
        for k, s in SERVICES.items()
    ]
    rows.append([("← Назад", "menu")])
    await ui.show(bot, chat_id, "".join(parts).rstrip(), kb(*rows), message_id=mid)


@router.callback_query(F.data == "book")
async def cb_book(call: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await ack(call)
    await reset_kb(bot, state, call.message.chat.id)
    await state.clear()
    await s_services(bot, call.message.chat.id, mid_of(call))


@router.callback_query(F.data.startswith("svc:"))
async def cb_service(call: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    key = call.data[4:]
    if key not in SERVICES:
        await ack(call)
        return
    await ack(call)
    await state.update_data(service=key, size=None, duration=None, price=None, day=None, start=None)
    await s_sizes(bot, call.message.chat.id, state, mid_of(call))


# ── Шаг 2: размер ────────────────────────────────────────────────────────────

async def s_sizes(bot: Bot, chat_id: int, state: FSMContext, mid: int | None) -> None:
    data = await state.get_data()
    svc = SERVICES[data["service"]]
    lines = [head(2, "Размер собаки"), f"<b>{esc(svc['title'])}</b>\n\n"]
    rows = []
    for k, z in SIZES.items():
        lines.append(
            f"{z['title']} ({z['hint']}) — {money(svc['price'][k])}, "
            f"около {duration(svc['mins'][k])}\n"
        )
        rows.append([(f"{z['title']} · {z['hint']} · {money(svc['price'][k])}", f"size:{k}")])
    lines.append("\n<i>Если шерсть сильно запутана, мастер уточнит стоимость на месте.</i>")
    rows.append([("← Назад", "book")])
    await ui.show(bot, chat_id, "".join(lines), kb(*rows), message_id=mid)


@router.callback_query(F.data.startswith("size:"))
async def cb_size(call: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    key = call.data[5:]
    data = await state.get_data()
    svc = SERVICES.get(data.get("service") or "")
    if svc is None or key not in SIZES:
        await expired(call, state, bot)
        return
    await ack(call)
    await state.update_data(
        size=key, duration=svc["mins"][key], price=svc["price"][key], day=None, start=None
    )
    await s_dates(bot, call.message.chat.id, state, mid_of(call))


# ── Шаг 3: день ──────────────────────────────────────────────────────────────

def summary_line(data: dict) -> str:
    svc = SERVICES[data["service"]]
    return (
        f"{esc(svc['title'])} · {SIZES[data['size']]['title'].lower()} · "
        f"{money(data['price'])} · около {duration(data['duration'])}"
    )


async def s_dates(bot: Bot, chat_id: int, state: FSMContext, mid: int | None,
                  notice: str = "") -> None:
    await state.set_state(None)
    data = await state.get_data()
    now = config.now_local()
    resch = data.get("resch")
    dates = db.available_dates(data["duration"], now, exclude_id=resch)
    back = f"bk_open:{resch}" if resch else "bk:size"
    title = head(None, "Выберите новый день") if resch else head(3, "Выберите день")
    summary = f"{summary_line(data)}\n\n"

    if not dates:
        text = (
            f"{notice}{title}{summary}"
            "В ближайшие две недели свободных окон нет.\n"
            f"Позвоните нам, подберём время вручную: {esc(SALON['phone'])}"
        )
        await ui.show(bot, chat_id, text, kb([("← Назад", back)]), message_id=mid)
        return

    buttons = []
    for d in dates:
        delta = (d - now.date()).days
        label = "Сегодня" if delta == 0 else "Завтра" if delta == 1 else d_btn(d)
        buttons.append((label, f"date:{d.isoformat()}"))
    rows = grid(buttons, 3) + [[("← Назад", back)]]
    await ui.show(bot, chat_id, f"{notice}{title}{summary}Доступные дни:", kb(*rows), message_id=mid)


@router.callback_query(F.data.startswith("date:"))
async def cb_date(call: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    try:
        date.fromisoformat(call.data[5:])
    except ValueError:
        await ack(call)
        return
    if not need(data, "duration", "price", "service", "size"):
        await expired(call, state, bot)
        return
    await ack(call)
    await state.update_data(day=call.data[5:], start=None)
    await s_times(bot, call.message.chat.id, state, mid_of(call))


# ── Шаг 4: время ─────────────────────────────────────────────────────────────

async def s_times(bot: Bot, chat_id: int, state: FSMContext, mid: int | None) -> None:
    await state.set_state(None)
    data = await state.get_data()
    d = date.fromisoformat(data["day"])
    times = db.free_times(d, data["duration"], config.now_local(), data.get("resch"))
    if not times:
        await s_dates(
            bot, chat_id, state, mid,
            notice="<i>На этот день свободного времени уже нет. Выберите другой.</i>\n\n",
        )
        return
    resch = data.get("resch")
    title = head(None, "Выберите новое время") if resch else head(4, "Выберите время")
    text = (
        f"{title}<b>{d_long(d)}</b>\n"
        f"Услуга займёт около {duration(data['duration'])}. Показано время начала."
    )
    rows = grid([(t, f"time:{t}") for t in times], 4) + [[("← Назад", "bk:date")]]
    await ui.show(bot, chat_id, text, kb(*rows), message_id=mid)


@router.callback_query(F.data.startswith("time:"))
async def cb_time(call: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    start = call.data[5:]
    data = await state.get_data()
    if not need(data, "duration", "day"):
        await expired(call, state, bot)
        return
    chat_id, mid = call.message.chat.id, mid_of(call)
    d = date.fromisoformat(data["day"])
    if start not in db.free_times(d, data["duration"], config.now_local(), data.get("resch")):
        await ack(call, "Это время только что заняли. Выберите другое.", alert=True)
        await s_times(bot, chat_id, state, mid)
        return
    await ack(call)
    await state.update_data(start=start)
    if data.get("resch"):
        await s_confirm_resch(bot, chat_id, state, mid)
    else:
        await s_pet(bot, chat_id, state, mid)


# ── Шаг 5: питомец и особенности ─────────────────────────────────────────────

async def s_pet(bot: Bot, chat_id: int, state: FSMContext, mid: int | None,
                notice: str = "") -> None:
    await state.set_state(Book.pet)
    text = (
        f"{head(5, 'О питомце')}"
        "Напишите одним сообщением, как зовут собаку и какой она породы.\n\n"
        "<i>Например: Бонни, той-терьер</i>"
        f"{notice}"
    )
    await ui.show(bot, chat_id, text, kb([("← Назад", "bk:time")]), message_id=mid)


@router.message(Book.pet, F.text, ~F.text.startswith("/"))
async def got_pet(msg: Message, state: FSMContext, bot: Bot) -> None:
    await ui.quiet_delete(msg)
    pet = " ".join(msg.text.split())[:80]
    if len(pet) < 2:
        await s_pet(bot, msg.chat.id, state, None,
                    notice="\n\n<i>Напишите, пожалуйста, имя и породу текстом.</i>")
        return
    await state.update_data(pet=pet)
    await s_notes(bot, msg.chat.id, state, None)


async def s_notes(bot: Bot, chat_id: int, state: FSMContext, mid: int | None) -> None:
    await state.set_state(None)
    data = await state.get_data()
    chosen = set(data.get("notes") or [])
    text = (
        f"{head(5, 'Особенности')}"
        f"Питомец: <b>{esc(data['pet'])}</b>\n\n"
        "Отметьте, что стоит учесть мастеру. Если ничего особенного, нажмите «Далее»."
    )
    if data.get("note_text"):
        text += f"\n\nВаша заметка: <i>{esc(data['note_text'])}</i>"
    rows = [[(("✓ " if i in chosen else "") + label, f"nt:{i}")] for i, label in enumerate(NOTE_OPTIONS)]
    rows.append([("Изменить заметку" if data.get("note_text") else "Своя заметка", "nt:own")])
    rows.append([("Далее", "nt:done")])
    rows.append([("← Назад", "bk:pet")])
    await ui.show(bot, chat_id, text, kb(*rows), message_id=mid)


@router.callback_query(F.data.startswith("nt:"))
async def cb_notes(call: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    arg = call.data[3:]
    data = await state.get_data()
    if not need(data, "pet", "start", "day", "duration"):
        await expired(call, state, bot)
        return
    await ack(call)
    chat_id, mid = call.message.chat.id, mid_of(call)

    if arg == "own":
        await state.set_state(Book.note)
        await ui.show(
            bot, chat_id,
            f"{head(5, 'Своя заметка')}Напишите одним сообщением, что важно знать мастеру "
            "(до 200 символов).",
            kb([("Отмена", "bk:notes")]), message_id=mid,
        )
    elif arg == "done":
        phone = db.get_phone(call.from_user.id)
        if phone:
            await state.update_data(phone=phone)
            await s_confirm(bot, chat_id, state, mid)
        else:
            await s_phone(bot, chat_id, state, mid)
    elif arg.isdigit() and int(arg) < len(NOTE_OPTIONS):
        chosen = set(data.get("notes") or [])
        chosen.symmetric_difference_update({int(arg)})
        await state.update_data(notes=sorted(chosen))
        await s_notes(bot, chat_id, state, mid)


@router.message(Book.note, F.text, ~F.text.startswith("/"))
async def got_note(msg: Message, state: FSMContext, bot: Bot) -> None:
    await ui.quiet_delete(msg)
    await state.update_data(note_text=" ".join(msg.text.split())[:200])
    await s_notes(bot, msg.chat.id, state, None)


# ── Шаг 6: контакт ───────────────────────────────────────────────────────────

async def s_phone(bot: Bot, chat_id: int, state: FSMContext, mid: int | None,
                  notice: str = "") -> None:
    await state.set_state(Book.phone)
    text = (
        f"{head(6, 'Контакт для связи')}"
        "Нажмите «Поделиться номером» под полем ввода или напишите номер сообщением. "
        "Он нужен, только чтобы мастер мог уточнить детали визита."
        f"{notice}"
    )
    await ui.show(
        bot, chat_id, text, kb([("Пропустить", "ph:skip")], [("← Назад", "bk:notes")]),
        message_id=mid,
    )
    data = await state.get_data()
    if not data.get("reply_kb"):
        helper = await bot.send_message(
            chat_id,
            "Кнопка для отправки номера — ниже.",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="Поделиться номером", request_contact=True)]],
                resize_keyboard=True,
                one_time_keyboard=True,
            ),
        )
        await state.update_data(reply_kb=helper.message_id)


async def finish_phone(bot: Bot, chat_id: int, state: FSMContext, phone: str) -> None:
    await reset_kb(bot, state, chat_id)
    await state.update_data(phone=phone)
    await s_confirm(bot, chat_id, state, None)


@router.message(Book.phone, F.contact)
async def got_contact(msg: Message, state: FSMContext, bot: Bot) -> None:
    await ui.quiet_delete(msg)
    phone = normalize_phone(msg.contact.phone_number)
    if phone is None:
        await s_phone(bot, msg.chat.id, state, None,
                      notice="\n\n<i>Не удалось распознать номер. Попробуйте ещё раз.</i>")
        return
    db.set_phone(msg.from_user.id, phone)
    await finish_phone(bot, msg.chat.id, state, phone)


@router.message(Book.phone, F.text, ~F.text.startswith("/"))
async def got_phone_text(msg: Message, state: FSMContext, bot: Bot) -> None:
    await ui.quiet_delete(msg)
    phone = normalize_phone(msg.text)
    if phone is None:
        await s_phone(bot, msg.chat.id, state, None,
                      notice="\n\n<i>Не похоже на номер. Пример: +7 900 123-45-67</i>")
        return
    db.set_phone(msg.from_user.id, phone)
    await finish_phone(bot, msg.chat.id, state, phone)


@router.callback_query(F.data == "ph:skip")
async def cb_phone_skip(call: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    if not need(data, "pet", "start", "day", "duration"):
        await expired(call, state, bot)
        return
    await ack(call)
    await reset_kb(bot, state, call.message.chat.id)
    await state.update_data(phone="")
    await s_confirm(bot, call.message.chat.id, state, mid_of(call))


# ── Подтверждение ────────────────────────────────────────────────────────────

async def s_confirm(bot: Bot, chat_id: int, state: FSMContext, mid: int | None) -> None:
    await state.set_state(None)
    data = await state.get_data()
    finish = to_hhmm(to_min(data["start"]) + data["duration"])
    preview = {
        "service": data["service"], "size": data["size"], "duration": data["duration"],
        "pet": data["pet"], "day": data["day"], "start": data["start"], "finish": finish,
        "price": data["price"], "note": compose_note(data), "status": "pending",
    }
    phone = data.get("phone")
    text = (
        f"{head(None, 'Проверьте запись')}"
        f"{client_card(preview, with_status=False)}\n"
        f"Телефон: {esc(phone) if phone else 'не указан'}"
    )
    if not config.AUTO_CONFIRM:
        text += "\n\n<i>После отправки мастер подтвердит запись, мы сразу сообщим.</i>"
    rows = [
        [("Подтвердить запись", "confirm")],
        [("Изменить время", "bk:date"), ("Отмена", "menu")],
    ]
    await ui.show(bot, chat_id, text, kb(*rows), message_id=mid)


@router.callback_query(F.data == "confirm")
async def cb_confirm(call: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    if not need(data, "service", "size", "duration", "price", "day", "start", "pet"):
        await expired(call, state, bot)
        return
    chat_id, mid = call.message.chat.id, mid_of(call)
    uid, now = call.from_user.id, config.now_local()
    db.upsert_user(call.from_user)

    if db.count_active(uid, now) >= MAX_ACTIVE_BOOKINGS:
        await ack(
            call,
            f"У вас уже {MAX_ACTIVE_BOOKINGS} активные записи. "
            "Отмените одну из них или дождитесь визита.",
            alert=True,
        )
        return

    status = "confirmed" if config.AUTO_CONFIRM else "pending"
    booking_id = db.create_booking(
        user_id=uid, service=data["service"], size=data["size"], price=data["price"],
        duration=data["duration"], day=data["day"], start=data["start"], pet=data["pet"],
        note=compose_note(data), phone=data.get("phone") or None, status=status, now=now,
    )
    if booking_id is None:
        await ack(call, "Это время только что заняли. Выберите другое.", alert=True)
        await state.update_data(start=None)
        await s_times(bot, chat_id, state, mid)
        return

    await ack(call)
    b = db.get_booking(booking_id)
    await state.clear()
    if status == "pending":
        text = (
            "<b>Заявка отправлена</b>\n\n"
            f"{client_card(b, with_status=False)}\n\n"
            f"{esc(MASTER['short'])} подтвердит запись в ближайшее время. "
            "Мы сразу пришлём уведомление в этот чат."
        )
    else:
        text = (
            "<b>Запись подтверждена</b>\n\n"
            f"{client_card(b, with_status=False)}\n\n{address_block()}\n\n"
            "За день и за 2 часа до визита пришлём напоминание."
        )
    await ui.show(
        bot, chat_id, text, kb([("Мои записи", "my")], [("Главное меню", "menu")]), message_id=mid
    )
    await notify.notify_admins(bot, b, "Новая запись")


# ── Навигация «Назад» по шагам записи ────────────────────────────────────────

BACK_REQUIRES = {
    "size": ("service",),
    "date": ("duration", "price", "service", "size"),
    "time": ("duration", "day"),
    "pet": ("start", "day", "duration"),
    "notes": ("pet",),
}


@router.callback_query(F.data.startswith("bk:"))
async def cb_back(call: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    where = call.data[3:]
    data = await state.get_data()
    if where not in BACK_REQUIRES or not need(data, *BACK_REQUIRES[where]):
        await expired(call, state, bot)
        return
    await ack(call)
    chat_id, mid = call.message.chat.id, mid_of(call)
    await reset_kb(bot, state, chat_id)
    await state.set_state(None)
    if where == "size":
        await s_sizes(bot, chat_id, state, mid)
    elif where == "date":
        await s_dates(bot, chat_id, state, mid)
    elif where == "time":
        await s_times(bot, chat_id, state, mid)
    elif where == "pet":
        await s_pet(bot, chat_id, state, mid)
    else:
        await s_notes(bot, chat_id, state, mid)


# ── Мои записи ───────────────────────────────────────────────────────────────

async def s_my(bot: Bot, chat_id: int, user_id: int, mid: int | None) -> None:
    rows_db = db.user_upcoming(user_id, config.now_local())
    if not rows_db:
        text = "<b>Мои записи</b>\n\nПредстоящих записей пока нет."
        rows = [[("Записаться", "book")], [("← Назад", "menu")]]
    else:
        text = "<b>Мои записи</b>\n\nВыберите запись, чтобы перенести или отменить её."
        rows = [
            [(
                f"{d_date(date.fromisoformat(b['day']))}, {b['start']} · {pet_short(b)}",
                f"bk_open:{b['id']}",
            )]
            for b in rows_db
        ]
        rows.append([("← Назад", "menu")])
    await ui.show(bot, chat_id, text, kb(*rows), message_id=mid)


@router.callback_query(F.data == "my")
async def cb_my(call: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await ack(call)
    await reset_kb(bot, state, call.message.chat.id)
    await state.clear()
    await s_my(bot, call.message.chat.id, call.from_user.id, mid_of(call))


def own_active(call: CallbackQuery, booking_id: str):
    """Запись пользователя, если она существует, принадлежит ему и ещё действует."""
    if not booking_id.isdigit():
        return None
    b = db.get_booking(int(booking_id))
    if b is None or b["user_id"] != call.from_user.id:
        return None
    if b["status"] not in ("pending", "confirmed"):
        return None
    return b


@router.callback_query(F.data.startswith("bk_open:"))
async def cb_open(call: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await ack(call)
    await state.clear()
    chat_id, mid = call.message.chat.id, mid_of(call)
    b = own_active(call, call.data[8:])
    if b is None:
        await s_my(bot, chat_id, call.from_user.id, mid)
        return
    text = (
        f"<b>Запись № {b['id']}</b>\n\n{client_card(b)}\n\n"
        f"<b>Адрес</b>\n{address_block()}"
    )
    rows = [
        [("Перенести", f"resch:{b['id']}"), ("Отменить запись", f"cancel:{b['id']}")],
        [("← Назад", "my")],
    ]
    await ui.show(bot, chat_id, text, kb(*rows), message_id=mid)


@router.callback_query(F.data.startswith("cancel:"))
async def cb_cancel_ask(call: CallbackQuery, bot: Bot) -> None:
    await ack(call)
    chat_id, mid = call.message.chat.id, mid_of(call)
    b = own_active(call, call.data[7:])
    if b is None:
        await s_my(bot, chat_id, call.from_user.id, mid)
        return
    d = date.fromisoformat(b["day"])
    text = (
        "<b>Отменить запись?</b>\n\n"
        f"{esc(pet_short(b))}, {d_date(d)} в {b['start']}, {esc(service_title(b)).lower()}."
    )
    rows = [[("Да, отменить", f"cancel_yes:{b['id']}")], [("Оставить", f"bk_open:{b['id']}")]]
    await ui.show(bot, chat_id, text, kb(*rows), message_id=mid)


@router.callback_query(F.data.startswith("cancel_yes:"))
async def cb_cancel_do(call: CallbackQuery, bot: Bot) -> None:
    await ack(call)
    chat_id, mid = call.message.chat.id, mid_of(call)
    b = own_active(call, call.data[11:])
    if b is None:
        await s_my(bot, chat_id, call.from_user.id, mid)
        return
    db.set_status(b["id"], "cancelled")
    b = db.get_booking(b["id"])
    await ui.show(
        bot, chat_id,
        "<b>Запись отменена</b>\n\nБудем рады видеть вас снова.",
        kb([("Записаться снова", "book")], [("Главное меню", "menu")]),
        message_id=mid,
    )
    await notify.notify_admins(bot, b, "Клиент отменил запись", with_buttons=False)


# ── Перенос записи ───────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("resch:"))
async def cb_resch(call: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await ack(call)
    chat_id, mid = call.message.chat.id, mid_of(call)
    b = own_active(call, call.data[6:])
    if b is None:
        await s_my(bot, chat_id, call.from_user.id, mid)
        return
    await state.clear()
    await state.update_data(
        resch=b["id"], service=b["service"], size=b["size"],
        duration=b["duration"], price=b["price"],
    )
    await s_dates(bot, chat_id, state, mid)


async def s_confirm_resch(bot: Bot, chat_id: int, state: FSMContext, mid: int | None) -> None:
    data = await state.get_data()
    b = db.get_booking(data["resch"])
    old, new = date.fromisoformat(b["day"]), date.fromisoformat(data["day"])
    finish = to_hhmm(to_min(data["start"]) + b["duration"])
    text = (
        f"{head(None, 'Перенос записи')}"
        f"<blockquote><b>{esc(service_title(b))}</b>\n{esc(b['pet'])}\n\n"
        f"Было: {d_long(old)}, {b['start']}\n"
        f"Станет: {d_long(new)}, {data['start']} – {finish}</blockquote>"
    )
    if not config.AUTO_CONFIRM:
        text += "\n\n<i>После переноса мастер подтвердит новое время.</i>"
    rows = [
        [("Подтвердить перенос", "rok")],
        [("Изменить время", "bk:date"), ("Отмена", f"bk_open:{b['id']}")],
    ]
    await ui.show(bot, chat_id, text, kb(*rows), message_id=mid)


@router.callback_query(F.data == "rok")
async def cb_resch_ok(call: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    if not need(data, "resch", "day", "start"):
        await expired(call, state, bot)
        return
    chat_id, mid = call.message.chat.id, mid_of(call)
    b = own_active(call, str(data["resch"]))
    if b is None:
        await ack(call)
        await state.clear()
        await s_my(bot, chat_id, call.from_user.id, mid)
        return
    status = "confirmed" if config.AUTO_CONFIRM else "pending"
    if not db.reschedule(b["id"], data["day"], data["start"], status, config.now_local()):
        await ack(call, "Это время только что заняли. Выберите другое.", alert=True)
        await state.update_data(start=None)
        await s_times(bot, chat_id, state, mid)
        return
    await ack(call)
    await state.clear()
    b = db.get_booking(b["id"])
    note = "" if status == "confirmed" else (
        f"\n\n{esc(MASTER['short'])} подтвердит новое время, мы сразу сообщим."
    )
    await ui.show(
        bot, chat_id,
        f"<b>Запись перенесена</b>\n\n{client_card(b, with_status=False)}{note}",
        kb([("Мои записи", "my")], [("Главное меню", "menu")]),
        message_id=mid,
    )
    await notify.notify_admins(bot, b, "Клиент перенёс запись")


# ── Всё остальное ────────────────────────────────────────────────────────────

@router.message()
async def fallback_message(msg: Message, bot: Bot) -> None:
    """Любые посторонние сообщения удаляем, чтобы чат оставался чистым."""
    await ui.quiet_delete(msg)
    if msg.chat.id not in ui.SCREENS:
        await s_menu(bot, msg.chat.id, msg.from_user)


@router.callback_query()
async def fallback_callback(call: CallbackQuery) -> None:
    await ack(call)
