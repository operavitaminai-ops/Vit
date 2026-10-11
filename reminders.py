# -*- coding: utf-8 -*-
"""Фоновая задача: напоминания клиентам за сутки и за 2 часа до визита."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from aiogram import Bot

import config
import db
import notify

log = logging.getLogger(__name__)


async def run_once(bot: Bot) -> None:
    now = config.now_local()
    for b in db.confirmed_future(now):
        start = datetime.fromisoformat(f"{b['day']}T{b['start']}")
        minutes = (start - now).total_seconds() / 60
        if minutes <= 0:
            continue
        if minutes <= 120 and not b["reminded_hours"]:
            db.mark_reminded(b["id"], day=True, hours=True)
            await notify.reminder(bot, b, soon=True)
        elif 120 < minutes <= 24 * 60 and not b["reminded_day"]:
            db.mark_reminded(b["id"], day=True)
            await notify.reminder(bot, b, soon=False)


async def loop(bot: Bot, every_seconds: int = 60) -> None:
    while True:
        try:
            await run_once(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Ошибка в задаче напоминаний")
        await asyncio.sleep(every_seconds)
