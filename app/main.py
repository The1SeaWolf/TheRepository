import base64
import binascii
import re
import secrets
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, db, foods, vision

STATIC = Path(__file__).parent / "static"
DAY_RE = r"^\d{4}-\d{2}-\d{2}$"



@asynccontextmanager
async def lifespan(_):
    db.init()
    yield


app = FastAPI(title="Carb Tracker", lifespan=lifespan)


@app.middleware("http")
async def basic_auth(request: Request, call_next):
    if not config.APP_PASSWORD or request.url.path == "/healthz":
        return await call_next(request)
    try:
        scheme, _, token = request.headers.get("authorization", "").partition(" ")
        user, _, password = base64.b64decode(token).decode().partition(":")
        ok = (scheme.lower() == "basic"
              and secrets.compare_digest(user, config.APP_USER)
              and secrets.compare_digest(password, config.APP_PASSWORD))
    except (binascii.Error, UnicodeDecodeError):
        ok = False
    if not ok:
        return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="Carb Tracker"'})
    return await call_next(request)


@app.get("/healthz")
def healthz():
    return {"ok": True}


# ---- food lookup -----------------------------------------------------------

@app.get("/api/search")
def search(q: str):
    q = q.strip()
    if len(q) < 2:
        raise HTTPException(400, "Query too short")
    results, errors = foods.search(q)
    return {"results": results, "errors": errors}


@app.get("/api/barcode/{code}")
def barcode(code: str):
    if not re.fullmatch(r"\d{6,14}", code):
        raise HTTPException(400, "Invalid barcode")
    try:
        food = foods.barcode(code)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Open Food Facts unavailable: {e}")
    if not food:
        raise HTTPException(404, "Product not found")
    return food


# ---- photo analysis --------------------------------------------------------

def _read_upload(file: UploadFile) -> bytes:
    data = file.file.read(config.MAX_UPLOAD_BYTES + 1)
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Image too large")
    return data


def _run_vision(fn, file, hint):
    try:
        return fn(_read_upload(file), hint)
    except vision.VisionError as e:
        raise HTTPException(422, str(e))


@app.post("/api/analyze/label")
def analyze_label(image: UploadFile = File(...), hint: str = Form("")):
    return _run_vision(vision.read_label, image, hint)


@app.post("/api/analyze/meal")
def analyze_meal(image: UploadFile = File(...), hint: str = Form("")):
    return _run_vision(vision.estimate_meal, image, hint)


# ---- diary -----------------------------------------------------------------

class EntryIn(BaseModel):
    day: str = Field(pattern=DAY_RE)
    meal: Literal["breakfast", "lunch", "dinner", "snack"]
    name: str = Field(min_length=1, max_length=200)
    amount: str = Field("", max_length=100)
    carbs_g: float = Field(ge=0, le=5000)
    fat_g: float = Field(ge=0, le=5000)
    source: str = Field("manual", max_length=30)


class Goals(BaseModel):
    carbs_g: float | None = Field(None, ge=0, le=5000)
    fat_g: float | None = Field(None, ge=0, le=5000)


def _goals(conn) -> dict:
    rows = {r["key"]: float(r["value"]) for r in conn.execute("SELECT key, value FROM settings")}
    return {"carbs_g": rows.get("goal_carbs_g"), "fat_g": rows.get("goal_fat_g")}


@app.get("/api/day/{day}")
def get_day(day: str):
    if not re.fullmatch(DAY_RE, day):
        raise HTTPException(400, "Invalid date")
    with db.connect() as conn:
        entries = [dict(r) for r in conn.execute("SELECT * FROM entries WHERE day = ? ORDER BY id", (day,))]
        goals = _goals(conn)
    return {
        "day": day,
        "entries": entries,
        "totals": {"carbs_g": round(sum(e["carbs_g"] for e in entries), 1),
                   "fat_g": round(sum(e["fat_g"] for e in entries), 1)},
        "goals": goals,
    }


@app.post("/api/entries", status_code=201)
def add_entry(e: EntryIn):
    with db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO entries (day, meal, name, amount, carbs_g, fat_g, source) VALUES (?,?,?,?,?,?,?)",
            (e.day, e.meal, e.name, e.amount, round(e.carbs_g, 1), round(e.fat_g, 1), e.source))
        return {"id": cur.lastrowid}


@app.put("/api/entries/{entry_id}")
def update_entry(entry_id: int, e: EntryIn):
    with db.connect() as conn:
        cur = conn.execute(
            "UPDATE entries SET day=?, meal=?, name=?, amount=?, carbs_g=?, fat_g=? WHERE id=?",
            (e.day, e.meal, e.name, e.amount, round(e.carbs_g, 1), round(e.fat_g, 1), entry_id))
        if not cur.rowcount:
            raise HTTPException(404, "Entry not found")
    return {"ok": True}


@app.delete("/api/entries/{entry_id}")
def delete_entry(entry_id: int):
    with db.connect() as conn:
        if not conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,)).rowcount:
            raise HTTPException(404, "Entry not found")
    return {"ok": True}


@app.get("/api/recent")
def recent():
    """Most recently logged distinct foods, for one-tap re-logging."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT name, amount, carbs_g, fat_g FROM entries WHERE id IN "
            "(SELECT MAX(id) FROM entries GROUP BY name) ORDER BY id DESC LIMIT 20")
        return [dict(r) for r in rows]


@app.get("/api/history")
def history(days: int = 30, end: str | None = None):
    days = max(1, min(days, 366))
    if end is not None and not re.fullmatch(DAY_RE, end):
        raise HTTPException(400, "Invalid date")
    end_day = date.fromisoformat(end) if end else date.today()
    start = (end_day - timedelta(days=days - 1)).isoformat()
    with db.connect() as conn:
        rows = {r["day"]: r for r in conn.execute(
            "SELECT day, SUM(carbs_g) c, SUM(fat_g) f FROM entries WHERE day BETWEEN ? AND ? GROUP BY day",
            (start, end_day.isoformat()))}
        goals = _goals(conn)
    out = []
    for i in range(days):
        d = (end_day - timedelta(days=days - 1 - i)).isoformat()
        r = rows.get(d)
        out.append({"day": d, "carbs_g": round(r["c"], 1) if r else 0, "fat_g": round(r["f"], 1) if r else 0})
    return {"days": out, "goals": goals}


@app.get("/api/goals")
def get_goals():
    with db.connect() as conn:
        return _goals(conn)


@app.put("/api/goals")
def put_goals(g: Goals):
    with db.connect() as conn:
        for key, val in (("goal_carbs_g", g.carbs_g), ("goal_fat_g", g.fat_g)):
            if val is None:
                conn.execute("DELETE FROM settings WHERE key = ?", (key,))
            else:
                conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                             "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(val)))
        return _goals(conn)


# ---- static ----------------------------------------------------------------

@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/", StaticFiles(directory=STATIC), name="static")
