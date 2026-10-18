from django.shortcuts import redirect
from django.views.generic import TemplateView

from .models import Outlet
from .permissions import DealerRequiredMixin


class SubscriptionView(DealerRequiredMixin, TemplateView):
    """Dealer-only: current plan, status and renewal date."""

    template_name = "tenants/subscription.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        business = self.request.business
        context["outlet_count"] = (
            Outlet.objects.for_business(business).filter(is_active=True).count()
        )
        context["user_count"] = business.users.filter(is_active=True).count()
        context["renewals"] = business.renewals.select_related("plan")[:10]
        return context


class SubscriptionInactiveView(TemplateView):
    """Shown when a business is suspended, cancelled or past its end date."""

    template_name = "tenants/subscription_inactive.html"

    def dispatch(self, request, *args, **kwargs):
        user = request.user
        if not user.is_business_user:
            return redirect("core:home")
        if user.business.has_access:
            return redirect("core:home")
        return super().dispatch(request, *args, **kwargs)
