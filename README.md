# Hackathons Belgium

Research agent finds hackathons in Belgium; results are stored in SQLite and shown on a simple web page.

## Populate the database

From the repo root (requires `GEMINI_API_KEY` and `GEMINI_MODEL` in `.env`):

```bash
uv run python -m app.agent
```

## Run the web app

```bash
uv run uvicorn app.main:app --reload
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). Set `DB_PATH` in `.env` if you want a non-default database file (see `.env_local`).
