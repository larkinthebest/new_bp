"""User-safe ingestion diagnostics. Never display upstream bodies or credentials."""

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    RateLimitError,
)


def chat_error_message(exc: Exception, provider: str) -> str:
    """Identify the failing provider without exposing its response or credentials."""
    host = getattr(getattr(getattr(exc, "request", None), "url", None), "host", "")
    name = (
        "Gemini"
        if "googleapis.com" in host
        else "OpenAI"
        if "openai.com" in host
        else provider.capitalize()
    )
    if isinstance(exc, AuthenticationError):
        return f"{name} rejected the API key. Check its key in .env and restart the server."
    if isinstance(exc, RateLimitError):
        return f"{name} quota or rate limit reached. Check billing and API limits, then retry."
    if isinstance(exc, APITimeoutError):
        return f"{name} did not respond in time. Retry or select another available model."
    if isinstance(exc, APIStatusError):
        if exc.status_code in (403, 404):
            return f"The configured {name} model is unavailable. Check the model name and access."
        if exc.status_code >= 500:
            return f"{name} is temporarily unavailable (HTTP {exc.status_code}). Retry or select another available model."
    if isinstance(exc, APIConnectionError):
        return f"Could not connect to {name}. Check your connection and retry."
    if isinstance(exc, TimeoutError):
        return "The analysis timed out. Select one source and retry."
    return "The answer could not be completed. Check the server log for the failed analysis stage."


class IngestionError(ValueError):
    """An application-authored message safe to show in the source library."""


def ingestion_error_message(exc: Exception) -> str:
    if isinstance(exc, ExceptionGroup):
        return ingestion_error_message(exc.exceptions[0])
    if isinstance(exc, IngestionError):
        return str(exc)
    if isinstance(exc, AuthenticationError):
        return "OpenAI rejected the API key. Check OPENAI_API_KEY in .env and restart the server."
    if isinstance(exc, RateLimitError):
        if exc.code == "insufficient_quota":
            return (
                "OpenAI API quota is exhausted. Check API billing and project limits, then retry."
            )
        return "OpenAI rate limit reached. Wait a moment and retry."
    if isinstance(exc, APIConnectionError):
        return "Could not connect to OpenAI. Check the network connection and retry."
    if isinstance(exc, APIStatusError) and exc.status_code in {403, 404}:
        return "The configured OpenAI model is unavailable for this API project. Check model access and the model names in .env."
    if isinstance(exc, TimeoutError):
        return "Processing timed out. Retry with a shorter file or check the service connections."
    return "Processing failed. Check the server log for the failed stage and retry."
