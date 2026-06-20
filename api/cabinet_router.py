"""FastAPI router: веб-кабинет пользователя."""
import secrets
import aiosqlite
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from database import DB_PATH

router = APIRouter(prefix="/diet")

# Токен кабинета храним в памяти {токен: tg_id}
_cabinet_tokens: dict[str, str] = {}


def generate_cabinet_token(tg_id: str) -> str:
    token = secrets.token_urlsafe(20)
    _cabinet_tokens[token] = tg_id
    return token


@router.get("/cabinet", response_class=HTMLResponse)
async def cabinet_page(request: Request, token: str = ""):
    tg_id = _cabinet_tokens.get(token)
    profile = {}
    if tg_id:
        async with aiosqlite.connect(DB_PATH, timeout=30) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM user_profiles WHERE tg_id=?", (tg_id,)) as c:
                row = await c.fetchone()
            if row:
                profile = dict(row)

    html = _render_cabinet(profile, token)
    return HTMLResponse(html)


@router.post("/cabinet/save")
async def cabinet_save(request: Request):
    data = await request.json()
    token = data.get("token", "")
    tg_id = _cabinet_tokens.get(token)
    if not tg_id:
        raise HTTPException(403, "Invalid token")
    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        await db.execute(
            "INSERT INTO user_profiles (tg_id,cook_level,experiment_level,budget_level,"
            "max_cook_time,excluded_foods,recipe_day_time,recipe_day_enabled) "
            "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(tg_id) DO UPDATE SET "
            "cook_level=excluded.cook_level, experiment_level=excluded.experiment_level,"
            "budget_level=excluded.budget_level, max_cook_time=excluded.max_cook_time,"
            "excluded_foods=excluded.excluded_foods, recipe_day_time=excluded.recipe_day_time,"
            "recipe_day_enabled=excluded.recipe_day_enabled",
            (tg_id,
             data.get("cook_level", "beginner"),
             data.get("experiment_level", "sometimes"),
             data.get("budget_level", "normal"),
             int(data.get("max_cook_time", 30)),
             data.get("excluded_foods", ""),
             data.get("recipe_day_time") or None,
             1 if data.get("recipe_day_enabled") else 0)
        )
        await db.commit()
    return JSONResponse({"ok": True})


