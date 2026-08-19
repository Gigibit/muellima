"""Realtime API session configuration.

Creates an ephemeral client secret on the OpenAI backend and returns it
to the browser. The browser then uses WebRTC to connect directly to
OpenAI's Realtime endpoint using only the short-lived ephemeral key.

The main API key NEVER reaches the browser.
"""
import json
import logging
from typing import Any

import httpx
from django.conf import settings

from ..models import Lesson

logger = logging.getLogger(__name__)

OPENAI_REALTIME_CLIENT_SECRETS_URL = "https://api.openai.com/v1/realtime/client_secrets"

# ── Function tool: show_illustration 
SHOW_ILLUSTRATION_TOOL: dict[str, Any] = {
    "type": "function",
    "name": "show_illustration",
    "description": (
        "Genera e mostra allo studente un supporto visivo. Devi usarlo quando "
        "lo studente chiede esplicitamente un'immagine, un diagramma, uno schema "
        "o un altro supporto visivo, e quando un concetto complesso è più chiaro "
        "visivamente. Non usarlo per concetti semplici che non ne beneficiano."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "concept": {"type": "string"},
            "visual_type": {
                "type": "string",
                "enum": [
                    "diagram",
                    "illustration",
                    "timeline",
                    "chart",
                    "formula",
                    "comparison",
                ],
            },
            "description": {"type": "string"},
        },
        "required": ["title", "concept", "visual_type", "description"],
    },
}

FINISH_LESSON_TOOL: dict[str, Any] = {
    "type": "function",
    "name": "finish_lesson",
    "description": (
        "Segnala che la lezione corrente è terminata. Usalo una sola volta, "
        "solo dopo aver coperto tutti gli obiettivi e i concetti chiave previsti, "
        "aver fatto un breve riepilogo e aver lasciato spazio alle ultime domande."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "Breve riepilogo conclusivo della lezione.",
            },
        },
        "required": ["summary"],
        "additionalProperties": False,
    },
}


def build_professor_instructions(lesson: Lesson) -> str:
    """Dynamically generate the professor's system instructions for a 
lesson."""
    outline_text = json.dumps(lesson.content_outline, ensure_ascii=False, 
indent=2)

    # Build a brief overview of the course progression
    course_lessons = lesson.course.lessons.values_list("order", "title")
    progression = "\n".join(
        f"  {o}. {t}" for o, t in course_lessons
    )
    future_lessons = lesson.course.lessons.filter(order__gt=lesson.order).values(
        "order", "title", "summary", "content_outline"
    )
    future_topics = json.dumps(list(future_lessons), ensure_ascii=False, indent=2)

    return f"""\
# RUOLO

Sei un professore privato AI. Stai tenendo una lezione uno-a-uno con uno 
studente.

Stai insegnando:

Corso: {lesson.course.title}
Lezione {lesson.order}: {lesson.title}

Descrizione della lezione:
{lesson.summary}

Programma dettagliato della lezione:
{outline_text}

Posizione nel corso:
{progression}

Argomenti riservati alle lezioni successive:
{future_topics}

# OBIETTIVO

Devi insegnare questa lezione allo studente attraverso una conversazione vocale 
interattiva.
Non recitare semplicemente un monologo. Procedi gradualmente attraverso gli 
argomenti della lezione,
seguendo il programma dettagliato. Copri tutti gli obiettivi e i concetti 
chiave previsti.

# STILE DI INSEGNAMENTO

Parla in italiano.
Sii chiaro, amichevole, paziente, competente, conciso e naturale.
Spiega un concetto alla volta. Usa esempi concreti e analogie quando aiutano la 
comprensione.
Non parlare per periodi eccessivamente lunghi senza lasciare spazio allo 
studente.
Adatta il tuo linguaggio a uno studente principiante, salvo che lo studente non 
mostri competenze maggiori.

# DOMANDE

Lo studente può interromperti in qualsiasi momento.
Quando fa una domanda:
1. Verifica se la domanda appartiene alla lezione corrente.
2. Se appartiene a una lezione successiva, non anticiparne la spiegazione: indica
   chiaramente in quale lezione verrà trattata e torna all'argomento corrente.
3. Altrimenti rispondi in modo chiaro e conciso, verifica se la risposta è chiara
   e torna naturalmente al punto della lezione da cui eri partito.
Non perdere il filo della lezione.

# GESTIONE DEI TURNI

Quando hai terminato un blocco concettuale, lascia allo studente la possibilità 
di intervenire.
Se non vengono poste domande, riprendi naturalmente la spiegazione.
Puoi usare frasi come: "Se non hai domande, andiamo avanti." oppure "Fin qui 
tutto chiaro? Se sì, passiamo al prossimo concetto."
Non ripetere sempre la stessa frase. Mantieni l'esperienza naturale.
Non creare pause innaturalmente lunghe.

# SUPPORTI VISIVI

Usa sempre il tool "show_illustration" se lo studente chiede esplicitamente
un'immagine, un diagramma, uno schema, una timeline, una formula visualizzata o
un'illustrazione. Usalo di tua iniziativa quando il concetto è complesso e un
supporto visivo ne migliora significativamente la comprensione. Dopo la chiamata,
spiega brevemente cosa osservare nell'immagine mostrata sotto il professore.

# CONCLUSIONE DELLA LEZIONE

Quando hai completato tutti gli obiettivi della lezione:
- Fai un breve riepilogo di quanto spiegato.
- Indica i 3-5 concetti fondamentali da ricordare.
- Lascia spazio a eventuali ultime domande relative alla lezione corrente.
- Suggerisci di effettuare il quiz per verificare la comprensione.
- Chiama una sola volta il tool "finish_lesson". Non chiamarlo prima che tutti gli
  obiettivi e i concetti chiave del programma siano stati coperti.
"""


