"""Django views for Muellima.

Pages are rendered with Django Templates. API endpoints return JSON.
All OpenAI calls are delegated to service modules — no API keys or
OpenAI SDK calls appear in views.
"""
import json
import logging
import unicodedata

from django.conf import settings
from django.core import signing
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model
from django.contrib.auth import login as auth_login
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_exempt, csrf_protect

from .access import (
    api_login_required,
    can_generate_illustrations,
    can_show_written_examples,
    free_trial_seconds_remaining,
    get_course_purchase,
    get_subscription,
    has_lesson_access,
    is_access_bypassed,
    subscription_required,
    touch_user_course,
)
from .billing import (
    PLAN_CONFIG,
    construct_webhook_event,
    create_checkout_session,
    create_portal_session,
    process_webhook_event,
)
from .models import Course, CourseInterest, CoursePurchase, Lesson, LessonSession, PageVisit, PaymentRecord, PurchaseWhitelist, Subscription, UsageRecord, UserCourse, UserProfile
from .forms import EmailAuthenticationForm, RegistrationForm, UserProfileForm
from .signals import default_display_name
from .services.curriculum_service import generate_curriculum
from .services.quiz_service import generate_quiz as generate_quiz_service
from .services.realtime_service import create_realtime_session as create_realtime_session_service
from .services.illustration_service import create_illustration
from .usage import estimate_usage_cost, record_usage

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


def _auth_redirect(request, fallback="plans"):
    next_url = request.POST.get("next") or request.GET.get("next") or ""
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(next_url)
    return redirect(fallback)


def login_page(request):
    if request.user.is_authenticated:
        return _auth_redirect(request)
    form = EmailAuthenticationForm(request=request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        auth_login(request, form.get_user())
        messages.success(request, "Accesso effettuato.")
        return _auth_redirect(request)
    return render(request, "school/login.html", {
        "form": form,
        "next_url": request.POST.get("next") or request.GET.get("next") or "",
    })


def register_page(request):
    if request.user.is_authenticated:
        return _auth_redirect(request)
    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        auth_login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(request, "Account creato. Benvenuto su Muellima!")
        return _auth_redirect(request)
    return render(request, "school/register.html", {
        "form": form,
        "next_url": request.POST.get("next") or request.GET.get("next") or "",
    })


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
        "purchases": request.user.course_purchases.filter(status="paid").select_related("course"),
        "access_bypassed": is_access_bypassed(request.user),
    })


