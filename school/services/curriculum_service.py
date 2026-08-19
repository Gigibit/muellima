"""Curriculum generation via OpenAI Responses API with Structured Outputs."""
import json
from typing import Any

from openai import OpenAI

from django.conf import settings

from .openai_client import get_client

# ── JSON Schema for structured course output 
COURSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "valid": {"type": "boolean"},
        "reason": {"type": "string"},
        "normalized_subject": {"type": "string"},
        "title": {"type": "string"},
        "description": {"type": "string"},
        "difficulty": {
            "type": "string",
            "enum": ["beginner", "intermediate", "advanced"],
        },
        "lessons": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "order": {"type": "integer"},
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "objectives": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "key_concepts": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "examples": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "prerequisites": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": [
                    "order",
                    "title",
                    "summary",
                    "objectives",
                    "key_concepts",
                    "examples",
                    "prerequisites",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "valid",
        "reason",
        "normalized_subject",
        "title",
        "description",
        "difficulty",
        "lessons",
    ],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """\
Sei un progettista didattico esperto. Il tuo compito è valutare se un argomento 
\
proposto da uno studente è adatto a costruire un percorso didattico strutturato 
e, \
in caso affermativo, generare un corso completo.

Valuta l'argomento: se è sensato, imposta "valid" a true e genera il programma. 
\
Se l'argomento è privo di senso, vuoto, offensivo, o non è un argomento 
apprendibile, \
imposta "valid" a false e spiega il motivo in "reason".

Quando generi il corso:
- Crea un titolo accattivante ma professionale.
- Scrivi una descrizione di 2-3 frasi.
- Imposta la difficoltà a "beginner" salvo indicazioni esplicite.
- Genera tra 8 e 15 lezioni, adattando il numero alla complessità della 
materia.
- Ogni lezione deve avere un progressione logica e didattica.
- Per ogni lezione fornisci: obiettivi, concetti chiave, esempi, prerequisiti.
- Tutti i testi devono essere in italiano.
"""


def generate_curriculum(subject: str, client: OpenAI | None = None) -> dict[str, Any]:
    """Call OpenAI to validate and generate a full course curriculum.

    Returns the parsed JSON dict matching COURSE_SCHEMA.
    Raises ``openai.OpenAIError`` on API failures.
    """
    if client is None:
        client = get_client()

    response = client.responses.create(
        model=settings.OPENAI_TEXT_MODEL,
        instructions=SYSTEM_PROMPT,
        input=f"Crea un corso su: {subject}",
        text={
            "format": {
                "type": "json_schema",
                "name": "course_curriculum",
                "schema": COURSE_SCHEMA,
                "strict": True,
            }
        },
    )

    parsed = json.loads(response.output_text)
    return parsed

