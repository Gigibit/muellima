from django.conf import settings

from .base import BoundedAgent


class LessonCreationAgent(BoundedAgent):
    name = "lesson_creation_agent"

    def __init__(self):
        super().__init__(settings.AGENT_MAX_ITERATIONS)

    @staticmethod
    def validate(curriculum):
        if not curriculum.get("valid") or curriculum.get("needs_clarification"):
            return None
        count = len(curriculum.get("lessons") or [])
        if count < settings.MIN_LESSON:
            return f"Genera almeno {settings.MIN_LESSON} lezioni distinte."
        if count > settings.MAX_LESSON:
            return f"Non superare {settings.MAX_LESSON} lezioni."
        orders = [lesson.get("order") for lesson in curriculum.get("lessons", [])]
        if orders != list(range(1, count + 1)):
            return "Numera le lezioni consecutivamente a partire da 1."
        return None
