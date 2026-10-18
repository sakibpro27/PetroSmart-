from datetime import date

from django.utils import timezone
from django.views.generic import TemplateView

from audit.models import AuditLog
from operations.services import due_reminders
from sales.services import viewable_outlets
from tenants.permissions import BusinessMemberRequiredMixin

from . import dashboard


class HomeView(BusinessMemberRequiredMixin, TemplateView):
    """Dashboard: today's sales, stock, deliveries, collections, exceptions and pending approvals."""

    template_name = "core/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        outlets = viewable_outlets(user).filter(is_active=True)
        selected = self.request.GET.get("outlet", "")
        if selected.isdigit():
            outlets = outlets.filter(pk=selected)
        day = timezone.localdate()
        try:
            day = min(date.fromisoformat(self.request.GET.get("day", "")), day)
        except ValueError:
            pass
        context.update(
            dash=dashboard.build(user, outlets, day),
            due_reminders=due_reminders(user),
            outlet_choices=viewable_outlets(user).filter(is_active=True),
            selected_outlet=selected,
            today=timezone.localdate(),
        )
        if user.is_dealer:
            context["recent_activity"] = (
                AuditLog.objects.filter(business=self.request.business).select_related("user")[:8]
            )
        return context
