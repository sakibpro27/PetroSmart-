"""
Credit sales now belong to a Shift Card. Credit sales recorded on the removed
shift-collection screen have no card to belong to, so they are removed before
the link becomes required. (Before this release only demo data existed.)
"""

import django.db.models.deletion
from django.db import migrations, models


def remove_orphans(apps, schema_editor):
    apps.get_model("finance", "CreditSale").objects.filter(sheet__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0003_remove_shiftcollection_business_and_more'),
        ('sales', '0004_corrections_applied_immediately'),
    ]

    operations = [
        migrations.RunPython(remove_orphans, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='creditsale',
            name='sheet',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='credit_sales', to='sales.dailysalessheet', verbose_name='shift card'),
        ),
    ]
