from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    openai_api_key: str = ""
    chat_model: str = "gpt-4.1"
    chat_provider: Literal["openai", "azure"] = "openai"
    azure_openai_api_key: str = ""
    azure_openai_endpoint: str = ""
    azure_openai_deployment: str = ""

    @field_validator("azure_openai_endpoint")
    @classmethod
    def validate_azure_endpoint(cls, value):
        value = value.strip().rstrip("/")
        if not value:
            return value
        parsed = urlparse(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.hostname == "ai.azure.com"
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/openai/v1")
        ):
            raise ValueError(
                "Use the Azure resource HTTPS endpoint, not the Foundry portal/project URL"
            )
        return value

    @property
    def chat_configured(self) -> bool:
        if self.chat_provider == "azure":
            return bool(
                self.azure_openai_api_key
                and self.azure_openai_endpoint
                and self.azure_openai_deployment
            )
        return bool(self.openai_api_key)

    @property
    def answer_model(self) -> str:
        return self.azure_openai_deployment if self.chat_provider == "azure" else self.chat_model

    planner_model: str = "gpt-4.1-mini"
    vision_model: str = "gpt-4.1-mini"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = Field(1536, ge=256, le=3072)
    qdrant_url: str = ""
    qdrant_api_key: str = ""
    qdrant_collection: str = "content_segments"
    data_dir: Path = Path("data")
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    audio_events: bool = False
    audio_model: str = "gpt-audio"
    app_token: str = ""
    max_upload_mb: int = Field(1024, ge=1, le=4096)
    max_media_seconds: int = Field(10800, ge=12, le=21600)
    segment_seconds: int = Field(6, ge=4, le=12)
    video_fps: int = Field(1, ge=1, le=2)
    frame_overlap_seconds: int = Field(1, ge=0, le=2)
    timeline_context_tokens: int = Field(100000, ge=4000, le=100000)
    timeline_max_segments: int = Field(1200, ge=20, le=4000)
    model_concurrency: int = Field(4, ge=1, le=16)
    candidate_k: int = Field(20, ge=5, le=30)
    retrieval_k: int = Field(30, ge=10, le=100)
    context_tokens: int = Field(18000, ge=2000, le=50000)

    @property
    def index_version(self) -> str:
        return f"v1:{self.embedding_model}:{self.embedding_dimensions}:lexical-v1"
