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
        "needs_clarification": {"type": "boolean"},
        "clarification_question": {"type": "string"},
        "clarification_options": {
            "type": "array",
            "maxItems": 10,
            "items": {"type": "string"},
        },
        "normalized_subject": {"type": "string"},
        "title": {"type": "string"},
        "description": {"type": "string"},
        "difficulty": {
            "type": "string",
            "enum": ["beginner", "intermediate", "advanced"],
        },
        "lessons": {
            "type": "array",
            "maxItems": settings.MAX_LESSON,
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
        "needs_clarification",
        "clarification_question",
        "clarification_options",
        "normalized_subject",
        "title",
        "description",
        "difficulty",
        "lessons",
    ],
    "additionalProperties": False,
}

SYSTEM_PROMPT = f"""\
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

Prima di generare valuta quanto l'argomento sia specifico. Se è troppo generico
per definire un percorso didattico coerente, imposta "needs_clarification" a true,
scrivi una sola domanda breve in "clarification_question", proponi opzioni concrete
in "clarification_options" e restituisci "lessons" vuoto. Per materie scolastiche
ampie come storia o geografia chiedi il livello e l'anno, ad esempio primo, secondo
o terzo anno delle medie oppure uno dei cinque anni delle superiori. Chiedi solo
informazioni che cambiano realmente programma, difficoltà o profondità.

Se nel messaggio è presente una "Specificazione scelta dallo studente", considerala
sufficiente, imposta "needs_clarification" a false e genera il corso senza fare una
seconda domanda. Quando non serve chiarire, usa domanda vuota e opzioni vuote.

Quando generi il corso:
- Crea un titolo accattivante ma professionale.
- Scrivi una descrizione di 2-3 frasi.
- Imposta la difficoltà a "beginner" salvo indicazioni esplicite.
- Se l'argomento è valido, genera almeno {settings.MIN_LESSON} lezioni e non più
  di {settings.MAX_LESSON}. Usa il minimo solo per argomenti circoscritti; aumenta
  liberamente il numero di lezioni, fino al massimo, quando complessità, ampiezza
  o prerequisiti accademici lo richiedono.
- Progetta il corso con granularità accademica: ogni lezione deve trattare una
  singola unità concettuale ben delimitata e avere profondità sufficiente per una
  lezione completa.
- Non accorpare macro-argomenti diversi in titoli generici. Suddividi teorie,
  tecniche, dimostrazioni, applicazioni e casi di studio in lezioni distinte
  quando costituiscono unità didattiche autonome.
- Costruisci una progressione rigorosa dai prerequisiti ai concetti avanzati,
  evitando ripetizioni e sovrapposizioni tra lezioni.
- Per ogni lezione fornisci: obiettivi, concetti chiave, esempi, prerequisiti.
- Tutti i testi devono essere in italiano.
"""


def generate_curriculum(
    subject: str,
    clarification: str = "",
    client: OpenAI | None = None,
) -> dict[str, Any]:
    """Call OpenAI to validate and generate a full course curriculum.

    Returns the parsed JSON dict matching COURSE_SCHEMA.
    Raises ``openai.OpenAIError`` on API failures.
    """
    if client is None:
        client = get_client()

    user_input = f"Crea un corso su: {subject}"
    if clarification:
        user_input += f"\nSpecificazione scelta dallo studente: {clarification}"

    response = client.responses.create(
        model=settings.OPENAI_TEXT_MODEL,
        instructions=SYSTEM_PROMPT,
        input=user_input,
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
    parsed["_usage"] = response.usage

    if parsed.get("valid") and not parsed.get("needs_clarification"):
        lesson_count = len(parsed.get("lessons", []))
        if not settings.MIN_LESSON <= lesson_count <= settings.MAX_LESSON:
            raise ValueError(
                "Il curriculum generato contiene "
                f"{lesson_count} lezioni; ne sono richieste tra "
                f"{settings.MIN_LESSON} e {settings.MAX_LESSON}."
            )

    return parsed
