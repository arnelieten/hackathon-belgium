from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading

from dotenv import load_dotenv

load_dotenv()

_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = os.getenv("DB_PATH", "database/hackathons.db")
if not Path(DB_PATH).is_absolute():
    DB_PATH = str(_ROOT / DB_PATH)

INIT_SQL = """
CREATE TABLE IF NOT EXISTS hackathons (
    uid TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    city TEXT,
    date TEXT NOT NULL,
    topics TEXT,
    url TEXT,
    description TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


def hackathon_uid(name: str, event_date: str) -> str:
    key = f"{name.strip().lower()}|{event_date.strip()}"
    return hashlib.sha256(key.encode()).hexdigest()


def connect_to_db():
    db_file = Path(DB_PATH)
    db_file.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(INIT_SQL)
    conn.commit()
    for column in ("registration_date", "duration"):
        try:
            conn.execute(f"ALTER TABLE hackathons DROP COLUMN {column}")
            conn.commit()
        except sqlite3.OperationalError:
            pass
    try:
        conn.execute("ALTER TABLE hackathons ADD COLUMN topics TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass
    cur = conn.cursor()
    lock = threading.Lock()
    return {"cur": cur, "conn": conn, "lock": lock}


def run_query(db_connection, query, params=None):
    cur = db_connection["cur"]
    conn = db_connection["conn"]
    lock = db_connection["lock"]

    with lock:
        if params:
            cur.execute(query, params)
        else:
            cur.execute(query)
        conn.commit()


def get_query(db_connection, query, params=None):
    cur = db_connection["cur"]
    lock = db_connection["lock"]

    with lock:
        if params:
            cur.execute(query, params)
        else:
            cur.execute(query)
        rows = cur.fetchall()

    return rows


def close_db(db_connection):
    db_connection["cur"].close()
    db_connection["conn"].close()


def _normalize_topic(raw) -> str:
    if raw is None:
        return ""
    if isinstance(raw, list):
        raw = raw[0] if raw else ""
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return raw.strip()
        if isinstance(parsed, list):
            parsed = parsed[0] if parsed else ""
        return str(parsed).strip()
    return str(raw).strip()


def _event_fields(event) -> tuple | None:
    """Return row fields or None if date is missing."""
    name = getattr(event, "name", None) or (event.get("name") if isinstance(event, dict) else None)
    city = getattr(event, "city", None) or (event.get("city") if isinstance(event, dict) else None)
    event_date = getattr(event, "date", None) or (
        event.get("date") if isinstance(event, dict) else None
    )
    url = getattr(event, "url", None) or (event.get("url") if isinstance(event, dict) else None)
    description = getattr(event, "description", None) or (
        event.get("description") if isinstance(event, dict) else None
    )
    topic = getattr(event, "topic", None)
    if topic is None:
        topic = getattr(event, "topics", None)
    if topic is None and isinstance(event, dict):
        topic = event.get("topic", event.get("topics"))

    if not name or not event_date or not str(event_date).strip():
        return None

    event_date = str(event_date).strip()

    uid = hackathon_uid(name, event_date)
    return (
        uid,
        name.strip(),
        (city or "").strip(),
        event_date,
        _normalize_topic(topic),
        url or None,
        description or "",
    )


def save_hackathons(db_connection, events) -> int:
    """Upsert hackathons by uid (hash of name + date). Returns count saved."""
    count = 0
    for event in events:
        row = _event_fields(event)
        if row is None:
            continue
        run_query(
            db_connection,
            """INSERT INTO hackathons
                (uid, name, city, date, topics, url, description)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(uid) DO UPDATE SET
                 city = excluded.city,
                 topics = excluded.topics,
                 url = excluded.url,
                 description = excluded.description""",
            row,
        )
        count += 1
    return count


def fetch_hackathons(
    db_connection,
    city: str | None = None,
    include_past: bool = False,
) -> list[dict[str, object]]:
    conditions: list[str] = []
    params: list[str] = []

    if not include_past:
        conditions.append("date >= date('now')")
    if city:
        conditions.append("city = ?")
        params.append(city)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    query = f"""SELECT name, city, date, topics, url, description
                FROM hackathons {where}
                ORDER BY date ASC"""
    rows = get_query(db_connection, query, tuple(params) if params else None)
    return [
        {
            "name": row[0] or "",
            "city": row[1] or "",
            "date": row[2] or "",
            "topic": _normalize_topic(row[3]),
            "url": row[4],
            "description": row[5] or "",
        }
        for row in rows
    ]


def fetch_cities(db_connection) -> list[str]:
    rows = get_query(
        db_connection,
        "SELECT DISTINCT city FROM hackathons WHERE city IS NOT NULL AND city != '' ORDER BY city",
    )
    return [row[0] for row in rows]
