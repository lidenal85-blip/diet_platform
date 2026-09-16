#!/usr/bin/env bash
#
# Wizard: R1 — ротация TELEGRAM_BOT_TOKEN продового бота «Пухляш»
# По TASK_SECRET_ROTATION_2026-09-16.md §2 R1. Запускать в Termux из корня репо.
# Эфемерный скрипт: после успешного прогона удалить.
#
# Владелец делает только шаги в Telegram (@BotFather); всё остальное — на whimco
# через SSH-алиас. Токен передаётся только через stdin (не в argv/историю).

set -euo pipefail

# ──────────────────────────────────────────────────────────────────────────
# Wizard library: delightful, consistent UX, identical across every wizard.
# ──────────────────────────────────────────────────────────────────────────

if [[ -t 1 ]] && command -v tput >/dev/null 2>&1 && [[ "$(tput colors 2>/dev/null || echo 0)" -ge 8 ]]; then
  BOLD=$(tput bold); DIM=$(tput dim); RESET=$(tput sgr0)
  BLUE=$(tput setaf 4); GREEN=$(tput setaf 2); YELLOW=$(tput setaf 3); RED=$(tput setaf 1)
else
  BOLD=""; DIM=""; RESET=""; BLUE=""; GREEN=""; YELLOW=""; RED=""
fi

TOTAL_STAGES=0

_STAGE_INDEX=0
ENV_FILE="${ENV_FILE:-.env}"
WRITTEN_ENV=()
WRITTEN_SECRET=()
SKIPPED=()

_clear() {
  [[ -t 1 ]] || return 0
  if command -v tput >/dev/null 2>&1; then tput clear; else printf '\033[2J\033[3J\033[H'; fi
}

banner() {
  _clear
  printf '\n%s%s  %s%s\n' "$BOLD" "$BLUE" "$1" "$RESET"
  printf '%s  %s stages%s\n\n' "$DIM" "$TOTAL_STAGES" "$RESET"
  printf '%s  You drive the browser; this wizard tells you exactly what to do and\n' "$DIM"
  printf '  captures the values you copy back. Stop any time with Ctrl-C and re-run\n'
  printf '  later, since it remembers values already saved.%s\n' "$RESET"
  pause "Ready to start?"
}

stage() {
  _clear
  _STAGE_INDEX=$((_STAGE_INDEX + 1))
  printf '\n%s%s▸ Stage %s/%s · %s%s\n' \
    "$BOLD" "$BLUE" "$_STAGE_INDEX" "$TOTAL_STAGES" "$1" "$RESET"
}

say()  { printf '  %s\n' "$1"; }
step() { printf '  %s•%s %s\n' "$BLUE" "$RESET" "$1"; }
note() { printf '  %s%s%s\n' "$DIM" "$1" "$RESET"; }
warn() { printf '  %s⚠ %s%s\n' "$YELLOW" "$1" "$RESET"; }

open_url() {
  local url="$1"
  printf '  %s↗ opening%s %s\n' "$GREEN" "$RESET" "$url"
  { if   command -v wslview     >/dev/null 2>&1; then wslview "$url"
    elif command -v explorer.exe >/dev/null 2>&1; then explorer.exe "$url"
    elif command -v xdg-open    >/dev/null 2>&1; then xdg-open "$url"
    elif command -v open        >/dev/null 2>&1; then open "$url"
    else warn "couldn't open a browser; visit it manually: $url"; fi
  } >/dev/null 2>&1 || warn "couldn't open a browser, so visit it manually: $url"
}

pause() {
  printf '  %s%s%s ' "$DIM" "${1:-Press Enter to continue}" "$RESET"
  read -r _ || true
}

confirm() {
  local reply=""
  printf '  %s? %s [y/N] ' "$YELLOW" "$1"
  read -r reply || true
  [[ "$reply" =~ ^[Yy] ]]
}

_existing() {
  [[ -f "$ENV_FILE" ]] || return 1
  local line; line=$(grep -E "^${1}=" "$ENV_FILE" | tail -n1) || return 1
  printf '%s' "${line#*=}"
}

ask() {
  local key="$1" prompt="$2" current input
  current=$(_existing "$key" || true)
  if [[ -n "$current" ]]; then
    printf '  %s%s%s %s[Enter keeps current]%s ' "$BOLD" "$prompt" "$RESET" "$DIM" "$RESET"
  else
    printf '  %s%s%s ' "$BOLD" "$prompt" "$RESET"
  fi
  read -r input || true
  [[ -z "$input" && -n "$current" ]] && input="$current"
  printf -v "$key" '%s' "$input"
}

