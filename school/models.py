"""Database models for Muellima.

Designed to be future-proof: every model that will eventually belong
to a user (Course, LessonSession, Quiz) has a nullable ``student``
ForeignKey placeholder commented out, ready to be activated when
authentication is added.
"""
import uuid

from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone


def validate_max_100_words(value: str) -> None:
    if len(value.split()) > 100:
        raise ValidationError("Il contesto non può superare 100 parole.")


class UserProfile(models.Model):
    REASONING_CHOICES = [
        ("low", "Low — più rapido"),
        ("medium", "Medium — bilanciato"),
        ("high", "High — più approfondito"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        related_name="school_profile",
        on_delete=models.CASCADE,
    )
    display_name = models.CharField(max_length=150)
    realtime_reasoning_effort = models.CharField(
        max_length=10,
        choices=REASONING_CHOICES,
        default="low",
    )
    learning_context = models.TextField(
        blank=True,
        max_length=1000,
        validators=[validate_max_100_words],
    )

    def __str__(self) -> str:
        return self.display_name


class Subscription(models.Model):
    PLAN_CHOICES = [
        ("base", "Base — €19,99/mese"),
        ("premium", "Premium — €45/mese"),
    ]
    STATUS_CHOICES = [
        ("inactive", "Non attivo"),
        ("incomplete", "Incompleto"),
        ("trialing", "In prova"),
        ("active", "Attivo"),
        ("past_due", "Pagamento scaduto"),
        ("unpaid", "Non pagato"),
        ("canceled", "Annullato"),
    ]
    ACCESS_STATUSES = {"active", "trialing"}

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        related_name="subscription",
        on_delete=models.CASCADE,
    )
    plan = models.CharField(max_length=10, choices=PLAN_CHOICES, blank=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="inactive",
    )
    stripe_customer_id = models.CharField(max_length=255, blank=True, db_index=True)
    stripe_subscription_id = models.CharField(max_length=255, blank=True, db_index=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def is_active(self) -> bool:
        return self.status in self.ACCESS_STATUSES

    @property
    def allows_illustrations(self) -> bool:
        return self.is_active and self.plan == "premium"

    def __str__(self) -> str:
        return f"{self.user} — {self.plan or 'nessun piano'} ({self.status})"


class CoursePurchase(models.Model):
    PLAN_CHOICES = [
        ("base", "Base — €9,99"),
        ("pro", "Pro — €19,99"),
        ("premium", "Premium — €49,99"),
    ]
    STATUS_CHOICES = [
        ("pending", "In attesa"),
        ("paid", "Pagato"),
        ("refunded", "Rimborsato"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="course_purchases",
        on_delete=models.CASCADE,
    )
    course = models.ForeignKey(
        "Course",
        related_name="purchases",
        on_delete=models.CASCADE,
    )
    plan = models.CharField(max_length=10, choices=PLAN_CHOICES)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="pending")
    stripe_customer_id = models.CharField(max_length=255, blank=True, db_index=True)
    stripe_checkout_session_id = models.CharField(max_length=255, blank=True, unique=True, null=True)
    stripe_payment_intent_id = models.CharField(max_length=255, blank=True, db_index=True)
    purchased_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "course"], name="unique_course_purchase")
        ]

    @property
    def is_paid(self) -> bool:
        return self.status == "paid"

    @property
    def allows_written_examples(self) -> bool:
        return self.is_paid and self.plan in {"pro", "premium"}

    @property
    def allows_illustrations(self) -> bool:
        return self.is_paid and self.plan == "premium"


class PurchaseWhitelist(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        related_name="purchase_whitelist_entry",
        on_delete=models.CASCADE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="purchase_whitelist_entries_created",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return getattr(self.user, "email", "") or str(self.user)


class CourseInterest(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="course_interests",
        on_delete=models.CASCADE,
    )
    course = models.ForeignKey(
        "Course",
        related_name="interests",
        on_delete=models.CASCADE,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "course"],
                name="unique_user_course_interest",
            )
        ]

    def __str__(self) -> str:
        return f"{self.user} — {self.course}"


class PaymentRecord(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="payments",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    stripe_invoice_id = models.CharField(max_length=255, unique=True)
    amount_cents = models.PositiveIntegerField(default=0)
    currency = models.CharField(max_length=3, default="eur")
    status = models.CharField(max_length=30)
    occurred_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-occurred_at"]


class StripeEvent(models.Model):
    stripe_event_id = models.CharField(max_length=255, unique=True)
    event_type = models.CharField(max_length=100)
    processed_at = models.DateTimeField(auto_now_add=True)


class UsageRecord(models.Model):
    KIND_CHOICES = [
        ("curriculum", "Generazione corso"),
        ("course_cache", "Corso dalla cache"),
        ("realtime_session", "Sessione Realtime"),
        ("realtime_response", "Risposta Realtime"),
        ("quiz", "Quiz"),
        ("illustration", "Illustrazione"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="usage_records",
        on_delete=models.CASCADE,
    )
    kind = models.CharField(max_length=30, choices=KIND_CHOICES)
    request_count = models.PositiveIntegerField(default=1)
    input_tokens = models.PositiveBigIntegerField(default=0)
    output_tokens = models.PositiveBigIntegerField(default=0)
    total_tokens = models.PositiveBigIntegerField(default=0)
    image_count = models.PositiveIntegerField(default=0)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class PageVisit(models.Model):
    visitor_id = models.UUIDField(default=uuid.uuid4, db_index=True, editable=False)
    ip_address = models.GenericIPAddressField(db_index=True)
    category = models.CharField(max_length=100)
    visit_count = models.PositiveBigIntegerField(default=1)
    last_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="page_visits",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    first_visited_at = models.DateTimeField(auto_now_add=True)
    last_visited_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-last_visited_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["visitor_id", "category"],
                name="unique_page_visit_per_visitor_category",
            )
        ]

    def __str__(self) -> str:
        return f"{self.ip_address} — {self.category} ({self.visit_count})"


class Course(models.Model):
    DIFFICULTY_CHOICES = [
        ("beginner", "Principiante"),
        ("intermediate", "Intermedio"),
        ("advanced", "Avanzato"),
    ]

    title = models.CharField(max_length=300)
    normalized_subject = models.CharField(max_length=300)
    cache_key = models.CharField(max_length=300, null=True, blank=True, unique=True)
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


class UserCourse(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="course_history",
        on_delete=models.CASCADE,
    )
    course = models.ForeignKey(
        Course,
        related_name="user_history",
        on_delete=models.CASCADE,
    )
    last_lesson = models.ForeignKey(
        "Lesson",
        related_name="+",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_accessed_at = models.DateTimeField(default=timezone.now, db_index=True)
    hidden_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-last_accessed_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "course"],
                name="unique_user_course_history",
            )
        ]

    def __str__(self) -> str:
        return f"{self.user} — {self.course}"


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
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="lesson_sessions",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
    )
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.PositiveIntegerField(default=0)
    is_trial = models.BooleanField(default=False)
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
