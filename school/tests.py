from django.contrib.auth import get_user_model
import json
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .access import free_trial_seconds_remaining
from .agents import ProfessorAgent, QuizAgent
from .forms import UserProfileForm
from .billing import process_webhook_event
from .models import CourseInterest, CoursePurchase, LessonSession, PageVisit, PaymentRecord, PurchaseWhitelist, StripeEvent, Subscription, UsageRecord, UserCourse
from .usage import estimate_usage_cost
from .services.realtime_service import (
    build_opening_instruction,
    build_professor_instructions,
    build_realtime_tools,
)
from .services.curriculum_service import generate_curriculum
from .models import Course, Lesson


class HomePageTests(TestCase):
    def test_page_visits_are_counted_by_ip_and_category(self):
        self.client.get(reverse("home"), REMOTE_ADDR="203.0.113.10")
        self.client.get(reverse("home"), REMOTE_ADDR="203.0.113.10")

        visit = PageVisit.objects.get(ip_address="203.0.113.10", category="homepage")
        self.assertEqual(visit.visit_count, 2)

    def test_course_ids_share_the_same_page_category(self):
        first = Course.objects.create(
            title="Primo", normalized_subject="primo", description="Corso"
        )
        second = Course.objects.create(
            title="Secondo", normalized_subject="secondo", description="Corso"
        )

        self.client.get(reverse("course_page", args=[first.id]), REMOTE_ADDR="203.0.113.11")
        self.client.get(reverse("course_page", args=[second.id]), REMOTE_ADDR="203.0.113.11")

        visit = PageVisit.objects.get(ip_address="203.0.113.11", category="course")
        self.assertEqual(visit.visit_count, 2)

    @override_settings(TRUST_PROXY_IP_HEADERS=True)
    def test_page_visits_use_trusted_proxy_ip(self):
        self.client.get(
            reverse("home"),
            REMOTE_ADDR="127.0.0.1",
            HTTP_X_REAL_IP="198.51.100.20",
        )

        self.assertTrue(PageVisit.objects.filter(ip_address="198.51.100.20").exists())

    def test_api_responses_are_not_tracked(self):
        self.client.get(reverse("api_subject_suggestions"), {"q": "sto"}, REMOTE_ADDR="203.0.113.12")
        self.assertFalse(PageVisit.objects.filter(ip_address="203.0.113.12").exists())

    def test_anonymous_prospect_uuid_is_merged_on_login_and_keeps_counts(self):
        self.client.get(reverse("home"), REMOTE_ADDR="203.0.113.13")
        self.client.get(reverse("home"), REMOTE_ADDR="203.0.113.13")
        prospect_cookie = self.client.cookies["muellima_visitor_id"]
        prospect_visit = PageVisit.objects.get(category="homepage")
        self.assertIsNone(prospect_visit.last_user)
        self.assertEqual(str(prospect_visit.visitor_id), prospect_cookie.value)
        self.assertEqual(prospect_visit.visit_count, 2)

        user = get_user_model().objects.create_user(
            username="prospect@example.com", email="prospect@example.com"
        )
        self.client.force_login(user)
        # The UUID cookie, unlike the IP, remains stable across the OAuth trip.
        self.client.get(reverse("profile"), REMOTE_ADDR="198.51.100.13")

        prospect_visit.refresh_from_db()
        self.assertEqual(prospect_visit.last_user, user)
        self.assertEqual(prospect_visit.visit_count, 2)
        self.assertTrue(
            PageVisit.objects.filter(
                visitor_id=prospect_visit.visitor_id,
                ip_address="198.51.100.13",
                category="profile",
                last_user=user,
            ).exists()
        )

    def test_login_merge_does_not_reassign_another_visitors_records(self):
        ip_address = "203.0.113.14"
        first = get_user_model().objects.create_user(username="first@example.com")
        second = get_user_model().objects.create_user(username="second@example.com")
        PageVisit.objects.create(
            ip_address=ip_address, category="homepage", last_user=first
        )

        self.client.force_login(second)
        self.client.get(reverse("profile"), REMOTE_ADDR=ip_address)

        self.assertEqual(
            PageVisit.objects.get(ip_address=ip_address, category="homepage").last_user,
            first,
        )

    def test_multiple_prospect_uuids_for_same_email_are_consolidated(self):
        user = get_user_model().objects.create_user(
            username="returning@example.com",
            email="returning@example.com",
        )
        first_browser = Client()
        second_browser = Client()

        first_browser.get(reverse("home"), REMOTE_ADDR="203.0.113.21")
        first_browser.get(reverse("home"), REMOTE_ADDR="203.0.113.21")
        first_browser.force_login(user)
        first_browser.get(reverse("profile"), REMOTE_ADDR="203.0.113.21")

        for _ in range(3):
            second_browser.get(reverse("home"), REMOTE_ADDR="198.51.100.21")
        second_browser.force_login(user)
        second_browser.get(reverse("profile"), REMOTE_ADDR="198.51.100.21")

        homepage = PageVisit.objects.get(last_user=user, category="homepage")
        self.assertEqual(homepage.visit_count, 5)
        self.assertEqual(
            PageVisit.objects.filter(last_user__email__iexact=user.email)
            .values("visitor_id")
            .distinct()
            .count(),
            1,
        )

    def test_home_has_random_examples_from_balanced_categories(self):
        response = self.client.get(reverse("home"))

        self.assertContains(response, 'id="example-chips"')
        self.assertContains(response, "EXAMPLE_CATEGORIES")
        self.assertContains(response, "Fisica quantistica")
        self.assertContains(response, "Intelligenza artificiale")
        self.assertContains(response, "Scrittura creativa")
        self.assertContains(response, "Come educare il cane")
        self.assertContains(response, "Come imparare a cucinare bene")
        self.assertContains(response, "Agente lezioni")
        self.assertContains(response, "Agente professore")
        self.assertContains(response, "Agente quiz")
        self.assertContains(response, "event.ctrlKey && event.key === 'Enter'")

    def test_clarification_modal_allows_custom_input(self):
        response = self.client.get(reverse("home"))

        self.assertContains(response, 'id="clarification-custom-form"')
        self.assertContains(response, 'id="clarification-custom-input"')
        self.assertContains(response, "oppure usa questa specificazione")
        self.assertContains(
            response,
            '<button type="submit" class="btn-primary">Invia</button>',
            html=True,
        )