def _render_cabinet(profile: dict, token: str) -> str:
    cl = profile.get("cook_level", "beginner")
    el = profile.get("experiment_level", "sometimes")
    bl = profile.get("budget_level", "normal")
    ct = profile.get("max_cook_time", 30)
    excl = profile.get("excluded_foods", "") or ""
    rdt = profile.get("recipe_day_time", "") or ""
    rde = bool(profile.get("recipe_day_enabled", 0))

    def sel(val, cur): return 'selected' if val == cur else ''
    def chk(v): return 'checked' if v else ''

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Пухляш — Мой кабинет</title>
<style>
  :root {{
    --bg: #1a1a2e; --card: #16213e; --accent: #e94560;
    --text: #eee; --sub: #aaa; --border: #2a2a4a;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: var(--bg); color: var(--text); font-family: -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; min-height: 100vh; padding: 20px; }}
  .card {{ background: var(--card); border-radius: 16px; padding: 24px; max-width: 480px; margin: 0 auto; }}
  h1 {{ font-size: 1.4rem; margin-bottom: 4px; }}
  .sub {{ color: var(--sub); font-size: .85rem; margin-bottom: 24px; }}
  .section {{ margin-bottom: 20px; }}
  label {{ display: block; color: var(--sub); font-size: .8rem; margin-bottom: 8px; text-transform: uppercase; letter-spacing: .05em; }}
  select, input[type=text], input[type=time] {{
    width: 100%; background: var(--bg); border: 1px solid var(--border);
    border-radius: 10px; padding: 12px 14px; color: var(--text); font-size: 1rem;
    outline: none;
  }}
  select:focus, input:focus {{ border-color: var(--accent); }}
  .toggle-row {{ display: flex; align-items: center; gap: 12px; }}
  .toggle {{ position: relative; width: 48px; height: 26px; }}
  .toggle input {{ opacity: 0; width: 0; height: 0; }}
  .slider {{ position: absolute; inset: 0; background: #333; border-radius: 26px; cursor: pointer; transition: .3s; }}
  .slider:before {{ content: ''; position: absolute; width: 20px; height: 20px; left: 3px; bottom: 3px; background: white; border-radius: 50%; transition: .3s; }}
  input:checked + .slider {{ background: var(--accent); }}
  input:checked + .slider:before {{ transform: translateX(22px); }}
  .btn {{ width: 100%; background: var(--accent); color: white; border: none; border-radius: 12px; padding: 14px; font-size: 1rem; font-weight: 600; cursor: pointer; margin-top: 8px; transition: opacity .2s; }}
  .btn:hover {{ opacity: .85; }}
  .toast {{ display: none; background: #27ae60; color: white; border-radius: 10px; padding: 12px 16px; text-align: center; margin-top: 12px; }}
  .toast.show {{ display: block; }}
</style>
</head>
<body>
<div class="card">
  <h1>👨‍🍳 Мой кабинет</h1>
  <p class="sub">Настройка рецептов под тебя</p>

  <div class="section">
    <label>🍳 Кулинарный уровень</label>
    <select id="cook_level">
      <option value="beginner" {sel('beginner',cl)}>🥚 Новичок — яичница, пельмени, макароны</option>
      <option value="amateur" {sel('amateur',cl)}>🍳 Любитель — омлет, суп, паста болоньезе</option>
      <option value="cook" {sel('cook',cl)}>👨‍🍳 Готовлю с удовольствием</option>
      <option value="expert" {sel('expert',cl)}>🌟 Эксперт — равиоли, ризотто</option>
    </select>
  </div>

  <div class="section">
    <label>🚀 Желание экспериментировать</label>
    <select id="experiment_level">
      <option value="classic" {sel('classic',el)}>🔒 Только проверенное</option>
      <option value="sometimes" {sel('sometimes',el)}>⚡ Иногда что-то новое</option>
      <option value="explorer" {sel('explorer',el)}>🚀 Люблю пробовать</option>
    </select>
  </div>

  <div class="section">
    <label>💰 Бюджет</label>
    <select id="budget_level">
      <option value="student" {sel('student',bl)}>🎓 Студенческий — без пармезана</option>
      <option value="normal" {sel('normal',bl)}>💰 Обычный</option>
      <option value="free" {sel('free',bl)}>💳 Не считаю</option>
    </select>
  </div>

  <div class="section">
    <label>⏱ Время на готовку</label>
    <select id="max_cook_time">
      <option value="15" {sel('15',str(ct))}>15 минут</option>
      <option value="30" {sel('30',str(ct))}>30 минут</option>
      <option value="60" {sel('60',str(ct))}>Сколько надо</option>
    </select>
  </div>

  <div class="section">
    <label>🚫 Исключения (через запятую)</label>
    <input type="text" id="excluded_foods" value="{excl}" placeholder="грибы, морепродукты...">
  </div>

  <div class="section">
    <label>🍝 Рецепт дня</label>
    <div class="toggle-row" style="margin-bottom:12px">
      <label class="toggle">
        <input type="checkbox" id="recipe_day_enabled" {chk(rde)}>
        <span class="slider"></span>
      </label>
      <span>Отправлять рецепт в телеграм</span>
    </div>
    <input type="time" id="recipe_day_time" value="{rdt}">
  </div>

  <button class="btn" onclick="save()">&#x2705; Сохранить</button>
  <div class="toast" id="toast">✅ Сохранено!</div>
</div>

<script>
async function save() {{
  const data = {{
    token: '{token}',
    cook_level: document.getElementById('cook_level').value,
    experiment_level: document.getElementById('experiment_level').value,
    budget_level: document.getElementById('budget_level').value,
    max_cook_time: parseInt(document.getElementById('max_cook_time').value),
    excluded_foods: document.getElementById('excluded_foods').value,
    recipe_day_time: document.getElementById('recipe_day_time').value || null,
    recipe_day_enabled: document.getElementById('recipe_day_enabled').checked,
  }};
  const r = await fetch('/diet/cabinet/save', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body: JSON.stringify(data)}});
  const j = await r.json();
  if (j.ok) {{
    const t = document.getElementById('toast');
    t.classList.add('show');
    setTimeout(() => t.classList.remove('show'), 3000);
  }}
}}
</script>
</body>
</html>"""