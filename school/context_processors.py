from django.conf import settings

from .access import is_access_bypassed


def social_auth(request):
    context = {
        "google_login_enabled": bool(
            settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET
        ),
        "facebook_login_enabled": bool(
            settings.FACEBOOK_APP_ID and settings.FACEBOOK_APP_SECRET
        ),
    }
    if request.user.is_authenticated:
        context.update({
            "nav_course_count": request.user.course_purchases.filter(status="paid").count(),
            "nav_access_bypassed": is_access_bypassed(request.user),
        })
    return context
