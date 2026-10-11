# -*- coding: utf-8 -*-
"""Настройки из файла .env и общие константы."""
from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent


def _load_env(path: Path) -> None:
    """Минимальный разбор .env (строки вида KEY=value), без сторонних библиотек."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


_load_env(BASE_DIR / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = {
    int(x) for x in re.split(r"[,\s;]+", os.getenv("ADMIN_IDS", "")) if x.strip().isdigit()
}
TIMEZONE = os.getenv("TIMEZONE", "Europe/Moscow").strip() or "Europe/Moscow"
_AUTO = os.getenv("AUTO_CONFIRM", "false").strip().lower() in ("1", "true", "yes", "да")

# Без мастера подтверждать некому, поэтому записи подтверждаются автоматически.
AUTO_CONFIRM = _AUTO or not ADMIN_IDS

DB_PATH = BASE_DIR / "data" / "bot.sqlite3"
ASSETS = BASE_DIR / "assets"
WELCOME_PHOTO = ASSETS / "welcome.jpg"
MASTER_PHOTO = ASSETS / "master.jpg"

_TZ = ZoneInfo(TIMEZONE)


def now_local() -> datetime:
    """Текущее время салона без указания часового пояса (наивное)."""
    return datetime.now(_TZ).replace(tzinfo=None, second=0, microsecond=0)
