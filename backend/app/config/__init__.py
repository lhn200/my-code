"""Application settings and startup validation."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PACKAGE_DIR = Path(__file__).resolve().parent
_APP_DIR = _PACKAGE_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    api_prefix: str = "/api"
    checkpoint_db_path: Path = Path("data/checkpoints.sqlite3")

    # --- authentication ---
    jwt_secret: str = ""
    jwt_expires_minutes: int = Field(default=120, gt=0)
    login_rate_limit_per_minute: int = Field(default=10, gt=0)
    trash_retention_days: int = Field(default=30, gt=0)
    max_session_title_chars: int = Field(default=100, ge=1)

    # --- model access ---
    llm_api_key: str = ""
    llm_base_url: str | None = None
    # 显式代理优先：为 true 时，存在 HTTP(S)_PROXY/ALL_PROXY 环境变量才走代理；
    # 否则忽略系统级代理（包括 Windows 注册表中的代理设置）。
    llm_respect_env_proxy: bool = True
    models_config_path: Path = _PACKAGE_DIR / "models.yaml"
    prompts_dir: Path = _APP_DIR / "prompts"
    node_retry_attempts: int = Field(default=2, ge=0)

    # --- workflow budget ---
    resume_match_threshold: int = Field(default=70, ge=0, le=100)
    max_optimization_rounds: int = Field(default=2, ge=1)
    max_jobs: int = Field(default=5, ge=1)
    max_concurrent_jobs: int = Field(default=4, ge=1)
    max_input_chars: int = Field(default=20000, ge=1)
    max_job_text_chars: int = Field(default=12000, ge=1)

    # --- auto interview ---
    interview_score_threshold: int = Field(default=70, ge=0, le=100)
    max_interview_rounds: int = Field(default=2, ge=1, le=5)

    # --- resume ingestion ---
    upload_dir: Path = Path("data/uploads")
    resume_max_file_mb: float = Field(default=5, gt=0)
    ocr_max_pages: int = Field(default=10, ge=1)
    ocr_min_chars: int = Field(default=30, ge=0)

    # --- session memory ---
    session_context_budget: int = Field(default=8000, gt=0)
    context_memory_tokens: int = Field(default=800, gt=0)
    context_summary_tokens: int = Field(default=1200, gt=0)
    context_recent_turns_tokens: int = Field(default=4800, gt=0)
    context_current_input_tokens: int = Field(default=1200, gt=0)

    recent_turns_keep: int = Field(default=6, gt=0)
    min_recent_turns: int = Field(default=2, gt=0)
    summary_trigger_turns: int = Field(default=12, gt=0)
    summary_max_chars: int = Field(default=1200, gt=0)
    summary_timeout_seconds: float = Field(default=20.0, gt=0)
    max_message_chars: int = Field(default=4000, gt=0)

    memory_enabled_default: bool = False
    memory_top_k: int = Field(default=5, gt=0)
    memory_max_top_k: int = Field(default=8, gt=0)
    memory_max_content_chars: int = Field(default=200, gt=0)
    memory_min_confidence: float = Field(default=0.7, ge=0, le=1)
    memory_pending_confidence: float = Field(default=0.4, ge=0, le=1)

    memory_ttl_days_fact: int = Field(default=180, ge=0)
    memory_ttl_days_goal: int = Field(default=365, ge=0)
    memory_ttl_days_preference: int = Field(default=0, ge=0)
    memory_ttl_days_constraint: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _validate_relationships(self) -> "Settings":
        if self.min_recent_turns > self.recent_turns_keep:
            raise ValueError("MIN_RECENT_TURNS must not exceed RECENT_TURNS_KEEP")
        if self.summary_trigger_turns < self.recent_turns_keep:
            raise ValueError("SUMMARY_TRIGGER_TURNS must not be less than RECENT_TURNS_KEEP")
        if self.memory_top_k > self.memory_max_top_k:
            raise ValueError("MEMORY_TOP_K must not exceed MEMORY_MAX_TOP_K")
        if self.memory_pending_confidence >= self.memory_min_confidence:
            raise ValueError("MEMORY_PENDING_CONFIDENCE must be less than MEMORY_MIN_CONFIDENCE")
        budget_sum = (
            self.context_memory_tokens
            + self.context_summary_tokens
            + self.context_recent_turns_tokens
            + self.context_current_input_tokens
        )
        if budget_sum > self.session_context_budget:
            raise ValueError(
                "context budget parts must not exceed SESSION_CONTEXT_BUDGET "
                f"({budget_sum} > {self.session_context_budget})"
            )
        return self

    def ttl_days_for(self, kind: str) -> int:
        """Return the configured TTL in days for a memory kind; 0 means never."""
        ttl = {
            "fact": self.memory_ttl_days_fact,
            "goal": self.memory_ttl_days_goal,
            "preference": self.memory_ttl_days_preference,
            "constraint": self.memory_ttl_days_constraint,
        }
        if kind not in ttl:
            raise ValueError(f"unknown memory kind: {kind}")
        return ttl[kind]

    @property
    def resume_max_file_bytes(self) -> int:
        return int(self.resume_max_file_mb * 1024 * 1024)


__all__ = ["Settings"]
