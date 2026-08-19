"""Django views for Muellima.

Pages are rendered with Django Templates. API endpoints return JSON.
All OpenAI calls are delegated to service modules — no API keys or
OpenAI SDK calls appear in views.
"""
import json
import logging
import unicodedata

from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_exempt, csrf_protect

from .access import (
    api_login_required,
    can_generate_illustrations,
    get_subscription,
    has_lesson_access,
    is_access_bypassed,
    subscription_required,
)
from .billing import (
    PLAN_CONFIG,
    construct_webhook_event,
    create_checkout_session,
    create_portal_session,
    process_webhook_event,
)
from .models import Course, Lesson, LessonSession, PaymentRecord, Subscription, UsageRecord, UserProfile
from .forms import UserProfileForm
from .signals import default_display_name
from .services.curriculum_service import generate_curriculum
from .services.quiz_service import generate_quiz
from .services.realtime_service import create_realtime_session as create_realtime_session_service
from .services.illustration_service import create_illustration
from .usage import record_usage

logger = logging.getLogger(__name__)

COMMON_SUBJECTS = [
    "Biologia", "Chimica", "Diritto", "Economia", "Filosofia", "Fisica",
    "Geografia", "Informatica", "Inglese", "Italiano", "Latino", "Marketing",
    "Matematica", "Python", "Scienze", "Storia", "Storia dell'arte",
]
GENERIC_SUBJECTS = {subject.casefold() for subject in COMMON_SUBJECTS} | {
    "letteratura", "programmazione", "arte", "musica",
}


def normalize_subject(subject: str) -> str:
    normalized = unicodedata.normalize("NFKC", subject).casefold()
    return " ".join(normalized.split())


@require_GET
def subject_suggestions(request):
    query = normalize_subject(request.GET.get("q", ""))[:100]
    suggestions = []
    if query:
        suggestions.extend(
            subject for subject in COMMON_SUBJECTS
            if query in subject.casefold()
        )
        cached = Course.objects.filter(
            Q(title__icontains=query) | Q(normalized_subject__icontains=query)
        ).values_list("title", flat=True)[:10]
        suggestions.extend(cached)
    unique = list(dict.fromkeys(suggestions))[:8]
    return JsonResponse({"suggestions": unique})

# ── Error response helper ──────────────────────────────────────────
def error_response(code: str, message: str, status: int = 400) -> JsonResponse:
    return JsonResponse(
        {"success": False, "error": {"code": code, "message": message}},
        status=status,
    )


# ── Pages ──────────────────────────────────────────────────────────

def home(request):
    """Home page: hero with subject input."""
    return render(request, "school/home.html")


def login_page(request):
    if request.user.is_authenticated:
        return redirect("plans")
    return render(request, "school/login.html")


@login_required
def profile_page(request):
    profile, _ = UserProfile.objects.get_or_create(
        user=request.user,
        defaults={"display_name": default_display_name(request.user)},
    )

    if request.method == "POST":
        form = UserProfileForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, "Profilo aggiornato.")
            return redirect("profile")
    else:
        form = UserProfileForm(instance=profile)

    return render(request, "school/profile.html", {
        "form": form,
        "subscription": get_subscription(request.user),
        "access_bypassed": is_access_bypassed(request.user),
    })


@login_required
def plans_page(request):
    return render(request, "school/plans.html", {
        "plans": PLAN_CONFIG,
        "subscription": get_subscription(request.user),
        "access_bypassed": is_access_bypassed(request.user),
        "next_url": request.GET.get("next", ""),
    })


