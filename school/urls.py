from django.urls import path
from . import views

urlpatterns = [
    # Pages
    path("", views.home, name="home"),
    path("login/", views.login_page, name="login"),
    path("register/", views.register_page, name="register"),
    path("profile/", views.profile_page, name="profile"),
    path("plans/", views.plans_page, name="plans"),
    path("dashboard/", views.staff_dashboard, name="staff_dashboard"),
    path("dashboard/purchase-whitelist/add/", views.add_purchase_whitelist, name="add_purchase_whitelist"),
    path("dashboard/purchase-whitelist/<int:user_id>/remove/", views.remove_purchase_whitelist, name="remove_purchase_whitelist"),
    path("course/<int:course_id>/", views.course_page, name="course_page"),
    path("course/<int:course_id>/lesson/", views.lesson_page, name="lesson_page"),

    # API
    path("api/courses/generate/", views.generate_course, name="api_generate_course"),
    path("api/me/courses/history/", views.course_history, name="api_course_history"),
    path("api/me/courses/history/<int:course_id>/hide/", views.hide_course_history, name="api_hide_course_history"),
    path("api/subjects/suggestions/", views.subject_suggestions, name="api_subject_suggestions"),
    path("api/realtime/session/", views.create_realtime_session, name="api_realtime_session"),
    path("api/realtime/end/", views.end_realtime_session, name="api_end_realtime_session"),
    path("api/lessons/<int:lesson_id>/quiz/", views.generate_quiz, name="api_generate_quiz"),
    path("api/lessons/<int:lesson_id>/complete/", views.complete_lesson, name="api_complete_lesson"),
    path("api/illustrations/", views.generate_illustration, name="api_generate_illustration"),
    path("api/realtime/usage/", views.record_realtime_usage, name="api_realtime_usage"),
    path("billing/checkout/<int:course_id>/<str:plan>/", views.create_checkout, name="create_checkout"),
    path("billing/success/", views.checkout_success, name="checkout_success"),
    path("billing/portal/", views.billing_portal, name="billing_portal"),
    path("billing/webhook/", views.stripe_webhook, name="stripe_webhook"),
]
