from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from .models import AuditLog


@receiver(user_logged_in)
def log_login(sender, request, user, **kwargs):
    AuditLog.record(AuditLog.Action.LOGIN, f"{user.username} logged in", user=user, request=request)


@receiver(user_logged_out)
def log_logout(sender, request, user, **kwargs):
    if user is not None:
        AuditLog.record(AuditLog.Action.LOGOUT, f"{user.username} logged out", user=user, request=request)


@receiver(user_login_failed)
def log_login_failed(sender, credentials, request=None, **kwargs):
    # Django already removes the password from `credentials`; store only the username.
    username = str(credentials.get("username", ""))[:150]
    # Link the attempt to the account's business so its Dealer can see it.
    from accounts.models import User

    target = User.objects.filter(username__iexact=username).only("business").first()
    AuditLog.record(
        AuditLog.Action.LOGIN_FAILED,
        f"Failed login for '{username}'",
        business=target.business if target is not None and target.business_id else None,
        changes={"username": username},
        request=request,
    )
