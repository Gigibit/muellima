"""Illustration service for generating educational visual aids.

Designed to be extensible: in the future, different visual types
(diagram, timeline, formula, chart) can be rendered via different
methods. Currently uses OpenAI image generation for illustrations.
"""
import os
import base64
import uuid
from typing import Any

from openai import OpenAI

from .openai_client import get_client
from django.conf import settings


def generate_image(
    concept: str,
    description: str,
    visual_type: str = "illustration",
    client: OpenAI | None = None,
) -> dict[str, Any]:
    """Generate an educational illustration via OpenAI image API.

    Returns a dict with the image URL (data URI) and metadata.
    """
    if client is None:
        client = get_client()

    style_map = {
        "diagram": "clean technical diagram with labeled components, arrows showing relationships",
        "illustration": "minimal educational textbook illustration with simple shapes and clear labels",
        "timeline": "horizontal timeline with key events marked and labeled",
        "chart": "clean data chart or graph with labeled axes and data points",
        "formula": "mathematical formula or equation rendered clearly with annotations",
        "comparison": "side-by-side comparison diagram with clear labels",
    }

    style = style_map.get(visual_type, style_map["illustration"])

    prompt = f"""\
Create a clean educational illustration explaining:

{concept}

Context:
{description}

Style:
{style},
simple shapes,
clear labels in Italian,
white background,
high information density,
no decorative elements,
no text other than labels,
easy to understand for a beginner.
"""

    result = client.images.generate(
        model=settings.OPENAI_IMAGE_MODEL,
        prompt=prompt,
        size="1024x1024",
    )

    image_data = result.data[0]

    # gpt-image-1 returns base64; dall-e-3 returns url
    if hasattr(image_data, "b64_json") and image_data.b64_json:
        b64 = image_data.b64_json
        data_uri = f"data:image/png;base64,{b64}"
    elif hasattr(image_data, "url") and image_data.url:
        data_uri = image_data.url
    else:
        raise ValueError("No image data returned from OpenAI")

    return {
        "image_url": data_uri,
        "concept": concept,
        "visual_type": visual_type,
        "title": concept,
    }


def render_diagram(concept: str, description: str) -> dict[str, Any]:
    """Placeholder for future SVG/HTML diagram rendering.

    Currently delegates to image generation. In the future this could
    render a pure SVG diagram without calling the image API.
    """
    return generate_image(concept, description, visual_type="diagram")


def render_formula(concept: str, description: str) -> dict[str, Any]:
    """Placeholder for future formula rendering (e.g. MathJax/SVG)."""
    return generate_image(concept, description, visual_type="formula")


def render_timeline(concept: str, description: str) -> dict[str, Any]:
    """Placeholder for future timeline rendering."""
    return generate_image(concept, description, visual_type="timeline")


def create_illustration(
    title: str,
    concept: str,
    visual_type: str,
    description: str,
    client: OpenAI | None = None,
) -> dict[str, Any]:
    """Main entry point: dispatch to the appropriate rendering method."""
    result = generate_image(concept, description, visual_type, client)
    result["title"] = title
    return result

