from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
from urllib.parse import urlparse

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


def is_valid_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    url = value.strip().lower()
    return url.startswith("https://") or url.startswith("http://")


def is_direct_event_url(value: object) -> bool:
    """True for a page about one event. Eventbrite directory and search URLs are not."""
    if not is_valid_url(value):
        return False
    parsed = urlparse(str(value).strip())
    host = parsed.netloc.lower().removeprefix("www.")
    if "eventbrite." in host:
        parts = [part for part in parsed.path.lower().split("/") if part]
        return len(parts) >= 2 and parts[0] == "e"
    return True


_TITLE_NOISE = re.compile(
    r"\b(grand final|grande finale|final|finale|qualifier|qualification)\b",
    re.IGNORECASE,
)


def core_event_name(name: str) -> str:
    """Name used to spot the same hackathon with a city or subtitle added."""
    text = name.lower().replace("\u2013", "-").replace("\u2014", "-")
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"\b20\d{2}\b", " ", text)
    parts = [part.strip(" .") for part in text.split("-")]
    head = parts[0] if parts else text
    if len(parts) > 1 and len(head.split()) >= 2:
        text = head
    text = _TITLE_NOISE.sub(" ", text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _url_rank(url: str) -> tuple[int, int]:
    host = urlparse(url).netloc.lower()
    aggregator = int(
        any(
            token in host
            for token in ("eventbrite.", "lu.ma", "luma.com", "devpost.com", "meetup.com")
        )
    )
    return (aggregator, len(url))


def _coerce_event(event) -> dict | None:
    if isinstance(event, dict) and "name" in event and "date" in event:
        name = str(event.get("name") or "").strip()
        event_date = str(event.get("date") or "").strip()
        if not name or not event_date:
            return None
        url = event.get("url")
        return {
            "name": name,
            "city": str(event.get("city") or "").strip(),
            "date": event_date,
            "topic": _normalize_topic(event.get("topic", event.get("topics"))),
            "url": url if is_direct_event_url(url) else None,
            "description": str(event.get("description") or ""),
        }

    row = _event_fields(event)
    if row is None:
        return None
    _uid, name, city, event_date, topic, url, description = row
    return {
        "name": name,
        "city": city,
        "date": event_date,
        "topic": topic,
        "url": url if is_direct_event_url(url) else None,
        "description": description,
    }


def _merge_group(items: list[dict]) -> dict:
    primary = min(items, key=lambda item: (len(item["name"]), item["name"]))
    cities: list[str] = []
    for item in items:
        city = item["city"].strip()
        if not city:
            continue
        if city.lower().startswith("multiple"):
            cities = ["Multiple"]
            break
        if city not in cities:
            cities.append(city)
    if len(cities) > 1:
        city = "Multiple"
    elif cities:
        city = cities[0]
    else:
        city = ""

    urls = [item["url"] for item in items if item.get("url")]
    topics = [item["topic"] for item in items if item.get("topic")]
    description = max((item["description"] for item in items), key=len, default="")
    return {
        "name": primary["name"],
        "city": city,
        "date": primary["date"],
        "topic": primary["topic"] or (topics[0] if topics else ""),
        "url": min(urls, key=_url_rank) if urls else None,
        "description": description,
    }


def dedupe_events(events) -> list[dict]:
    """Collapse same-day city splits and subtitle variants into one event."""
    grouped: dict[tuple[str, str], list[dict]] = {}
    order: list[tuple[str, str]] = []
    for event in events:
        item = _coerce_event(event)
        if item is None:
            continue
        core = core_event_name(item["name"]) or re.sub(
            r"[^a-z0-9]+", " ", item["name"].lower()
        ).strip()
        key = (core, item["date"])
        if key not in grouped:
            order.append(key)
            grouped[key] = []
        grouped[key].append(item)
    return [_merge_group(grouped[key]) for key in order]


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
        url if is_direct_event_url(url) else None,
        description or "",
    )


def save_hackathons(db_connection, events) -> int:
    """Upsert hackathons by uid (hash of name + date). Returns count saved."""
    count = 0
    for event in dedupe_events(events):
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
    conditions.append(
        "url IS NOT NULL AND (url LIKE 'http://%' OR url LIKE 'https://%')"
    )
    if city:
        conditions.append("city = ?")
        params.append(city)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    query = f"""SELECT name, city, date, topics, url, description
                FROM hackathons {where}
                ORDER BY date ASC"""
    rows = get_query(db_connection, query, tuple(params) if params else None)
    events = [
        {
            "name": row[0] or "",
            "city": row[1] or "",
            "date": row[2] or "",
            "topic": _normalize_topic(row[3]),
            "url": row[4],
            "description": row[5] or "",
        }
        for row in rows
        if is_direct_event_url(row[4])
    ]
    return dedupe_events(events)


def fetch_cities(db_connection) -> list[str]:
    rows = get_query(
        db_connection,
        "SELECT DISTINCT city FROM hackathons WHERE city IS NOT NULL AND city != '' ORDER BY city",
    )
    return [row[0] for row in rows]
