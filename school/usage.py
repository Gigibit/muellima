from typing import Any
from decimal import Decimal

from django.conf import settings

from .models import UsageRecord


def usage_values(usage: Any) -> dict[str, int]:
    if usage is None:
        return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    if hasattr(usage, "model_dump"):
        usage = usage.model_dump()
    if not isinstance(usage, dict):
        return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    input_tokens = max(0, int(usage.get("input_tokens") or 0))
    output_tokens = max(0, int(usage.get("output_tokens") or 0))
    total_tokens = max(0, int(usage.get("total_tokens") or input_tokens + output_tokens))
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def record_usage(user, kind: str, usage: Any = None, **extra) -> UsageRecord:
    values = usage_values(usage)
    return UsageRecord.objects.create(user=user, kind=kind, **values, **extra)


def estimate_usage_cost(records) -> dict[str, Decimal]:
    """Estimate OpenAI spend in USD from persisted usage counters."""
    million = Decimal(1_000_000)
    costs = {"text": Decimal("0"), "realtime": Decimal("0"), "images": Decimal("0")}

    for record in records:
        if record.kind == "illustration":
            costs["images"] += Decimal(record.image_count) * settings.OPENAI_IMAGE_USD_PER_IMAGE
            continue

        if record.kind == "realtime_response":
            metadata = record.metadata or {}
            audio_input = min(max(int(metadata.get("audio_input_tokens") or 0), 0), record.input_tokens)
            audio_output = min(max(int(metadata.get("audio_output_tokens") or 0), 0), record.output_tokens)
            text_input = record.input_tokens - audio_input
            text_output = record.output_tokens - audio_output
            costs["realtime"] += (
                Decimal(text_input) * settings.OPENAI_REALTIME_TEXT_INPUT_USD_PER_1M
                + Decimal(text_output) * settings.OPENAI_REALTIME_TEXT_OUTPUT_USD_PER_1M
                + Decimal(audio_input) * settings.OPENAI_REALTIME_AUDIO_INPUT_USD_PER_1M
                + Decimal(audio_output) * settings.OPENAI_REALTIME_AUDIO_OUTPUT_USD_PER_1M
            ) / million
            continue

        if record.kind in {"curriculum", "quiz"}:
            costs["text"] += (
                Decimal(record.input_tokens) * settings.OPENAI_TEXT_INPUT_USD_PER_1M
                + Decimal(record.output_tokens) * settings.OPENAI_TEXT_OUTPUT_USD_PER_1M
            ) / million

    costs["total"] = costs["text"] + costs["realtime"] + costs["images"]
    return costs
