from django.apps import AppConfig


class StationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "station"
    verbose_name = "Outlet set-up"

    def ready(self):
        from . import signals  # noqa: F401  (adds MS and HSD to every new business)
