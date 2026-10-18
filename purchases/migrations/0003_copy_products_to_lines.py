"""Move each existing invoice's single product, litres and rate into a PurchaseLine."""

from django.db import migrations


def copy_to_lines(apps, schema_editor):
    FuelPurchase = apps.get_model("purchases", "FuelPurchase")
    PurchaseLine = apps.get_model("purchases", "PurchaseLine")
    for purchase in FuelPurchase.objects.all():
        PurchaseLine.objects.get_or_create(
            purchase=purchase, product_id=purchase.product_id,
            defaults={"business_id": purchase.business_id, "invoiced_litres": purchase.invoiced_litres,
                      "purchase_rate": purchase.purchase_rate},
        )


class Migration(migrations.Migration):
    dependencies = [("purchases", "0002_purchaseline")]

    operations = [migrations.RunPython(copy_to_lines, migrations.RunPython.noop)]
