from django.urls import path
from . import views

urlpatterns = [
    # Pages
    path("", views.home, name="home"),
    path("course/<int:course_id>/", views.course_page, name="course_page"),
    path("course/<int:course_id>/lesson/", views.lesson_page, name="lesson_page"),

    # API
    path("api/courses/generate/", views.generate_course, name="api_generate_course"),
    path("api/realtime/session/", views.create_realtime_session, name="api_realtime_session"),
    path("api/lessons/<int:lesson_id>/quiz/", views.generate_quiz, name="api_generate_quiz"),
    path("api/lessons/<int:lesson_id>/complete/", views.complete_lesson, name="api_complete_lesson"),
    path("api/illustrations/", views.generate_illustration, name="api_generate_illustration"),
]