@staff_member_required
def staff_dashboard(request):
    users = list(get_user_model().objects.select_related("school_profile", "subscription").order_by("-date_joined"))
    for user in users:
        usage = user.usage_records.aggregate(
            requests=Sum("request_count"),
            tokens=Sum("total_tokens"),
            images=Sum("image_count"),
        )
        user.usage_requests = usage["requests"] or 0
        user.usage_tokens = usage["tokens"] or 0
        user.usage_images = usage["images"] or 0
        user.payments_cents = user.payments.filter(status="paid").aggregate(
            total=Sum("amount_cents")
        )["total"] or 0
    totals = UsageRecord.objects.aggregate(
        requests=Sum("request_count"),
        input_tokens=Sum("input_tokens"),
        output_tokens=Sum("output_tokens"),
        total_tokens=Sum("total_tokens"),
        images=Sum("image_count"),
    )
    return render(request, "school/dashboard.html", {
        "users": users,
        "totals": totals,
        "user_count": get_user_model().objects.count(),
        "active_subscriptions": Subscription.objects.filter(status__in=Subscription.ACCESS_STATUSES).count(),
        "payments": PaymentRecord.objects.select_related("user")[:50],
        "revenue_cents": PaymentRecord.objects.filter(status="paid").aggregate(total=Sum("amount_cents"))["total"] or 0,
    })


def course_page(request, course_id: int):
    """Course detail page: shows lessons list."""
    course = get_object_or_404(Course, id=course_id)
    lessons = course.lessons.all()
    if not request.user.is_authenticated:
        action_url = f"{reverse('login')}?next={reverse('lesson_page', args=[course.id])}"
        action_label = "Accedi per iniziare"
    elif has_lesson_access(request.user):
        action_url = reverse("lesson_page", args=[course.id])
        action_label = "Inizia a studiare →"
    else:
        action_url = f"{reverse('plans')}?next={reverse('lesson_page', args=[course.id])}"
        action_label = "Scegli un piano per iniziare"
    return render(request, "school/course.html", {
        "course": course,
        "lessons": lessons,
        "action_url": action_url,
        "action_label": action_label,
    })


@subscription_required()
def lesson_page(request, course_id: int):
    """Professor page: Realtime voice lesson interface."""
    course = get_object_or_404(Course, id=course_id)
    lessons = course.lessons.all()
    if not lessons.exists():
        return redirect("course_page", course_id=course_id)
    return render(request, "school/lesson.html", {"course": course, "lessons": 
lessons})


# ── API endpoints ──────────────────────────────────────────────────

@csrf_protect
@require_POST
@api_login_required
def generate_course(request):
    """Generate a course from a subject string.

    POST body: {"subject": "Fisica quantistica"}
    Returns: {"success": true, "course_id": 1} or error.
    """
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return error_response("INVALID_REQUEST", "Richiesta non valida.")

    subject = (data.get("subject") or "").strip()
    clarification = (data.get("clarification") or "").strip()

    if not subject or len(subject) < 2:
        return error_response("EMPTY_SUBJECT", "Inserisci una materia o un argomento.")

    if len(subject) > 200:
        return error_response("SUBJECT_TOO_LONG", "L'argomento è troppo lungo (massimo 200 caratteri).")
    if len(clarification) > 200:
        return error_response("CLARIFICATION_TOO_LONG", "La specificazione è troppo lunga.")

    base_subject_key = normalize_subject(subject)
    cache_key = normalize_subject(f"{subject} {clarification}")
    requires_scope_check = not clarification and base_subject_key in GENERIC_SUBJECTS
    cached_course = None if requires_scope_check else Course.objects.filter(cache_key=cache_key).first()
    if not cached_course and not requires_scope_check and not clarification:
        cached_course = Course.objects.filter(normalized_subject__iexact=subject).first()
        if cached_course and not cached_course.cache_key:
            cached_course.cache_key = cache_key
            cached_course.save(update_fields=["cache_key"])
    if cached_course:
        record_usage(
            request.user,
            "course_cache",
            metadata={"course_id": cached_course.id, "subject": cache_key},
        )
        return JsonResponse({"success": True, "course_id": cached_course.id, "cached": True})

    try:
        curriculum = generate_curriculum(subject, clarification=clarification)
    except Exception:
        logger.exception("Curriculum generation failed")
        return error_response(
            "OPENAI_UNAVAILABLE",
            "Non sono riuscito a contattare il servizio AI. Riprova tra qualche istante.",
            status=503,
        )

    usage = curriculum.pop("_usage", None)
    record_usage(
        request.user,
        "curriculum",
        usage,
        metadata={"subject": cache_key, "clarification": bool(clarification)},
    )

    if not curriculum.get("valid"):
        reason = curriculum.get("reason", "Argomento non valido.")
        return error_response("INVALID_SUBJECT", f"Non sono riuscito a creare un corso su questo argomento. {reason}")

    if curriculum.get("needs_clarification"):
        question = curriculum.get("clarification_question", "Puoi specificare meglio il livello desiderato?")
        options = [str(option).strip() for option in curriculum.get("clarification_options", []) if str(option).strip()]
        if not options:
            return error_response("CLARIFICATION_MISSING", "Non sono riuscito a determinare le opzioni di approfondimento.")
        return JsonResponse({
            "success": False,
            "needs_clarification": True,
            "question": question,
            "options": options[:10],
        })

    lessons_data = curriculum.get("lessons", [])
    if not lessons_data:
        return error_response("NO_LESSONS", "Il corso non contiene lezioni.")

    # Persist course
    course = Course.objects.create(
        title=curriculum["title"],
        normalized_subject=curriculum["normalized_subject"],
        cache_key=cache_key,
        description=curriculum["description"],
        difficulty=curriculum.get("difficulty", "beginner"),
    )

    # Persist lessons
    for lesson_data in lessons_data:
        Lesson.objects.create(
            course=course,
            order=lesson_data["order"],
            title=lesson_data["title"],
            summary=lesson_data["summary"],
            content_outline={
                "objectives": lesson_data.get("objectives", []),
                "key_concepts": lesson_data.get("key_concepts", []),
                "examples": lesson_data.get("examples", []),
                "prerequisites": lesson_data.get("prerequisites", []),
            },
        )

    return JsonResponse({"success": True, "course_id": course.id})