class CurriculumGenerationTests(TestCase):
    @staticmethod
    def curriculum(lesson_count):
        return {
            "valid": True,
            "reason": "",
            "needs_clarification": False,
            "clarification_question": "",
            "clarification_options": [],
            "normalized_subject": "chimica organica",
            "title": "Chimica organica",
            "description": "Un corso completo.",
            "difficulty": "beginner",
            "lessons": [
                {
                    "order": order,
                    "title": f"Lezione {order}",
                    "summary": "Argomento",
                    "objectives": [],
                    "key_concepts": [],
                    "examples": [],
                    "prerequisites": [],
                }
                for order in range(1, lesson_count + 1)
            ],
        }

    @override_settings(MIN_LESSON=10, MAX_LESSON=24)
    def test_retries_with_minimum_lesson_constraint(self):
        client = Mock()
        client.responses.create.side_effect = [
            SimpleNamespace(
                output_text=json.dumps(self.curriculum(3)),
                usage=SimpleNamespace(input_tokens=100, output_tokens=200),
            ),
            SimpleNamespace(
                output_text=json.dumps(self.curriculum(10)),
                usage=SimpleNamespace(input_tokens=120, output_tokens=500),
            ),
        ]

        curriculum = generate_curriculum("Chimica organica", client=client)

        self.assertEqual(len(curriculum["lessons"]), 10)
        self.assertEqual(client.responses.create.call_count, 2)
        retry_schema = client.responses.create.call_args_list[1].kwargs["text"]["format"]["schema"]
        self.assertEqual(retry_schema["properties"]["lessons"]["minItems"], 10)
        self.assertEqual(curriculum["_agent"]["name"], "lesson_creation_agent")
        self.assertEqual(curriculum["_agent"]["attempts"], 2)
        self.assertEqual(curriculum["_usage"]["input_tokens"], 220)
        self.assertEqual(curriculum["_usage"]["output_tokens"], 700)


class AgentArchitectureTests(TestCase):
    def test_quiz_agent_retries_invalid_output_with_validation_feedback(self):
        invalid = {"title": "Quiz", "questions": []}
        valid_questions = [
            {
                "question": f"Domanda {index}",
                "options": ["A", "B", "C", "D"],
                "correct_index": 0,
                "explanation": "Spiegazione",
            }
            for index in range(5)
        ]
        valid = {"title": "Quiz", "questions": valid_questions}
        outputs = [(invalid, {"input_tokens": 10}), (valid, {"output_tokens": 20})]
        feedback_seen = []

        def execute(attempt, feedback):
            feedback_seen.append(feedback)
            return outputs[attempt - 1]

        result = QuizAgent().run(execute, QuizAgent.validate)

        self.assertEqual(result["_agent"]["attempts"], 2)
        self.assertIn("5 a 10", feedback_seen[1])
        self.assertEqual(result["_usage"]["total_tokens"], 30)

    def test_professor_agent_marks_realtime_tool_loop(self):
        result = ProfessorAgent().run(lambda: {"ephemeral_key": "secret"})

        self.assertEqual(result["agent"]["name"], "professor_agent")
        self.assertEqual(result["agent"]["mode"], "realtime_tool_loop")


