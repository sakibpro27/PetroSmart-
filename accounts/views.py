"""
Dealer screens for managing the people who use PetroSmart in their business.

Every lookup is limited to `request.business`, so a dealer can never see or
change a user of another business by editing the URL.
"""

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils.functional import cached_property
from django.views.generic import CreateView, FormView, ListView, UpdateView

from audit.models import AuditLog
from core.crud import AuditedFormViewMixin
from tenants.permissions import DealerRequiredMixin

from .forms import BusinessUserCreateForm, BusinessUserForm, StyledSetPasswordForm
from .models import User


class BusinessUsersMixin(DealerRequiredMixin):
    model = User

    def get_queryset(self):
        return User.objects.filter(business=self.request.business)


class UserListView(BusinessUsersMixin, ListView):
    template_name = "accounts/user_list.html"
    context_object_name = "users"

    def get_queryset(self):
        return super().get_queryset().prefetch_related("assigned_outlets").order_by("-is_active", "role", "username")


class UserFormMixin(BusinessUsersMixin, AuditedFormViewMixin):
    success_url = reverse_lazy("accounts:user_list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs.update(business=self.request.business, editor=self.request.user)
        return kwargs


class UserCreateView(UserFormMixin, CreateView):
    form_class = BusinessUserCreateForm
    page_title = "Add user"


class UserUpdateView(UserFormMixin, UpdateView):
    form_class = BusinessUserForm
    page_title = "Edit user"


class UserSetPasswordView(BusinessUsersMixin, FormView):
    """The Dealer sets a new password for a user, e.g. when a manager forgets theirs."""

    form_class = StyledSetPasswordForm
    template_name = "crud/form.html"

    @cached_property
    def target(self):
        # Only reached after DealerRequiredMixin has checked the request.
        return get_object_or_404(self.get_queryset(), pk=self.kwargs["pk"])

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.target
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = f"Set new password for {self.target.get_full_name() or self.target.username}"
        context["cancel_url"] = reverse("accounts:user_list")
        return context

    def form_valid(self, form):
        form.save()
        if self.target.pk == self.request.user.pk:
            update_session_auth_hash(self.request, self.target)  # stay logged in
        AuditLog.record(
            AuditLog.Action.UPDATE,
            f"Password changed for {self.target.username}",
            user=self.request.user,
            business=self.request.business,
            obj=self.target,
            request=self.request,
        )
        messages.success(self.request, f"Password updated for {self.target.username}.")
        return redirect("accounts:user_list")
