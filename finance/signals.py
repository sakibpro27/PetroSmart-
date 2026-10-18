from django.db.models.signals import post_save
from django.dispatch import receiver

from tenants.models import Business

from .models import create_default_finance_setup


@receiver(post_save, sender=Business)
def add_default_finance_setup(sender, instance, created, raw=False, **kwargs):
    if created and not raw:
        create_default_finance_setup(instance)
