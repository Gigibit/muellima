from django.db import migrations, models


def reset_prelaunch_analytics(apps, schema_editor):
    apps.get_model("school", "LessonSession").objects.all().delete()
    apps.get_model("school", "UsageRecord").objects.all().delete()
    apps.get_model("school", "PageVisit").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("school", "0008_purchasewhitelist_courseinterest")]

    operations = [
        migrations.RunPython(reset_prelaunch_analytics, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name="pagevisit",
            name="unique_page_visit_per_ip_path",
        ),
        migrations.RenameField(
            model_name="pagevisit",
            old_name="path",
            new_name="category",
        ),
        migrations.AlterField(
            model_name="pagevisit",
            name="category",
            field=models.CharField(max_length=100),
        ),
        migrations.AddConstraint(
            model_name="pagevisit",
            constraint=models.UniqueConstraint(
                fields=("ip_address", "category"),
                name="unique_page_visit_per_ip_category",
            ),
        ),
    ]
