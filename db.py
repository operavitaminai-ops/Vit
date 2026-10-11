# -*- coding: utf-8 -*-
"""Хранилище записей на SQLite (один файл data/bot.sqlite3)."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime

import config
import slots

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id    INTEGER PRIMARY KEY,
    first_name TEXT,
    username   TEXT,
    phone      TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS bookings (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL,
    service        TEXT NOT NULL,
    size           TEXT NOT NULL,
    price          INTEGER NOT NULL,
    duration       INTEGER NOT NULL,
    day            TEXT NOT NULL,      -- YYYY-MM-DD
    start          TEXT NOT NULL,      -- HH:MM
    finish         TEXT NOT NULL,      -- HH:MM
    pet            TEXT,
    note           TEXT,
    phone          TEXT,
    status         TEXT NOT NULL,      -- pending | confirmed | declined | cancelled
    created_at     TEXT,
    reminded_day   INTEGER NOT NULL DEFAULT 0,
    reminded_hours INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_bookings_day ON bookings(day, status);
CREATE INDEX IF NOT EXISTS idx_bookings_user ON bookings(user_id, status);

-- Закрытое время. start/finish = NULL означает «весь день».
CREATE TABLE IF NOT EXISTS blocks (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    day    TEXT NOT NULL,
    start  TEXT,
    finish TEXT
);
"""

ACTIVE = "('pending','confirmed')"
SELECT_BOOKING = (
    "SELECT b.*, u.first_name AS first_name, u.username AS username "
    "FROM bookings b LEFT JOIN users u ON u.user_id = b.user_id "
)

_conn: sqlite3.Connection | None = None


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(config.DB_PATH, isolation_level=None)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
    return _conn


def init() -> None:
    conn().executescript(SCHEMA)


def _stamp(now: datetime) -> str:
    return now.strftime("%Y-%m-%d %H:%M")


def _minutes_to(day: str, start: str, now: datetime) -> float:
    begin = datetime.fromisoformat(f"{day}T{start}")
    return (begin - now).total_seconds() / 60


# ── Пользователи ─────────────────────────────────────────────────────────────

def upsert_user(user) -> None:
    conn().execute(
        "INSERT INTO users(user_id, first_name, username, created_at) VALUES(?,?,?,?) "
        "ON CONFLICT(user_id) DO UPDATE SET first_name=excluded.first_name, "
        "username=excluded.username",
        (user.id, user.first_name, user.username, _stamp(config.now_local())),
    )


def get_phone(user_id: int) -> str | None:
    row = conn().execute("SELECT phone FROM users WHERE user_id=?", (user_id,)).fetchone()
    return row["phone"] if row and row["phone"] else None


def set_phone(user_id: int, phone: str) -> None:
    conn().execute("UPDATE users SET phone=? WHERE user_id=?", (phone, user_id))


# ── Свободное время ──────────────────────────────────────────────────────────

def busy_for(d: date, exclude_id: int | None = None) -> list[tuple[int, int]]:
    """Занятые интервалы дня в минутах: записи и закрытое мастером время."""
    iso = d.isoformat()
    query = f"SELECT start, finish FROM bookings WHERE day=? AND status IN {ACTIVE}"
    args: list = [iso]
    if exclude_id:
        query += " AND id<>?"
        args.append(exclude_id)
    busy = [
        (slots.to_min(r["start"]), slots.to_min(r["finish"]))
        for r in conn().execute(query, args)
    ]
    for r in conn().execute("SELECT start, finish FROM blocks WHERE day=?", (iso,)):
        if r["start"] is None:
            busy.append((0, 24 * 60))
        else:
            busy.append((slots.to_min(r["start"]), slots.to_min(r["finish"])))
    return busy


def free_times(d: date, duration: int, now: datetime, exclude_id: int | None = None) -> list[str]:
    return slots.free_starts(d, duration, busy_for(d, exclude_id), now)


def available_dates(duration: int, now: datetime, exclude_id: int | None = None) -> list[date]:
    from content import HORIZON_DAYS

    result = []
    for i in range(HORIZON_DAYS):
        d = date.fromordinal(now.date().toordinal() + i)
        if free_times(d, duration, now, exclude_id):
            result.append(d)
    return result


# ── Записи ───────────────────────────────────────────────────────────────────

