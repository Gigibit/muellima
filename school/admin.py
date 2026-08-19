from django.contrib import admin

from .models import Course, Lesson, LessonSession, Quiz, QuizQuestion


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
    list_display = ("lesson", "status", "started_at", "ended_at")
    list_filter = ("status",)


@admin.register(Quiz)
class QuizAdmin(admin.ModelAdmin):
    list_display = ("lesson", "created_at")


@admin.register(QuizQuestion)
class QuizQuestionAdmin(admin.ModelAdmin):
    list_display = ("quiz", "order", "question")

