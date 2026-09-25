from __future__ import annotations

from datetime import date
import os
from pathlib import Path

from agno.agent import Agent
from agno.models.google import GeminiInteractions
from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel, Field

load_dotenv()

APP_DIR = Path(__file__).parent
MODEL_NAME = os.getenv("GEMINI_MODEL")
API_KEY = os.getenv("GEMINI_API_KEY")


class HackathonEvent(BaseModel):
    name: str = Field(description="Official name of the hackathon")
    city: str = Field(description="Belgian city where it takes place")
    date: str = Field(description="ISO date, or null if unknown")
    duration: int = Field(description="How long the hackathon lasts")
    url: str = Field(default=None, description="Official event URL")
    description: str = Field(description="Short description of the event")


class HackathonBrief(BaseModel):
    events: list[HackathonEvent] = Field(description="Hackathons found in Belgium")


def load_prompt(**kwargs: object) -> str:
    env = Environment(loader=FileSystemLoader(APP_DIR), autoescape=False)
    template = env.get_template("prompt.jinja2")
    return template.render(today=date.today().isoformat(), **kwargs)


def build_research_agent() -> Agent:
    return Agent(
        model=GeminiInteractions(
            agent="deep-research-preview-04-2026",
            api_key=API_KEY,
        ),
        markdown=True,
    )


def build_deduplication_agent() -> Agent:
    return Agent(
        model=GeminiInteractions(
            id=MODEL_NAME,
            api_key=API_KEY,
        ),
        instructions=(
            "Deduplicate hackathon events from the research report and format them. "
            "Merge the same event listed more than once. Do not invent events."
        ),
        output_schema=HackathonBrief,
        markdown=False,
    )


def run() -> HackathonBrief | str:
    research = build_research_agent().run(load_prompt())
    response = build_deduplication_agent().run(research.content)
    return response.content


if __name__ == "__main__":
    result = run()
    print(result)
