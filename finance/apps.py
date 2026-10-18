from django.apps import AppConfig


class FinanceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "finance"
    verbose_name = "Collections, credit and expenses"

    def ready(self):
        from . import signals  # noqa: F401  (default payment methods and expense categories)