@login_required
def plans_page(request):
    course_id = request.GET.get("course_id", "")
    course = get_object_or_404(Course, id=int(course_id)) if course_id.isdigit() else None
    return render(request, "school/plans.html", {
        "plans": PLAN_CONFIG,
        "course": course,
        "purchase": get_course_purchase(request.user, course),
        "access_bypassed": is_access_bypassed(request.user),
        "next_url": request.GET.get("next", ""),
        "mock_demo": settings.MOCK_TIME > 0,
        "trial_minutes": settings.MOCK_TIME if settings.MOCK_TIME > 0 else settings.FREE_TRIAL_MINUTES,
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
        user.estimated_cost_usd = estimate_usage_cost(user.usage_records.all())["total"]
        attributed_visits = user.page_visits.aggregate(total=Sum("visit_count"))["total"] or 0
        user.page_visit_count = attributed_visits
        user.visit_ips = ", ".join(
            user.page_visits.order_by("ip_address")
            .values_list("ip_address", flat=True)
            .distinct()
        ) or "—"
        user.payments_cents = user.payments.filter(status="paid").aggregate(
            total=Sum("amount_cents")
        )["total"] or 0
        purchases = list(user.course_purchases.filter(status="paid"))
        user.purchased_course_count = len(purchases)
        user.purchase_plans = ", ".join(sorted({purchase.plan.title() for purchase in purchases})) or "—"
    totals = UsageRecord.objects.aggregate(
        requests=Sum("request_count"),
        input_tokens=Sum("input_tokens"),
        output_tokens=Sum("output_tokens"),
        total_tokens=Sum("total_tokens"),
        images=Sum("image_count"),
    )
    visit_totals = PageVisit.objects.aggregate(visits=Sum("visit_count"))
    category_labels = {
        "homepage": "Homepage",
        "course": "Corso / programma",
        "lessons": "Lezioni",
        "profile": "Profilo",
        "plans": "Piani e acquisto",
        "login": "Login",
        "dashboard": "Dashboard",
    }
    top_pages = list(
        PageVisit.objects.values("category")
        .annotate(visits=Sum("visit_count"))
        .order_by("-visits")[:20]
    )
    for page in top_pages:
        page["label"] = category_labels.get(page["category"], page["category"].replace("_", " ").title())

    ip_visitors = {}
    for visit in PageVisit.objects.select_related("last_user").order_by("-last_visited_at"):
        summary = ip_visitors.setdefault(visit.visitor_id, {
            "visitor_id": visit.visitor_id,
            "ip_address": visit.ip_address,
            "visits": 0,
            "last_user": visit.last_user,
            "last_category": category_labels.get(visit.category, visit.category.replace("_", " ").title()),
            "last_visited_at": visit.last_visited_at,
        })
        summary["visits"] += visit.visit_count
    ip_visitors = sorted(ip_visitors.values(), key=lambda item: item["last_visited_at"], reverse=True)
    estimated_costs = estimate_usage_cost(UsageRecord.objects.all())
    purchase_whitelist = PurchaseWhitelist.objects.select_related("user", "created_by")
    course_interests = CourseInterest.objects.select_related("user", "course")[:100]
    interests_by_course = (
        Course.objects.annotate(interested_count=Count("interests"))
        .filter(interested_count__gt=0)
        .order_by("-interested_count", "title")
    )
    return render(request, "school/dashboard.html", {
        "users": users,
        "totals": totals,
        "user_count": get_user_model().objects.count(),
        "active_subscriptions": CoursePurchase.objects.filter(status="paid").count(),
        "payments": PaymentRecord.objects.select_related("user")[:50],
        "revenue_cents": PaymentRecord.objects.filter(status="paid").aggregate(total=Sum("amount_cents"))["total"] or 0,
        "unique_visitors": PageVisit.objects.values("visitor_id").distinct().count(),
        "page_visits": visit_totals["visits"] or 0,
        "top_pages": top_pages,
        "ip_visitors": ip_visitors,
        "estimated_costs": estimated_costs,
        "purchase_whitelist": purchase_whitelist,
        "interested_users_total": CourseInterest.objects.values("user_id").distinct().count(),
        "interests_by_course": interests_by_course,
        "course_interests": course_interests,
    })


@staff_member_required
@require_POST
def add_purchase_whitelist(request):
    email = (request.POST.get("email") or "").strip()
    user = get_user_model().objects.filter(email__iexact=email).first()
    if not user:
        messages.error(request, "Nessun utente trovato con questa email.")
    else:
        _, created = PurchaseWhitelist.objects.get_or_create(
            user=user,
            defaults={"created_by": request.user},
        )
        if created:
            messages.success(request, "Utente aggiunto alla whitelist acquisti.")
        else:
            messages.info(request, "L’utente è già nella whitelist acquisti.")
    return redirect("staff_dashboard")


@staff_member_required
@require_POST
def remove_purchase_whitelist(request, user_id: int):
    deleted, _ = PurchaseWhitelist.objects.filter(user_id=user_id).delete()
    if deleted:
        messages.success(request, "Utente rimosso dalla whitelist acquisti.")
    return redirect("staff_dashboard")


def course_page(request, course_id: int):
    """Course detail page: shows lessons list."""
    course = get_object_or_404(Course, id=course_id)
    if request.user.is_authenticated:
        touch_user_course(request.user, course)
    lessons = course.lessons.all()
    if not request.user.is_authenticated:
        action_url = f"{reverse('login')}?next={reverse('lesson_page', args=[course.id])}"
        action_label = "Accedi per iniziare"
    elif has_lesson_access(request.user, course):
        action_url = reverse("lesson_page", args=[course.id])
        action_label = "Inizia a studiare →"
    else:
        action_url = f"{reverse('plans')}?course_id={course.id}"
        action_label = "Acquista il corso per continuare"
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
    requested_lesson = request.GET.get("lesson", "")
    initial_lesson = lessons.filter(id=int(requested_lesson)).first() if requested_lesson.isdigit() else lessons.first()
    touch_user_course(request.user, course, lesson=initial_lesson)
    return render(request, "school/lesson.html", {
        "course": course,
        "lessons": lessons,
        "initial_lesson_id": initial_lesson.id,
    })


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
    if cached_course and settings.MIN_LESSON <= cached_course.lessons.count() <= settings.MAX_LESSON:
        touch_user_course(request.user, cached_course)
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
    agent_trace = curriculum.pop("_agent", None)
    record_usage(
        request.user,
        "curriculum",
        usage,
        metadata={
            "subject": cache_key,
            "clarification": bool(clarification),
            "agent": agent_trace,
        },
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
            "agent": agent_trace,
        })

    lessons_data = curriculum.get("lessons", [])
    if not lessons_data:
        return error_response("NO_LESSONS", "Il corso non contiene lezioni.")

    # Persist the entire curriculum atomically. Reuse and repair an incomplete
    # cached course left by an older failed generation, if one exists.
    with transaction.atomic():
        course, _ = Course.objects.update_or_create(
            cache_key=cache_key,
            defaults={
                "title": curriculum["title"],
                "normalized_subject": curriculum["normalized_subject"],
                "description": curriculum["description"],
                "difficulty": curriculum.get("difficulty", "beginner"),
            },
        )
        course.lessons.all().delete()
        Lesson.objects.bulk_create([
            Lesson(
                course=course,
                # The sequence is authoritative: model-provided order values
                # may be duplicated, missing, or otherwise inconsistent.
                order=order,
                title=lesson_data["title"],
                summary=lesson_data["summary"],
                content_outline={
                    "objectives": lesson_data.get("objectives", []),
                    "key_concepts": lesson_data.get("key_concepts", []),
                    "examples": lesson_data.get("examples", []),
                    "prerequisites": lesson_data.get("prerequisites", []),
                },
            )
            for order, lesson_data in enumerate(lessons_data, start=1)
        ])

    touch_user_course(request.user, course)

    return JsonResponse({
        "success": True,
        "course_id": course.id,
        "agent": agent_trace,
    })


@require_GET
@api_login_required
def course_history(request):
    page_size = 20
    history = (
        UserCourse.objects.filter(user=request.user, hidden_at__isnull=True)
        .select_related("course", "last_lesson")
        .prefetch_related("course__lessons")
        .order_by("-last_accessed_at", "-id")
    )

    cursor = request.GET.get("cursor")
    if cursor:
        try:
            cursor_data = signing.loads(cursor, salt="course-history")
            cursor_time = parse_datetime(cursor_data["at"])
            cursor_id = int(cursor_data["id"])
            if cursor_time is None:
                raise ValueError
        except (signing.BadSignature, KeyError, TypeError, ValueError):
            return error_response("INVALID_CURSOR", "Cursore della cronologia non valido.")
        history = history.filter(
            Q(last_accessed_at__lt=cursor_time)
            | Q(last_accessed_at=cursor_time, id__lt=cursor_id)
        )

    entries = list(history[: page_size + 1])
    has_more = len(entries) > page_size
    entries = entries[:page_size]
    course_ids = [entry.course_id for entry in entries]
    completed_pairs = set(
        LessonSession.objects.filter(
            student=request.user,
            status="completed",
            lesson__course_id__in=course_ids,
        ).values_list("lesson__course_id", "lesson_id")
    )
    purchases = {
        purchase.course_id: purchase
        for purchase in CoursePurchase.objects.filter(
            user=request.user,
            course_id__in=course_ids,
            status="paid",
        )
    }

    items = []
    for entry in entries:
        lessons = list(entry.course.lessons.all())
        completed_ids = {
            lesson_id for course_id, lesson_id in completed_pairs
            if course_id == entry.course_id
        }
        resume_lesson = (
            entry.last_lesson
            if entry.last_lesson and entry.last_lesson.course_id == entry.course_id
            else next((lesson for lesson in lessons if lesson.id not in completed_ids), None)
        )
        if resume_lesson is None and lessons:
            resume_lesson = lessons[0]
        resume_url = reverse("lesson_page", args=[entry.course_id])
        if resume_lesson:
            resume_url = f"{resume_url}?lesson={resume_lesson.id}"

        purchase = purchases.get(entry.course_id)
        if is_access_bypassed(request.user):
            access_label = "Accesso completo"
            access_available = True
        elif purchase:
            access_label = f"Piano {purchase.plan.title()}"
            access_available = True
        else:
            access_available = free_trial_seconds_remaining(request.user, entry.course) > 0
            access_label = "Demo" if settings.MOCK_TIME > 0 else "Prova gratuita"

        items.append({
            "course_id": entry.course_id,
            "title": entry.course.title,
            "difficulty": entry.course.get_difficulty_display(),
            "last_accessed_at": entry.last_accessed_at.isoformat(),
            "completed_lessons": len(completed_ids),
            "total_lessons": len(lessons),
            "access_label": access_label,
            "access_available": access_available,
            "resume_url": resume_url,
        })

    next_cursor = None
    if has_more and entries:
        last_entry = entries[-1]
        next_cursor = signing.dumps(
            {"at": last_entry.last_accessed_at.isoformat(), "id": last_entry.id},
            salt="course-history",
            compress=True,
        )
    return JsonResponse({"success": True, "items": items, "next_cursor": next_cursor})


@csrf_protect
@require_POST
@api_login_required
def hide_course_history(request, course_id: int):
    history = get_object_or_404(UserCourse, user=request.user, course_id=course_id)
    history.hidden_at = timezone.now()
    history.save(update_fields=["hidden_at"])
    return JsonResponse({"success": True, "course_id": course_id})


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
    touch_user_course(request.user, lesson.course, lesson=lesson)

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
            allow_illustrations=can_generate_illustrations(request.user, lesson.course),
            allow_written_examples=can_show_written_examples(request.user, lesson.course),
        )
    except Exception:
        logger.exception("Realtime session creation failed")
        return error_response(
            "REALTIME_ERROR",
            "Non sono riuscito ad avviare la sessione vocale. Riprova.",
            status=503,
        )

    has_paid_access = is_access_bypassed(request.user) or bool(get_course_purchase(request.user, lesson.course))
    trial_seconds = None if has_paid_access else free_trial_seconds_remaining(request.user, lesson.course)

    # Create a LessonSession record
    lesson_session = LessonSession.objects.create(
        lesson=lesson,
        student=request.user,
        status="active",
        is_trial=not has_paid_access,
    )
    record_usage(
        request.user,
        "realtime_session",
        metadata={"lesson_id": lesson.id},
    )

    return JsonResponse({
        "success": True,
        **session,
        "lesson_session_id": lesson_session.id,
        "trial_seconds_remaining": trial_seconds,
    })


