"""
Access-control building blocks for every business screen.

Use `BusinessMemberRequiredMixin` on any view that shows tenant data, and
`DealerRequiredMixin` on views that only the Dealer may use. Both check the
rules on the server for every request.
"""

from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect


class BusinessMemberRequiredMixin:
    """
    Allows only Dealers and Managers whose business has an active subscription.

    * Platform administrators are sent to the platform admin site.
    * Users of a suspended/expired business see the subscription notice.
    """

    allowed_roles = ("DEALER", "MANAGER")

    def dispatch(self, request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated:
            return redirect("login")
        if not user.is_business_user:
            if user.is_staff:
                return redirect("admin:index")
            raise PermissionDenied("This account is not linked to a business.")
        if not user.business.has_access:
            return redirect("tenants:inactive")
        if user.role not in self.allowed_roles:
            raise PermissionDenied("Your role does not allow this action.")
        return super().dispatch(request, *args, **kwargs)


class DealerRequiredMixin(BusinessMemberRequiredMixin):
    allowed_roles = ("DEALER",)


def get_for_business(model, business, **lookup):
    """
    Fetch one tenant-owned object or raise 404.

    Returning 404 (not 403) for another tenant's ID avoids confirming that the
    record exists at all.
    """
    return get_object_or_404(model.objects.for_business(business), **lookup)
