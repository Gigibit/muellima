"""Quiz generation via OpenAI Responses API with Structured Outputs."""
import json
from typing import Any

from openai import OpenAI

from django.conf import settings

from ..agents import QuizAgent
from .openai_client import get_client
from ..models import Lesson, Quiz, QuizQuestion

QUIZ_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 4,
                        "maxItems": 4,
                    },
                    "correct_index": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 3,
                    },
                    "explanation": {"type": "string"},
                },
                "required": [
                    "question",
                    "options",
                    "correct_index",
                    "explanation",
                ],
                "additionalProperties": False,
            },
            "minItems": 5,
            "maxItems": 10,
        },
    },
    "required": ["title", "questions"],
    "additionalProperties": False,
}

QUIZ_SYSTEM_PROMPT = """\
You are an expert quiz creator for an educational platform.

You will receive a course title, lesson title, lesson summary, and lesson 
content outline.

Generate a quiz strictly based on the lesson content provided.

Rules:
- Generate between 5 and 10 questions.
- Each question must have exactly 4 options.
- Exactly one answer must be correct (indicated by correct_index, 0-based).
- Include a brief explanation for each answer.
- Mix question types: understanding, application, conceptual reasoning.
- Avoid trivial or overly obvious questions.
- Do NOT test topics that have not been covered in the lesson.
- Write all content in Italian.
"""


def generate_quiz(lesson: Lesson, client: OpenAI | None = None) -> dict[str, 
Any]:
    """Generate a quiz for a lesson and persist it to the database.

    Returns a dict with quiz title and questions list.
    """
    if client is None:
        client = get_client()

    outline_text = json.dumps(lesson.content_outline, ensure_ascii=False, 
indent=2)

    user_prompt = f"""\
Course: {lesson.course.title}
Lesson: {lesson.title}
Lesson summary: {lesson.summary}

Lesson content outline:
{outline_text}

Generate a quiz for this lesson.
"""

    agent = QuizAgent()

    def execute(attempt: int, feedback: str):
        iteration_input = user_prompt
        if feedback:
            iteration_input += f"\nCorreggi il quiz precedente: {feedback}"
        response = client.responses.create(
            model=settings.OPENAI_TEXT_MODEL,
            instructions=QUIZ_SYSTEM_PROMPT,
            input=iteration_input,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "lesson_quiz",
                    "schema": QUIZ_SCHEMA,
                    "strict": True,
                }
            },
        )
        return json.loads(response.output_text), response.usage

    data = agent.run(execute, agent.validate)

    # Persist to database
    quiz = Quiz.objects.create(lesson=lesson)
    for idx, q in enumerate(data["questions"]):
        QuizQuestion.objects.create(
            quiz=quiz,
            question=q["question"],
            options=q["options"],
            correct_answer=q["correct_index"],
            explanation=q["explanation"],
            order=idx,
        )

    return data
