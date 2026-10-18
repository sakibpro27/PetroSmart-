from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from tenants.models import Business, Outlet
from tenants.test_utils import TEST_PASSWORD, make_business, make_outlet, make_user


class LoginFlowTests(TestCase):
    def setUp(self):
        self.business = make_business("Shree Ganesh Fuels")
        make_user("dealer", self.business, User.Role.DEALER)

    def test_login_page_loads(self):
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "csrfmiddlewaretoken")

    def test_valid_login_goes_to_overview(self):
        response = self.client.post(reverse("login"), {"username": "dealer", "password": TEST_PASSWORD})
        self.assertRedirects(response, reverse("core:home"))

    def test_wrong_password_is_rejected(self):
        response = self.client.post(reverse("login"), {"username": "dealer", "password": "wrong"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_logout_requires_post(self):
        self.client.login(username="dealer", password=TEST_PASSWORD)
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        response = self.client.post(reverse("logout"))
        self.assertRedirects(response, reverse("login"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_password_reset_page_is_public(self):
        self.assertEqual(self.client.get(reverse("password_reset")).status_code, 200)

    def test_suspended_business_cannot_use_app(self):
        self.business.status = Business.Status.SUSPENDED
        self.business.save()
        self.client.login(username="dealer", password=TEST_PASSWORD)
        self.assertRedirects(self.client.get(reverse("core:home")), reverse("tenants:inactive"))


class HomeTenantIsolationTests(TestCase):
    """End-to-end check that each tenant sees only its own outlets."""

    def setUp(self):
        self.ganesh = make_business("Shree Ganesh Fuels")
        self.omsai = make_business("Om Sai Petroleum")
        make_outlet(self.ganesh, "SGF-01", "Ganesh Highway")
        make_outlet(self.ganesh, "SGF-02", "Ganesh City")
        make_outlet(self.omsai, "OSP-01", "Om Sai Main Road")
        make_user("ganesh.dealer", self.ganesh, User.Role.DEALER)
        manager = make_user("ganesh.manager", self.ganesh, User.Role.MANAGER)
        manager.assigned_outlets.add(Outlet.objects.get(business=self.ganesh, code="SGF-01"))

    def test_dealer_sees_own_outlets_not_other_tenants(self):
        self.client.login(username="ganesh.dealer", password=TEST_PASSWORD)
        response = self.client.get(reverse("core:home"))
        self.assertContains(response, "Ganesh Highway")
        self.assertContains(response, "Ganesh City")
        self.assertNotContains(response, "Om Sai")

    def test_manager_sees_only_assigned_outlet(self):
        self.client.login(username="ganesh.manager", password=TEST_PASSWORD)
        response = self.client.get(reverse("core:home"))
        self.assertContains(response, "Ganesh Highway")
        self.assertNotContains(response, "Ganesh City")
        self.assertNotContains(response, "Om Sai")

    def test_manager_does_not_see_dealer_navigation(self):
        self.client.login(username="ganesh.manager", password=TEST_PASSWORD)
        response = self.client.get(reverse("core:home"))
        self.assertNotContains(response, reverse("tenants:subscription"))


class PlatformAdminSeparationTests(TestCase):
    def test_platform_admin_is_sent_to_platform_admin_site(self):
        User.objects.create_superuser(username="platform", password=TEST_PASSWORD, email="p@example.com")
        self.client.login(username="platform", password=TEST_PASSWORD)
        self.assertRedirects(self.client.get(reverse("core:home")), reverse("admin:index"))

    def test_business_user_cannot_open_platform_admin(self):
        business = make_business("Shree Ganesh Fuels")
        make_user("dealer", business, User.Role.DEALER)
        self.client.login(username="dealer", password=TEST_PASSWORD)
        response = self.client.get(reverse("admin:index"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("admin:login"), response.url)