@csrf_protect
@require_POST
@subscription_required(api=True)
def create_realtime_session(request):
    """Create an OpenAI Realtime ephemeral session for a lesson.

    POST body: {"lesson_id": 42}
    Returns: {"success": true, "ephemeral_key": "...", "model": "..."}
    """
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return error_response("INVALID_REQUEST", "Richiesta non valida.")

    lesson_id = data.get("lesson_id")
    if not lesson_id:
        return error_response("MISSING_LESSON", "Lezione non specificata.")

    lesson = get_object_or_404(Lesson, id=lesson_id)

    try:
        profile, _ = UserProfile.objects.get_or_create(
            user=request.user,
            defaults={"display_name": default_display_name(request.user)},
        )
        session = create_realtime_session_service(
            lesson,
            learner_name=profile.display_name,
            reasoning_effort=profile.realtime_reasoning_effort,
            learning_context=profile.learning_context,
            allow_illustrations=can_generate_illustrations(request.user),
        )
    except Exception:
        logger.exception("Realtime session creation failed")
        return error_response(
            "REALTIME_ERROR",
            "Non sono riuscito ad avviare la sessione vocale. Riprova.",
            status=503,
        )

    # Create a LessonSession record
    LessonSession.objects.create(lesson=lesson, student=request.user, status="active")
    record_usage(
        request.user,
        "realtime_session",
        metadata={"lesson_id": lesson.id},
    )

    return JsonResponse({"success": True, **session})


@csrf_protect
@require_POST
@subscription_required(api=True)
def generate_quiz(request, lesson_id: int):
    """Generate a quiz for a specific lesson.

    Returns: {"success": true, "title": "...", "questions": [...]}
    """
    lesson = get_object_or_404(Lesson, id=lesson_id)

    try:
        quiz_data = generate_quiz(lesson)
    except Exception:
        logger.exception("Quiz generation failed")
        return error_response(
            "QUIZ_ERROR",
            "Non sono riuscito a generare il quiz. Riprova tra qualche istante.",
            status=503,
        )

    usage = quiz_data.pop("_usage", None)
    record_usage(request.user, "quiz", usage, metadata={"lesson_id": lesson.id})
    return JsonResponse({"success": True, **quiz_data})


@csrf_protect
@require_POST
@subscription_required(api=True)
def complete_lesson(request, lesson_id: int):
    """Mark the most recent active session for a lesson as completed."""
    lesson = get_object_or_404(Lesson, id=lesson_id)
    lesson_session = lesson.sessions.filter(student=request.user, status="active").first()

    if lesson_session:
        lesson_session.status = "completed"
        lesson_session.ended_at = timezone.now()
        lesson_session.save(update_fields=["status", "ended_at"])

    return JsonResponse({"success": True, "lesson_id": lesson.id})


