import json
from functools import wraps

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import redirect
from django.utils import timezone

from .models import Course, CoursePurchase, Lesson, Subscription, UserCourse


def normalized_email(user) -> str:
    return (getattr(user, "email", "") or "").strip().casefold()


def is_access_bypassed(user) -> bool:
    return bool(user.is_authenticated and normalized_email(user) in settings.USERS_WHITELIST)


def get_subscription(user) -> Subscription:
    """Legacy accessor retained for historical admin data."""
    subscription, _ = Subscription.objects.get_or_create(user=user)
    return subscription


def get_course_purchase(user, course) -> CoursePurchase | None:
    if not user.is_authenticated or not course:
        return None
    return CoursePurchase.objects.filter(user=user, course=course, status="paid").first()


def touch_user_course(user, course, *, lesson=None) -> UserCourse | None:
    if not user.is_authenticated or not course:
        return None
    defaults = {"last_accessed_at": timezone.now(), "hidden_at": None}
    if lesson is not None and lesson.course_id == course.id:
        defaults["last_lesson"] = lesson
    history, _ = UserCourse.objects.update_or_create(
        user=user,
        course=course,
        defaults=defaults,
    )
    return history


def free_trial_seconds_remaining(user, course) -> int:
    if not user.is_authenticated or not course:
        return 0
    if settings.MOCK_TIME > 0:
        # Demo mode is intentionally global per account, not renewed per course.
        limit = settings.MOCK_TIME * 60
        sessions = user.lesson_sessions.filter(is_trial=True)
    else:
        limit = settings.FREE_TRIAL_MINUTES * 60
        sessions = user.lesson_sessions.filter(is_trial=True, lesson__course=course)
    used = sessions.aggregate(total=Sum("duration_seconds"))["total"] or 0
    active_elapsed = sum(
        max(0, int((timezone.now() - started_at).total_seconds()))
        for started_at in sessions.filter(status="active").values_list("started_at", flat=True)
    )
    return max(0, limit - used - active_elapsed)


def has_lesson_access(user, course) -> bool:
    return bool(user.is_authenticated and (
        is_access_bypassed(user)
        or get_course_purchase(user, course)
        or free_trial_seconds_remaining(user, course) > 0
    ))


def can_show_written_examples(user, course) -> bool:
    if is_access_bypassed(user):
        return True
    purchase = get_course_purchase(user, course)
    return bool(purchase and purchase.allows_written_examples)


def can_generate_illustrations(user, course) -> bool:
    if is_access_bypassed(user):
        return True
    purchase = get_course_purchase(user, course)
    return bool(purchase and purchase.allows_illustrations)


def _request_course(request, kwargs):
    if kwargs.get("course_id"):
        return Course.objects.filter(id=kwargs["course_id"]).first()
    if kwargs.get("lesson_id"):
        lesson = Lesson.objects.select_related("course").filter(id=kwargs["lesson_id"]).first()
        return lesson.course if lesson else None
    try:
        lesson_id = json.loads(request.body or b"{}").get("lesson_id")
    except (json.JSONDecodeError, TypeError):
        lesson_id = None
    lesson = Lesson.objects.select_related("course").filter(id=lesson_id).first() if lesson_id else None
    return lesson.course if lesson else None


def subscription_required(*, api: bool = False):
    """Legacy name: enforce purchase or trial for the request's course."""
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                if api:
                    return JsonResponse({"success": False, "error": {"code": "AUTH_REQUIRED", "message": "Accedi per continuare."}}, status=401)
                return redirect_to_login(request.get_full_path())
            course = _request_course(request, kwargs)
            if not has_lesson_access(request.user, course):
                if api:
                    return JsonResponse({"success": False, "error": {"code": "COURSE_PURCHASE_REQUIRED", "message": "Hai terminato il tempo gratuito disponibile. Acquista il corso per continuare."}}, status=403)
                return redirect(f"/plans/?course_id={course.id}" if course else "/")
            return view_func(request, *args, **kwargs)
        return wrapped
    return decorator


def api_login_required(view_func):
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"success": False, "error": {"code": "AUTH_REQUIRED", "message": "Accedi per creare un corso."}}, status=401)
        return view_func(request, *args, **kwargs)
    return wrapped