ask_secret() {
  local key="$1" prompt="$2" current input
  current=$(_existing "$key" || true)
  if [[ -n "$current" ]]; then
    printf '  %s%s%s %s[Enter keeps current]%s ' "$BOLD" "$prompt" "$RESET" "$DIM" "$RESET"
  else
    printf '  %s%s%s ' "$BOLD" "$prompt" "$RESET"
  fi
  read -rs input || true
  printf '\n'
  [[ -z "$input" && -n "$current" ]] && input="$current"
  printf -v "$key" '%s' "$input"
}

write_env() {
  local key="$1" value="$2" tmp
  touch "$ENV_FILE"
  tmp=$(mktemp)
  grep -vE "^${key}=" "$ENV_FILE" > "$tmp" || true
  printf '%s=%s\n' "$key" "$value" >> "$tmp"
  mv "$tmp" "$ENV_FILE"
  WRITTEN_ENV+=("$key")
  printf '  %s✓ wrote%s %s → %s\n' "$GREEN" "$RESET" "$key" "$ENV_FILE"
}

set_secret() {
  local name="$1" value="$2"
  if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
    if printf '%s' "$value" | gh secret set "$name" >/dev/null 2>&1; then
      WRITTEN_SECRET+=("$name")
      printf '  %s✓ set%s GitHub secret %s\n' "$GREEN" "$RESET" "$name"
      return
    fi
  fi
  SKIPPED+=("GitHub secret $name (set it manually: gh secret set $name)")
  warn "skipped GitHub secret $name: gh not ready; set it later"
}

set_var() {
  local name="$1" value="$2"
  if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
    if gh variable set "$name" --body "$value" >/dev/null 2>&1; then
      printf '  %s✓ set%s GitHub variable %s\n' "$GREEN" "$RESET" "$name"
      return
    fi
  fi
  SKIPPED+=("GitHub variable $name")
  warn "skipped GitHub variable $name, gh not ready; set it later"
}