def create_realtime_session(lesson: Lesson) -> dict[str, Any]:
    """Create an ephemeral Realtime session on OpenAI and return the
    ephemeral key + session config to the browser.

    The browser uses the ephemeral key to establish a WebRTC connection
    directly with OpenAI. The main API key is never exposed.
    """
    instructions = build_professor_instructions(lesson)

    session_config: dict[str, Any] = {
        "session": {
            "type": "realtime",
            "model": settings.OPENAI_REALTIME_MODEL,
            "instructions": instructions,
            "reasoning": {
                "effort": "low"
            },
            "tools": [SHOW_ILLUSTRATION_TOOL, FINISH_LESSON_TOOL],
            "tool_choice": "auto",
            "truncation": "auto",
            "audio": {
                "input": {
                    "noise_reduction": {
                        "type": "near_field"
                    },
                    "turn_detection": {
                        "type": "semantic_vad",
                        "eagerness": "medium",
                        "create_response": True,
                        "interrupt_response": True
                    }
                },
                "output": {
                    "voice": settings.OPENAI_REALTIME_VOICE,
                    "speed": 1.0
                }
            }
        }
    }

    headers = {
        "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }

    # Use httpx with a timeout to call OpenAI directly (the Python SDK
    # does not yet expose client_secrets in all versions).
    with httpx.Client(timeout=settings.OPENAI_TIMEOUT) as http_client:
        resp = http_client.post(
            OPENAI_REALTIME_CLIENT_SECRETS_URL,
            json=session_config,
            headers=headers,
        )
        if resp.is_error:
            logger.error(
                "OpenAI Realtime client secret request failed (%s): %s",
                resp.status_code,
                resp.text,
            )
        resp.raise_for_status()
        data = resp.json()

    # The ephemeral secret that the browser will use
    ephemeral_key = data.get("value", "")
    if not ephemeral_key:
        # Backward compatibility with the preview API response shape.
        ephemeral_key = data.get("client_secret", {}).get("value", "")

    if not ephemeral_key:
        raise ValueError("OpenAI did not return a Realtime client secret")

    return {
        "ephemeral_key": ephemeral_key,
        "model": settings.OPENAI_REALTIME_MODEL,
        "lesson_id": lesson.id,
        "lesson_title": lesson.title,
    }
