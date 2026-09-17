"""User-safe ingestion diagnostics. Never display upstream bodies or credentials."""

from openai import APIConnectionError, APIStatusError, AuthenticationError, RateLimitError


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
