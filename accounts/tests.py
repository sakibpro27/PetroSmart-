from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings

from tenants.test_utils import make_business, make_outlet, make_user

from .models import User


class UserRuleTests(TestCase):
    def setUp(self):
        self.business = make_business("Shree Ganesh Fuels")

    def test_business_user_requires_valid_role_at_database_level(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user(username="x", password="x", business=self.business, role="")

    def test_role_without_business_is_rejected_at_database_level(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user(username="x", password="x", role=User.Role.DEALER)

    def test_business_user_cannot_be_platform_staff(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user(
                username="x", password="x", business=self.business, role=User.Role.DEALER, is_staff=True
            )

    def test_platform_admin_has_no_business(self):
        admin = User.objects.create_superuser(username="platform", password="x", email="p@example.com")
        self.assertFalse(admin.is_business_user)
        self.assertFalse(admin.accessible_outlets().exists())

    def test_clean_explains_invalid_combination(self):
        user = User(username="x", business=self.business, role="")
        with self.assertRaises(ValidationError):
            user.clean()

    def test_password_is_hashed(self):
        # The test run swaps in a fast hasher; check the real production default here.
        from django.conf import global_settings

        with override_settings(PASSWORD_HASHERS=global_settings.PASSWORD_HASHERS):
            user = make_user("dealer", self.business, User.Role.DEALER)
        self.assertNotIn("Test-Password", user.password)
        self.assertTrue(user.password.startswith("pbkdf2_sha256$"))


class AccessibleOutletTests(TestCase):
    def setUp(self):
        self.business = make_business("Shree Ganesh Fuels")
        self.highway = make_outlet(self.business, "SGF-01")
        self.city = make_outlet(self.business, "SGF-02")
        self.other_business = make_business("Om Sai Petroleum")
        self.other_outlet = make_outlet(self.other_business, "OSP-01")

    def test_dealer_sees_all_own_outlets_only(self):
        dealer = make_user("dealer", self.business, User.Role.DEALER)
        self.assertQuerySetEqual(dealer.accessible_outlets(), [self.city, self.highway], ordered=False)

    def test_manager_sees_only_assigned_outlets(self):
        manager = make_user("manager", self.business, User.Role.MANAGER)
        manager.assigned_outlets.add(self.highway)
        self.assertQuerySetEqual(manager.accessible_outlets(), [self.highway])

    def test_wrongly_assigned_outlet_from_other_tenant_is_ignored(self):
        manager = make_user("manager", self.business, User.Role.MANAGER)
        manager.assigned_outlets.add(self.highway, self.other_outlet)
        self.assertNotIn(self.other_outlet, manager.accessible_outlets())

    def test_inactive_outlets_are_excluded(self):
        self.city.is_active = False
        self.city.save()
        dealer = make_user("dealer", self.business, User.Role.DEALER)
        self.assertQuerySetEqual(dealer.accessible_outlets(), [self.highway])