class UserProfileTests(TestCase):
    def test_profile_uses_email_name_and_low_reasoning_by_default(self):
        user = get_user_model().objects.create_user(
            username="maria@example.com",
            email="maria@example.com",
        )

        self.assertEqual(user.school_profile.display_name, "maria")
        self.assertEqual(user.school_profile.realtime_reasoning_effort, "low")

    def test_learning_context_is_limited_to_100_words(self):
        user = get_user_model().objects.create_user(username="maria")
        form = UserProfileForm(
            data={
                "display_name": "Maria",
                "realtime_reasoning_effort": "medium",
                "learning_context": "parola " * 101,
            },
            instance=user.school_profile,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("learning_context", form.errors)


class EmailAuthenticationTests(TestCase):
    @override_settings(
        GOOGLE_CLIENT_ID="google-id",
        GOOGLE_CLIENT_SECRET="google-secret",
        FACEBOOK_APP_ID="facebook-id",
        FACEBOOK_APP_SECRET="facebook-secret",
        SOCIALACCOUNT_PROVIDERS={
            "google": {"APPS": [{"client_id": "google-id", "secret": "google-secret", "key": ""}]},
            "facebook": {"APPS": [{"client_id": "facebook-id", "secret": "facebook-secret", "key": ""}]},
        },
    )
    def test_login_page_has_email_form_registration_and_social_icons(self):
        response = self.client.get(reverse("login"))

        self.assertContains(response, 'name="username"')
        self.assertContains(response, 'name="password"')
        self.assertContains(response, reverse("register"))
        self.assertContains(response, "Continua con Google")
        self.assertContains(response, "Continua con Facebook")
        self.assertContains(response, "<svg", count=2)

    def test_registration_creates_user_profile_logs_in_and_merges_prospect(self):
        self.client.get(reverse("home"), REMOTE_ADDR="203.0.113.40")
        prospect = PageVisit.objects.get(category="homepage")

        response = self.client.post(
            reverse("register"),
            {
                "first_name": "Ada",
                "last_name": "Lovelace",
                "email": "Ada@example.com",
                "password": "Analytical-Engine-1843!",
                "password_confirm": "Analytical-Engine-1843!",
            },
            REMOTE_ADDR="203.0.113.40",
            follow=True,
        )

        user = get_user_model().objects.get(email="ada@example.com")
        prospect.refresh_from_db()
        self.assertTrue(response.context["user"].is_authenticated)
        self.assertEqual(user.get_full_name(), "Ada Lovelace")
        self.assertEqual(user.school_profile.display_name, "Ada Lovelace")
        self.assertEqual(prospect.last_user, user)

    def test_registration_rejects_mismatched_passwords_and_duplicate_email(self):
        get_user_model().objects.create_user(
            username="existing@example.com", email="existing@example.com"
        )
        response = self.client.post(
            reverse("register"),
            {
                "first_name": "Existing",
                "last_name": "User",
                "email": "EXISTING@example.com",
                "password": "Strong-password-1843!",
                "password_confirm": "different-password",
            },
        )

        self.assertContains(response, "Esiste già un account con questa email.")
        self.assertContains(response, "Le password non coincidono.")

    def test_email_login_respects_safe_next_url(self):
        user = get_user_model().objects.create_user(
            username="login@example.com",
            email="login@example.com",
            password="Strong-password-1843!",
        )

        response = self.client.post(
            reverse("login"),
            {
                "username": user.email,
                "password": "Strong-password-1843!",
                "next": reverse("profile"),
            },
        )

        self.assertRedirects(response, reverse("profile"), fetch_redirect_response=False)

    def test_profile_requires_login(self):
        response = self.client.get(reverse("profile"))
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('profile')}")


