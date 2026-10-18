"""Give businesses that existed before Phase 2 their MS and HSD products."""

from django.db import migrations

DEFAULT_PRODUCTS = [("MS", "MS", "Petrol (MS)"), ("HSD", "HSD", "Diesel (HSD)")]


def add_default_products(apps, schema_editor):
    Business = apps.get_model("tenants", "Business")
    FuelProduct = apps.get_model("station", "FuelProduct")
    for business in Business.objects.all():
        for category, code, name in DEFAULT_PRODUCTS:
            FuelProduct.objects.get_or_create(
                business=business, code=code, defaults={"category": category, "name": name}
            )


class Migration(migrations.Migration):
    dependencies = [
        ("station", "0001_initial"),
        ("tenants", "0002_alter_outlet_unique_outlet_code_per_business"),
    ]

    # Reversing leaves the products in place; the 0001 reversal drops the table anyway.
    operations = [migrations.RunPython(add_default_products, migrations.RunPython.noop)]
