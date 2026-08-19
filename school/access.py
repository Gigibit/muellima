from functools import wraps

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.http import JsonResponse
from django.shortcuts import redirect

from .models import Subscription


def normalized_email(user) -> str:
    return (getattr(user, "email", "") or "").strip().casefold()


def is_access_bypassed(user) -> bool:
    return bool(
        settings.MOCK
        or (user.is_authenticated and normalized_email(user) in settings.USERS_WHITELIST)
    )


def get_subscription(user) -> Subscription:
    subscription, _ = Subscription.objects.get_or_create(user=user)
    return subscription


def has_lesson_access(user) -> bool:
    if not user.is_authenticated:
        return False
    return is_access_bypassed(user) or get_subscription(user).is_active


def can_generate_illustrations(user) -> bool:
    if not user.is_authenticated:
        return False
    return is_access_bypassed(user) or get_subscription(user).allows_illustrations


def subscription_required(*, api: bool = False):
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                if api:
                    return JsonResponse(
                        {"success": False, "error": {"code": "AUTH_REQUIRED", "message": "Accedi per continuare."}},
                        status=401,
                    )
                return redirect_to_login(request.get_full_path())
            if not has_lesson_access(request.user):
                if api:
                    return JsonResponse(
                        {"success": False, "error": {"code": "SUBSCRIPTION_REQUIRED", "message": "Scegli un piano per iniziare la lezione."}},
                        status=403,
                    )
                return redirect("plans")
            return view_func(request, *args, **kwargs)
        return wrapped
    return decorator


def api_login_required(view_func):
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse(
                {"success": False, "error": {"code": "AUTH_REQUIRED", "message": "Accedi per creare un corso."}},
                status=401,
            )
        return view_func(request, *args, **kwargs)
    return wrapped
