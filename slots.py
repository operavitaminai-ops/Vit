# -*- coding: utf-8 -*-
"""Расчёт свободного времени. Чистые функции, без базы данных и Telegram."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

import content as C


def to_min(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def to_hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def day_hours(d: date) -> tuple[int, int] | None:
    """Рабочие часы дня в минутах от полуночи или None, если выходной."""
    hours = C.SCHEDULE.get(d.weekday())
    if not hours:
        return None
    return to_min(hours[0]), to_min(hours[1])


def free_starts(d: date, duration: int, busy: list[tuple[int, int]], now: datetime) -> list[str]:
    """
    Время начала, на которое услуга длительностью duration минут помещается
    в рабочий день, не пересекается с перерывами и занятыми интервалами busy
    и начинается не раньше чем через MIN_LEAD_MINUTES от now.
    """
    hours = day_hours(d)
    if not hours:
        return []
    opens, closes = hours
    blocked = list(busy) + [(to_min(a), to_min(b)) for a, b in C.BREAKS]
    earliest = now + timedelta(minutes=C.MIN_LEAD_MINUTES)

    result: list[str] = []
    t = opens
    while t + duration <= closes:
        end = t + duration
        if all(end <= b_start or t >= b_end for b_start, b_end in blocked):
            start_dt = datetime.combine(d, time(t // 60, t % 60))
            if start_dt >= earliest:
                result.append(to_hhmm(t))
        t += C.SLOT_STEP
    return result
