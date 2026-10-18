"""
Credit slips get an automatic slip number (one series per outlet), a product,
rate and litres, and can be put on a credit bill.

Existing credit sales keep their amounts. They are numbered 1, 2, 3... per
outlet in the order they were entered, and their product, rate and litres
stay empty because they were never recorded.
"""

import django.core.validators
import django.db.models.deletion
from decimal import Decimal

from django.conf import settings
from django.db import migrations, models


def number_existing_slips(apps, schema_editor):
    CreditSale = apps.get_model("finance", "CreditSale")
    counters = {}
    for sale in CreditSale.objects.select_related("sheet").order_by("pk"):
        outlet_id = sale.sheet.outlet_id
        counters[outlet_id] = counters.get(outlet_id, 0) + 1
        sale.outlet_id = outlet_id
        sale.slip_no = counters[outlet_id]
        sale.save(update_fields=["outlet", "slip_no"])


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0004_creditsale_sheet_required"),
        ("station", "0003_tank_nozzle_tank_tank_unique_tank_code_per_outlet"),
        ("tenants", "0004_outlet_bill_letterhead"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="creditsale",
            name="outlet",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name="credit_sales", to="tenants.outlet"),
        ),
        migrations.AddField(
            model_name="creditsale",
            name="slip_no",
            field=models.PositiveIntegerField(null=True, verbose_name="slip no."),
        ),
        migrations.RunPython(number_existing_slips, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="creditsale",
            name="outlet",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="credit_sales",
                                    to="tenants.outlet"),
        ),
        migrations.AlterField(
            model_name="creditsale",
            name="slip_no",
            field=models.PositiveIntegerField(verbose_name="slip no."),
        ),
        migrations.RemoveField(model_name="creditsale", name="slip_number"),
        migrations.AddField(
            model_name="creditsale",
            name="product",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name="credit_sales", to="station.fuelproduct"),
        ),
        migrations.AddField(
            model_name="creditsale",
            name="rate",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=7, null=True, verbose_name="rate (₹/L)"),
        ),
        migrations.AddField(
            model_name="creditsale",
            name="litres",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True, verbose_name="qty (L)"),
        ),
        migrations.AddConstraint(
            model_name="creditsale",
            constraint=models.UniqueConstraint(fields=("outlet", "slip_no"), name="unique_slip_no_per_outlet"),
        ),
        migrations.CreateModel(
            name="CreditBill",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("bill_no", models.PositiveIntegerField(verbose_name="bill no.")),
                ("bill_date", models.DateField(help_text="Slips up to and including this date are billed.")),
                ("period_from", models.DateField()),
                ("status", models.CharField(choices=[("ISSUED", "Issued"), ("CANCELLED", "Cancelled")],
                                            default="ISSUED", max_length=10)),
                ("slips_total", models.DecimalField(decimal_places=2, max_digits=14)),
                ("round_off", models.DecimalField(decimal_places=2, default=Decimal("0"), max_digits=14)),
                ("previous_balance", models.DecimalField(decimal_places=2, max_digits=14)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("cancelled_at", models.DateTimeField(blank=True, null=True)),
                ("cancel_reason", models.CharField(blank=True, max_length=255)),
                ("business", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+",
                                               to="tenants.business")),
                ("outlet", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                             related_name="credit_bills", to="tenants.outlet")),
                ("customer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="bills",
                                               to="finance.creditcustomer")),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+",
                                                 to=settings.AUTH_USER_MODEL)),
                ("cancelled_by", models.ForeignKey(blank=True, null=True,
                                                   on_delete=django.db.models.deletion.PROTECT, related_name="+",
                                                   to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-bill_date", "-bill_no"],
                "constraints": [models.UniqueConstraint(fields=("outlet", "bill_no"), name="unique_bill_no_per_outlet")],
            },
        ),
        migrations.AddField(
            model_name="creditsale",
            name="bill",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name="sales", to="finance.creditbill"),
        ),
    ]