class RealtimeProfileTests(TestCase):
    def test_opening_instruction_is_grounded_in_selected_lesson(self):
        course = Course.objects.create(
            title="Programmazione Python",
            normalized_subject="programmazione python",
            description="Corso Python",
        )
        lesson = Lesson.objects.create(
            course=course,
            order=2,
            title="Cicli for",
            summary="Iterare su una sequenza",
            content_outline={"objectives": ["Comprendere range e iterazione"]},
        )

        instruction = build_opening_instruction(lesson)

        self.assertIn("Lezione 2: Cicli for", instruction)
        self.assertIn("Comprendere range e iterazione", instruction)
        self.assertIn("Non parlare di altri corsi", instruction)
        self.assertIn('"Cominciamo?"', instruction)

    def test_written_examples_are_exposed_only_with_premium_supports(self):
        base_tool_names = {tool["name"] for tool in build_realtime_tools(False, False)}
        pro_tool_names = {tool["name"] for tool in build_realtime_tools(True, False)}
        premium_tool_names = {tool["name"] for tool in build_realtime_tools(True, True)}

        self.assertEqual(base_tool_names, {"finish_lesson"})
        self.assertIn("show_written_example", pro_tool_names)
        self.assertNotIn("show_illustration", pro_tool_names)
        self.assertIn("show_written_example", premium_tool_names)
        self.assertIn("show_illustration", premium_tool_names)

    def test_professor_can_proactively_render_textual_markup(self):
        course = Course.objects.create(
            title="Fisica",
            normalized_subject="fisica",
            description="Corso di fisica",
        )
        lesson = Lesson.objects.create(
            course=course,
            order=1,
            title="Moto",
            summary="Il moto rettilineo",
        )

        instructions = build_professor_instructions(lesson, allow_illustrations=True)

        self.assertIn("Chiamalo anche autonomamente", instructions)
        self.assertIn("markup testuale strutturato", instructions)

    def test_learning_context_is_delimited_in_professor_instructions(self):
        course = Course.objects.create(
            title="Analisi",
            normalized_subject="analisi",
            description="Corso di analisi",
        )
        lesson = Lesson.objects.create(
            course=course,
            order=1,
            title="Limiti",
            summary="Introduzione ai limiti",
        )

        instructions = build_professor_instructions(
            lesson,
            learner_name="Maria",
            learning_context="Spiegami tutto con esempi visivi.",
        )

        self.assertIn("Nome: Maria", instructions)
        self.assertIn("<student_preferences>", instructions)
        self.assertIn("Spiegami tutto con esempi visivi.", instructions)

    def test_professor_rejects_off_topic_questions_briefly(self):
        course = Course.objects.create(
            title="Analisi",
            normalized_subject="analisi matematica",
            description="Corso di analisi",
        )
        lesson = Lesson.objects.create(
            course=course,
            order=1,
            title="Limiti",
            summary="Introduzione ai limiti",
        )

        instructions = build_professor_instructions(lesson)

        self.assertIn("non è pertinente né al corso né ai suoi argomenti", instructions)
        self.assertIn("Non usare tool per richieste fuori argomento", instructions)