finish() {
  _clear
  printf '\n%s%s  ✓ Setup complete%s\n' "$BOLD" "$GREEN" "$RESET"
  (( ${#WRITTEN_ENV[@]} ))    && note "wrote ${#WRITTEN_ENV[@]} value(s) to $ENV_FILE: ${WRITTEN_ENV[*]}"
  (( ${#WRITTEN_SECRET[@]} )) && note "set ${#WRITTEN_SECRET[@]} GitHub secret(s): ${WRITTEN_SECRET[*]}"
  if (( ${#SKIPPED[@]} )); then
    printf '\n'; warn "still to do by hand:"
    for s in "${SKIPPED[@]}"; do note "  - $s"; done
  fi
  printf '\n'
}

# ──────────────────────────────────────────────────────────────────────────
# STAGES
# ──────────────────────────────────────────────────────────────────────────

TOTAL_STAGES=6

SSH="ssh -o ControlMaster=no -o ControlPath=none -F $HOME/.ssh/config whimco"

banner "Ротация TELEGRAM_BOT_TOKEN · бот «Пухляш» (R1)"

# ── Stage 1: префлайт — сервер жив, старый токен жив, health ok ───────────
stage "Префлайт сервера"

step "Ставлю на сервер два безопасных помощника (без секретов)."
$SSH 'cat > /tmp/dp_getme.py && chmod 600 /tmp/dp_getme.py' <<'PYEOF'
import sys, json, urllib.request, urllib.error
tok = sys.stdin.read().strip()
try:
    r = json.load(urllib.request.urlopen("https://api.telegram.org/bot" + tok + "/getMe", timeout=15))
    u = r["result"]
    print("OK @" + u["username"])
except urllib.error.HTTPError as e:
    print("HTTP " + str(e.code))
except Exception as e:
    print("ERR " + str(e))
PYEOF

$SSH 'cat > /tmp/dp_getme_env.py && chmod 600 /tmp/dp_getme_env.py' <<'PYEOF'
import sys, json, urllib.request, urllib.error
tok = None
for ln in open("/opt/diet_platform/.env"):
    if ln.startswith("TELEGRAM_BOT_TOKEN="):
        tok = ln.split("=", 1)[1].strip()
if not tok:
    print("NO_TOKEN"); sys.exit(0)
try:
    r = json.load(urllib.request.urlopen("https://api.telegram.org/bot" + tok + "/getMe", timeout=15))
    u = r["result"]
    print("OK @" + u["username"])
except urllib.error.HTTPError as e:
    print("HTTP " + str(e.code))
except Exception as e:
    print("ERR " + str(e))
PYEOF

say "Проверяю состояние сервера и текущего (утёкшего) токена…"
STATUS=$($SSH 'systemctl is-active diet-platform' || true)
OLD_PID=$($SSH 'systemctl show -p MainPID --value diet-platform' || true)
HEALTH=$($SSH 'curl -s -m 5 http://127.0.0.1:8150/health' || true)
OLD_RES=$($SSH 'python3 /tmp/dp_getme_env.py' </dev/null || true)

say "Сервис:            $STATUS (PID $OLD_PID)"
say "Health:            $HEALTH"
say "Старый токен:      $OLD_RES"

case "$STATUS" in
  active) : ;;
  *) warn "Сервис не active — ротация всё равно возможна, но проверь сервер."; confirm "Продолжить?";;
esac

case "$OLD_RES" in
  OK\ @*) BOT_USERNAME="${OLD_RES#OK @}" ;;
  HTTP\ 401)
    warn "Старый токен уже НЕ работает (401)."
    warn "Это значит: либо его уже ревокнули, либо бот уже перехвачен."
    confirm "Продолжить установку нового токена?";;
  *)
    warn "Не удалось проверить старый токен ($OLD_RES) — сеть/Telegram недоступны с сервера?"
    confirm "Продолжить?";;
esac
pause "Префлайт готов. Enter — к смене токена."

# ── Stage 2: BotFather — revoke + новый токен ─────────────────────────────
stage "BotFather: Revoke и новый токен"

step "Открой Telegram → @BotFather (проверь, что это настоящий @BotFather с галочкой)."
step "Команда: /mybots → выбери бота «Пухляш» → API Token → Revoke current token."
step "Скопируй НОВЫЙ токен (формат 123456789:ABCdef…). Он показывается один раз!"

NEW_BOT_TOKEN=""
for _try in 1 2 3; do
  ask_secret NEW_BOT_TOKEN "Вставь НОВЫЙ токен (скрытый ввод):"
  if [[ "$NEW_BOT_TOKEN" =~ ^[0-9]{8,12}:[A-Za-z0-9_-]{30,}$ ]]; then
    break
  fi
  warn "Не похоже на Telegram-токен. Формат: цифры : букво-цифры (пример 123456789:AAH…)."
  NEW_BOT_TOKEN=""
done
if ! [[ "$NEW_BOT_TOKEN" =~ ^[0-9]{8,12}:[A-Za-z0-9_-]{30,}$ ]]; then
  warn "Токен так и не распознан — выхожу. НИЧЕГО не изменено."
  exit 1
fi

say "Проверяю новый токен живым запросом getMe с сервера (токен уходит только в stdin)…"
NEW_RES=$(printf '%s' "$NEW_BOT_TOKEN" | $SSH 'python3 /tmp/dp_getme.py' || true)
say "Новый токен:       $NEW_RES"

case "$NEW_RES" in
  OK\ @*) : ;;
  HTTP\ 401) warn "Telegram ответил 401 — токен неверный. НИЧЕГО не изменено."; exit 1;;
  *) warn "Не удалось проверить токен ($NEW_RES) — прерываю, НИЧЕГО не изменено."; exit 1;;
esac

NEW_USERNAME="${NEW_RES#OK @}"
if [[ -n "${BOT_USERNAME:-}" && "$NEW_USERNAME" != "$BOT_USERNAME" ]]; then
  warn "Имя бота изменилось: было @$BOT_USERNAME, стало @$NEW_USERNAME."
  warn "Так не должно быть — возможно, вставлен токен ДРУГОГО бота!"
  confirm "Всё равно продолжить?"; else :; fi
pause "Токен проверен и жив. Enter — обновить прод."

# ── Stage 3: обновление .env на whimco ────────────────────────────────────
stage "Обновление прода (.env на whimco)"

$SSH 'cat > /tmp/dp_settoken.py && chmod 600 /tmp/dp_settoken.py' <<'PYEOF'
import sys, hashlib, shutil, os, datetime
tok = sys.stdin.read().strip()
p = "/opt/diet_platform/.env"
stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
bak = p + ".bak-rot-" + stamp
shutil.copy2(p, bak); os.chmod(bak, 0o600)
old = None
lines = open(p).read().splitlines()
out = []; done = False
for ln in lines:
    if ln.startswith("TELEGRAM_BOT_TOKEN="):
        old = ln.split("=", 1)[1].strip()
        out.append("TELEGRAM_BOT_TOKEN=" + tok); done = True
    else:
        out.append(ln)
if not done:
    out.append("TELEGRAM_BOT_TOKEN=" + tok)
open(p, "w").write("\n".join(out) + "\n"); os.chmod(p, 0o600)
open("/tmp/.dp_old_token", "w").write(old + "\n"); os.chmod("/tmp/.dp_old_token", 0o600)
print("BACKUP " + bak)
print("TOKEN md5:" + hashlib.md5(tok.encode()).hexdigest()[:10] + " len=" + str(len(tok)) + " replaced=" + str(done))
PYEOF

if ! confirm "Заменить TELEGRAM_BOT_TOKEN в /opt/diet_platform/.env (с бэкапом)?"; then
  warn "Отменено. НИЧЕГО не изменено."; exit 1
fi
SET_RES=$(printf '%s' "$NEW_BOT_TOKEN" | $SSH 'python3 /tmp/dp_settoken.py' || true)
say "$SET_RES"
NEW_BOT_TOKEN=""
case "$SET_RES" in
  BACKUP\ *) : ;;
  *) warn "Замена не подтверждена — проверь сервер вручную."; exit 1;;
