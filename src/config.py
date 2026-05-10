"""Global settings — read env vars once on import."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Anthropic ────────────────────────────────────────────────────────────
    anthropic_api_key: str = Field(default="sk-ant-placeholder")
    lily_model: str = "claude-sonnet-4-6"
    lily_model_fallback: str = "claude-haiku-4-5-20251001"

    # ── Voice ─────────────────────────────────────────────────────────────────
    lily_voice_id: str = Field(default="EXAVITQu4vr4xnSDxMaL")
    elevenlabs_api_key: str = Field(default="")
    elevenlabs_model: str = "eleven_flash_v2_5"

    # ── STT ──────────────────────────────────────────────────────────────────
    deepgram_api_key: str = Field(default="")

    # ── Telephony ─────────────────────────────────────────────────────────────
    twilio_account_sid: str = Field(default="")
    twilio_auth_token: str = Field(default="")
    twilio_phone_number: str = Field(default="")

    # ── Database (NeonDB / PostgreSQL) ────────────────────────────────────────
    database_url: str = Field(default="sqlite+aiosqlite:///./lily_dev.db")

    # ── Vector DB (Pinecone) ──────────────────────────────────────────────────
    pinecone_api_key: str = Field(default="")
    pinecone_env: str = Field(default="us-east-1")
    pinecone_index: str = "lily-patient-memory"

    # ── Embeddings (Pinecone native inference — llama-text-embed-v2) ─────────
    pinecone_embedding_model: str = "llama-text-embed-v2"
    pinecone_embedding_dimension: int = 1024

    # ── OpenAI (optional — not required when using Pinecone native embeddings)
    openai_api_key: str = Field(default="")

    # ── Cache / Queue ─────────────────────────────────────────────────────────
    redis_url: str = Field(default="redis://localhost:6379/0")

    # ── App ───────────────────────────────────────────────────────────────────
    environment: Literal["dev", "development", "staging", "prod"] = "dev"
    port: int = 8000
    debug: bool = False
    log_level: str = "INFO"
    phi_redaction: bool = True

    # ── Latency budgets (ms) ─────────────────────────────────────────────────
    brain_ttft_budget_ms: int = 400
    tts_ttfb_budget_ms: int = 150
    total_loop_budget_ms: int = 800

    # ── Brain behaviour ───────────────────────────────────────────────────────
    brain_max_tokens: int = 1024
    brain_temperature: float = 0.4
    brain_max_retries: int = 2
    brain_request_timeout_s: float = 10.0
    brain_max_tool_iterations: int = 6

    # ── Chunking ──────────────────────────────────────────────────────────────
    tts_chunk_max_chars: int = 80
    tts_chunk_min_chars: int = 20

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalize_db_url(cls, v: str) -> str:
        """
        Convert NeonDB postgres:// URL to async-compatible postgresql+asyncpg://.
        Strips sslmode and channel_binding URL params — asyncpg handles SSL
        via connect_args (ssl="require"), not URL query strings.
        """
        if not v:
            return v
        # Replace scheme for asyncpg
        if v.startswith("postgresql://") or v.startswith("postgres://"):
            v = v.replace("postgresql://", "postgresql+asyncpg://", 1)
            v = v.replace("postgres://", "postgresql+asyncpg://", 1)
        # Strip asyncpg-incompatible query params from the URL
        _strip = {"sslmode", "channel_binding", "sslrootcert", "sslcert", "sslkey"}
        if "?" in v:
            base, qs = v.split("?", 1)
            params = [p for p in qs.split("&") if p.split("=")[0] not in _strip]
            v = base + ("?" + "&".join(params) if params else "")
        return v

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
