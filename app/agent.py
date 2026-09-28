from __future__ import annotations

from datetime import date
import json
import os
from pathlib import Path

from agno.agent import Agent
from agno.models.google import GeminiInteractions
from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel, Field

from database import close_db, connect_to_db, save_hackathons

load_dotenv()

APP_DIR = Path(__file__).parent
MODEL_NAME = os.getenv("GEMINI_MODEL")
API_KEY = os.getenv("GEMINI_API_KEY")


class HackathonEvent(BaseModel):
    name: str = Field(description="Official name of the hackathon")
    city: str = Field(description="Belgian city where it takes place")
    date: str = Field(description="Required ISO date (YYYY-MM-DD) of the hackathon event")
    topic: str = Field(description="Single short topic label (e.g. AI, climate, health)")
    url: str = Field(default=None, description="Official hackathon event URL or most relevant url for more information regarding the hackathon")
    description: str = Field(description="Short description of the hackathon topic")


class HackathonBrief(BaseModel):
    events: list[HackathonEvent] = Field(description="Hackathons found in Belgium")


def load_prompt(template: str, **kwargs: object) -> str:
    env = Environment(loader=FileSystemLoader(APP_DIR), autoescape=False)
    return env.get_template(template).render(today=date.today().isoformat(), **kwargs)


def build_research_agent() -> Agent:
    return Agent(
        model=GeminiInteractions(
            agent="deep-research-preview-04-2026",
            api_key=API_KEY,
        ),
        markdown=True,
    )


def build_compiler_agent() -> Agent:
    return Agent(
        model=GeminiInteractions(
            id=MODEL_NAME,
            api_key=API_KEY,
        ),
        instructions=load_prompt(
            "compiler.jinja2",
            event_schema=json.dumps(HackathonEvent.model_json_schema(), indent=2),
        ),
        output_schema=HackathonBrief,
        markdown=False,
    )


def run() -> HackathonBrief | str:
    research = build_research_agent().run(load_prompt("research.jinja2"))
    response = build_compiler_agent().run(research.content)
    content = response.content
    if isinstance(content, HackathonBrief):
        db = connect_to_db()
        try:
            save_hackathons(db, content.events)
        finally:
            close_db(db)
    return content


if __name__ == "__main__":
    result = run()
