# -*- coding: utf-8 -*-
"""
Заполняет базу вымышленными записями, чтобы на демонстрации список записей
мастера и занятые окна в календаре выглядели «живыми».

Запуск:  python seed_demo.py
Очистить демо-данные: остановите бота и удалите файл data/bot.sqlite3.
"""
from __future__ import annotations

from datetime import timedelta

import config
import db
import slots

# (id клиента, имя, услуга, размер, номер рабочего дня от завтра, время, питомец, особенности, статус)
DEMO = [
    (900000001, "Мария", "full", "s", 0, "10:00", "Бонни, йоркширский терьер", "Боится фена", "confirmed"),
    (900000002, "Алексей", "bath", "m", 0, "12:00", "Рэй, лабрадор", "", "confirmed"),
    (900000003, "Ольга", "hygiene", "s", 0, "15:00", "Фиона, шпиц", "", "confirmed"),
    (900000004, "Игорь", "express", "m", 0, "16:30", "Макс, кокер-спаниель", "", "pending"),
    (900000005, "Наталья", "trim", "m", 1, "10:00", "Грета, фокстерьер", "Нервничает с незнакомыми", "confirmed"),
    (900000006, "Дмитрий", "bath", "s", 1, "15:00", "Локи, вест-хайленд-уайт-терьер", "", "pending"),
    (900000007, "Анна", "full", "m", 2, "11:00", "Милка, пудель", "Чувствительная кожа или аллергия", "confirmed"),
    (900000008, "Сергей", "spa", "s", 2, "15:00", "Лотта, мальтезе", "", "confirmed"),
    (900000009, "Елена", "hygiene", "m", 3, "10:30", "Арчи, бишон фризе", "", "confirmed"),
    (900000010, "Павел", "express", "s", 3, "12:00", "Тайсон, чихуахуа", "Не любит, когда трогают лапы", "confirmed"),
    (900000011, "Ирина", "bath", "l", 3, "15:30", "Тор, золотистый ретривер", "", "pending"),
]


class _User:
    def __init__(self, uid: int, name: str):
        self.id, self.first_name, self.username = uid, name, None


def next_working_days(start, count: int):
    days, d = [], start
    while len(days) < count:
        if slots.day_hours(d):
            days.append(d)
        d += timedelta(days=1)
    return days


def main() -> None:
    db.init()
    if db.conn().execute("SELECT COUNT(*) FROM bookings").fetchone()[0]:
        print("В базе уже есть записи, демо-данные не добавлены. "
              "Чтобы начать с чистого листа, удалите data/bot.sqlite3.")
        return

    now = config.now_local()
    days = next_working_days(now.date() + timedelta(days=1), 4)
    created = 0
    for uid, name, service, size, day_no, start, pet, note, status in DEMO:
        from content import SERVICES

        db.upsert_user(_User(uid, name))
        booking_id = db.create_booking(
            user_id=uid, service=service, size=size,
            price=SERVICES[service]["price"][size], duration=SERVICES[service]["mins"][size],
            day=days[day_no].isoformat(), start=start, pet=pet, note=note, phone=None,
            status=status, now=now,
        )
        if booking_id is None:  # время не подошло под график — пропускаем
            continue
        # Демо-клиентов не существует в Telegram, поэтому напоминания им не нужны.
        db.mark_reminded(booking_id, day=True, hours=True)
        created += 1
    print(f"Добавлено демо-записей: {created}")


if __name__ == "__main__":
    main()
