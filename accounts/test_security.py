from django.test import TestCase
from django.urls import reverse

from audit.models import AuditLog
from tenants.test_utils import TEST_PASSWORD, make_business, make_user

from .forms import MAX_FAILURES_PER_USERNAME
from .models import User


class LoginLockoutTests(TestCase):
    def setUp(self):
        self.business = make_business("Shree Ganesh Fuels")
        make_user("dealer", self.business, User.Role.DEALER)

    def fail(self, username="dealer"):
        return self.client.post(reverse("login"), {"username": username, "password": "wrong-password"})

    def test_locked_after_repeated_failures_even_with_right_password(self):
        for _ in range(MAX_FAILURES_PER_USERNAME):
            self.fail()
        response = self.client.post(reverse("login"), {"username": "dealer", "password": TEST_PASSWORD})
        self.assertContains(response, "Too many failed attempts")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_lockout_ignores_username_case(self):
        for _ in range(MAX_FAILURES_PER_USERNAME):
            self.fail("DEALER")
        self.assertContains(self.client.post(reverse("login"), {"username": "dealer", "password": TEST_PASSWORD}),
                            "Too many failed attempts")

    def test_other_users_not_affected(self):
        make_user("manager", self.business, User.Role.MANAGER)
        for _ in range(MAX_FAILURES_PER_USERNAME):
            self.fail()
        response = self.client.post(reverse("login"), {"username": "manager", "password": TEST_PASSWORD})
        self.assertRedirects(response, reverse("core:home"))

    def test_failed_login_is_visible_to_that_business(self):
        self.fail()
        entry = AuditLog.objects.get(action=AuditLog.Action.LOGIN_FAILED)
        self.assertEqual(entry.business, self.business)
        unknown = self.fail("nobody")
        self.assertEqual(unknown.status_code, 200)
        self.assertIsNone(AuditLog.objects.get(changes__username="nobody").business)


class ProductionSettingsTests(TestCase):
    def test_secure_defaults(self):
        from django.conf import settings

        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)
        self.assertEqual(settings.X_FRAME_OPTIONS, "DENY")
        self.assertIn("django.contrib.auth.middleware.LoginRequiredMiddleware", settings.MIDDLEWARE)
        self.assertIn("django.middleware.csrf.CsrfViewMiddleware", settings.MIDDLEWARE)
