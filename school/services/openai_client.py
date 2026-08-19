"""Centralised OpenAI client factory.

All services import the client from here so that configuration
(model names, timeouts, API key) lives in exactly one place.
"""
import openai
from django.conf import settings


def get_client() -> openai.OpenAI:
    """Return a configured OpenAI client instance."""
    return openai.OpenAI(
        api_key=settings.OPENAI_API_KEY,
        timeout=settings.OPENAI_TIMEOUT,
    )

