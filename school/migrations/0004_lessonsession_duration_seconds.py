from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("school", "0003_stripeevent_course_cache_key_lessonsession_student_and_more")
    ]

    operations = [
        migrations.AddField(
            model_name="lessonsession",
            name="duration_seconds",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="lessonsession",
            name="is_trial",
            field=models.BooleanField(default=False),
        ),
    ]
