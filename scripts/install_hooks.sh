#!/bin/sh
# Установка pre-commit gitleaks-хука для diet_platform.
#
# Два режима:
#  1) Обычная Linux-ФС (exec-биты работают):
#       git config core.hooksPath githooks
#  2) Termux/sdcard (FUSE: exec-биты не сохраняются — хук игнорируется git'ом):
#       shim-копия хука в $HOME (настоящий exec-бит) + core.hooksPath на неё.
#
# Запуск:  sh scripts/install_hooks.sh
# Проверка: git config core.hooksPath && sh -n "$(git config core.hooksPath)/pre-commit"

set -eu
REPO="$(git rev-parse --show-toplevel)"
HOOK_SRC="$REPO/githooks/pre-commit"

if [ ! -f "$HOOK_SRC" ]; then
    echo "ERROR: $HOOK_SRC не найден" >&2
    exit 1
fi

# FUSE-детект: chmod +x «проходит», но exec-бит не читается назад.
chmod +x "$HOOK_SRC" 2>/dev/null || true
if [ -x "$HOOK_SRC" ]; then
    echo "[1/3] Exec-биты работают -> режим 1 (core.hooksPath=githooks)"
    git config core.hooksPath githooks
else
    echo "[1/3] FUSE-ФС (exec-бит не сохраняется) -> режим 2 (shim в \$HOME)"
    SHIM_DIR="$HOME/.local/share/diet_platform_githooks"
    mkdir -p "$SHIM_DIR"
    cp "$HOOK_SRC" "$SHIM_DIR/pre-commit"
    chmod 700 "$SHIM_DIR/pre-commit"
    # Копия самонастраивается: HOOK_SRC меняется на shim-путь внутри копии.
    git config core.hooksPath "$SHIM_DIR"
    echo "      shim: $SHIM_DIR/pre-commit"
    echo "      ВНИМАНИЕ: после правки githooks/pre-commit перезапусти install_hooks.sh."
fi

echo "[2/3] Проверка синтаксиса хука:"
sh -n "$(git config core.hooksPath)/pre-commit" && echo "      OK"

echo "[3/3] Проверка gitleaks:"
if command -v gitleaks >/dev/null 2>&1 || [ -x "$HOME/.local/bin/gitleaks" ]; then
    echo "      найден — хук будет блокировать коммиты с секретами"
else
    echo "      НЕ найден — хук будет работать в fail-open (пропуск скана)."
    echo "      Установи: https://github.com/gitleaks/gitleaks/releases"
fi

echo "Готово. Тест: git commit с файлом 'ghp_AAA...' должен быть ЗАБЛОКИРОВАН."
