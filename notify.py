# -*- coding: utf-8 -*-
"""Уведомления: мастеру о записях и клиентам о решениях и напоминаниях."""
from __future__ import annotations

import logging
from datetime import date

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

import config
from cards import address_block, admin_card, client_card, pet_short, service_title
from fmt import d_date, esc
from keyboards import kb

log = logging.getLogger(__name__)


async def notify_admins(bot: Bot, b, title: str, with_buttons: bool = True) -> None:
    """Отправляет мастеру карточку записи. Для новых записей — кнопки «Принять/Отклонить»."""
    markup = None
    if with_buttons:
        if b["status"] == "pending":
            markup = kb([("Принять", f"adm_acc:{b['id']}"), ("Отклонить", f"adm_dec:{b['id']}")])
        elif b["status"] == "confirmed":
            markup = kb([("Отменить запись", f"adm_cx:{b['id']}")])
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, admin_card(b, title), reply_markup=markup)
        except TelegramAPIError as e:
            log.warning("Не удалось отправить уведомление мастеру %s: %s", admin_id, e)


async def tell_client(bot: Bot, user_id: int, text: str, markup=None) -> None:
    try:
        await bot.send_message(user_id, text, reply_markup=markup)
    except TelegramAPIError as e:
        log.warning("Не удалось написать клиенту %s: %s", user_id, e)


def text_confirmed(b) -> str:
    return (
        "<b>Запись подтверждена</b>\n\n"
        f"{client_card(b, with_status=False)}\n\n"
        f"{address_block()}\n\n"
        "За день и за 2 часа до визита пришлём напоминание. Если планы изменятся, "
        "перенесите или отмените запись в разделе «Мои записи»."
    )


async def client_confirmed(bot: Bot, b) -> None:
    await tell_client(bot, b["user_id"], text_confirmed(b), kb([("Мои записи", "my")]))


async def client_declined(bot: Bot, b) -> None:
    d = date.fromisoformat(b["day"])
    text = (
        "<b>Запись не подтверждена</b>\n\n"
        f"К сожалению, мастер не сможет принять {esc(pet_short(b))} "
        f"{d_date(d)} в {b['start']}. Выберите, пожалуйста, другое время."
    )
    await tell_client(
        bot, b["user_id"], text, kb([("Выбрать другое время", "book")], [("Главное меню", "menu")])
    )


async def client_cancelled(bot: Bot, b) -> None:
    d = date.fromisoformat(b["day"])
    text = (
        "<b>Запись отменена мастером</b>\n\n"
        f"Приём {esc(pet_short(b))} {d_date(d)} в {b['start']} не состоится. "
        "Приносим извинения. Выберите другое время, мы подберём удобное."
    )
    await tell_client(
        bot, b["user_id"], text, kb([("Записаться снова", "book")], [("Главное меню", "menu")])
    )


async def reminder(bot: Bot, b, soon: bool) -> None:
    d = date.fromisoformat(b["day"])
    pet = esc(pet_short(b))
    if soon:
        text = (
            "<b>Скоро визит</b>\n\n"
            f"Ждём {pet} сегодня в {b['start']}: {esc(service_title(b)).lower()}.\n\n"
            f"{address_block()}"
        )
    else:
        when = "сегодня" if d == config.now_local().date() else "завтра"
        text = (
            "<b>Напоминание о визите</b>\n\n"
            f"Ждём {pet} {when}, {d_date(d)}, в {b['start']}: "
            f"{esc(service_title(b)).lower()}.\n\n"
            f"{address_block()}\n\n"
            "Если планы изменились, перенесите или отмените запись заранее."
        )
    await tell_client(bot, b["user_id"], text, kb([("Мои записи", "my")]))
