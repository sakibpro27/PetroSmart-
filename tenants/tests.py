from datetime import timedelta

from django.http import Http404
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User

from .models import Business, Outlet
from .permissions import get_for_business
from .test_utils import TEST_PASSWORD, make_business, make_outlet, make_user


class SubscriptionAccessRuleTests(TestCase):
    def test_active_and_current_has_access(self):
        self.assertTrue(make_business("A").has_access)

    def test_trial_has_access(self):
        self.assertTrue(make_business("A", status=Business.Status.TRIAL).has_access)

    def test_last_day_still_has_access(self):
        self.assertTrue(make_business("A", days_left=0).has_access)

    def test_expired_has_no_access(self):
        self.assertFalse(make_business("A", days_left=-1).has_access)

    def test_suspended_and_cancelled_have_no_access(self):
        self.assertFalse(make_business("A", status=Business.Status.SUSPENDED).has_access)
        self.assertFalse(make_business("B", status=Business.Status.CANCELLED).has_access)

    def test_end_date_before_start_date_is_invalid(self):
        business = make_business("A")
        business.subscription_ends_on = business.subscription_starts_on - timedelta(days=1)
        with self.assertRaises(Exception):
            business.full_clean()


class TenantQueryIsolationTests(TestCase):
    def setUp(self):
        self.ganesh = make_business("Shree Ganesh Fuels")
        self.omsai = make_business("Om Sai Petroleum")
        self.ganesh_outlet = make_outlet(self.ganesh, "SGF-01")
        self.omsai_outlet = make_outlet(self.omsai, "OSP-01")

    def test_for_business_returns_only_that_tenant(self):
        self.assertQuerySetEqual(Outlet.objects.for_business(self.ganesh), [self.ganesh_outlet])
        self.assertQuerySetEqual(Outlet.objects.for_business(self.omsai), [self.omsai_outlet])

    def test_for_business_none_returns_nothing(self):
        self.assertFalse(Outlet.objects.for_business(None).exists())

    def test_fetching_other_tenants_record_by_id_raises_404(self):
        with self.assertRaises(Http404):
            get_for_business(Outlet, self.ganesh, pk=self.omsai_outlet.pk)

    def test_same_outlet_code_allowed_in_different_businesses(self):
        make_outlet(self.omsai, "SGF-01")  # no error: codes are unique per business only


class SubscriptionViewTests(TestCase):
    def setUp(self):
        self.business = make_business("Shree Ganesh Fuels")
        self.dealer = make_user("dealer", self.business, User.Role.DEALER)
        self.manager = make_user("manager", self.business, User.Role.MANAGER)
        self.url = reverse("tenants:subscription")

    def test_dealer_can_view_subscription(self):
        self.client.login(username="dealer", password=TEST_PASSWORD)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Shree Ganesh Fuels")

    def test_manager_is_forbidden(self):
        self.client.login(username="manager", password=TEST_PASSWORD)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_anonymous_is_sent_to_login(self):
        response = self.client.get(self.url)
        self.assertRedirects(response, f"{reverse('login')}?next={self.url}")

    def test_expired_business_is_sent_to_inactive_page(self):
        self.business.subscription_ends_on = timezone.localdate() - timedelta(days=1)
        self.business.save()
        self.client.login(username="dealer", password=TEST_PASSWORD)
        self.assertRedirects(self.client.get(self.url), reverse("tenants:inactive"))
        inactive = self.client.get(reverse("tenants:inactive"))
        self.assertContains(inactive, "does not have an active PetroSmart subscription")

    def test_inactive_page_redirects_home_when_subscription_is_fine(self):
        self.client.login(username="dealer", password=TEST_PASSWORD)
        self.assertRedirects(self.client.get(reverse("tenants:inactive")), reverse("core:home"))
