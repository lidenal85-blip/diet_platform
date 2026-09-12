#!/usr/bin/env bash
# ============================================================
# dump_project.sh — собирает проект в один Markdown-дамп
# Использование:
#   bash dump_project.sh [путь_к_проекту] [путь_к_выходному_md]
# ============================================================
set -u

PROJECT_DIR="${1:-/storage/emulated/0/PROJECTS/workstation/freebuff/projects_17/diet_platform}"
OUT="${2:-$PROJECT_DIR/PROJECT_DUMP.md}"
MAX_SIZE=150000   # файлы крупнее (байт) идут только в список, без содержимого

# текстовые расширения, которые попадают в дамп
EXTS='md|txt|html|htm|css|scss|js|mjs|cjs|ts|tsx|jsx|json|py|sh|bash|yml|yaml|xml|svg|toml|ini|cfg|conf|log|csv|sql|kt|java|dart|php|rb|go|rs|ipynb'
# файлы без расширения / dotfiles, которые тоже считаем текстом
NAMES='Makefile|Dockerfile|LICENSE|Procfile|\.gitignore|\.gitattributes|\.editorconfig|\.env|\.env\..*'
# директории-мусор, которые пропускаем
EXCLUDE='/(node_modules|\.git|__pycache__|\.venv|venv|dist|build|\.idea|\.vscode|\.cache|__MACOSX|\.dart_tool)/'

TMP_SKIPPED=$(mktemp)
trap 'rm -f "$TMP_SKIPPED"' EXIT

rel(){ echo "${1#"$PROJECT_DIR"/}"; }

# ---------- заголовок + дерево файлов ----------
{
  echo "# Дамп проекта: $(basename "$PROJECT_DIR")"
  echo
  echo "> Собран: $(date '+%Y-%m-%d %H:%M:%S')"
  echo
  echo "## Дерево файлов"
  echo '````text'
} > "$OUT"

find "$PROJECT_DIR" -type f 2>/dev/null | grep -vE "$EXCLUDE" | sort \
  | while IFS= read -r f; do printf '%s\n' "$(rel "$f")"; done >> "$OUT"

echo '````' >> "$OUT"

# ---------- содержимое текстовых файлов ----------
COUNT=0
while IFS= read -r f; do
  [ -e "$f" ] || continue
  [ "$f" = "$OUT" ] && continue
  r=$(rel "$f")
  base=$(basename "$f")
  ext="${base##*.}"; [ "$ext" = "$base" ] && ext=""
  size=$(wc -c < "$f" 2>/dev/null | tr -d ' ')

  want=0
  echo "$ext"  | grep -qE "^($EXTS)$"  && want=1
  echo "$base" | grep -qE "^($NAMES)$" && want=1

  if [ "$want" = 0 ]; then
    echo "- \`$r\` — медиа/бинарный, $size байт" >> "$TMP_SKIPPED"; continue
  fi
  if [ "$size" -gt "$MAX_SIZE" ]; then
    echo "- \`$r\` — слишком большой, $size байт" >> "$TMP_SKIPPED"; continue
  fi
  if ! grep -qI . "$f" 2>/dev/null; then
    echo "- \`$r\` — бинарный, $size байт" >> "$TMP_SKIPPED"; continue
  fi

  {
    echo; echo "---"; echo
    echo "## Файл: $r"
    echo
    echo "\`$size байт\`"
    echo
    echo '````'
    cat "$f"
    echo
    echo '````'
  } >> "$OUT"
  COUNT=$((COUNT+1))
done < <(find "$PROJECT_DIR" -type f 2>/dev/null | grep -vE "$EXCLUDE" | sort)

# ---------- список пропущенных ----------
{
  echo; echo "---"; echo
  echo "## Пропущенные файлы (медиа/бинарные/крупные)"
  echo
  if [ -s "$TMP_SKIPPED" ]; then cat "$TMP_SKIPPED"; else echo "- нет"; fi
} >> "$OUT"

echo
echo "✅ Готово: $OUT"
echo "   Файлов с содержимым: $COUNT"
echo "   Размер дампа: $(wc -c < "$OUT" | tr -d ' ') байт"