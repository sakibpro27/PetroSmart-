from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from audit.models import AuditLog

from .models import Business, SubscriptionPlan
from .services import renew
from .test_utils import make_business, make_outlet, make_user


class RenewalTests(TestCase):
    def setUp(self):
        self.business = make_business("Shree Ganesh Fuels", days_left=10)
        self.admin = User.objects.create_superuser(username="platform", password="x", email="p@example.com")

    def test_active_subscription_extends_from_current_end(self):
        old_end = self.business.subscription_ends_on
        renewal = renew(self.business, months=12, recorded_by=self.admin, amount=12000, reference="INV-77")
        self.business.refresh_from_db()
        self.assertEqual(self.business.subscription_ends_on, old_end.replace(year=old_end.year + 1))
        self.assertEqual((renewal.previous_end, renewal.new_end), (old_end, self.business.subscription_ends_on))
        self.assertTrue(AuditLog.objects.filter(business=self.business, description__startswith="Subscription renewed").exists())

    def test_expired_subscription_extends_from_today_and_reactivates(self):
        self.business.subscription_ends_on = timezone.localdate() - timedelta(days=40)
        self.business.status = Business.Status.SUSPENDED
        self.business.save()
        renew(self.business, months=1, recorded_by=self.admin)
        self.business.refresh_from_db()
        self.assertTrue(self.business.has_access)
        self.assertGreaterEqual(self.business.subscription_ends_on, timezone.localdate() + timedelta(days=28))

    def test_admin_renew_action(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("admin:tenants_business_changelist"),
                                    {"action": "renew_12_months", "_selected_action": [self.business.pk]})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.business.renewals.count(), 1)

    def test_plan_downgrade_beyond_usage_is_refused(self):
        make_outlet(self.business, "SGF-01")
        make_outlet(self.business, "SGF-02")
        tiny = SubscriptionPlan.objects.create(name="Tiny", code="tiny", max_outlets=1, max_users=5)
        self.business.plan = tiny
        with self.assertRaisesMessage(ValidationError, "allows 1 active outlet"):
            self.business.full_clean()

    def test_dealer_sees_expiry_warning_and_history(self):
        dealer = make_user("dealer", self.business, User.Role.DEALER)
        renew(self.business, months=0, recorded_by=self.admin)  # history entry without extending
        self.client.force_login(dealer)
        self.assertContains(self.client.get(reverse("core:home")), "subscription ends on")
        self.assertContains(self.client.get(reverse("tenants:subscription")), "Renewal history")
