"""
Append-only audit log.

Records are written by the application and can never be edited or deleted
through the ORM. Later phases (Daily Sales approvals, corrections, etc.) call
`AuditLog.record(...)` for every important action.
"""

from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    class Action(models.TextChoices):
        LOGIN = "LOGIN", "Logged in"
        LOGOUT = "LOGOUT", "Logged out"
        LOGIN_FAILED = "LOGIN_FAILED", "Failed login"
        CREATE = "CREATE", "Created"
        UPDATE = "UPDATE", "Updated"
        DELETE = "DELETE", "Deleted"
        SUBMIT = "SUBMIT", "Submitted"
        APPROVE = "APPROVE", "Approved"
        REJECT = "REJECT", "Rejected"
        CORRECT = "CORRECT", "Corrected"

    business = models.ForeignKey(
        "tenants.Business", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    action = models.CharField(max_length=20, choices=Action.choices)
    object_type = models.CharField(max_length=100, blank=True)
    object_id = models.CharField(max_length=64, blank=True)
    description = models.CharField(max_length=255)
    changes = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["business", "-created_at"])]

    def __str__(self):
        return f"{self.created_at:%d-%m-%Y %H:%M} {self.get_action_display()}: {self.description}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionError("Audit log entries cannot be modified.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Audit log entries cannot be deleted.")

    @classmethod
    def record(cls, action, description, *, user=None, business=None, obj=None, changes=None, request=None):
        if business is None and user is not None and getattr(user, "business_id", None):
            business = user.business
        return cls.objects.create(
            action=action,
            description=description[:255],
            user=user if user is not None and user.is_authenticated else None,
            business=business,
            object_type=obj._meta.label if obj is not None else "",
            object_id=str(obj.pk) if obj is not None else "",
            changes=changes or {},
            ip_address=client_ip(request) if request is not None else None,
        )


def client_ip(request):
    # REMOTE_ADDR is set by the server; X-Forwarded-For is only trustworthy
    # behind a known proxy, which is configured in Phase 9.
    return request.META.get("REMOTE_ADDR") or None
