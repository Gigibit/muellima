from django.contrib.auth import get_user_model
import json

from django.test import TestCase, override_settings
from django.urls import reverse

from .forms import UserProfileForm
from .billing import process_webhook_event
from .models import StripeEvent, Subscription, UsageRecord
from .services.realtime_service import build_professor_instructions
from .models import Course, Lesson


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

    def test_lesson_requires_an_active_plan(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("lesson_page", args=[self.course.id]))
        self.assertRedirects(response, reverse("plans"))

    @override_settings(USERS_WHITELIST={"student@example.com"})
    def test_whitelisted_user_bypasses_plan(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("lesson_page", args=[self.course.id]))
        self.assertEqual(response.status_code, 200)

    def test_base_plan_cannot_call_illustration_backend(self):
        subscription = self.user.subscription
        subscription.plan = "base"
        subscription.status = "active"
        subscription.save()
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("api_generate_illustration"),
            data=json.dumps({"concept": "Un atomo"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "PREMIUM_REQUIRED")

    @override_settings(MOCK=True)
    def test_mock_checkout_activates_selected_plan(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("create_checkout", args=["premium"]))
        self.assertRedirects(response, reverse("profile"))
        self.user.subscription.refresh_from_db()
        self.assertEqual(self.user.subscription.plan, "premium")
        self.assertEqual(self.user.subscription.status, "active")


class BillingAndDashboardTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="payer@example.com",
            email="payer@example.com",
        )

    def test_checkout_webhook_is_idempotent(self):
        event = {
            "id": "evt_checkout_1",
            "type": "checkout.session.completed",
            "data": {"object": {
                "object": "checkout.session",
                "client_reference_id": str(self.user.id),
                "customer": "cus_123",
                "subscription": "sub_123",
                "payment_status": "paid",
                "metadata": {"user_id": str(self.user.id), "plan": "premium"},
            }},
        }
        self.assertTrue(process_webhook_event(event))
        self.assertFalse(process_webhook_event(event))
        self.user.subscription.refresh_from_db()
        self.assertEqual(self.user.subscription.plan, "premium")
        self.assertEqual(self.user.subscription.status, "active")
        self.assertEqual(StripeEvent.objects.filter(stripe_event_id="evt_checkout_1").count(), 1)

    def test_dashboard_is_staff_only(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("staff_dashboard"))
        self.assertEqual(response.status_code, 302)

        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        response = self.client.get(reverse("staff_dashboard"))
        self.assertEqual(response.status_code, 200)
