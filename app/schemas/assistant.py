"""Pydantic models for the AI assistant: requests, and the validated shape of LLM output."""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.analytics import CONTENT_TYPES, ContentType, DashboardFilters, Platform

OBJECTIVES = ["Build awareness", "Drive engagement", "Get link clicks", "Generate leads", "Promote a product update"]
TONES = ["Professional", "Friendly", "Playful", "Authoritative", "Empathetic"]


class ChatTurn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    role: Literal["user", "assistant"]
    content: str = Field(max_length=1500)


class AskRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    question: str = Field(min_length=3, max_length=500)
    history: list[ChatTurn] = Field(default_factory=list, max_length=12)
    filters: DashboardFilters = Field(default_factory=DashboardFilters)


class GenerateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    topic: str = Field(min_length=2, max_length=80)
    platform: Platform
    content_type: ContentType
    audience: str = Field(min_length=3, max_length=120)
    objective: str = Field(max_length=60)
    tone: str = Field(max_length=30)
    fresh: bool = False          # True = skip the cache and ask the model again

    @field_validator("objective")
    @classmethod
    def _objective(cls, v: str) -> str:
        if v not in OBJECTIVES:
            raise ValueError("Choose one of the listed objectives.")
        return v

    @field_validator("tone")
    @classmethod
    def _tone(cls, v: str) -> str:
        if v not in TONES:
            raise ValueError("Choose one of the listed tones.")
        return v


class GeneratedPost(BaseModel):
    """What the model must return. Anything else is rejected, not guessed at."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")
    hook: str = Field(min_length=3, max_length=220)
    body: str = Field(min_length=10, max_length=2000)
    call_to_action: str = Field(min_length=3, max_length=220)
    hashtags: list[str] = Field(default_factory=list, max_length=12)
    alignment: str = Field(min_length=10, max_length=900)

    @field_validator("hashtags", mode="before")
    @classmethod
    def _clean_tags(cls, v):
        if isinstance(v, str):
            v = v.split()
        tags = []
        for t in v or []:
            t = re.sub(r"[^\w]", "", str(t))
            if t and t.lower() not in {x.lower() for x in tags}:
                tags.append(t)
        return tags
