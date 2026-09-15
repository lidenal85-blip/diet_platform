"""§20 step 6: Mini App routes DISABLED в Phase 0 (owner decision).

Контракт (ARCHITECTURE_PHASE0 §20, step 6 + owner decisions):
- Все маршруты ``/diet/app*`` недоступны (404): GET /app, GET/POST /app/profile.
- Причина: неаутентифицированные чтение/запись профиля без initData validation.
- Повторное включение = отдельная задача (initData validation) + флаг конфига.
- Кабинет ``/diet/cabinet`` НЕ затронут — DISABLE строго скоупится на Mini App.

Тесты — HTTP-уровень через httpx.ASGITransport (lifespan не запускается:
init_db/worker не выполняются; starlette.TestClient несовместим с httpx>=0.28).
DB miniapp-обработчиков подменяется на temp-файл (прод-БД не используется).
"""
from __future__ import annotations

import os
import sqlite3
import sys
import types

import httpx
import pytest

pytestmark = pytest.mark.asyncio

PROBE_TG_ID = "999000111"

# Минимальный user_profiles — чтобы POST-проба в RED-фазе была детерминированной
# (200 {"ok": true} сейчас; 404 после DISABLE), без побочных эффектов.
_CREATE_PROFILES = """
CREATE TABLE IF NOT EXISTS user_profiles (
    tg_id TEXT PRIMARY KEY,
    cook_level TEXT,
    experiment_level TEXT,
    budget_level TEXT,
    max_cook_time INTEGER,
    excluded_foods TEXT,
    recipe_day_time TEXT,
    recipe_day_enabled INTEGER,
    notify_personal INTEGER,
    notify_meals INTEGER,
    notify_recipe_day INTEGER
)
"""


async def _request(app, method: str, url: str, **kw) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        return await c.request(method, url, **kw)


@pytest.fixture()
def asgi_app(tmp_path, monkeypatch):
    db = tmp_path / "miniapp_probe.db"
    con = sqlite3.connect(db)
    con.execute(_CREATE_PROFILES)
    con.commit()
    con.close()

    # NB: под pytest на sys.path попадает /mnt/sdcard/PROJECTS/workstation с
    # теневым пакетом ``api`` (регулярный, с __init__.py), а локальный ``api/`` —
    # namespace-пакет (без __init__.py): регулярный всегда выигрывает. Пиним
    # ``api`` к каталогу проекта явно.
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    monkeypatch.syspath_prepend(root)
    fake_api = types.ModuleType("api")
    fake_api.__path__ = [os.path.join(root, "api")]
    monkeypatch.setitem(sys.modules, "api", fake_api)
    monkeypatch.delitem(sys.modules, "api.miniapp_router", raising=False)

    import api.miniapp_router as miniapp_router  # noqa
    from modules.delivery_api.controllers.api import app  # noqa

    # DB_PATH импортирован по значению в miniapp_router — патчим сам модуль.
    monkeypatch.setattr(miniapp_router, "DB_PATH", str(db))
    return app


class TestMiniAppDisabled:
    async def test_get_app_html_is_404(self, asgi_app):
        r = await _request(asgi_app, "GET", "/diet/app")
        assert r.status_code == 404

    async def test_get_profile_is_404(self, asgi_app):
        r = await _request(asgi_app, "GET", f"/diet/app/profile?tg_id={PROBE_TG_ID}")
        assert r.status_code == 404

    async def test_post_profile_is_404(self, asgi_app):
        r = await _request(
            asgi_app,
            "POST",
            "/diet/app/profile",
            json={"tg_id": PROBE_TG_ID, "cook_level": "cook"},
        )
        assert r.status_code == 404


class TestDisableIsScopedToMiniApp:
    async def test_cabinet_page_still_served(self, asgi_app):
        # Без токена кабинет рендерит форму по умолчанию (БД не трогает).
        r = await _request(asgi_app, "GET", "/diet/cabinet")
        assert r.status_code == 200

    def test_route_table_contains_cabinet_but_not_miniapp(self, asgi_app):
        paths = {getattr(route, "path", "") for route in asgi_app.routes}
        assert "/diet/cabinet" in paths
        assert not any(p.startswith("/diet/app") for p in paths)


class TestOwnerDecisionLockedInConfig:
    def test_miniapp_enabled_defaults_to_false(self):
        from building_blocks.config import Settings

        assert Settings().miniapp_enabled is False
