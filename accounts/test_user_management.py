from django.test import TestCase
from django.urls import reverse

from tenants.test_utils import TEST_PASSWORD, make_business, make_outlet, make_user

from .models import User

NEW_PASSWORD = "Fuel-Station-Pune-77"


class UserManagementTests(TestCase):
    def setUp(self):
        self.ganesh = make_business("Shree Ganesh Fuels")
        self.omsai = make_business("Om Sai Petroleum")
        self.highway = make_outlet(self.ganesh, "SGF-01")
        self.omsai_outlet = make_outlet(self.omsai, "OSP-01")
        self.dealer = make_user("ganesh.dealer", self.ganesh, User.Role.DEALER)
        self.omsai_manager = make_user("omsai.manager", self.omsai, User.Role.MANAGER)
        self.client.login(username="ganesh.dealer", password=TEST_PASSWORD)

    def new_manager_data(self, **overrides):
        data = {
            "first_name": "Ravi", "last_name": "Patil", "username": "ravi.manager", "email": "",
            "phone": "", "role": "MANAGER", "assigned_outlets": [self.highway.pk],
            "password1": NEW_PASSWORD, "password2": NEW_PASSWORD,
        }
        data.update(overrides)
        return data

    def test_dealer_creates_manager_who_can_log_in(self):
        response = self.client.post(reverse("accounts:user_create"), self.new_manager_data())
        self.assertRedirects(response, reverse("accounts:user_list"))
        manager = User.objects.get(username="ravi.manager")
        self.assertEqual((manager.business, manager.role), (self.ganesh, User.Role.MANAGER))
        self.assertQuerySetEqual(manager.assigned_outlets.all(), [self.highway])
        self.assertTrue(manager.check_password(NEW_PASSWORD))
        self.client.logout()
        self.assertTrue(self.client.login(username="ravi.manager", password=NEW_PASSWORD))

    def test_manager_needs_an_outlet(self):
        response = self.client.post(reverse("accounts:user_create"), self.new_manager_data(assigned_outlets=[]))
        self.assertContains(response, "Assign at least one outlet")

    def test_cannot_assign_other_tenants_outlet(self):
        response = self.client.post(
            reverse("accounts:user_create"), self.new_manager_data(assigned_outlets=[self.omsai_outlet.pk])
        )
        self.assertIn("assigned_outlets", response.context["form"].errors)
        self.assertFalse(User.objects.filter(username="ravi.manager").exists())

    def test_weak_or_mismatched_password_rejected(self):
        weak = self.client.post(reverse("accounts:user_create"), self.new_manager_data(password1="12345", password2="12345"))
        self.assertIn("password1", weak.context["form"].errors)
        mismatch = self.client.post(reverse("accounts:user_create"), self.new_manager_data(password2="Different-Pass-99"))
        self.assertIn("password2", mismatch.context["form"].errors)

    def test_user_limit_of_plan_is_enforced(self):
        plan = self.ganesh.plan
        plan.max_users = 1  # the dealer already uses the only place
        plan.save()
        response = self.client.post(reverse("accounts:user_create"), self.new_manager_data())
        self.assertContains(response, "allows 1 active users")

    def test_dealer_role_clears_outlet_assignments(self):
        self.client.post(reverse("accounts:user_create"), self.new_manager_data(role="DEALER", username="partner"))
        partner = User.objects.get(username="partner")
        self.assertTrue(partner.is_dealer)
        self.assertFalse(partner.assigned_outlets.exists())

    def test_role_cannot_be_set_to_platform_admin(self):
        response = self.client.post(reverse("accounts:user_create"), self.new_manager_data(role="ADMIN", is_staff="on"))
        self.assertIn("role", response.context["form"].errors)

    def test_dealer_cannot_lock_themselves_out(self):
        self.client.post(reverse("accounts:user_edit", args=[self.dealer.pk]), {
            "first_name": "Ganesh", "username": "ganesh.dealer", "role": "MANAGER",  # is_active omitted = off
        })
        self.dealer.refresh_from_db()
        self.assertTrue(self.dealer.is_active)
        self.assertTrue(self.dealer.is_dealer)

    def test_other_tenants_users_are_not_reachable(self):
        for url in [
            reverse("accounts:user_edit", args=[self.omsai_manager.pk]),
            reverse("accounts:user_password", args=[self.omsai_manager.pk]),
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)
        self.assertNotContains(self.client.get(reverse("accounts:user_list")), "omsai.manager")

    def test_dealer_resets_manager_password(self):
        manager = make_user("ravi", self.ganesh, User.Role.MANAGER)
        response = self.client.post(reverse("accounts:user_password", args=[manager.pk]), {
            "new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD,
        })
        self.assertRedirects(response, reverse("accounts:user_list"))
        manager.refresh_from_db()
        self.assertTrue(manager.check_password(NEW_PASSWORD))

    def test_manager_cannot_manage_users(self):
        manager = make_user("ravi", self.ganesh, User.Role.MANAGER)
        manager.assigned_outlets.add(self.highway)
        self.client.logout()
        self.client.login(username="ravi", password=TEST_PASSWORD)
        self.assertEqual(self.client.get(reverse("accounts:user_list")).status_code, 403)
        self.assertEqual(self.client.get(reverse("accounts:user_password", args=[self.dealer.pk])).status_code, 403)