@csrf_protect
@require_POST
@api_login_required
def end_realtime_session(request):
    """Close an owned session and persist its elapsed duration."""
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return error_response("INVALID_REQUEST", "Richiesta non valida.")

    lesson_session = get_object_or_404(
        LessonSession,
        id=data.get("lesson_session_id"),
        student=request.user,
        status="active",
    )
    ended_at = timezone.now()
    elapsed = max(0, int((ended_at - lesson_session.started_at).total_seconds()))
    lesson_session.ended_at = ended_at
    lesson_session.duration_seconds = elapsed
    lesson_session.status = "abandoned"
    lesson_session.save(update_fields=["ended_at", "duration_seconds", "status"])
    return JsonResponse({"success": True, "duration_seconds": elapsed})


@csrf_protect
@require_POST
@subscription_required(api=True)
def generate_quiz(request, lesson_id: int):
    """Generate a quiz for a specific lesson.

    Returns: {"success": true, "title": "...", "questions": [...]}
    """
    lesson = get_object_or_404(Lesson, id=lesson_id)

    try:
        quiz_data = generate_quiz_service(lesson)
    except Exception:
        logger.exception("Quiz generation failed")
        return error_response(
            "QUIZ_ERROR",
            "Non sono riuscito a generare il quiz. Riprova tra qualche istante.",
            status=503,
        )

    usage = quiz_data.pop("_usage", None)
    agent_trace = quiz_data.pop("_agent", None)
    record_usage(
        request.user,
        "quiz",
        usage,
        metadata={"lesson_id": lesson.id, "agent": agent_trace},
    )
    return JsonResponse({"success": True, "agent": agent_trace, **quiz_data})