def create_booking(*, user_id: int, service: str, size: str, price: int, duration: int,
                   day: str, start: str, pet: str, note: str, phone: str | None,
                   status: str, now: datetime) -> int | None:
    """
    Создаёт запись. Проверка свободного времени и вставка выполняются в одной
    транзакции, поэтому двойной записи на одно время не будет.
    Возвращает id записи или None, если время уже занято.
    """
    c = conn()
    d = date.fromisoformat(day)
    c.execute("BEGIN IMMEDIATE")
    try:
        if start not in slots.free_starts(d, duration, busy_for(d), now):
            c.execute("ROLLBACK")
            return None
        finish = slots.to_hhmm(slots.to_min(start) + duration)
        mins = _minutes_to(day, start, now)
        cur = c.execute(
            "INSERT INTO bookings(user_id, service, size, price, duration, day, start, finish, "
            "pet, note, phone, status, created_at, reminded_day, reminded_hours) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (user_id, service, size, price, duration, day, start, finish, pet, note, phone,
             status, _stamp(now), int(mins <= 24 * 60), int(mins <= 120)),
        )
        c.execute("COMMIT")
        return cur.lastrowid
    except Exception:
        c.execute("ROLLBACK")
        raise


def reschedule(booking_id: int, day: str, start: str, status: str, now: datetime) -> bool:
    """Переносит запись на новое время. False, если время занято."""
    c = conn()
    row = c.execute("SELECT duration FROM bookings WHERE id=?", (booking_id,)).fetchone()
    if row is None:
        return False
    duration = row["duration"]
    d = date.fromisoformat(day)
    c.execute("BEGIN IMMEDIATE")
    try:
        if start not in slots.free_starts(d, duration, busy_for(d, booking_id), now):
            c.execute("ROLLBACK")
            return False
        finish = slots.to_hhmm(slots.to_min(start) + duration)
        mins = _minutes_to(day, start, now)
        c.execute(
            "UPDATE bookings SET day=?, start=?, finish=?, status=?, reminded_day=?, "
            "reminded_hours=? WHERE id=?",
            (day, start, finish, status, int(mins <= 24 * 60), int(mins <= 120), booking_id),
        )
        c.execute("COMMIT")
        return True
    except Exception:
        c.execute("ROLLBACK")
        raise


def get_booking(booking_id: int):
    return conn().execute(SELECT_BOOKING + "WHERE b.id=?", (booking_id,)).fetchone()


def set_status(booking_id: int, status: str) -> None:
    conn().execute("UPDATE bookings SET status=? WHERE id=?", (status, booking_id))


def user_upcoming(user_id: int, now: datetime):
    return conn().execute(
        SELECT_BOOKING + f"WHERE b.user_id=? AND b.status IN {ACTIVE} "
        "AND b.day || ' ' || b.start >= ? ORDER BY b.day, b.start",
        (user_id, _stamp(now)),
    ).fetchall()


def count_active(user_id: int, now: datetime) -> int:
    row = conn().execute(
        f"SELECT COUNT(*) AS n FROM bookings WHERE user_id=? AND status IN {ACTIVE} "
        "AND day || ' ' || start >= ?",
        (user_id, _stamp(now)),
    ).fetchone()
    return row["n"]


def day_bookings(day: str):
    return conn().execute(
        SELECT_BOOKING + f"WHERE b.day=? AND b.status IN {ACTIVE} ORDER BY b.start", (day,)
    ).fetchall()


def upcoming_all(now: datetime, limit: int = 12):
    return conn().execute(
        SELECT_BOOKING + f"WHERE b.status IN {ACTIVE} AND b.day || ' ' || b.start >= ? "
        "ORDER BY b.day, b.start LIMIT ?",
        (_stamp(now), limit),
    ).fetchall()


def pending_count(now: datetime) -> int:
    row = conn().execute(
        "SELECT COUNT(*) AS n FROM bookings WHERE status='pending' AND day || ' ' || start >= ?",
        (_stamp(now),),
    ).fetchone()
    return row["n"]


def confirmed_future(now: datetime):
    return conn().execute(
        SELECT_BOOKING + "WHERE b.status='confirmed' AND b.day || ' ' || b.start > ? "
        "AND (b.reminded_day=0 OR b.reminded_hours=0)",
        (_stamp(now),),
    ).fetchall()


def mark_reminded(booking_id: int, *, day: bool = False, hours: bool = False) -> None:
    if day:
        conn().execute("UPDATE bookings SET reminded_day=1 WHERE id=?", (booking_id,))
    if hours:
        conn().execute("UPDATE bookings SET reminded_hours=1 WHERE id=?", (booking_id,))


# ── Закрытое время ───────────────────────────────────────────────────────────

def add_block(day: str, start: str | None = None, finish: str | None = None) -> int:
    cur = conn().execute(
        "INSERT INTO blocks(day, start, finish) VALUES(?,?,?)", (day, start, finish)
    )
    return cur.lastrowid


def list_blocks(from_day: str):
    return conn().execute(
        "SELECT * FROM blocks WHERE day>=? ORDER BY day, start", (from_day,)
    ).fetchall()


def remove_block(block_id: int) -> None:
    conn().execute("DELETE FROM blocks WHERE id=?", (block_id,))
