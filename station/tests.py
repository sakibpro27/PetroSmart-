from datetime import time, timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from audit.models import AuditLog
from tenants.models import Outlet
from tenants.test_utils import TEST_PASSWORD, make_business, make_outlet, make_user

from .models import Dispenser, FuelPrice, FuelProduct, Nozzle, Shift


def make_dispenser(outlet, code="DU-1"):
    return Dispenser.objects.create(business=outlet.business, outlet=outlet, code=code)


def make_nozzle(dispenser, code="N1", product_code="MS", reading="1000.00"):
    product = FuelProduct.objects.get(business=dispenser.business, code=product_code)
    return Nozzle.objects.create(
        business=dispenser.business, outlet=dispenser.outlet, dispenser=dispenser,
        product=product, code=code, initial_reading=Decimal(reading),
    )


class SetupTestCase(TestCase):
    """Two tenants, each with a dealer; Ganesh also has a manager."""

    def setUp(self):
        self.ganesh = make_business("Shree Ganesh Fuels")
        self.omsai = make_business("Om Sai Petroleum")
        self.ganesh_outlet = make_outlet(self.ganesh, "SGF-01", "Ganesh Highway")
        self.omsai_outlet = make_outlet(self.omsai, "OSP-01", "Om Sai Main Road")
        self.dealer = make_user("ganesh.dealer", self.ganesh, User.Role.DEALER)
        self.manager = make_user("ganesh.manager", self.ganesh, User.Role.MANAGER)
        self.manager.assigned_outlets.add(self.ganesh_outlet)
        make_user("omsai.dealer", self.omsai, User.Role.DEALER)

    def login(self, username="ganesh.dealer"):
        self.client.login(username=username, password=TEST_PASSWORD)


class DefaultProductTests(SetupTestCase):
    def test_new_business_gets_ms_and_hsd(self):
        codes = set(FuelProduct.objects.for_business(self.ganesh).values_list("code", flat=True))
        self.assertEqual(codes, {"MS", "HSD"})

    def test_products_are_separate_per_business(self):
        ganesh_ms = FuelProduct.objects.get(business=self.ganesh, code="MS")
        self.assertNotIn(ganesh_ms, FuelProduct.objects.for_business(self.omsai))


