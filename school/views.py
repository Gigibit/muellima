"""Django views for Personal School.

Pages are rendered with Django Templates. API endpoints return JSON.
All OpenAI calls are delegated to service modules — no API keys or
OpenAI SDK calls appear in views.
"""
import json
import logging

from django.conf import settings
from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_protect

from .models import Course, Lesson, LessonSession
from .services.curriculum_service import generate_curriculum
from .services.quiz_service import generate_quiz
from .services.realtime_service import create_realtime_session as create_realtime_session_service
from .services.illustration_service import create_illustration

logger = logging.getLogger(__name__)

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


def course_page(request, course_id: int):
    """Course detail page: shows lessons list."""
    course = get_object_or_404(Course, id=course_id)
    lessons = course.lessons.all()
    return render(request, "school/course.html", {"course": course, "lessons": 
lessons})


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

    if not subject or len(subject) < 2:
        return error_response("EMPTY_SUBJECT", "Inserisci una materia o un argomento.")

    if len(subject) > 200:
        return error_response("SUBJECT_TOO_LONG", "L'argomento è troppo lungo (massimo 200 caratteri).")

    try:
        curriculum = generate_curriculum(subject)
    except Exception:
        logger.exception("Curriculum generation failed")
        return error_response(
            "OPENAI_UNAVAILABLE",
            "Non sono riuscito a contattare il servizio AI. Riprova tra qualche istante.",
            status=503,
        )

    if not curriculum.get("valid"):
        reason = curriculum.get("reason", "Argomento non valido.")
        return error_response("INVALID_SUBJECT", f"Non sono riuscito a creare un corso su questo argomento. {reason}")

    lessons_data = curriculum.get("lessons", [])
    if not lessons_data:
        return error_response("NO_LESSONS", "Il corso non contiene lezioni.")

    # Persist course
    course = Course.objects.create(
        title=curriculum["title"],
        normalized_subject=curriculum["normalized_subject"],
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
        session = create_realtime_session_service(lesson)
    except Exception:
        logger.exception("Realtime session creation failed")
        return error_response(
            "REALTIME_ERROR",
            "Non sono riuscito ad avviare la sessione vocale. Riprova.",
            status=503,
        )

    # Create a LessonSession record
    LessonSession.objects.create(lesson=lesson, status="active")

    return JsonResponse({"success": True, **session})


@csrf_protect
@require_POST
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

    return JsonResponse({"success": True, **quiz_data})


@csrf_protect
@require_POST
def complete_lesson(request, lesson_id: int):
    """Mark the most recent active session for a lesson as completed."""
    lesson = get_object_or_404(Lesson, id=lesson_id)
    lesson_session = lesson.sessions.filter(status="active").first()

    if lesson_session:
        lesson_session.status = "completed"
        lesson_session.ended_at = timezone.now()
        lesson_session.save(update_fields=["status", "ended_at"])

    return JsonResponse({"success": True, "lesson_id": lesson.id})


@csrf_protect
@require_POST
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

    try:
        result = create_illustration(title, concept, visual_type, description)
    except Exception:
        logger.exception("Illustration generation failed")
        return error_response(
            "ILLUSTRATION_ERROR",
            "Non sono riuscito a generare l'illustrazione.",
            status=503,
        )

    return JsonResponse({"success": True, **result})
