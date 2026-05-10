"""Global settings — read env vars once on import."""

from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    anthropic_api_key: str = Field(default="sk-ant-placeholder")
    lily_model: str = "claude-sonnet-4-6"
    lily_model_fallback: str = "claude-haiku-4-5-20251001"
    lily_voice_id: str = Field(default="EXAVITQu4vr4xnSDxMaL")
    environment: Literal["dev", "staging", "prod"] = "dev"
    log_level: str = "INFO"
    phi_redaction: bool = True

    # Latency budgets (ms)
    brain_ttft_budget_ms: int = 400
    tts_ttfb_budget_ms: int = 150
    total_loop_budget_ms: int = 800

    # Brain behaviour
    brain_max_tokens: int = 1024
    brain_temperature: float = 0.4
    brain_max_retries: int = 2
    brain_request_timeout_s: float = 10.0
    brain_max_tool_iterations: int = 6

    # Chunking
    tts_chunk_max_chars: int = 80
    tts_chunk_min_chars: int = 20

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
