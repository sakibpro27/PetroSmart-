"""Login, password and user-management forms."""

from datetime import timedelta

from django import forms
from django.utils import timezone
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm, PasswordResetForm, SetPasswordForm
from django.core.exceptions import ValidationError

from core.forms import BootstrapFormMixin, TenantModelForm
from tenants.models import Outlet

from .models import User


LOCKOUT_MINUTES = 15
MAX_FAILURES_PER_USERNAME = 5
MAX_FAILURES_PER_IP = 20


class StyledAuthenticationForm(BootstrapFormMixin, AuthenticationForm):
    error_messages = {
        **AuthenticationForm.error_messages,
        "locked": f"Too many failed attempts. For your security, wait {LOCKOUT_MINUTES} minutes and try again, "
                  "or ask your Dealer to reset your password.",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update({"autofocus": True, "autocomplete": "username"})
        self.fields["password"].widget.attrs.update({"autocomplete": "current-password"})

    def clean(self):
        # Slow down password guessing: refuse to even check the password after
        # repeated recent failures for this username or from this address.
        from audit.models import AuditLog, client_ip

        since = timezone.now() - timedelta(minutes=LOCKOUT_MINUTES)
        failures = AuditLog.objects.filter(action=AuditLog.Action.LOGIN_FAILED, created_at__gte=since)
        username = (self.cleaned_data.get("username") or "").strip()
        ip = client_ip(self.request) if self.request is not None else None
        if (username and failures.filter(changes__username__iexact=username).count() >= MAX_FAILURES_PER_USERNAME) or (
            ip and failures.filter(ip_address=ip).count() >= MAX_FAILURES_PER_IP
        ):
            raise ValidationError(self.error_messages["locked"], code="locked")
        return super().clean()


class StyledPasswordResetForm(BootstrapFormMixin, PasswordResetForm):
    pass


class StyledSetPasswordForm(BootstrapFormMixin, SetPasswordForm):
    pass


class BusinessUserForm(TenantModelForm):
    """The Dealer's form for editing a Dealer or Manager of their own business."""

    class Meta:
        model = User
        fields = ["first_name", "last_name", "username", "email", "phone", "role", "assigned_outlets", "is_active"]
        widgets = {"assigned_outlets": forms.CheckboxSelectMultiple}
        labels = {"is_active": "Account active", "assigned_outlets": "Outlets this manager works at"}
        help_texts = {
            "username": "Used to log in. Letters, digits and @ . + - _ only.",
            "is_active": "Inactive users cannot log in. Their past records are kept.",
            "assigned_outlets": "Dealers can always access every outlet.",
        }

    def __init__(self, *args, editor, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].required = True
        self.fields["role"].required = True
        self.fields["role"].choices = User.Role.choices
        self.fields["assigned_outlets"].queryset = (
            Outlet.objects.for_business(self.business).filter(is_active=True)
        )
        self._was_active = bool(self.instance.pk and self.instance.is_active)

        # A dealer must not lock themselves out by mistake.
        if self.instance.pk and self.instance.pk == editor.pk:
            for name in ("role", "is_active"):
                if name in self.fields:
                    self.fields[name].disabled = True
                    self.fields[name].help_text = "You cannot change your own role or deactivate your own account."

    def clean(self):
        cleaned = super().clean()
        role = cleaned.get("role")
        if role == User.Role.DEALER:
            cleaned["assigned_outlets"] = Outlet.objects.none()
        elif role == User.Role.MANAGER and not cleaned.get("assigned_outlets"):
            self.add_error("assigned_outlets", "Assign at least one outlet to a manager.")

        becoming_active = cleaned.get("is_active", True) and not self._was_active
        if becoming_active:
            plan = self.business.plan
            active_users = User.objects.filter(business=self.business, is_active=True).count()
            if active_users >= plan.max_users:
                raise ValidationError(
                    f"Your {plan.name} plan allows {plan.max_users} active users. "
                    "Deactivate a user or upgrade your plan."
                )
        return cleaned


class BusinessUserCreateForm(BusinessUserForm):
    password1 = forms.CharField(
        label="Password",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text=password_validation.password_validators_help_text_html(),
    )
    password2 = forms.CharField(
        label="Confirm password",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    class Meta(BusinessUserForm.Meta):
        fields = ["first_name", "last_name", "username", "email", "phone", "role", "assigned_outlets"]

    def clean(self):
        cleaned = super().clean()
        password1, password2 = cleaned.get("password1"), cleaned.get("password2")
        if password1 and password2 and password1 != password2:
            self.add_error("password2", "The two passwords do not match.")
        elif password1:
            # Check the password against this user's own details (e.g. not like the username).
            candidate = User(
                username=cleaned.get("username", ""),
                first_name=cleaned.get("first_name", ""),
                last_name=cleaned.get("last_name", ""),
                email=cleaned.get("email", ""),
            )
            try:
                password_validation.validate_password(password1, candidate)
            except ValidationError as error:
                self.add_error("password1", error)
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
            self.save_m2m()
        return user
