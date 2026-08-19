"""Database models for Personal School.

Designed to be future-proof: every model that will eventually belong
to a user (Course, LessonSession, Quiz) has a nullable ``student``
ForeignKey placeholder commented out, ready to be activated when
authentication is added.
"""
from django.db import models


class Course(models.Model):
    DIFFICULTY_CHOICES = [
        ("beginner", "Principiante"),
        ("intermediate", "Intermedio"),
        ("advanced", "Avanzato"),
    ]

    title = models.CharField(max_length=300)
    normalized_subject = models.CharField(max_length=300)
    description = models.TextField()
    difficulty = models.CharField(
        max_length=20, choices=DIFFICULTY_CHOICES, default="beginner"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # student = models.ForeignKey(
    #     "auth.User", null=True, blank=True, on_delete=models.CASCADE
    # )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.title


class Lesson(models.Model):
    course = models.ForeignKey(Course, related_name="lessons", 
on_delete=models.CASCADE)
    order = models.PositiveIntegerField()
    title = models.CharField(max_length=400)
    summary = models.TextField()
    content_outline = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order"]
        unique_together = [("course", "order")]

    def __str__(self) -> str:
        return f"{self.order}. {self.title}"


class LessonSession(models.Model):
    STATUS_CHOICES = [
        ("active", "Attiva"),
        ("completed", "Completata"),
        ("abandoned", "Abbandonata"),
    ]

    lesson = models.ForeignKey(
        Lesson, related_name="sessions", on_delete=models.CASCADE
    )
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="active"
    )

    # student = models.ForeignKey(
    #     "auth.User", null=True, blank=True, on_delete=models.CASCADE
    # )

    class Meta:
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return f"Session {self.id} — {self.lesson.title}"


class Quiz(models.Model):
    lesson = models.ForeignKey(
        Lesson, related_name="quizzes", on_delete=models.CASCADE
    )
    created_at = models.DateTimeField(auto_now_add=True)

    # student = models.ForeignKey(
    #     "auth.User", null=True, blank=True, on_delete=models.CASCADE
    # )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Quiz — {self.lesson.title}"


class QuizQuestion(models.Model):
    quiz = models.ForeignKey(
        Quiz, related_name="questions", on_delete=models.CASCADE
    )
    question = models.TextField()
    options = models.JSONField(default=list)
    correct_answer = models.PositiveSmallIntegerField()  # index into options
    explanation = models.TextField()
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order"]

    def __str__(self) -> str:
        return f"Q{self.order}: {self.question[:60]}…"

