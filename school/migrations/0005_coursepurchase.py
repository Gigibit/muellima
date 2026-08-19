import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("school", "0004_lessonsession_duration_seconds"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CoursePurchase",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("plan", models.CharField(choices=[("base", "Base — €9,99"), ("pro", "Pro — €19,99"), ("premium", "Premium — €49,99")], max_length=10)),
                ("status", models.CharField(choices=[("pending", "In attesa"), ("paid", "Pagato"), ("refunded", "Rimborsato")], default="pending", max_length=10)),
                ("stripe_customer_id", models.CharField(blank=True, db_index=True, max_length=255)),
                ("stripe_checkout_session_id", models.CharField(blank=True, max_length=255, null=True, unique=True)),
                ("stripe_payment_intent_id", models.CharField(blank=True, db_index=True, max_length=255)),
                ("purchased_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("course", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="purchases", to="school.course")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="course_purchases", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "constraints": [models.UniqueConstraint(fields=("user", "course"), name="unique_course_purchase")],
            },
        ),
    ]
