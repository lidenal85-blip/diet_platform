"""Telegram Mini App — Diet Platform."""
import aiosqlite
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from database import DB_PATH

router = APIRouter(prefix="/diet")


@router.get("/app", response_class=HTMLResponse)
async def mini_app(request: Request):
    return HTMLResponse(MINIAPP_HTML)


@router.get("/app/profile")
async def get_profile(tg_id: str = ""):
    if not tg_id:
        return JSONResponse({"exists": False})
    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM user_profiles WHERE tg_id=?", (tg_id,)) as c:
            row = await c.fetchone()
    if not row:
        return JSONResponse({"exists": False})
    d = dict(row)
    d["exists"] = True
    return JSONResponse(d)


@router.post("/app/profile")
async def save_profile(request: Request):
    data = await request.json()
    tg_id = str(data.get("tg_id", ""))
    if not tg_id:
        return JSONResponse({"ok": False, "error": "no tg_id"}, status_code=400)
    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        await db.execute(
            "INSERT INTO user_profiles "
            "(tg_id,cook_level,experiment_level,budget_level,max_cook_time,"
            "excluded_foods,recipe_day_time,recipe_day_enabled,"
            "notify_personal,notify_meals,notify_recipe_day) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(tg_id) DO UPDATE SET "
            "cook_level=excluded.cook_level,experiment_level=excluded.experiment_level,"
            "budget_level=excluded.budget_level,max_cook_time=excluded.max_cook_time,"
            "excluded_foods=excluded.excluded_foods,recipe_day_time=excluded.recipe_day_time,"
            "recipe_day_enabled=excluded.recipe_day_enabled,"
            "notify_personal=excluded.notify_personal,"
            "notify_meals=excluded.notify_meals,"
            "notify_recipe_day=excluded.notify_recipe_day",
            (tg_id,
             data.get("cook_level", "beginner"),
             data.get("experiment_level", "sometimes"),
             data.get("budget_level", "normal"),
             int(data.get("max_cook_time", 30)),
             data.get("excluded_foods", ""),
             data.get("recipe_day_time") or None,
             1 if data.get("recipe_day_enabled") else 0,
             1 if data.get("notify_personal", True) else 0,
             1 if data.get("notify_meals", True) else 0,
             1 if data.get("notify_recipe_day", True) else 0)
        )
        await db.commit()
    return JSONResponse({"ok": True})


