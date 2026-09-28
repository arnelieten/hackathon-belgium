from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from database import close_db, connect_to_db, fetch_hackathons

APP_DIR = Path(__file__).parent

app = FastAPI(title="Hackathons in Belgium")
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
templates = Jinja2Templates(directory=APP_DIR / "templates")


def format_event_date(value: str | None) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.strptime(value[:10], "%Y-%m-%d")
    except ValueError:
        return value
    return f"{parsed.day} {parsed.strftime('%B')}"


templates.env.filters["event_date"] = format_event_date


@app.get("/")
def index(request: Request):
    db = connect_to_db()
    try:
        hackathons = fetch_hackathons(db, include_past=False)
    finally:
        close_db(db)

    return templates.TemplateResponse(
        request,
        "index.html",
        {"hackathons": hackathons},
    )
