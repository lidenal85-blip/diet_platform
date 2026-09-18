"""Тесты identity_monitor v2: зонд доставки, streak для transient, recovery-DM.

Урок инцидента 2026-09-18: getMe отвечает ok:true у деактивированного бота —
здоровье проверяется реальной доставкой (sendMessage+deleteMessage).
Логика main() тестируется подменой call/probe_delivery/dm_owner (без сети);
внутренности зонда (urllib) — отдельным тестом с настоящим Request.
"""
import importlib.util
import json
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "identity_monitor.py"

BASELINE = {
    "bot_id": 1,
    "username": "test_bot",
    "first_name": "ПУХЛЯШ",
    "my_name": "ПУХЛЯШ",
    "description": "d",
    "short_description": "sd",
}
ENV_OK = ["TELEGRAM_BOT_TOKEN=x", "TELEGRAM_ADMIN_CHAT_ID=7709651193"]


def load_module(env_lines, baseline):
    """Импорт скрипта с изолированными ENV/BASE/STATE (tmp-каталог)."""
    tmp = tempfile.mkdtemp()
    env_path = Path(tmp) / ".env"
    env_path.write_text("\n".join(env_lines) + "\n")
    base_path = Path(tmp) / "identity_baseline.json"
    base_path.write_text(json.dumps(baseline, ensure_ascii=False))
    spec = importlib.util.spec_from_file_location("identity_monitor", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.ENV = str(env_path)
    mod.BASE = str(base_path)
    mod.STATE = str(Path(tmp) / "state.json")
    return mod


def api_result(**kwargs):
    """Геттеры возвращают эталонные значения."""
    data = {
        "getMe": {"username": "test_bot", "first_name": "ПУХЛЯШ"},
        "getWebhookInfo": {"url": ""},
        "getMyName": {"name": "ПУХЛЯШ"},
        "getMyDescription": {"description": "d"},
    }
    resp = {m: {"result": v} for m, v in data.items()}

    def _call(tok, method):
        return resp[method]
    return _call


def run_main(mod, state, probe=(True, False, ""), dm_returns=True):
    """Прогон main() с типовыми моками; возвращает (dm_mock, states_list)."""
    states = [dict(state)]
    with mock.patch.object(mod, "call", side_effect=api_result()), \
         mock.patch.object(mod, "probe_delivery", return_value=probe), \
         mock.patch.object(mod, "load_state", side_effect=lambda: dict(states[-1])), \
         mock.patch.object(mod, "save_state", side_effect=lambda s: states.append(s)), \
         mock.patch.object(mod, "clear_state") as cs, \
         mock.patch.object(mod, "dm_owner", return_value=dm_returns) as dm:
        mod.main()
    return dm, states, cs


def test_healthy_bot_identity_ok():
    mod = load_module(ENV_OK, BASELINE)
    dm, states, cs = run_main(mod, {})
    dm.assert_not_called()
    cs.assert_called_once()
    assert states[-1].get("probe_fail_streak", 0) == 0


def test_probe_transient_below_threshold_no_alert():
    """Сеть лежит 1-2 раза подряд — алерта нет, streak копится."""
    mod = load_module(ENV_OK, BASELINE)
    dm, states, _ = run_main(mod, {}, probe=(False, True, "URLError"))
    dm.assert_not_called()
    assert states[-1]["probe_fail_streak"] == 1
    assert not states[-1].get("probe_alerted")


def test_probe_persistent_403_alerts_immediately():
    """403 Forbidden (бот не может писать в чат) — алерт сразу, без streak."""
    mod = load_module(ENV_OK, BASELINE)
    dm, states, _ = run_main(mod, {}, probe=(False, False, "HTTP 403 Forbidden"))
    assert dm.called
    text = dm.call_args[0][1]
    assert "зонд доставки не проходит" in text
    assert "403" in text
    assert states[-1].get("probe_alerted") is True


def test_probe_streak_reaches_threshold_then_alerts():
    """3 transient-неудачи подряд → алерт на третьей."""
    mod = load_module(ENV_OK, BASELINE)
    dm, states, _ = run_main(mod, {}, probe=(False, True, "URLError"))
    assert not dm.called                      # streak 1 — тихо
    dm, states, _ = run_main(mod, states[-1], probe=(False, True, "URLError"))
    assert not dm.called                      # streak 2 — тихо
    dm, states, _ = run_main(mod, states[-1], probe=(False, True, "URLError"))
    assert dm.called                          # streak 3 = порог → алерт
    assert states[-1].get("probe_alerted") is True


def test_recovery_resets_streak_and_no_alert():
    """После алерта зонд восстановился → recovery-DM, state чист, streak 0."""
    mod = load_module(ENV_OK, BASELINE)
    state = {"alerted": True, "probe_alerted": True, "probe_fail_streak": 2}
    dm, states, cs = run_main(mod, state, probe=(True, False, ""))
    dm.assert_called_once()
    assert "восстановлена" in dm.call_args[0][1]
    cs.assert_called_once()


def test_recovery_probe_only_alert():
    """Был только probe-алерт (без identity) → recovery тоже приходит."""
    mod = load_module(ENV_OK, BASELINE)
    state = {"probe_alerted": True, "probe_fail_streak": 3}
    dm, _, cs = run_main(mod, state, probe=(True, False, ""))
    dm.assert_called_once()
    cs.assert_called_once()


def test_dm_owner_prefers_alert_bot_token():
    """ALERT_BOT_TOKEN задан → алерт идёт через него, не через основной токен."""
    mod = load_module(ENV_OK + ["ALERT_BOT_TOKEN=alt"], BASELINE)
    used = []
    with mock.patch.object(mod, "post") as mp:
        mp.side_effect = lambda t, method, payload: (used.append(t), {"ok": True})[1]
        assert mod.dm_owner("main_tok", "text") is True
    assert used == ["alt"], "алерт должен идти через ALERT_BOT_TOKEN"


def test_dm_owner_falls_back_to_main_token():
    """ALERT_BOT_TOKEN мёртв → фолбэк на основной токен."""
    mod = load_module(ENV_OK + ["ALERT_BOT_TOKEN=alt"], BASELINE)
    used = []
    with mock.patch.object(mod, "post") as mp:
        def side(t, method, payload):
            used.append(t)
            if t == "alt":
                raise urllib.error.HTTPError("u", 401, "Unauthorized", {}, None)
            return {"ok": True}
        mp.side_effect = side
        assert mod.dm_owner("main_tok", "text") is True
    assert used == ["alt", "main_tok"]


def test_no_admin_chat_probe_skipped():
    """Нет TELEGRAM_ADMIN_CHAT_ID → зонд пропущен, identity OK без алертов."""
    mod = load_module(["TELEGRAM_BOT_TOKEN=x"], BASELINE)
    with mock.patch.object(mod, "call", side_effect=api_result()), \
         mock.patch.object(mod, "probe_delivery") as pd, \
         mock.patch.object(mod, "load_state", return_value={}), \
         mock.patch.object(mod, "clear_state"), \
         mock.patch.object(mod, "dm_owner") as dm:
        mod.main()
    pd.assert_not_called()
    dm.assert_not_called()


def test_identity_drift_still_alerts():
    """Регресс v1: подмена username по-прежнему алертит."""
    mod = load_module(ENV_OK, BASELINE)
    with mock.patch.object(mod, "call") as mcall, \
         mock.patch.object(mod, "probe_delivery", return_value=(True, False, "")), \
         mock.patch.object(mod, "load_state", return_value={}), \
         mock.patch.object(mod, "save_state"), \
         mock.patch.object(mod, "dm_owner", return_value=True) as dm:
        mcall.side_effect = lambda tok, m: (
            {"result": {"username": "evil_bot", "first_name": "ПУХЛЯШ"}}
            if m == "getMe" else {"result": {"url": ""}} if m == "getWebhookInfo"
            else {"result": {"name": "ПУХЛЯШ"}} if m == "getMyName"
            else {"result": {"description": "d"}})
        mod.main()
    text = dm.call_args[0][1]
    assert "username='evil_bot'" in text


# — внутренности зонда: реальный urllib, URL-перехват через socket — #

def test_probe_delivery_silent_and_deletes():
    """Зонд: sendMessage с disable_notification → deleteMessage; transient для сети."""
    mod = load_module(ENV_OK, BASELINE)
    seen = []

    class FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self):
            return json.dumps({"ok": True, "result": {"message_id": 42}}).encode()

    def fake_urlopen(req, timeout=15):
        url = req.full_url
        seen.append((url.split("/bot")[1].split("/")[1], json.loads(req.data.decode())))
        return FakeResp()

    with mock.patch.object(urllib.request, "urlopen", side_effect=fake_urlopen):
        ok, transient, detail = mod.probe_delivery("tok", "123")
    assert ok and not transient and detail == ""
    methods = [m for m, _ in seen]
    assert methods == ["sendMessage", "deleteMessage"]
    assert seen[0][1]["disable_notification"] is True
    assert seen[1][1]["message_id"] == 42


def test_probe_delivery_classifies_403_persistent():
    mod = load_module(ENV_OK, BASELINE)

    def fake_urlopen(req, timeout=15):
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, b"{}")

    with mock.patch.object(urllib.request, "urlopen", side_effect=fake_urlopen):
        ok, transient, detail = mod.probe_delivery("tok", "123")
    assert not ok and not transient and "403" in detail


def test_probe_delivery_classifies_500_transient():
    mod = load_module(ENV_OK, BASELINE)

    def fake_urlopen(req, timeout=15):
        raise urllib.error.HTTPError(req.full_url, 502, "Bad Gateway", {}, b"{}")

    with mock.patch.object(urllib.request, "urlopen", side_effect=fake_urlopen):
        ok, transient, detail = mod.probe_delivery("tok", "123")
    assert not ok and transient
