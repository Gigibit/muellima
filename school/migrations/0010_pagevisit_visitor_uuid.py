import uuid

from django.db import migrations, models


def assign_visitor_ids(apps, schema_editor):
    PageVisit = apps.get_model("school", "PageVisit")
    visitor_ids_by_ip = {}
    for visit in PageVisit.objects.order_by("ip_address", "id").iterator():
        visitor_id = visitor_ids_by_ip.setdefault(visit.ip_address, uuid.uuid4())
        PageVisit.objects.filter(pk=visit.pk).update(visitor_id=visitor_id)


class Migration(migrations.Migration):
    dependencies = [("school", "0009_pagevisit_categories_reset_analytics")]

    operations = [
        migrations.RemoveConstraint(
            model_name="pagevisit",
            name="unique_page_visit_per_ip_category",
        ),
        migrations.AddField(
            model_name="pagevisit",
            name="visitor_id",
            field=models.UUIDField(db_index=True, editable=False, null=True),
        ),
        migrations.RunPython(assign_visitor_ids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="pagevisit",
            name="visitor_id",
            field=models.UUIDField(default=uuid.uuid4, db_index=True, editable=False),
        ),
        migrations.AddConstraint(
            model_name="pagevisit",
            constraint=models.UniqueConstraint(
                fields=("visitor_id", "category"),
                name="unique_page_visit_per_visitor_category",
            ),
        ),
    ]
