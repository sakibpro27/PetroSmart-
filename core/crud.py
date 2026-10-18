"""
Reusable view behaviour for the Dealer's add/edit screens.

Every save is written to the audit log with the fields that changed, and the
record is always looked up inside the logged-in user's business.
"""

from django.contrib import messages

from audit.models import AuditLog
from tenants.models import Outlet
from tenants.permissions import DealerRequiredMixin, get_for_business


class AuditedFormViewMixin:
    """Use with CreateView or UpdateView. Renders the shared form page."""

    template_name = "crud/form.html"
    page_title = ""

    def get_page_title(self):
        if self.page_title:
            return self.page_title
        name = self.model._meta.verbose_name
        return f"Edit {name}" if getattr(self, "object", None) else f"Add {name}"

    def get_cancel_url(self):
        # Use a fixed success_url directly: Django's get_success_url() needs a
        # saved object, which a new record with form errors does not have yet.
        if getattr(self, "success_url", None):
            return str(self.success_url)
        return self.get_success_url()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = self.get_page_title()
        context["cancel_url"] = self.get_cancel_url()
        return context

    def form_valid(self, form):
        is_new = form.instance.pk is None
        response = super().form_valid(form)
        changes = form.audit_changes()
        name = self.model._meta.verbose_name
        if is_new or changes:
            AuditLog.record(
                AuditLog.Action.CREATE if is_new else AuditLog.Action.UPDATE,
                f"{'Added' if is_new else 'Updated'} {name} {self.object}",
                user=self.request.user,
                business=self.request.business,
                obj=self.object,
                changes=changes,
                request=self.request,
            )
            messages.success(self.request, f"{name.capitalize()} “{self.object}” saved.")
        else:
            messages.info(self.request, "No changes were made.")
        return response


class TenantFormViewMixin(DealerRequiredMixin, AuditedFormViewMixin):
    """Dealer-only add/edit of a tenant-owned model."""

    def get_queryset(self):
        return self.model.objects.for_business(self.request.business)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["business"] = self.request.business
        return kwargs


class OutletScopedFormViewMixin(TenantFormViewMixin):
    """
    For records that belong to one outlet (dispensers, nozzles, shifts, prices).
    Add URLs carry `outlet_pk`; edit URLs take the outlet from the record.
    """

    def get_outlet(self):
        if not hasattr(self, "_outlet"):
            if "outlet_pk" in self.kwargs:
                self._outlet = get_for_business(Outlet, self.request.business, pk=self.kwargs["outlet_pk"])
            else:
                self._outlet = self.object.outlet
        return self._outlet

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["outlet"] = self.get_outlet()
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_subtitle"] = str(self.get_outlet())
        return context

    def get_success_url(self):
        return self.get_outlet().get_setup_url()