esac
pause "Прод обновлён. Enter — рестарт сервиса (может занять ~2 минуты)."

# ── Stage 4: рестарт ──────────────────────────────────────────────────────
stage "Рестарт diet-platform.service"

say "Известная хрупкость: хендлеры игнорируют SIGTERM, поэтому рестарт идёт"
say "через полный TimeoutStopSec и SIGKILL — ssh-вызов может «висеть» ~90 сек."
if ! confirm "Рестартовать сейчас? (короткий даунтайм бота)"; then
  warn "Отменено на этом шаге: токен в .env уже новый, применится при следующем рестарте."
  exit 0
fi
set +e
timeout 170 $SSH 'systemctl restart diet-platform'
RC=$?
set -e
if [[ "$RC" == "124" ]]; then
  note "ssh-таймаут при restart — ожидаемо (SIGTERM→SIGKILL). Проверяю состояние…"
else
  note "restart вернул код $RC."
fi
sleep 3
NEW_PID=$($SSH 'systemctl show -p MainPID --value diet-platform' || true)
IS_ACTIVE=$($SSH 'systemctl is-active diet-platform' || true)
say "Сервис:            $IS_ACTIVE (PID $NEW_PID, был $OLD_PID)"
if [[ "$IS_ACTIVE" != "active" ]]; then
  warn "Сервис не active! Смотри: journalctl -u diet-platform -n 50"
  exit 1
fi
if [[ -n "${OLD_PID:-}" && "$NEW_PID" == "$OLD_PID" ]]; then
  warn "PID не изменился ($NEW_PID) — старый процесс мог не умереть (зомби-хрупкость)."
  warn "Проверь через минуту; при зависании: systemctl kill -s SIGKILL diet-platform"
fi
pause "Рестарт выполнен. Enter — финальная верификация."

# ── Stage 5: верификация ──────────────────────────────────────────────────
stage "Верификация"

say "Лог старта (Traceback / 401 / startup):"
$SSH 'journalctl -u diet-platform --since "4 minutes ago" --no-pager | grep -c Traceback || true' | { read -r N; say "  Traceback: $N"; }
$SSH 'journalctl -u diet-platform --since "4 minutes ago" --no-pager | grep -ciE "40[13]" || true' | { read -r N; say "  401/403 в логе: $N"; }
$SSH 'journalctl -u diet-platform --since "4 minutes ago" --no-pager | grep -m1 "Application startup complete" || true'
say "Health: $($SSH 'curl -s -m 5 http://127.0.0.1:8150/health' || true)"
say "Новый токен в проде: $($SSH 'python3 /tmp/dp_getme_env.py' </dev/null || true)"
say "Старый (утёкший) токен должен быть мёртв:"
say "  $($SSH 'cat /tmp/.dp_old_token' | $SSH 'python3 /tmp/dp_getme.py' || true)   ← ожидаем HTTP 401"

step "Ручная проверка (6.4): напиши боту «Пухляш» в Telegram: /start — бот должен ответить."
pause "Ответил? Enter — финал."

# ── Stage 6: очистка и итог ───────────────────────────────────────────────
stage "Очистка и итог"

$SSH 'rm -f /tmp/dp_getme.py /tmp/dp_getme_env.py /tmp/dp_settoken.py; shred -u /tmp/.dp_old_token 2>/dev/null || rm -f /tmp/.dp_old_token; echo CLEANED'
say "Помощники и копия старого токена на сервере удалены."
say ""
say "ИТОГ R1:"
say "  ✓ Новый токен в /opt/diet_platform/.env (бэкап рядом, chmod 600)"
say "  ✓ Сервис перезапущен на новом токене"
say "  ✗ Локальный .env на телефоне всё ещё содержит СТАРЫЙ токен — для дев-запусков"
say "  → Обнови пункт R1 в TASK_SECRET_ROTATION_2026-09-16.md"
say "  → Дальше по задаче: R2 (relay), R3 (9 ключей Gemini), R4 (PAT), R5/R6 (git)"
say "  → Этот скрипт эфемерный: rm scripts/rotate_bot_token_wizard.sh"
pause "Готово. Enter — выход."

finish
