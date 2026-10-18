"""
Purchase invoice rows now match the printed invoice: quantity in KL, rate per
KL, delivery charges, VAT, cess, TCS and a tank on every row, with the invoice
amount calculated from the rows.

Older purchases only stored litres x rate and a typed-in invoice amount, so
the tax split cannot be recovered from them. Rather than guess, this
migration stops if any old purchases exist (none did when it was written).
"""

from django.db import migrations, models
import django.core.validators
import django.db.models.deletion
from decimal import Decimal


def refuse_old_purchases(apps, schema_editor):
    if apps.get_model("purchases", "PurchaseLine").objects.exists():
        raise RuntimeError(
            "Existing fuel purchases cannot be converted automatically to the new invoice layout. "
            "Export or delete them, run the migration, then re-enter them."
        )


class Migration(migrations.Migration):

    dependencies = [
        ("purchases", "0005_line_order"),
        ("station", "0003_tank_nozzle_tank_tank_unique_tank_code_per_outlet"),
    ]

    operations = [
        migrations.RunPython(refuse_old_purchases, migrations.RunPython.noop),
        migrations.RemoveConstraint(model_name="purchaseline", name="unique_product_per_purchase"),
        migrations.RemoveField(model_name="purchaseline", name="purchase_rate"),
        migrations.AddField(
            model_name="purchaseline",
            name="tank",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="purchase_lines",
                                    to="station.tank"),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="purchaseline",
            name="rate_per_kl",
            field=models.DecimalField(decimal_places=2, max_digits=12, verbose_name="rate (₹ per KL)",
                                      validators=[django.core.validators.MinValueValidator(Decimal("0.01"))]),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="purchaseline",
            name="delivery_charges",
            field=models.DecimalField(decimal_places=2, default=Decimal("0"), max_digits=14,
                                      verbose_name="dly taxable charges",
                                      validators=[django.core.validators.MinValueValidator(Decimal("0"))]),
        ),
        migrations.AddField(
            model_name="purchaseline",
            name="vat",
            field=models.DecimalField(decimal_places=2, default=Decimal("0"), max_digits=14, verbose_name="VAT",
                                      validators=[django.core.validators.MinValueValidator(Decimal("0"))]),
        ),
        migrations.AddField(
            model_name="purchaseline",
            name="cess",
            field=models.DecimalField(decimal_places=2, default=Decimal("0"), max_digits=14,
                                      validators=[django.core.validators.MinValueValidator(Decimal("0"))]),
        ),
        migrations.AddField(
            model_name="purchaseline",
            name="tcs",
            field=models.DecimalField(decimal_places=2, default=Decimal("0"), max_digits=14, verbose_name="TCS",
                                      validators=[django.core.validators.MinValueValidator(Decimal("0"))]),
        ),
        migrations.AddField(
            model_name="purchaseline",
            name="received_litres",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True,
                                      help_text="Litres actually unloaded into the tank. Empty means the same as the invoice.",
                                      validators=[django.core.validators.MinValueValidator(Decimal("0.01"))]),
        ),
        migrations.AddConstraint(
            model_name="purchaseline",
            constraint=models.UniqueConstraint(fields=("purchase", "tank"), name="unique_tank_per_purchase"),
        ),
        migrations.AddField(
            model_name="fuelpurchase",
            name="round_up",
            field=models.BooleanField(default=False, help_text="Round the invoice total to the nearest rupee."),
        ),
        migrations.AddField(
            model_name="fuelpurchase",
            name="round_off",
            field=models.DecimalField(decimal_places=2, default=Decimal("0"), editable=False, max_digits=14),
        ),
    ]
