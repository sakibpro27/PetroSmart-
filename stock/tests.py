from datetime import timedelta
from decimal import Decimal as D

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import SimpleTestCase
from django.urls import reverse

from accounts.models import User
from sales import services as sales_services
from sales.tests import TODAY, SalesTestCase
from station.models import FuelProduct, Nozzle, Tank
from tenants.test_utils import make_business, make_outlet, make_user

from . import services
from .calculations import reconcile
from .models import StockLine, StockSheet, TankReceipt

YESTERDAY = TODAY - timedelta(days=1)


class ReconcileFormulaTests(SimpleTestCase):
    def test_testing_litres_are_not_subtracted_twice(self):
        # Opening 1000 L, nothing received, nozzle delivered 20 L of which 2 L was testing.
        figures = reconcile(D("1000"), D("0"), D("20"), measured_closing=D("980"))
        self.assertEqual(figures.calculated_closing, D("980"))  # not 978 or 982
        self.assertEqual(figures.variation, D("0"))

    def test_receipts_add_and_variation_sign(self):
        figures = reconcile(D("5000"), D("12000"), D("850.50"), measured_closing=D("16140.00"))
        self.assertEqual(figures.calculated_closing, D("16149.50"))
        self.assertEqual(figures.variation, D("-9.50"))

    def test_no_dip_yet_means_no_variation(self):
        self.assertIsNone(reconcile(D("1"), D("0"), D("0")).variation)


class StockTestCase(SalesTestCase):
    """SalesTestCase outlet plus two tanks: N1 (MS) draws from T1, N2 (HSD) from T2."""

    def setUp(self):
        super().setUp()
        self.t1 = Tank.objects.create(business=self.business, outlet=self.outlet, product=self.ms, code="T1",
                                      capacity_litres=D("20000"), starting_stock=D("1000"))
        self.t2 = Tank.objects.create(business=self.business, outlet=self.outlet, product=self.hsd, code="T2",
                                      capacity_litres=D("20000"), starting_stock=D("5000"))
        Nozzle.objects.filter(pk=self.n1.pk).update(tank=self.t1)
        Nozzle.objects.filter(pk=self.n2.pk).update(tank=self.t2)
        self.n1.refresh_from_db()
        self.n2.refresh_from_db()

    def receive(self, tank, litres, day=TODAY):
        return TankReceipt.objects.create(business=self.business, outlet=self.outlet, tank=tank, received_on=day,
                                          litres=D(litres), entered_by=self.manager)

    def save_stock(self, measured, day=TODAY, notes=None, sheet=None, user=None):
        """measured: {tank: litres}"""
        notes = notes or {}
        entries = {tank.pk: (D(value), notes.get(tank, "")) for tank, value in measured.items()}
        return services.save_stock_sheet(user=user or self.manager, outlet=self.outlet, business_date=day,
                                         entries=entries, sheet=sheet)

    def stock_line(self, sheet, tank):
        return StockLine.objects.get(sheet=sheet, tank=tank)


