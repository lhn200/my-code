"""Strict request models for the run API."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator
from pydantic_core import PydanticCustomError


class JobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str | None = None
    title: str
    original_position_text: str

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise PydanticCustomError("blank", "title must not be blank")
        return value.strip()

    @field_validator("original_position_text")
    @classmethod
    def _position_text_not_blank(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise PydanticCustomError(
                "blank", "original_position_text must not be blank"
            )
        return value


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: str
    resume_text: str
    jobs: list[JobRequest]

    @field_validator("goal")
    @classmethod
    def _goal_not_blank(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise PydanticCustomError("blank", "goal must not be blank")
        return value.strip()

    @field_validator("resume_text")
    @classmethod
    def _resume_not_blank(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise PydanticCustomError("blank", "resume_text must not be blank")
        return value


__all__ = ["JobRequest", "RunRequest"]