@csrf_protect
@require_POST
@subscription_required(api=True)
def generate_illustration(request):
    """Generate an educational illustration.

    POST body: {"title": "...", "concept": "...", "visual_type": "...", 
"description": "..."}
    Returns: {"success": true, "image_url": "...", "title": "..."}
    """
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return error_response("INVALID_REQUEST", "Richiesta non valida.")

    title = (data.get("title") or "").strip()
    concept = (data.get("concept") or "").strip()
    visual_type = (data.get("visual_type") or "illustration").strip()
    description = (data.get("description") or "").strip()

    if not concept:
        return error_response("MISSING_CONCEPT", "Concept non specificato.")

    if not can_generate_illustrations(request.user):
        return error_response(
            "PREMIUM_REQUIRED",
            "Le illustrazioni sono disponibili con il piano Premium.",
            status=403,
        )

    try:
        result = create_illustration(title, concept, visual_type, description)
    except Exception:
        logger.exception("Illustration generation failed")
        return error_response(
            "ILLUSTRATION_ERROR",
            "Non sono riuscito a generare l'illustrazione.",
            status=503,
        )

    usage = result.pop("_usage", None)
    record_usage(
        request.user,
        "illustration",
        usage,
        image_count=1,
        metadata={"visual_type": visual_type},
    )
    return JsonResponse({"success": True, **result})


@login_required
@require_POST
def create_checkout(request, plan: str):
    if plan not in PLAN_CONFIG:
        messages.error(request, "Piano non valido.")
        return redirect("plans")
    if settings.MOCK:
        subscription = get_subscription(request.user)
        subscription.plan = plan
        subscription.status = "active"
        subscription.save(update_fields=["plan", "status", "updated_at"])
        messages.success(request, "Abbonamento mock attivato.")
        next_url = request.POST.get("next", "")
        if next_url and url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            return redirect(next_url)
        return redirect("profile")
    try:
        checkout = create_checkout_session(
            request.user,
            plan,
            request.build_absolute_uri(reverse("checkout_success")),
            request.build_absolute_uri(reverse("plans")),
        )
    except Exception:
        logger.exception("Stripe checkout creation failed")
        messages.error(request, "Non è stato possibile avviare il pagamento.")
        return redirect("plans")
    return redirect(checkout.url)


@login_required
def checkout_success(request):
    messages.success(
        request,
        "Pagamento ricevuto. L’accesso si attiverà non appena Stripe conferma il webhook.",
    )
    return redirect("profile")


@login_required
@require_POST
def billing_portal(request):
    try:
        portal = create_portal_session(
            request.user,
            request.build_absolute_uri(reverse("profile")),
        )
    except Exception:
        logger.exception("Stripe portal creation failed")
        messages.error(request, "Portale pagamenti non disponibile.")
        return redirect("profile")
    return redirect(portal.url)


@csrf_exempt
@require_POST
def stripe_webhook(request):
    try:
        event = construct_webhook_event(
            request.body,
            request.headers.get("Stripe-Signature", ""),
        )
        process_webhook_event(event)
    except (ValueError, KeyError):
        logger.warning("Invalid Stripe webhook", exc_info=True)
        return HttpResponse(status=400)
    except Exception:
        logger.exception("Stripe webhook processing failed")
        return HttpResponse(status=400)
    return HttpResponse(status=200)


@csrf_protect
@require_POST
@subscription_required(api=True)
def record_realtime_usage(request):
    try:
        data = json.loads(request.body)
        input_tokens = min(max(int(data.get("input_tokens", 0)), 0), 10_000_000)
        output_tokens = min(max(int(data.get("output_tokens", 0)), 0), 10_000_000)
        total_tokens = min(
            max(int(data.get("total_tokens", input_tokens + output_tokens)), 0),
            20_000_000,
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        return error_response("INVALID_USAGE", "Dati di utilizzo non validi.")
    UsageRecord.objects.create(
        user=request.user,
        kind="realtime_response",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        metadata={"lesson_id": data.get("lesson_id")},
    )
    return JsonResponse({"success": True})
