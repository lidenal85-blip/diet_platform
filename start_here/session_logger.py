"""
start_here/session_logger.py

Система логирования сессий AI-разработки.

Каждое действие пишется в Markdown-файл сессии:
  - задача (TASK)
  - в процессе (DOING)
  - сделано (DONE)
  - следующее (NEXT)
  - ошибка (ERROR)
  - снапшот блока (snapshot_BLOCK.md)

Использование:
    from start_here.session_logger import get_session_logger
    log = get_session_logger("v2_recipes")
    log.task("Реализовать режимы рецептов")
    log.doing("Создаю modules/recipes/")
    log.done("Модуль создан, 4 режима")
    log.next("Добавить кнопки в bot.py")
    log.snapshot()
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

LOGS_DIR = Path(__file__).parent / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)


class SessionLogger:
    """
    Пишет Markdown-лог в `start_here/logs/session_YYYYMMDD_NNN.md`.
    Снапшот блока — в `snapshot_BLOCK.md`.
    """

    def __init__(self, block_name: str, session_file: Optional[Path] = None):
        self.block_name = _slugify(block_name)
        ts = datetime.now().strftime("%Y%m%d")

        if session_file:
            self._path = session_file
        else:
            # Автономер сессий за день
            n = 1
            while True:
                candidate = LOGS_DIR / f"session_{ts}_{n:03d}.md"
                if not candidate.exists():
                    break
                # Если файл с этим блоком уже существует — подключаемся к нему
                content = candidate.read_text()
                if f"block: {self.block_name}" in content:
                    candidate = candidate
                    n = -1  # сентинел
                    break
                n += 1
            if n == -1:
                self._path = LOGS_DIR / f"session_{ts}_{1:03d}.md"
                # Найдём по блоку
                for f in sorted(LOGS_DIR.glob(f"session_{ts}_*.md")):
                    if f"block: {self.block_name}" in f.read_text():
                        self._path = f
                        break
            else:
                self._path = candidate

        self._init_file()

    def _init_file(self):
        if not self._path.exists():
            ts_full = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            self._path.write_text(
                f"# 📓 Сессия: {self.block_name}\n"
                f"**started:** {ts_full}\n"
                f"**block:** {self.block_name}\n"
                f"**file:** {self._path.name}\n\n"
                f"---\n\n",
                encoding="utf-8",
            )

    def _append(self, emoji: str, label: str, text: str):
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        line = f"**[{ts}]** {emoji} `{label}` {text}\n\n"
        with self._path.open("a", encoding="utf-8") as f:
            f.write(line)

    def task(self, text: str):
        """TASK: что нужно сделать."""
        self._append("🟡", "TASK", text)

    def doing(self, text: str):
        """DOING: как делаю."""
        self._append("🔧", "DOING", text)

    def done(self, text: str):
        """DONE: что сделано."""
        self._append("✅", "DONE", text)

    def next(self, text: str):
        """NEXT: что дальше."""
        self._append("➡️", "NEXT", text)

    def error(self, text: str):
        """ERROR: ошибка."""
        self._append("❌", "ERROR", text)

    def info(self, text: str):
        """INFO: произвольная пометка."""
        self._append("ℹ️", "INFO", text)

    def snapshot(self, summary: str = ""):
        """
        Сохраняет снапшот блока в `snapshot_BLOCK.md`.
        Вызывай по завершению блока работы.
        """
        snap_path = LOGS_DIR / f"snapshot_{self.block_name}.md"
        ts_full = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        session_content = self._path.read_text(encoding="utf-8")

        snap = (
            f"# 📸 Snapshot: {self.block_name}\n"
            f"**Выполнено:** {ts_full}\n\n"
        )
        if summary:
            snap += f"## Резюме\n{summary}\n\n"
        snap += f"## Полная сессия\n\n{session_content}"

        snap_path.write_text(snap, encoding="utf-8")
        self._append("📸", "SNAPSHOT", f"Сохранён в `{snap_path.name}`")
        return snap_path


# ── singleton-список активных логгеров по block_name ──────────────
_LOGGERS: dict[str, SessionLogger] = {}


def get_session_logger(block_name: str) -> SessionLogger:
    """Возвращает существующий логгер или создаёт новый."""
    slug = _slugify(block_name)
    if slug not in _LOGGERS:
        _LOGGERS[slug] = SessionLogger(block_name)
    return _LOGGERS[slug]


def _slugify(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[\s\-]+", "_", s)
    s = re.sub(r"[^\w]", "", s)
    return s[:40]