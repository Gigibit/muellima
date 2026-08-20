from django.contrib import admin

from .models import (
    Course,
    CourseInterest,
    CoursePurchase,
    Lesson,
    LessonSession,
    PaymentRecord,
    PageVisit,
    PurchaseWhitelist,
    Quiz,
    QuizQuestion,
    StripeEvent,
    Subscription,
    UsageRecord,
    UserCourse,
    UserProfile,
)


@admin.register(PurchaseWhitelist)
class PurchaseWhitelistAdmin(admin.ModelAdmin):
    list_display = ("user", "created_at", "created_by")
    search_fields = ("user__email", "user__username")


@admin.register(CourseInterest)
class CourseInterestAdmin(admin.ModelAdmin):
    list_display = ("user", "course", "created_at")
    search_fields = ("user__email", "course__title")


@admin.register(UserCourse)
class UserCourseAdmin(admin.ModelAdmin):
    list_display = ("user", "course", "last_lesson", "last_accessed_at", "hidden_at")
    search_fields = ("user__email", "course__title")
    list_filter = ("hidden_at",)


@admin.register(PageVisit)
class PageVisitAdmin(admin.ModelAdmin):
    list_display = ("visitor_id", "ip_address", "category", "visit_count", "last_user", "last_visited_at")
    search_fields = ("visitor_id", "ip_address", "category", "last_user__email")
    readonly_fields = ("first_visited_at", "last_visited_at")


@admin.register(CoursePurchase)
class CoursePurchaseAdmin(admin.ModelAdmin):
    list_display = ("user", "course", "plan", "status", "purchased_at")
    list_filter = ("plan", "status")
    search_fields = ("user__email", "course__title", "stripe_payment_intent_id")


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