@csrf_protect
@require_POST
@subscription_required(api=True)
def complete_lesson(request, lesson_id: int):
    """Mark a lesson completed and return the next course destination."""
    lesson = get_object_or_404(Lesson, id=lesson_id)
    lesson_session = lesson.sessions.filter(student=request.user, status="active").first()

    if lesson_session:
        ended_at = timezone.now()
        elapsed = max(0, int((ended_at - lesson_session.started_at).total_seconds()))
        lesson_session.status = "completed"
        lesson_session.ended_at = ended_at
        lesson_session.duration_seconds = elapsed
        lesson_session.save(update_fields=["status", "ended_at", "duration_seconds"])
    elif not lesson.sessions.filter(student=request.user, status="completed").exists():
        LessonSession.objects.create(
            lesson=lesson,
            student=request.user,
            status="completed",
            ended_at=timezone.now(),
            is_trial=not (
                is_access_bypassed(request.user)
                or bool(get_course_purchase(request.user, lesson.course))
            ),
        )

    lessons = list(lesson.course.lessons.order_by("order", "id"))
    completed_ids = set(
        LessonSession.objects.filter(
            student=request.user,
            lesson__course=lesson.course,
            status="completed",
        ).values_list("lesson_id", flat=True)
    )
    course_completed = bool(lessons) and all(item.id in completed_ids for item in lessons)
    next_lesson = next((item for item in lessons if item.order > lesson.order), None)
    if next_lesson is None and not course_completed:
        next_lesson = next((item for item in lessons if item.id not in completed_ids), None)
    next_lesson_url = ""
    if next_lesson:
        next_lesson_url = f"{reverse('lesson_page', args=[lesson.course_id])}?lesson={next_lesson.id}"

    return JsonResponse({
        "success": True,
        "lesson_id": lesson.id,
        "course_completed": course_completed,
        "next_lesson_id": next_lesson.id if next_lesson else None,
        "next_lesson_url": next_lesson_url,
    })


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

    lesson_id = data.get("lesson_id")
    lesson = get_object_or_404(Lesson, id=lesson_id) if lesson_id else None
    if not lesson or not can_generate_illustrations(request.user, lesson.course):
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
def create_checkout(request, course_id: int, plan: str):
    if plan not in PLAN_CONFIG:
        messages.error(request, "Piano non valido.")
        return redirect("plans")
    course = get_object_or_404(Course, id=course_id)
    if not PurchaseWhitelist.objects.filter(user=request.user).exists():
        CourseInterest.objects.get_or_create(user=request.user, course=course)
        messages.success(
            request,
            "Perfetto, ti avviseremo appena la possibilità per l’acquisto del corso sarà disponibile.",
        )
        return redirect(f"{reverse('plans')}?course_id={course.id}")
    if settings.MOCK:
        CoursePurchase.objects.update_or_create(
            user=request.user,
            course=course,
            defaults={"plan": plan, "status": "paid", "purchased_at": timezone.now()},
        )
        messages.success(request, "Acquisto mock completato.")
        next_url = request.POST.get("next", "")
        if next_url and url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            return redirect(next_url)
        return redirect("lesson_page", course_id=course.id)
    try:
        checkout = create_checkout_session(
            request.user,
            course,
            plan,
            request.build_absolute_uri(f"{reverse('checkout_success')}?course_id={course.id}"),
            request.build_absolute_uri(f"{reverse('plans')}?course_id={course.id}"),
        )
    except Exception:
        logger.exception("Stripe checkout creation failed")
        messages.error(request, "Non è stato possibile avviare il pagamento.")
        return redirect(f"{reverse('plans')}?course_id={course.id}")
    return redirect(checkout.url)


@login_required
def checkout_success(request):
    messages.success(
        request,
        "Pagamento ricevuto. Il corso si attiverà non appena Stripe conferma il webhook.",
    )
    course_id = request.GET.get("course_id")
    return redirect("course_page", course_id=course_id) if course_id else redirect("profile")


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
        audio_input_tokens = min(max(int(data.get("audio_input_tokens", 0)), 0), input_tokens)
        audio_output_tokens = min(max(int(data.get("audio_output_tokens", 0)), 0), output_tokens)
    except (TypeError, ValueError, json.JSONDecodeError):
        return error_response("INVALID_USAGE", "Dati di utilizzo non validi.")
    UsageRecord.objects.create(
        user=request.user,
        kind="realtime_response",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        metadata={
            "lesson_id": data.get("lesson_id"),
            "audio_input_tokens": audio_input_tokens,
            "audio_output_tokens": audio_output_tokens,
        },
    )
    return JsonResponse({"success": True})