@override_settings(MOCK=False, MOCK_TIME=0, USERS_WHITELIST=set())
class AccessAndCachingTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="student@example.com",
            email="student@example.com",
        )
        self.course = Course.objects.create(
            title="Fisica quantistica",
            normalized_subject="Fisica quantistica",
            cache_key="fisica quantistica",
            description="Corso",
        )
        self.lesson = Lesson.objects.create(
            course=self.course,
            order=1,
            title="Introduzione",
            summary="Fondamenti",
        )

    def test_course_generation_requires_login(self):
        response = self.client.post(
            reverse("api_generate_course"),
            data=json.dumps({"subject": "Python"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)

    def test_course_cache_is_case_insensitive(self):
        for order in range(2, 11):
            Lesson.objects.create(
                course=self.course,
                order=order,
                title=f"Lezione {order}",
                summary="Fondamenti",
            )
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("api_generate_course"),
            data=json.dumps({"subject": "  FISICA   QUANTISTICA "}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["cached"])
        self.assertEqual(response.json()["course_id"], self.course.id)
        self.assertTrue(UsageRecord.objects.filter(user=self.user, kind="course_cache").exists())
        self.assertTrue(UserCourse.objects.filter(user=self.user, course=self.course).exists())

    @patch("school.views.generate_curriculum")
    def test_incomplete_cached_course_is_repaired_and_duplicate_orders_are_normalized(self, generate):
        generate.return_value = {
            "_usage": None,
            "valid": True,
            "needs_clarification": False,
            "title": "Fisica quantistica",
            "normalized_subject": "fisica quantistica",
            "description": "Corso completo",
            "difficulty": "beginner",
            "lessons": [
                {
                    "order": 1,
                    "title": f"Lezione generata {number}",
                    "summary": "Argomento",
                    "objectives": [],
                    "key_concepts": [],
                    "examples": [],
                    "prerequisites": [],
                }
                for number in range(1, 11)
            ],
        }
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("api_generate_course"),
            data=json.dumps({"subject": "Fisica quantistica"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["course_id"], self.course.id)
        self.assertEqual(
            list(self.course.lessons.order_by("order").values_list("order", flat=True)),
            list(range(1, 11)),
        )

    def test_subject_autocomplete_returns_common_subjects(self):
        response = self.client.get(reverse("api_subject_suggestions"), {"q": "stor"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("Storia", response.json()["suggestions"])

    @patch("school.views.generate_curriculum")
    def test_generic_subject_returns_clarification_before_course(self, generate):
        generate.return_value = {
            "_usage": None,
            "valid": True,
            "needs_clarification": True,
            "clarification_question": "Quale anno frequenti?",
            "clarification_options": ["Prima media", "Seconda media"],
        }
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("api_generate_course"),
            data=json.dumps({"subject": "Storia"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["needs_clarification"])
        self.assertEqual(response.json()["question"], "Quale anno frequenti?")
        generate.assert_called_once_with("Storia", clarification="")

    @patch("school.views.generate_curriculum")
    def test_clarification_is_sent_to_curriculum_generator(self, generate):
        generate.return_value = {
            "_usage": None,
            "valid": True,
            "needs_clarification": False,
            "title": "Storia per la prima media",
            "normalized_subject": "storia prima media",
            "description": "Corso",
            "difficulty": "beginner",
            "lessons": [{
                "order": 1,
                "title": "Introduzione",
                "summary": "Introduzione",
                "objectives": [],
                "key_concepts": [],
                "examples": [],
                "prerequisites": [],
            }],
        }
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("api_generate_course"),
            data=json.dumps({"subject": "Storia", "clarification": "Prima media"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        generate.assert_called_once_with("Storia", clarification="Prima media")

    def test_new_account_can_open_lesson_during_free_trial(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("lesson_page", args=[self.course.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="lesson-tutorial"')
        self.assertContains(response, "Parla liberamente")
        self.assertContains(response, "una risposta corretta in più della metà")
        self.assertContains(response, "initializeLessonTutorial")
        self.assertContains(response, "lesson-tutorial.seen.v3.course")
        self.assertContains(response, 'id="quiz-feedback-toast"')
        self.assertContains(response, 'id="quiz-feedback-toast-close"')
        self.assertContains(response, "quiz.js")

    def test_lesson_completion_returns_next_lesson_then_course_completion(self):
        next_lesson = Lesson.objects.create(
            course=self.course,
            order=2,
            title="Applicazioni",
            summary="Applicazioni pratiche",
        )
        LessonSession.objects.create(
            lesson=self.lesson,
            student=self.user,
            status="active",
        )
        self.client.force_login(self.user)

        first_response = self.client.post(
            reverse("api_complete_lesson", args=[self.lesson.id]),
            data="{}",
            content_type="application/json",
        )
        second_response = self.client.post(
            reverse("api_complete_lesson", args=[next_lesson.id]),
            data="{}",
            content_type="application/json",
        )

        self.assertFalse(first_response.json()["course_completed"])
        self.assertEqual(first_response.json()["next_lesson_id"], next_lesson.id)
        self.assertEqual(
            first_response.json()["next_lesson_url"],
            f"{reverse('lesson_page', args=[self.course.id])}?lesson={next_lesson.id}",
        )
        self.assertTrue(second_response.json()["course_completed"])
        self.assertIsNone(second_response.json()["next_lesson_id"])
        self.assertEqual(
            LessonSession.objects.filter(
                student=self.user,
                status="completed",
                lesson__course=self.course,
            ).values("lesson_id").distinct().count(),
            2,
        )

    @override_settings(FREE_TRIAL_MINUTES=5)
    def test_active_session_uses_wall_clock_time_for_trial(self):
        session = LessonSession.objects.create(
            lesson=self.lesson,
            student=self.user,
            status="active",
            is_trial=True,
        )
        LessonSession.objects.filter(pk=session.pk).update(
            started_at=timezone.now() - timedelta(minutes=6)
        )

        self.assertEqual(free_trial_seconds_remaining(self.user, self.course), 0)

    def test_account_is_sent_to_plans_after_free_trial_is_consumed(self):
        LessonSession.objects.create(
            lesson=self.lesson,
            student=self.user,
            status="abandoned",
            is_trial=True,
            duration_seconds=300,
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("lesson_page", args=[self.course.id]))

        self.assertRedirects(response, f"{reverse('plans')}?course_id={self.course.id}")

    def test_each_course_has_its_own_free_trial(self):
        LessonSession.objects.create(
            lesson=self.lesson,
            student=self.user,
            status="abandoned",
            is_trial=True,
            duration_seconds=300,
        )
        other_course = Course.objects.create(
            title="Chimica",
            normalized_subject="chimica",
            cache_key="chimica",
            description="Corso",
        )
        Lesson.objects.create(
            course=other_course,
            order=1,
            title="Atomi",
            summary="Introduzione",
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("lesson_page", args=[other_course.id]))

        self.assertEqual(response.status_code, 200)

    @override_settings(MOCK_TIME=5, USERS_WHITELIST=set())
    def test_mock_demo_time_is_shared_across_courses(self):
        LessonSession.objects.create(
            lesson=self.lesson,
            student=self.user,
            status="abandoned",
            is_trial=True,
            duration_seconds=300,
        )
        other_course = Course.objects.create(
            title="Chimica",
            normalized_subject="chimica",
            cache_key="chimica-demo",
            description="Corso",
        )

        self.assertEqual(free_trial_seconds_remaining(self.user, other_course), 0)

    @override_settings(USERS_WHITELIST={"student@example.com"})
    def test_whitelisted_user_bypasses_plan(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("lesson_page", args=[self.course.id]))
        self.assertEqual(response.status_code, 200)

    def test_base_plan_cannot_call_illustration_backend(self):
        CoursePurchase.objects.create(
            user=self.user, course=self.course, plan="base", status="paid"
        )
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("api_generate_illustration"),
            data=json.dumps({"concept": "Un atomo", "lesson_id": self.lesson.id}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "PREMIUM_REQUIRED")

    def test_free_trial_cannot_call_illustration_backend(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("api_generate_illustration"),
            data=json.dumps({"concept": "Un atomo", "lesson_id": self.lesson.id}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "PREMIUM_REQUIRED")

    @patch("school.views.generate_quiz_service")
    def test_quiz_endpoint_calls_service_without_name_collision(self, generate):
        generate.return_value = {
            "_usage": None,
            "title": "Quiz sui fondamenti",
            "questions": [],
        }
        self.client.force_login(self.user)

        response = self.client.post(reverse("api_generate_quiz", args=[self.lesson.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["title"], "Quiz sui fondamenti")
        generate.assert_called_once_with(self.lesson)

    @override_settings(MOCK=True)
    def test_mock_checkout_activates_selected_plan(self):
        PurchaseWhitelist.objects.create(user=self.user)
        self.client.force_login(self.user)
        response = self.client.post(reverse("create_checkout", args=[self.course.id, "premium"]))
        self.assertRedirects(response, reverse("lesson_page", args=[self.course.id]))
        purchase = CoursePurchase.objects.get(user=self.user, course=self.course)
        self.assertEqual(purchase.plan, "premium")
        self.assertEqual(purchase.status, "paid")

    @override_settings(MOCK=False)
    @patch("school.views.create_checkout_session")
    def test_non_whitelisted_checkout_records_interest_without_stripe(self, checkout):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("create_checkout", args=[self.course.id, "base"]),
            follow=True,
        )
        self.client.post(reverse("create_checkout", args=[self.course.id, "premium"]))

        checkout.assert_not_called()
        self.assertEqual(
            CourseInterest.objects.filter(user=self.user, course=self.course).count(),
            1,
        )
        self.assertContains(
            response,
            "Perfetto, ti avviseremo appena la possibilità per l’acquisto del corso sarà disponibile.",
        )

    @override_settings(MOCK=False)
    @patch("school.views.create_checkout_session")
    def test_purchase_whitelist_keeps_existing_stripe_flow(self, checkout):
        checkout.return_value = SimpleNamespace(url="https://checkout.stripe.test/session")
        PurchaseWhitelist.objects.create(user=self.user)
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("create_checkout", args=[self.course.id, "pro"])
        )

        self.assertRedirects(
            response,
            "https://checkout.stripe.test/session",
            fetch_redirect_response=False,
        )
        checkout.assert_called_once()
        self.assertFalse(CourseInterest.objects.filter(user=self.user).exists())


@override_settings(MOCK=False, MOCK_TIME=60, USERS_WHITELIST=set())
class CourseHistoryTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="history@example.com",
            email="history@example.com",
        )
        self.other_user = get_user_model().objects.create_user(
            username="other-history@example.com",
            email="other-history@example.com",
        )
        self.course = Course.objects.create(
            title="Storia medievale",
            normalized_subject="storia medievale",
            cache_key="storia-medievale-history",
            description="Corso",
        )
        self.lessons = [
            Lesson.objects.create(
                course=self.course,
                order=order,
                title=f"Lezione {order}",
                summary="Sommario",
            )
            for order in range(1, 4)
        ]

    def test_drawer_replaces_profile_link_for_authenticated_user(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("home"))

        self.assertContains(response, 'id="account-drawer-trigger"')
        self.assertContains(response, 'aria-controls="account-drawer"')
        self.assertContains(response, 'id="account-history-sentinel"')
        self.assertContains(response, "IntersectionObserver")

    def test_opening_course_records_and_reopens_history(self):
        history = UserCourse.objects.create(
            user=self.user,
            course=self.course,
            hidden_at=timezone.now(),
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("course_page", args=[self.course.id]))

        self.assertEqual(response.status_code, 200)
        history.refresh_from_db()
        self.assertIsNone(history.hidden_at)

    def test_selected_lesson_becomes_resume_lesson(self):
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("lesson_page", args=[self.course.id]),
            {"lesson": self.lessons[1].id},
        )

        self.assertEqual(response.status_code, 200)
        history = UserCourse.objects.get(user=self.user, course=self.course)
        self.assertEqual(history.last_lesson, self.lessons[1])
        self.assertContains(response, f'value="{self.lessons[1].id}" selected')

    def test_history_api_requires_login(self):
        response = self.client.get(reverse("api_course_history"))
        self.assertEqual(response.status_code, 401)
        hide_response = self.client.post(
            reverse("api_hide_course_history", args=[self.course.id])
        )
        self.assertEqual(hide_response.status_code, 401)

    def test_history_progress_is_distinct_and_resumes_first_incomplete(self):
        UserCourse.objects.create(user=self.user, course=self.course)
        LessonSession.objects.create(
            lesson=self.lessons[0], student=self.user, status="completed"
        )
        LessonSession.objects.create(
            lesson=self.lessons[0], student=self.user, status="completed"
        )
        self.client.force_login(self.user)

        item = self.client.get(reverse("api_course_history")).json()["items"][0]

        self.assertEqual(item["completed_lessons"], 1)
        self.assertEqual(item["total_lessons"], 3)
        self.assertEqual(
            item["resume_url"],
            f'{reverse("lesson_page", args=[self.course.id])}?lesson={self.lessons[1].id}',
        )

    def test_history_cursor_paginates_twenty_at_a_time(self):
        now = timezone.now()
        for index in range(22):
            course = Course.objects.create(
                title=f"Corso {index:02d}",
                normalized_subject=f"corso {index:02d}",
                cache_key=f"history-course-{index}",
                description="Corso",
            )
            history = UserCourse.objects.create(user=self.user, course=course)
            UserCourse.objects.filter(pk=history.pk).update(
                last_accessed_at=now - timedelta(minutes=index)
            )
        self.client.force_login(self.user)

        first = self.client.get(reverse("api_course_history")).json()
        second = self.client.get(
            reverse("api_course_history"), {"cursor": first["next_cursor"]}
        ).json()

        self.assertEqual(len(first["items"]), 20)
        self.assertIsNotNone(first["next_cursor"])
        self.assertEqual(len(second["items"]), 2)
        self.assertIsNone(second["next_cursor"])

    def test_hide_is_user_scoped_and_removes_entry(self):
        own = UserCourse.objects.create(user=self.user, course=self.course)
        other_course = Course.objects.create(
            title="Corso altrui",
            normalized_subject="corso altrui",
            cache_key="other-history-course",
            description="Corso",
        )
        UserCourse.objects.create(user=self.other_user, course=other_course)
        self.client.force_login(self.user)

        denied = self.client.post(
            reverse("api_hide_course_history", args=[other_course.id])
        )
        hidden = self.client.post(
            reverse("api_hide_course_history", args=[self.course.id])
        )

        self.assertEqual(denied.status_code, 404)
        self.assertEqual(hidden.status_code, 200)
        own.refresh_from_db()
        self.assertIsNotNone(own.hidden_at)
        self.assertEqual(self.client.get(reverse("api_course_history")).json()["items"], [])


class BillingAndDashboardTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="payer@example.com",
            email="payer@example.com",
        )
        self.course = Course.objects.create(
            title="Astronomia",
            normalized_subject="astronomia",
            description="Corso",
        )

    def test_checkout_webhook_is_idempotent(self):
        event = {
            "id": "evt_checkout_1",
            "type": "checkout.session.completed",
            "data": {"object": {
                "object": "checkout.session",
                "client_reference_id": str(self.user.id),
                "customer": "cus_123",
                "payment_intent": "pi_123",
                "currency": "eur",
                "payment_status": "paid",
                "metadata": {
                    "user_id": str(self.user.id),
                    "course_id": str(self.course.id),
                    "plan": "premium",
                },
            }},
        }
        self.assertTrue(process_webhook_event(event))
        self.assertFalse(process_webhook_event(event))
        purchase = CoursePurchase.objects.get(user=self.user, course=self.course)
        self.assertEqual(purchase.plan, "premium")
        self.assertEqual(purchase.status, "paid")
        self.assertEqual(StripeEvent.objects.filter(stripe_event_id="evt_checkout_1").count(), 1)

    def test_dashboard_is_staff_only(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("staff_dashboard"))
        self.assertEqual(response.status_code, 302)

        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        response = self.client.get(reverse("staff_dashboard"))
        self.assertEqual(response.status_code, 200)

    @override_settings(
        OPENAI_TEXT_INPUT_USD_PER_1M=Decimal("2"),
        OPENAI_TEXT_OUTPUT_USD_PER_1M=Decimal("10"),
        OPENAI_REALTIME_TEXT_INPUT_USD_PER_1M=Decimal("4"),
        OPENAI_REALTIME_TEXT_OUTPUT_USD_PER_1M=Decimal("20"),
        OPENAI_REALTIME_AUDIO_INPUT_USD_PER_1M=Decimal("30"),
        OPENAI_REALTIME_AUDIO_OUTPUT_USD_PER_1M=Decimal("60"),
        OPENAI_IMAGE_USD_PER_IMAGE=Decimal("0.05"),
    )
    def test_usage_cost_estimate_separates_text_realtime_and_images(self):
        UsageRecord.objects.create(
            user=self.user, kind="curriculum", input_tokens=1_000_000, output_tokens=1_000_000
        )
        UsageRecord.objects.create(
            user=self.user,
            kind="realtime_response",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            metadata={"audio_input_tokens": 500_000, "audio_output_tokens": 500_000},
        )
        UsageRecord.objects.create(user=self.user, kind="illustration", image_count=2)

        costs = estimate_usage_cost(UsageRecord.objects.all())

        self.assertEqual(costs["text"], Decimal("12"))
        self.assertEqual(costs["realtime"], Decimal("57"))
        self.assertEqual(costs["images"], Decimal("0.10"))
        self.assertEqual(costs["total"], Decimal("69.10"))

    def test_dashboard_shows_paid_revenue_costs_and_ip(self):
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        PaymentRecord.objects.create(
            user=self.user,
            stripe_invoice_id="pi_dashboard_paid",
            amount_cents=999,
            status="paid",
        )
        PaymentRecord.objects.create(
            user=self.user,
            stripe_invoice_id="pi_dashboard_failed",
            amount_cents=4999,
            status="failed",
        )
        PageVisit.objects.create(
            ip_address="203.0.113.30", category="lessons", last_user=self.user, visit_count=3
        )
        anonymous = PageVisit.objects.create(
            ip_address="198.51.100.30", category="homepage", visit_count=2
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("staff_dashboard"))

        self.assertContains(response, "€9,99")
        self.assertEqual(response.context["revenue_cents"], 999)
        self.assertContains(response, "203.0.113.30")
        self.assertContains(response, "Lezioni")
        self.assertContains(response, "Costi AI stimati")
        self.assertContains(response, "Pagine visitate")
        self.assertContains(response, "Ultimo UUID noto")
        self.assertContains(response, str(anonymous.visitor_id), count=2)
        self.assertEqual(response.context["users"][0].page_visit_count, 3)
        self.assertEqual(response.context["users"][0].visit_ips, "203.0.113.30")

    def test_staff_can_manage_purchase_whitelist_and_see_interests(self):
        interested = get_user_model().objects.create_user(
            username="interested@example.com",
            email="interested@example.com",
        )
        CourseInterest.objects.create(user=interested, course=self.course)
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        self.client.force_login(self.user)

        added = self.client.post(
            reverse("add_purchase_whitelist"),
            {"email": interested.email},
        )
        dashboard = self.client.get(reverse("staff_dashboard"))
        removed = self.client.post(
            reverse("remove_purchase_whitelist", args=[interested.id])
        )

        self.assertRedirects(added, reverse("staff_dashboard"))
        self.assertContains(dashboard, "Whitelist acquisti")
        self.assertContains(dashboard, interested.email)
        self.assertContains(dashboard, self.course.title)
        self.assertRedirects(removed, reverse("staff_dashboard"))
        self.assertFalse(PurchaseWhitelist.objects.filter(user=interested).exists())
