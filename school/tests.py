from django.contrib.auth import get_user_model
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import TestCase, override_settings
from django.urls import reverse

from .forms import UserProfileForm
from .billing import process_webhook_event
from .models import CoursePurchase, LessonSession, StripeEvent, Subscription, UsageRecord
from .services.realtime_service import (
    build_opening_instruction,
    build_professor_instructions,
    build_realtime_tools,
)
from .services.curriculum_service import generate_curriculum
from .models import Course, Lesson


class HomePageTests(TestCase):
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


@override_settings(MOCK=False, USERS_WHITELIST=set())
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
        self.client.force_login(self.user)
        response = self.client.post(reverse("create_checkout", args=[self.course.id, "premium"]))
        self.assertRedirects(response, reverse("lesson_page", args=[self.course.id]))
        purchase = CoursePurchase.objects.get(user=self.user, course=self.course)
        self.assertEqual(purchase.plan, "premium")
        self.assertEqual(purchase.status, "paid")


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
