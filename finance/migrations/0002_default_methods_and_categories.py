"""Give businesses that existed before Phase 6 the default payment methods and expense categories."""

from django.db import migrations

DEFAULT_METHODS = [("Cash", "CASH", 1), ("UPI", "UPI", 2), ("Card", "CARD", 3), ("Bank transfer", "BANK", 4)]
DEFAULT_CATEGORIES = ["Electricity", "Salaries and wages", "Repairs and maintenance", "Rent", "Bank charges",
                      "Office and stationery", "Other"]


def add_defaults(apps, schema_editor):
    Business = apps.get_model("tenants", "Business")
    PaymentMethod = apps.get_model("finance", "PaymentMethod")
    ExpenseCategory = apps.get_model("finance", "ExpenseCategory")
    for business in Business.objects.all():
        for name, kind, order in DEFAULT_METHODS:
            PaymentMethod.objects.get_or_create(business=business, name=name, defaults={"kind": kind, "sort_order": order})
        for name in DEFAULT_CATEGORIES:
            ExpenseCategory.objects.get_or_create(business=business, name=name)


class Migration(migrations.Migration):
    dependencies = [("finance", "0001_initial")]

    operations = [migrations.RunPython(add_defaults, migrations.RunPython.noop)]
