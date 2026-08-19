from django.contrib import admin

from .models import (
    Course,
    Lesson,
    LessonSession,
    PaymentRecord,
    Quiz,
    QuizQuestion,
    StripeEvent,
    Subscription,
    UsageRecord,
    UserProfile,
)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("display_name", "user", "realtime_reasoning_effort")
    search_fields = ("display_name", "user__email")


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("user", "plan", "status", "current_period_end", "updated_at")
    list_filter = ("plan", "status")
    search_fields = ("user__email", "stripe_customer_id", "stripe_subscription_id")


@admin.register(PaymentRecord)
class PaymentRecordAdmin(admin.ModelAdmin):
    list_display = ("user", "amount_cents", "currency", "status", "occurred_at")
    list_filter = ("status", "currency")
    search_fields = ("user__email", "stripe_invoice_id")


@admin.register(UsageRecord)
class UsageRecordAdmin(admin.ModelAdmin):
    list_display = ("user", "kind", "request_count", "total_tokens", "image_count", "created_at")
    list_filter = ("kind",)
    search_fields = ("user__email",)


@admin.register(StripeEvent)
class StripeEventAdmin(admin.ModelAdmin):
    list_display = ("stripe_event_id", "event_type", "processed_at")
    search_fields = ("stripe_event_id", "event_type")


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("title", "normalized_subject", "difficulty", "created_at")
    list_filter = ("difficulty",)
    search_fields = ("title", "normalized_subject")


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ("order", "title", "course")
    list_filter = ("course",)
    search_fields = ("title",)


@admin.register(LessonSession)
class LessonSessionAdmin(admin.ModelAdmin):
    list_display = ("lesson", "student", "status", "started_at", "ended_at")
    list_filter = ("status",)


@admin.register(Quiz)
class QuizAdmin(admin.ModelAdmin):
    list_display = ("lesson", "created_at")


@admin.register(QuizQuestion)
class QuizQuestionAdmin(admin.ModelAdmin):
    list_display = ("quiz", "order", "question")