class StockSheetTests(StockTestCase):
    def test_master_prompt_example_stock_uses_total_delivery(self):
        # N1: 460 -> 480 with 2 L testing. T1 must go down by 20 L, not 18 L.
        self.card()
        rows = {row["tank"]: row for row in services.tank_rows(self.outlet, TODAY)}
        self.assertEqual((rows[self.t1]["total_delivery"], rows[self.t1]["testing_litres"]), (D("20"), D("2")))
        self.assertEqual(rows[self.t1]["calculated"], D("980"))
        sheet = self.save_stock({self.t1: "980", self.t2: "4900"})
        self.assertEqual(self.stock_line(sheet, self.t1).variation, D("0"))

    def test_receipts_and_all_cards_included(self):
        self.card()  # T1 20 L, T2 100 L
        self.card(self.evening, readings={"N1": ("500", "0"), "N2": ("1150", "1")})  # T1 20 L, T2 50 L
        self.receive(self.t2, "4000")
        rows = {row["tank"]: row for row in services.tank_rows(self.outlet, TODAY)}
        self.assertEqual((rows[self.t2]["fuel_received"], rows[self.t2]["total_delivery"]), (D("4000"), D("150")))
        self.assertEqual(rows[self.t2]["calculated"], D("8850"))
        self.assertEqual(rows[self.t1]["total_delivery"], D("40"))

    def test_saved_in_one_step_without_approval(self):
        sheet = self.save_stock({self.t1: "1000", self.t2: "5000"})
        self.assertFalse(hasattr(sheet, "status"))
        self.assertEqual(sheet.lines.count(), 2)

    def test_opening_is_previous_measured_closing(self):
        self.save_stock({self.t1: "995", self.t2: "5000"}, day=YESTERDAY)
        rows = {row["tank"]: row for row in services.tank_rows(self.outlet, TODAY)}
        self.assertEqual(rows[self.t1]["opening"], D("995"))

    def test_large_variation_needs_a_note(self):
        self.card()
        with self.assertRaisesMessage(ValidationError, "Explain it here"):
            self.save_stock({self.t1: "940", self.t2: "4900"})  # T1 calculated 980: -40 beyond 25
        sheet = self.save_stock({self.t1: "940", self.t2: "4900"}, notes={self.t1: "Dip re-checked"})
        self.assertTrue(self.stock_line(sheet, self.t1).is_flagged)

    def test_every_tank_needed_and_capacity_respected(self):
        with self.assertRaisesMessage(ValidationError, "do not match"):
            self.save_stock({self.t1: "1000"})
        with self.assertRaisesMessage(ValidationError, "tank capacity"):
            self.save_stock({self.t1: "25000", self.t2: "5000"}, notes={self.t1: "x"})

    def test_unlinked_nozzle_blocks_saving(self):
        Nozzle.objects.filter(pk=self.n2.pk).update(tank=None)
        self.card()
        with self.assertRaisesMessage(ValidationError, "not linked to a tank"):
            self.save_stock({self.t1: "980", self.t2: "5000"})

    def test_tank_recorded_on_card_is_used_after_relinking(self):
        self.card()
        spare = Tank.objects.create(business=self.business, outlet=self.outlet, product=self.ms, code="T3",
                                    capacity_litres=D("10000"), starting_stock=D("0"))
        Nozzle.objects.filter(pk=self.n1.pk).update(tank=spare)
        rows = {row["tank"]: row for row in services.tank_rows(self.outlet, TODAY)}
        self.assertEqual(rows[self.t1]["total_delivery"], D("20"))
        self.assertEqual(rows[spare]["total_delivery"], D("0"))

    def test_order_and_future_rules(self):
        self.save_stock({self.t1: "1000", self.t2: "5000"})
        with self.assertRaisesMessage(ValidationError, "date order"):
            self.save_stock({self.t1: "1000", self.t2: "5000"}, day=YESTERDAY)
        with self.assertRaisesMessage(ValidationError, "future date"):
            self.save_stock({self.t1: "1000", self.t2: "5000"}, day=TODAY + timedelta(days=1))

    def test_only_latest_sheet_can_change(self):
        first = self.save_stock({self.t1: "1000", self.t2: "5000"}, day=YESTERDAY)
        latest = self.save_stock({self.t1: "1000", self.t2: "5000"})
        self.assertFalse(services.can_change(first, self.manager))
        with self.assertRaisesMessage(ValidationError, "cannot be changed"):
            self.save_stock({self.t1: "999", self.t2: "5000"}, sheet=first)
        with self.assertRaisesMessage(ValidationError, "Only the latest"):
            services.delete_stock_sheet(first, user=self.manager)
        edited = self.save_stock({self.t1: "999", self.t2: "5000"}, sheet=latest, notes={self.t1: ""})
        self.assertEqual(self.stock_line(edited, self.t1).measured_closing, D("999"))
        services.delete_stock_sheet(latest, user=self.manager)
        self.assertEqual(StockSheet.objects.count(), 1)


class LockingTests(StockTestCase):
    def test_receipts_locked_after_stock_saved(self):
        receipt = self.receive(self.t1, "100")
        self.save_stock({self.t1: "1100", self.t2: "5000"})
        with self.assertRaisesMessage(ValidationError, "locked"):
            services.delete_receipt(receipt, user=self.manager)

    def test_cards_locked_after_stock_saved(self):
        card = self.card()
        self.save_stock({self.t1: "980", self.t2: "4900"})
        with self.assertRaisesMessage(ValidationError, "already saved"):
            self.card(self.evening, readings={"N1": ("500", "0"), "N2": ("1150", "0")})
        self.assertFalse(sales_services.can_change(card, self.manager))

    def test_correction_moving_litres_between_cards_keeps_stock_valid(self):
        morning = self.card()
        self.card(self.evening, readings={"N1": ("500", "0"), "N2": ("1150", "0")})
        stock = self.save_stock({self.t1: "960", self.t2: "4850"})
        n1 = self.line(morning, "N1")
        sales_services.correct_card(morning, user=self.manager, reason="closing misread",
                                    changes=[(n1, D("485"), n1.testing_litres, n1.price_per_litre)])
        # Morning +5 L and evening -5 L: the day's total delivery is unchanged.
        self.assertEqual(services.stale_tanks(stock), [])

    def test_correction_changing_the_days_total_is_flagged_stale(self):
        self.card()
        evening = self.card(self.evening, readings={"N1": ("500", "0"), "N2": ("1150", "0")})
        stock = self.save_stock({self.t1: "960", self.t2: "4850"})
        n1 = self.line(evening, "N1")
        sales_services.correct_card(evening, user=self.manager, reason="closing misread",
                                    changes=[(n1, D("505"), n1.testing_litres, n1.price_per_litre)])
        self.assertEqual(services.stale_tanks(stock), ["T1"])
        self.assertEqual(self.stock_line(stock, self.t1).total_delivery, D("40"))  # as saved


