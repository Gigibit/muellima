"""Modular AI agents used by Muellima's educational workflows."""

from .lesson_creation import LessonCreationAgent
from .professor import ProfessorAgent
from .quiz import QuizAgent

__all__ = ["LessonCreationAgent", "ProfessorAgent", "QuizAgent"]
