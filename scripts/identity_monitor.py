#!/usr/bin/env python3
"""§4.1 Монитор идентичности бота: алерт при отклонении getMe/getMyName/описания
от эталона или при появлении webhook. Запускается systemd-таймером каждые 5 мин.
Зависимостей нет (stdlib). Алерт: journald всегда + DM владельцу, если в .env
задан TELEGRAM_ADMIN_CHAT_ID (одна попытка на инцидент, дедуп через /run state).

v2 (2026-09-18): зондирующий sendMessage — закрытие слепой зоны getMe.
Урок инцидента 2026-09-18: getMe может отвечать ok:true даже у деактивированного
бота (кэш реестра Telegram). Здоровье бота = реальная доставка сообщения:
беззвучный зонд в чат владельца + немедленное удаление (чат остаётся чистым).
- Transient-ошибки (сеть, таймаут, 429, 5xx) не алертятся сразу: только после
  PROBE_STREAK_ALERT неудач подряд (streak в /run state).
- Стойкие ошибки (400 chat not found, 401, 403 forbidden) — problem сразу.
- После алерта при восстановлении шлётся «✅ восстановлено» (один раз).
- dm_owner: если в .env задан ALERT_BOT_TOKEN — алерты идут через второй бот
  (решение проблемы «алерт через мёртвого бота»), иначе через основной токен.
"""
import json, os, urllib.request, urllib.error

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "identity_baseline.json")
ENV = "/opt/diet_platform/.env"
STATE = "/run/diet_platform_identity_state.json"
PROBE_STREAK_ALERT = 3  # неудачных прогонов подряд (~15 мин при 5-мин таймере)

def read_env_key(key):
    for ln in open(ENV):
        if ln.startswith(key + "="):
            return ln.split("=", 1)[1].strip()
    return ""

def read_token():
    tok = read_env_key("TELEGRAM_BOT_TOKEN")
    if not tok:
        raise SystemExit("TELEGRAM_BOT_TOKEN not found")
    return tok

def call(tok, method):
    with urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/{method}", timeout=15) as r:
        return json.load(r)

def post(tok, method, payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{tok}/{method}", data=data,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)

def probe_delivery(tok, chat):
    """Беззвучный зонд: sendMessage + немедленное удаление (чат остаётся чистым).
    Возвращает (ok, transient, detail)."""
    try:
        r = post(tok, "sendMessage", {"chat_id": chat, "text": "\U0001F3BA probe",
                                      "disable_notification": True})
        mid = (r.get("result") or {}).get("message_id")
        if mid:
            try:
                post(tok, "deleteMessage", {"chat_id": chat, "message_id": mid})
            except Exception:
                pass  # удаление не критично, доставка уже подтверждена
        return True, False, ""
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode()[:150]
        except Exception:
            pass
        # 429/5xx и сеть — transient; 400/401/403 — стойкие проблемы
        return False, (e.code == 429 or e.code >= 500), f"HTTP {e.code} {body}"
    except Exception as e:
        return False, True, f"{type(e).__name__}: {e}"

def dm_owner(tok, text):
    chat = read_env_key("TELEGRAM_ADMIN_CHAT_ID")
    if not chat:
        return False
    alt = read_env_key("ALERT_BOT_TOKEN")  # второй бот для алертов (опция)
    for t in ([alt] if alt else []) + [tok]:
        try:
            post(t, "sendMessage", {"chat_id": chat, "text": text})
            return True
        except Exception:
            continue
    return False

def load_state():
    try:
        return json.load(open(STATE))
    except Exception:
        return {}

def save_state(state):
    json.dump(state, open(STATE, "w"))

def clear_state():
    if os.path.exists(STATE):
        os.remove(STATE)

def main():
    tok = read_token()
    base = json.load(open(BASE))
    state = load_state()
    problems = []
    me = call(tok, "getMe")["result"]
    if me.get("username") != base["username"]:
        problems.append(f"username={me.get('username')!r} (эталон {base['username']!r})")
    if me.get("first_name") != base["first_name"]:
        problems.append(f"first_name={me.get('first_name')!r} (эталон {base['first_name']!r})")
    wh = call(tok, "getWebhookInfo")["result"]
    if wh.get("url"):
        problems.append(f"postoronniy webhook: {wh['url']}")
    name = (call(tok, "getMyName").get("result") or {}).get("name", "")
    if base.get("my_name") and name and name != base["my_name"]:
        problems.append(f"my_name={name!r} (эталон {base['my_name']!r})")
    desc = (call(tok, "getMyDescription").get("result") or {}).get("description", "")
    if base.get("description") and desc and desc != base["description"]:
        problems.append(f"description={desc!r} (эталон {base['description']!r})")

    # — v2: зонд реальной доставки —
    probe_note = ""
    probe_chat = read_env_key("TELEGRAM_ADMIN_CHAT_ID")
    if probe_chat:
        ok, transient, detail = probe_delivery(tok, probe_chat)
        if ok:
            state["probe_fail_streak"] = 0
        else:
            streak = int(state.get("probe_fail_streak", 0)) + 1
            state["probe_fail_streak"] = streak
            if transient and streak < PROBE_STREAK_ALERT:
                probe_note = f"(probe transient {streak}/{PROBE_STREAK_ALERT}: {detail})"
            else:
                problems.append("зонд доставки не проходит: " + detail)
                state["probe_alerted"] = True
    else:
        probe_note = "(probe skipped: TELEGRAM_ADMIN_CHAT_ID не задан)"

    if not problems:
        was_alerted = bool(state.get("alerted") or state.get("probe_alerted"))
        if was_alerted:
            clear_state()
            dm_owner(tok, "✅ diet_platform: идентичность/доставка восстановлена")
            print("identity OK (recovery DM sent)")
        elif state.get("probe_fail_streak"):
            save_state(state)  # помним streak transient-неудач, файл не чистим
            print("identity OK" + ((" " + probe_note) if probe_note else ""))
        else:
            clear_state()
            print("identity OK" + ((" " + probe_note) if probe_note else ""))
        return

    alert = "\U0001F6A8 diet_platform: " + "; ".join(problems)
    if not state.get("alerted") and dm_owner(tok, alert):
        state["alerted"] = True
    if state:
        save_state(state)
    print(alert + ((" " + probe_note) if probe_note else ""))

if __name__ == "__main__":
    main()
