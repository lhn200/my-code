"""Strict request models for the run API."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator
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


class InterviewCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread_id: str
    job_id: str

    @field_validator("thread_id", "job_id")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise PydanticCustomError("blank", "value must not be blank")
        return value.strip()


class InterviewAnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str

    @field_validator("answer")
    @classmethod
    def _answer_not_blank(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise PydanticCustomError("blank", "answer must not be blank")
        return value


class CoachSessionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread_id: str | None = None
    title: str = Field(default="", max_length=100)

    @field_validator("thread_id", "title")
    @classmethod
    def _normalize(cls, value: str | None) -> str | None:
        return value.strip() if isinstance(value, str) else value


class CoachSessionUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread_id: str | None = None
    title: str | None = Field(default=None, max_length=100)

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            raise PydanticCustomError("blank", "title must not be blank")
        return value.strip()

    @field_validator("thread_id")
    @classmethod
    def _thread_strip(cls, value: str | None) -> str | None:
        return value.strip() if isinstance(value, str) else value


class CoachMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str


__all__ = [
    "CoachMessageRequest",
    "CoachSessionCreateRequest",
    "CoachSessionUpdateRequest",
    "InterviewAnswerRequest",
    "InterviewCreateRequest",
    "JobRequest",
    "RunRequest",
]