class DealerOnlyAccessTests(SetupTestCase):
    def test_manager_cannot_open_setup_screens(self):
        self.login("ganesh.manager")
        for url in [
            reverse("station:outlet_list"),
            reverse("station:outlet_detail", args=[self.ganesh_outlet.pk]),
            reverse("station:product_list"),
            reverse("station:business"),
            reverse("station:nozzle_create", args=[self.ganesh_outlet.pk]),
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_dealer_can_open_setup_screens(self):
        self.login()
        for url in [
            reverse("station:outlet_list"),
            reverse("station:outlet_detail", args=[self.ganesh_outlet.pk]),
            reverse("station:product_list"),
            reverse("station:business"),
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)


class OutletManagementTests(SetupTestCase):
    def test_dealer_adds_outlet_and_it_is_audited(self):
        self.login()
        response = self.client.post(reverse("station:outlet_create"), {
            "name": "Ganesh City", "code": "SGF-02", "oil_company": "IOCL", "address": "", "is_active": "on",
        })
        outlet = Outlet.objects.get(business=self.ganesh, code="SGF-02")
        self.assertRedirects(response, outlet.get_setup_url())
        log = AuditLog.objects.get(action=AuditLog.Action.CREATE, object_id=str(outlet.pk))
        self.assertEqual(log.business, self.ganesh)
        self.assertEqual(log.user, self.dealer)

    def test_duplicate_code_shows_form_error_not_crash(self):
        self.login()
        response = self.client.post(reverse("station:outlet_create"), {
            "name": "Copy", "code": "SGF-01", "is_active": "on",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already uses this code")

    def test_plan_outlet_limit_is_enforced(self):
        plan = self.ganesh.plan
        plan.max_outlets = 1
        plan.save()
        self.login()
        response = self.client.post(reverse("station:outlet_create"), {
            "name": "Second", "code": "SGF-02", "is_active": "on",
        })
        self.assertContains(response, "allows 1 active outlet")
        self.assertFalse(Outlet.objects.filter(code="SGF-02").exists())

    def test_edit_records_what_changed(self):
        self.login()
        self.client.post(reverse("station:outlet_edit", args=[self.ganesh_outlet.pk]), {
            "name": "Ganesh Highway NH-48", "code": "SGF-01", "is_active": "on",
        })
        log = AuditLog.objects.get(action=AuditLog.Action.UPDATE)
        self.assertEqual(log.changes["name"], {"from": "Ganesh Highway", "to": "Ganesh Highway NH-48"})


class CrossTenantTests(SetupTestCase):
    """A dealer must never reach another dealer's set-up, even by guessing IDs."""

    def setUp(self):
        super().setUp()
        self.omsai_dispenser = make_dispenser(self.omsai_outlet)
        self.omsai_nozzle = make_nozzle(self.omsai_dispenser)
        self.ganesh_dispenser = make_dispenser(self.ganesh_outlet)

    def test_other_tenants_pages_return_404(self):
        self.login()
        for url in [
            reverse("station:outlet_detail", args=[self.omsai_outlet.pk]),
            reverse("station:outlet_edit", args=[self.omsai_outlet.pk]),
            reverse("station:nozzle_edit", args=[self.omsai_nozzle.pk]),
            reverse("station:dispenser_edit", args=[self.omsai_dispenser.pk]),
            reverse("station:nozzle_create", args=[self.omsai_outlet.pk]),
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)

    def test_cannot_edit_other_tenants_nozzle_by_post(self):
        self.login()
        response = self.client.post(reverse("station:nozzle_edit", args=[self.omsai_nozzle.pk]), {
            "code": "HACKED", "dispenser": self.omsai_dispenser.pk,
            "product": self.omsai_nozzle.product.pk, "initial_reading": "0",
        })
        self.assertEqual(response.status_code, 404)
        self.omsai_nozzle.refresh_from_db()
        self.assertEqual(self.omsai_nozzle.code, "N1")

    def test_cannot_attach_nozzle_to_other_tenants_dispenser_or_product(self):
        self.login()
        omsai_hsd = FuelProduct.objects.get(business=self.omsai, code="HSD")
        response = self.client.post(reverse("station:nozzle_create", args=[self.ganesh_outlet.pk]), {
            "code": "N9", "dispenser": self.omsai_dispenser.pk, "product": omsai_hsd.pk,
            "initial_reading": "100", "is_active": "on",
        })
        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertIn("dispenser", form.errors)
        self.assertIn("product", form.errors)
        self.assertFalse(Nozzle.objects.filter(code="N9").exists())

    def test_cannot_attach_nozzle_to_dispenser_at_another_own_outlet(self):
        other_outlet = make_outlet(self.ganesh, "SGF-02")
        other_dispenser = make_dispenser(other_outlet, "DU-9")
        self.login()
        response = self.client.post(reverse("station:nozzle_create", args=[self.ganesh_outlet.pk]), {
            "code": "N9", "dispenser": other_dispenser.pk,
            "product": FuelProduct.objects.get(business=self.ganesh, code="MS").pk,
            "initial_reading": "100", "is_active": "on",
        })
        self.assertIn("dispenser", response.context["form"].errors)

    def test_business_comes_from_login_not_from_form(self):
        self.login()
        self.client.post(reverse("station:shift_create", args=[self.ganesh_outlet.pk]), {
            "name": "Morning", "start_time": "06:00", "end_time": "14:00", "sort_order": 1,
            "is_active": "on", "business": self.omsai.pk,  # tampered extra field is ignored
        })
        shift = Shift.objects.get(name="Morning")
        self.assertEqual(shift.business, self.ganesh)
        self.assertEqual(shift.outlet, self.ganesh_outlet)


class NozzleAndProductRuleTests(SetupTestCase):
    def setUp(self):
        super().setUp()
        self.dispenser = make_dispenser(self.ganesh_outlet)
        self.nozzle = make_nozzle(self.dispenser)

    def test_nozzle_code_unique_within_outlet(self):
        self.login()
        response = self.client.post(reverse("station:nozzle_create", args=[self.ganesh_outlet.pk]), {
            "code": "N1", "dispenser": self.dispenser.pk, "product": self.nozzle.product.pk,
            "initial_reading": "5", "is_active": "on",
        })
        self.assertContains(response, "already exists at this outlet")

    def test_negative_initial_reading_is_rejected(self):
        self.login()
        response = self.client.post(reverse("station:nozzle_create", args=[self.ganesh_outlet.pk]), {
            "code": "N2", "dispenser": self.dispenser.pk, "product": self.nozzle.product.pk,
            "initial_reading": "-1", "is_active": "on",
        })
        self.assertIn("initial_reading", response.context["form"].errors)

    def test_cannot_deactivate_product_used_by_active_nozzle(self):
        self.login()
        product = self.nozzle.product
        response = self.client.post(reverse("station:product_edit", args=[product.pk]), {"name": product.name})
        self.assertContains(response, "Active nozzles still use this product")
        product.refresh_from_db()
        self.assertTrue(product.is_active)

    def test_product_code_cannot_be_changed_after_creation(self):
        self.login()
        product = self.nozzle.product
        self.client.post(reverse("station:product_edit", args=[product.pk]), {
            "category": "HSD", "code": "XX", "name": "Renamed", "is_active": "on",
        })
        product.refresh_from_db()
        self.assertEqual((product.code, product.category, product.name), ("MS", "MS", "Renamed"))

    def test_cannot_deactivate_dispenser_with_active_nozzles(self):
        self.login()
        response = self.client.post(reverse("station:dispenser_edit", args=[self.dispenser.pk]), {"code": "DU-1"})
        self.assertContains(response, "still has active nozzles")


class PriceTests(SetupTestCase):
    def setUp(self):
        super().setUp()
        self.ms = FuelProduct.objects.get(business=self.ganesh, code="MS")
        self.today = timezone.localdate()

    def add_price(self, days_from_today, price):
        return FuelPrice.objects.create(
            business=self.ganesh, outlet=self.ganesh_outlet, product=self.ms,
            effective_from=self.today + timedelta(days=days_from_today), price_per_litre=Decimal(price),
        )

    def test_price_on_uses_latest_price_not_after_date(self):
        self.add_price(-10, "100.00")
        self.add_price(-2, "101.50")
        self.add_price(3, "103.00")
        self.assertEqual(FuelPrice.price_on(self.ganesh_outlet, self.ms, self.today).price_per_litre, Decimal("101.50"))
        self.assertEqual(
            FuelPrice.price_on(self.ganesh_outlet, self.ms, self.today - timedelta(days=5)).price_per_litre,
            Decimal("100.00"),
        )

    def test_no_price_before_first_effective_date(self):
        self.add_price(0, "100.00")
        self.assertIsNone(FuelPrice.price_on(self.ganesh_outlet, self.ms, self.today - timedelta(days=1)))

    def test_prices_are_per_outlet(self):
        self.add_price(0, "100.00")
        other = make_outlet(self.ganesh, "SGF-02")
        self.assertIsNone(FuelPrice.price_on(other, self.ms, self.today))

    def test_zero_price_and_duplicate_date_rejected(self):
        self.add_price(0, "100.00")
        self.login()
        url = reverse("station:price_create", args=[self.ganesh_outlet.pk])
        zero = self.client.post(url, {"product": self.ms.pk, "effective_from": self.today, "price_per_litre": "0"})
        self.assertIn("price_per_litre", zero.context["form"].errors)
        duplicate = self.client.post(url, {"product": self.ms.pk, "effective_from": self.today, "price_per_litre": "99"})
        self.assertContains(duplicate, "already starts on this date")

    def test_outlet_page_shows_missing_price_warning(self):
        self.login()
        response = self.client.get(reverse("station:outlet_detail", args=[self.ganesh_outlet.pk]))
        self.assertContains(response, "Not set")


class ShiftTests(SetupTestCase):
    def test_overnight_shift_is_allowed(self):
        shift = Shift(business=self.ganesh, outlet=self.ganesh_outlet, name="Night",
                      start_time=time(22), end_time=time(6))
        shift.full_clean()
        self.assertTrue(shift.crosses_midnight)

    def test_shift_name_unique_per_outlet(self):
        Shift.objects.create(business=self.ganesh, outlet=self.ganesh_outlet, name="Morning",
                             start_time=time(6), end_time=time(14))
        self.login()
        response = self.client.post(reverse("station:shift_create", args=[self.ganesh_outlet.pk]), {
            "name": "Morning", "start_time": "07:00", "end_time": "15:00", "sort_order": 1, "is_active": "on",
        })
        self.assertContains(response, "already exists at this outlet")


class BusinessProfileTests(SetupTestCase):
    def test_dealer_updates_contact_details_but_not_plan(self):
        plan_before, ends_before = self.ganesh.plan_id, self.ganesh.subscription_ends_on
        self.login()
        response = self.client.post(reverse("station:business_edit"), {
            "name": "Shree Ganesh Fuels", "legal_name": "Shree Ganesh Fuels Pvt Ltd",
            "contact_phone": "9800000000", "contact_email": "owner@example.com", "address": "Pune",
            "subscription_ends_on": "2099-12-31", "status": "ACTIVE",  # tampered extras are ignored
        })
        self.assertRedirects(response, reverse("station:business"))
        self.ganesh.refresh_from_db()
        self.assertEqual(self.ganesh.legal_name, "Shree Ganesh Fuels Pvt Ltd")
        self.assertEqual((self.ganesh.plan_id, self.ganesh.subscription_ends_on), (plan_before, ends_before))
