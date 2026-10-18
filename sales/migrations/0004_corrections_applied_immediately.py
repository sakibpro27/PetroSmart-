"""
Shift Cards have no approval step. Corrections that were approved under the
old workflow are kept as "Applied"; pending or rejected ones never changed any
figure, so they are removed.
"""

from django.db import migrations


def mark_applied(apps, schema_editor):
    SalesCorrection = apps.get_model("sales", "SalesCorrection")
    SalesCorrection.objects.exclude(status__in=["APPROVED", "APPLIED"]).delete()
    SalesCorrection.objects.filter(status="APPROVED").update(status="APPLIED")


class Migration(migrations.Migration):
    dependencies = [("sales", "0003_alter_dailysalessheet_options_and_more")]

    operations = [migrations.RunPython(mark_applied, migrations.RunPython.noop)]
