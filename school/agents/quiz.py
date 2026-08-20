from django.conf import settings

from .base import BoundedAgent


class QuizAgent(BoundedAgent):
    name = "quiz_agent"

    def __init__(self):
        super().__init__(settings.AGENT_MAX_ITERATIONS)

    @staticmethod
    def validate(quiz):
        questions = quiz.get("questions") or []
        if not 5 <= len(questions) <= 10:
            return "Genera da 5 a 10 domande."
        normalized_questions = set()
        for question in questions:
            text = str(question.get("question") or "").strip().casefold()
            options = question.get("options") or []
            correct_index = question.get("correct_index")
            if not text or text in normalized_questions:
                return "Le domande devono essere non vuote e non duplicate."
            normalized_questions.add(text)
            if len(options) != 4 or len({str(option).strip().casefold() for option in options}) != 4:
                return "Ogni domanda deve avere quattro opzioni distinte."
            if not isinstance(correct_index, int) or not 0 <= correct_index < 4:
                return "Ogni domanda deve indicare una risposta corretta valida."
            if not str(question.get("explanation") or "").strip():
                return "Ogni risposta deve avere una spiegazione."
        return None