class TankRuleTests(StockTestCase):
    def test_nozzle_cannot_use_tank_of_other_product(self):
        self.n1.tank = self.t2
        with self.assertRaisesMessage(ValidationError, "different product"):
            self.n1.full_clean()

    def test_tank_with_active_nozzles_cannot_be_deactivated(self):
        self.t1.is_active = False
        with self.assertRaisesMessage(ValidationError, "Active nozzles"):
            self.t1.full_clean()

    def test_starting_stock_within_capacity(self):
        tank = Tank(business=self.business, outlet=self.outlet, product=self.ms, code="T9",
                    capacity_litres=D("100"), starting_stock=D("101"))
        with self.assertRaisesMessage(ValidationError, "capacity"):
            tank.full_clean()

    def test_mixed_volume_basis_is_refused(self):
        receipt = self.receive(self.t1, "100")
        TankReceipt.objects.filter(pk=receipt.pk).update(volume_basis="STANDARD_15C")
        with self.assertRaisesMessage(ValidationError, "cannot be mixed"):
            services.movements(self.t1, TODAY)


class StockViewTests(StockTestCase):
    def setUp(self):
        super().setUp()
        self.other = make_business("Om Sai Petroleum")
        self.other_dealer = make_user("omsai.dealer", self.other, User.Role.DEALER)

    def test_full_flow_through_screens(self):
        self.card()
        self.client.force_login(self.manager)
        self.client.post(reverse("stock:receipt_create"), {
            "tank": self.t2.pk, "received_on": TODAY, "litres": "4000", "reference": "INV-1001", "notes": "",
        })
        page = self.client.get(reverse("stock:sheet_create"), {"outlet": self.outlet.pk, "business_date": TODAY})
        self.assertEqual(len(page.context["rows"]), 2)
        data = {"outlet": self.outlet.pk, "business_date": TODAY, "notes": "",
                "tanks-TOTAL_FORMS": 2, "tanks-INITIAL_FORMS": 2, "tanks-MIN_NUM_FORMS": 0, "tanks-MAX_NUM_FORMS": 1000}
        for i, (tank, measured) in enumerate(((self.t1, "980"), (self.t2, "8900"))):
            data.update({f"tanks-{i}-tank_id": tank.pk, f"tanks-{i}-measured_closing": measured, f"tanks-{i}-notes": ""})
        response = self.client.post(reverse("stock:sheet_create"), data)
        sheet = StockSheet.objects.get()
        self.assertRedirects(response, sheet.get_absolute_url())
        t2 = self.stock_line(sheet, self.t2)
        self.assertEqual((t2.fuel_received, t2.calculated_closing, t2.variation), (D("4000"), D("8900"), D("0")))
        self.assertContains(self.client.get(sheet.get_absolute_url()), "Edit")

    def test_other_tenant_and_unassigned_manager_get_404(self):
        sheet = self.save_stock({self.t1: "1000", self.t2: "5000"})
        receipt = self.receive(self.t1, "10", day=YESTERDAY)
        self.client.force_login(self.other_dealer)
        for url in (reverse("stock:sheet_detail", args=[sheet.pk]), reverse("stock:sheet_edit", args=[sheet.pk]),
                    reverse("stock:receipt_edit", args=[receipt.pk])):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(reverse("stock:receipt_delete", args=[receipt.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("stock:sheet_delete", args=[sheet.pk])).status_code, 404)
        page = self.client.get(reverse("stock:sheet_create"), {"outlet": self.outlet.pk, "business_date": TODAY})
        self.assertEqual(page.context["rows"], [])

    def test_receipt_form_offers_only_own_tanks(self):
        other_outlet = make_outlet(self.other, "OSP-01")
        foreign = Tank.objects.create(business=self.other, outlet=other_outlet,
                                      product=FuelProduct.objects.get(business=self.other, code="MS"),
                                      code="T1", capacity_litres=D("100"), starting_stock=D("0"))
        self.client.force_login(self.manager)
        response = self.client.post(reverse("stock:receipt_create"), {
            "tank": foreign.pk, "received_on": TODAY, "litres": "10", "reference": "", "notes": "",
        })
        self.assertIn("tank", response.context["form"].errors)
        self.assertFalse(TankReceipt.objects.exists())

    def test_manager_outside_outlet_cannot_save(self):
        other_outlet = make_outlet(self.business, "SGF-02")
        with self.assertRaises(PermissionDenied):
            services.save_stock_sheet(user=self.manager, outlet=other_outlet, business_date=TODAY, entries={})