MINIAPP_HTML = """\
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>\u041f\u0443\u0445\u043b\u044f\u0448</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
:root{
  --bg:var(--tg-theme-bg-color,#1a1a2e);
  --card:var(--tg-theme-secondary-bg-color,#16213e);
  --text:var(--tg-theme-text-color,#eee);
  --hint:var(--tg-theme-hint-color,#999);
  --accent:var(--tg-theme-button-color,#e94560);
  --btn-txt:var(--tg-theme-button-text-color,#fff);
  --sep:rgba(255,255,255,.07);
}
*{box-sizing:border-box;margin:0;padding:0;-webkit-tap-highlight-color:transparent}
body{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;padding:12px 14px 80px;min-height:100vh}
.hdr{text-align:center;padding:14px 0 18px}
.hdr h1{font-size:1.25rem}
.hdr p{color:var(--hint);font-size:.82rem;margin-top:3px}
.tabs{display:flex;gap:6px;margin-bottom:14px}
.tab{flex:1;padding:9px 4px;border:1px solid var(--sep);border-radius:10px;background:transparent;color:var(--hint);font-size:.82rem;cursor:pointer;transition:.2s;font-weight:500}
.tab.on{background:var(--accent);color:var(--btn-txt);border-color:var(--accent)}
.pg{display:none}.pg.on{display:block}
.card{background:var(--card);border-radius:14px;padding:4px 14px;margin-bottom:10px}
.row{display:flex;align-items:center;justify-content:space-between;padding:13px 0;border-bottom:1px solid var(--sep)}
.row:last-child{border-bottom:none}
.rl{font-size:.95rem}
.rs{font-size:.75rem;color:var(--hint);margin-top:2px}
select{background:transparent;border:none;color:var(--accent);font-size:.92rem;cursor:pointer;-webkit-appearance:none;outline:none;text-align:right;max-width:140px}
input[type=text]{background:transparent;border:none;color:var(--text);font-size:.92rem;outline:none;width:100%;padding:4px 0}
input[type=time]{background:transparent;border:none;color:var(--accent);font-size:.92rem;outline:none;color-scheme:dark}
.tog{position:relative;width:46px;height:26px;flex-shrink:0}
.tog input{opacity:0;width:0;height:0}
.sl{position:absolute;inset:0;background:rgba(255,255,255,.15);border-radius:26px;cursor:pointer;transition:.25s}
.sl:before{content:'';position:absolute;width:20px;height:20px;left:3px;bottom:3px;background:#fff;border-radius:50%;transition:.25s}
input:checked+.sl{background:var(--accent)}
input:checked+.sl:before{transform:translateX(20px)}
.save-bar{position:fixed;bottom:0;left:0;right:0;padding:10px 14px;background:var(--bg);border-top:1px solid var(--sep)}
.save-btn{width:100%;background:var(--accent);color:var(--btn-txt);border:none;border-radius:12px;padding:13px;font-size:1rem;font-weight:600;cursor:pointer;transition:opacity .15s}
.save-btn:active{opacity:.75}
.toast{position:fixed;top:20px;left:50%;transform:translateX(-50%);background:#27ae60;color:#fff;border-radius:10px;padding:10px 22px;font-size:.9rem;opacity:0;transition:opacity .3s;pointer-events:none;z-index:99}
.toast.on{opacity:1}
.lbl{font-size:.72rem;text-transform:uppercase;letter-spacing:.06em;color:var(--hint);padding:14px 0 6px}
</style>
</head>
<body>
<div class="hdr">
  <h1>\U0001f35d \u041f\u0443\u0445\u043b\u044f\u0448</h1>
  <p>\u041d\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0430 \u043f\u043e\u0434 \u0442\u0435\u0431\u044f</p>
</div>

<div class="tabs">
  <button class="tab on" onclick="tab('s',this)">\u041d\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0438</button>
  <button class="tab" onclick="tab('n',this)">\u0423\u0432\u0435\u0434\u043e\u043c\u043b\u0435\u043d\u0438\u044f</button>
</div>

<div id="pg-s" class="pg on">
  <div class="card">
    <div class="lbl">\U0001f373 \u0423\u0440\u043e\u0432\u0435\u043d\u044c \u043a\u0443\u043b\u0438\u043d\u0430\u0440\u0438\u0438</div>
    <div class="row">
      <div><div class="rl">\u041a\u0442\u043e \u044f \u043d\u0430 \u043a\u0443\u0445\u043d\u0435</div>
      <div class="rs">\u0421\u043b\u043e\u0436\u043d\u043e\u0441\u0442\u044c \u0440\u0435\u0446\u0435\u043f\u0442\u043e\u0432</div></div>
      <select id="cook_level">
        <option value="beginner">\U0001f95a \u041d\u043e\u0432\u0438\u0447\u043e\u043a</option>
        <option value="amateur">\U0001f373 \u041b\u044e\u0431\u0438\u0442\u0435\u043b\u044c</option>
        <option value="cook">\U0001f468\u200d\U0001f373 \u0413\u043e\u0442\u043e\u0432\u043b\u044e</option>
        <option value="expert">\U0001f31f \u042d\u043a\u0441\u043f\u0435\u0440\u0442</option>
      </select>
    </div>
    <div class="row">
      <div><div class="rl">\u042d\u043a\u0441\u043f\u0435\u0440\u0438\u043c\u0435\u043d\u0442\u044b</div>
      <div class="rs">\u0416\u0435\u043b\u0430\u043d\u0438\u0435 \u043f\u0440\u043e\u0431\u043e\u0432\u0430\u0442\u044c \u043d\u043e\u0432\u043e\u0435</div></div>
      <select id="experiment_level">
        <option value="classic">\U0001f512 \u041f\u0440\u043e\u0432\u0435\u0440\u0435\u043d\u043d\u043e\u0435</option>
        <option value="sometimes">\u26a1 \u0418\u043d\u043e\u0433\u0434\u0430</option>
        <option value="explorer">\U0001f680 \u041b\u044e\u0431\u043b\u044e \u043f\u0440\u043e\u0431\u043e\u0432\u0430\u0442\u044c</option>
      </select>
    </div>
    <div class="row">
      <div><div class="rl">\u0411\u044e\u0434\u0436\u0435\u0442</div>
      <div class="rs">\u0426\u0435\u043d\u0430 \u0438\u043d\u0433\u0440\u0435\u0434\u0438\u0435\u043d\u0442\u043e\u0432</div></div>
      <select id="budget_level">
        <option value="student">\U0001f393 \u0421\u0442\u0443\u0434\u0435\u043d\u0442</option>
        <option value="normal">\U0001f4b0 \u041e\u0431\u044b\u0447\u043d\u044b\u0439</option>
        <option value="free">\U0001f4b3 \u041d\u0435 \u0441\u0447\u0438\u0442\u0430\u044e</option>
      </select>
    </div>
    <div class="row">
      <div><div class="rl">\u0412\u0440\u0435\u043c\u044f \u043d\u0430 \u0433\u043e\u0442\u043e\u0432\u043a\u0443</div>
      <div class="rs">\u041c\u0430\u043a\u0441\u0438\u043c\u0430\u043b\u044c\u043d\u043e</div></div>
      <select id="max_cook_time">
        <option value="15">15 \u043c\u0438\u043d</option>
        <option value="30">30 \u043c\u0438\u043d</option>
        <option value="60">\u0411\u0435\u0437 \u043e\u0433\u0440\u0430\u043d\u0438\u0447</option>
      </select>
    </div>
  </div>
  <div class="card">
    <div class="lbl">\U0001f6ab \u0418\u0441\u043a\u043b\u044e\u0447\u0435\u043d\u0438\u044f</div>
    <div class="row">
      <input id="excluded" type="text" placeholder="\u0433\u0440\u0438\u0431\u044b, \u043c\u043e\u0440\u0435\u043f\u0440\u043e\u0434\u0443\u043a\u0442\u044b...">
    </div>
  </div>
</div>

<div id="pg-n" class="pg">
  <div class="card">
    <div class="lbl">\U0001f514 \u041f\u0443\u0448 \u0432 \u043b\u0438\u0447\u043a\u0443</div>
    <div class="row">
      <div><div class="rl">\u0412\u0441\u0435 \u0443\u0432\u0435\u0434\u043e\u043c\u043b\u0435\u043d\u0438\u044f</div>
      <div class="rs">\u041c\u0430\u0441\u0442\u0435\u0440-\u0432\u044b\u043a\u043b\u044e\u0447\u0430\u0442\u0435\u043b\u044c</div></div>
      <label class="tog"><input type="checkbox" id="notify_personal" checked><span class="sl"></span></label>
    </div>
    <div class="row">
      <div><div class="rl">\U0001f37d \u041f\u0440\u0438\u0451\u043c \u043f\u0438\u0449\u0438</div>
      <div class="rs">\u0420\u0435\u0446\u0435\u043f\u0442 + \u0443\u043f\u0440\u0430\u0436\u043d\u0435\u043d\u0438\u044f \u043f\u0435\u0440\u0435\u0434 \u0435\u0434\u043e\u0439</div></div>
      <label class="tog"><input type="checkbox" id="notify_meals" checked><span class="sl"></span></label>
    </div>
    <div class="row">
      <div><div class="rl">\U0001f35d \u0420\u0435\u0446\u0435\u043f\u0442 \u0434\u043d\u044f</div>
      <div class="rs">\u0415\u0436\u0435\u0434\u043d\u0435\u0432\u043d\u044b\u0439 \u043e\u0442 \u041f\u0443\u0445\u043b\u044f\u0448\u0430</div></div>
      <label class="tog"><input type="checkbox" id="notify_recipe_day" checked><span class="sl"></span></label>
    </div>
  </div>
  <div class="card">
    <div class="lbl">\u23f0 \u0412\u0440\u0435\u043c\u044f \u0440\u0435\u0446\u0435\u043f\u0442\u0430 \u0434\u043d\u044f</div>
    <div class="row">
      <div class="rl">\u041a\u043e\u0433\u0434\u0430 \u043f\u0440\u0438\u0441\u044b\u043b\u0430\u0442\u044c</div>
      <input type="time" id="recipe_day_time" value="10:00">
    </div>
  </div>
</div>

<div class="save-bar">
  <button class="save-btn" onclick="save()">\u2705 \u0421\u043e\u0445\u0440\u0430\u043d\u0438\u0442\u044c</button>
</div>
<div class="toast" id="toast">\u2705 \u0421\u043e\u0445\u0440\u0430\u043d\u0435\u043d\u043e!</div>

<script>
const tg = window.Telegram?.WebApp;
if(tg){ tg.ready(); tg.expand(); }

// tg_id: from initDataUnsafe OR URL param
const urlP = new URLSearchParams(location.search);
const tgId = tg?.initDataUnsafe?.user?.id?.toString() || urlP.get('uid') || '';

// Show form immediately with defaults, then load profile async
async function loadProfile(){
  if(!tgId) return;
  try{
    const r = await fetch('/diet/app/profile?tg_id='+tgId);
    const d = await r.json();
    if(!d.exists) return;
    const s=(id,v)=>{const e=document.getElementById(id);if(e)e.value=v||''};
    const c=(id,v)=>{const e=document.getElementById(id);if(e)e.checked=v!==0&&v!==false&&v!==null};
    s('cook_level',d.cook_level);
    s('experiment_level',d.experiment_level);
    s('budget_level',d.budget_level);
    s('max_cook_time',d.max_cook_time);
    s('excluded',d.excluded_foods);
    s('recipe_day_time',d.recipe_day_time);
    c('notify_personal',d.notify_personal??1);
    c('notify_meals',d.notify_meals??1);
    c('notify_recipe_day',d.notify_recipe_day??1);
  }catch(e){console.warn('profile load:',e);}
}
loadProfile();

async function save(){
  const g=id=>document.getElementById(id);
  const data={
    tg_id:tgId,
    cook_level:g('cook_level').value,
    experiment_level:g('experiment_level').value,
    budget_level:g('budget_level').value,
    max_cook_time:parseInt(g('max_cook_time').value),
    excluded_foods:g('excluded').value,
    recipe_day_time:g('recipe_day_time').value||null,
    recipe_day_enabled:g('notify_recipe_day').checked,
    notify_personal:g('notify_personal').checked,
    notify_meals:g('notify_meals').checked,
    notify_recipe_day:g('notify_recipe_day').checked,
  };
  try{
    const r=await fetch('/diet/app/profile',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
    const j=await r.json();
    if(j.ok){
      tg?.HapticFeedback?.notificationOccurred('success');
      const t=document.getElementById('toast');
      t.classList.add('on');
      setTimeout(()=>{t.classList.remove('on');setTimeout(()=>tg?.close(),300);},1000);
    }
  }catch(e){alert('\u041e\u0448\u0438\u0431\u043a\u0430: '+e);}
}

function tab(name,el){
  document.querySelectorAll('.pg').forEach(p=>p.classList.remove('on'));
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('on'));
  document.getElementById('pg-'+name).classList.add('on');
  el.classList.add('on');
  tg?.HapticFeedback?.selectionChanged();
}

document.querySelectorAll('input[type=checkbox]').forEach(el=>{
  el.addEventListener('change',()=>tg?.HapticFeedback?.impactOccurred('light'));
});
</script>
</body>
</html>"""