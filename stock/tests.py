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

Status = StockSheet.Status
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
        self.assertEqual(figures.variation, D("-9.50"))  # less in the tank than the records explain

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

    def receive(self, tank, litres, day=TODAY):
        return TankReceipt.objects.create(business=self.business, outlet=self.outlet, tank=tank, received_on=day,
                                          litres=D(litres), entered_by=self.manager)

    def stock_sheet(self, day=TODAY, user=None):
        return services.create_stock_sheet(user=user or self.manager, outlet=self.outlet, business_date=day)

    def stock_line(self, sheet, tank):
        return StockLine.objects.get(sheet=sheet, tank=tank)

    def dip(self, sheet, values, notes=""):
        for tank, measured in values.items():
            line = self.stock_line(sheet, tank)
            line.measured_closing, line.notes = D(measured), notes
            line.save()


class StockSheetTests(StockTestCase):
    def test_master_prompt_example_stock_uses_total_delivery(self):
        # N1: 460 -> 480 with 2 L testing. T1 must go down by 20 L, not 18 L.
        self.approved_sheet()
        sheet = self.stock_sheet()
        t1 = self.stock_line(sheet, self.t1)
        self.assertEqual((t1.opening_stock, t1.total_delivery, t1.testing_litres), (D("1000"), D("20"), D("2")))
        self.assertEqual(t1.calculated_closing, D("980"))

    def test_receipts_and_all_shifts_are_included(self):
        self.approved_sheet()  # morning: T1 20 L, T2 100 L
        evening = self.start(self.evening)
        self.fill(evening, {"N1": ("500", "0"), "N2": ("1150", "1")})
        sales_services.submit_sheet(evening, user=self.manager)  # submitted counts too
        self.receive(self.t2, "4000")
        sheet = self.stock_sheet()
        t2 = self.stock_line(sheet, self.t2)
        self.assertEqual((t2.fuel_received, t2.total_delivery, t2.testing_litres), (D("4000"), D("150"), D("1")))
        self.assertEqual(t2.calculated_closing, D("8850"))  # 5000 + 4000 - 150
        self.assertEqual(self.stock_line(sheet, self.t1).total_delivery, D("40"))

    def test_opening_is_previous_measured_closing(self):
        first = self.stock_sheet(YESTERDAY)
        self.dip(first, {self.t1: "995", self.t2: "5000"})
        services.submit_stock_sheet(first, user=self.manager)
        today = self.stock_sheet()
        self.assertEqual(self.stock_line(today, self.t1).opening_stock, D("995"))

    def test_variation_and_alert_need_a_note(self):
        self.approved_sheet()
        sheet = self.stock_sheet()
        self.dip(sheet, {self.t1: "940", self.t2: "4900"})  # T1 calculated 980 -> variation -40, beyond 25
        line = self.stock_line(sheet, self.t1)
        self.assertEqual(line.variation, D("-40"))
        self.assertTrue(line.is_flagged)
        with self.assertRaisesMessage(ValidationError, "Explain it here"):
            services.submit_stock_sheet(sheet, user=self.manager)
        self.dip(sheet, {self.t1: "940", self.t2: "4900"}, notes="Dip re-checked twice")
        services.submit_stock_sheet(sheet, user=self.manager)
        sheet.refresh_from_db()
        self.assertEqual(sheet.status, Status.SUBMITTED)

    def test_measured_cannot_exceed_capacity(self):
        sheet = self.stock_sheet()
        self.dip(sheet, {self.t1: "25000", self.t2: "5000"}, notes="x")
        with self.assertRaisesMessage(ValidationError, "tank capacity"):
            services.submit_stock_sheet(sheet, user=self.manager)

    def test_draft_sales_block_submission(self):
        self.start()  # Daily Sales still in Draft
        sheet = self.stock_sheet()
        self.dip(sheet, {self.t1: "1000", self.t2: "5000"})
        with self.assertRaisesMessage(ValidationError, "still in Draft"):
            services.submit_stock_sheet(sheet, user=self.manager)

    def test_draft_sales_are_not_counted(self):
        sheet = self.start()
        self.fill(sheet, {"N1": ("480", "2"), "N2": ("1100", "0")})
        self.assertEqual(self.stock_line(self.stock_sheet(), self.t1).total_delivery, D("0"))

    def test_unlinked_nozzle_blocks_submission(self):
        Nozzle.objects.filter(pk=self.n2.pk).update(tank=None)
        sheet = self.start()
        self.fill(sheet, {"N1": ("480", "2"), "N2": ("1100", "0")})
        sales_services.submit_sheet(sheet, user=self.manager)
        stock = self.stock_sheet()
        self.dip(stock, {self.t1: "980", self.t2: "5000"})
        with self.assertRaisesMessage(ValidationError, "not linked to a tank"):
            services.submit_stock_sheet(stock, user=self.manager)

    def test_tank_recorded_on_sales_line_is_used_after_relinking(self):
        self.approved_sheet()
        spare = Tank.objects.create(business=self.business, outlet=self.outlet, product=self.ms, code="T3",
                                    capacity_litres=D("10000"), starting_stock=D("0"))
        Nozzle.objects.filter(pk=self.n1.pk).update(tank=spare)
        sheet = self.stock_sheet()
        self.assertEqual(self.stock_line(sheet, self.t1).total_delivery, D("20"))
        self.assertEqual(self.stock_line(sheet, spare).total_delivery, D("0"))

    def test_order_and_future_rules(self):
        first = self.stock_sheet()
        with self.assertRaisesMessage(ValidationError, "date order"):
            self.stock_sheet(YESTERDAY)
        with self.assertRaisesMessage(ValidationError, "future date"):
            self.stock_sheet(TODAY + timedelta(days=1))
        self.assertEqual(first.status, Status.DRAFT)

    def test_dealer_approves_and_manager_cannot(self):
        sheet = self.stock_sheet()
        self.dip(sheet, {self.t1: "1000", self.t2: "5000"})
        services.submit_stock_sheet(sheet, user=self.manager)
        with self.assertRaises(PermissionDenied):
            services.approve_stock_sheet(sheet, user=self.manager)
        services.approve_stock_sheet(sheet, user=self.dealer)
        sheet.refresh_from_db()
        self.assertEqual((sheet.status, sheet.approved_by), (Status.APPROVED, self.dealer))

    def test_return_only_latest(self):
        first = self.stock_sheet(YESTERDAY)
        self.dip(first, {self.t1: "1000", self.t2: "5000"})
        services.submit_stock_sheet(first, user=self.manager)
        self.stock_sheet()
        with self.assertRaisesMessage(ValidationError, "later stock sheet"):
            services.return_stock_sheet(first, user=self.dealer, note="check")


class LockingTests(StockTestCase):
    def submitted_stock(self):
        sheet = self.stock_sheet()
        self.dip(sheet, {self.t1: "1000", self.t2: "5000"})
        return services.submit_stock_sheet(sheet, user=self.manager)

    def test_receipts_locked_after_stock_submitted(self):
        receipt = self.receive(self.t1, "100")
        sheet = self.stock_sheet()
        self.dip(sheet, {self.t1: "1100", self.t2: "5000"})
        services.submit_stock_sheet(sheet, user=self.manager)
        with self.assertRaisesMessage(ValidationError, "locked"):
            services.delete_receipt(receipt, user=self.manager)

    def test_no_new_sales_sheet_after_stock_submitted(self):
        self.submitted_stock()
        with self.assertRaisesMessage(ValidationError, "already submitted"):
            self.start()

    def test_sales_change_after_approval_is_flagged_stale(self):
        sales_sheet = self.approved_sheet()
        stock = self.stock_sheet()
        self.dip(stock, {self.t1: "980", self.t2: "4900"})
        services.submit_stock_sheet(stock, user=self.manager)
        line = self.line(sales_sheet, "N1")
        correction = sales_services.request_correction(
            sales_sheet, user=self.manager, reason="closing misread",
            changes=[(line, D("485"), line.testing_litres, line.price_per_litre)])
        sales_services.approve_correction(correction, user=self.dealer)
        self.assertEqual(services.stale_tanks(stock), ["T1"])
        self.assertEqual(self.stock_line(stock, self.t1).total_delivery, D("20"))  # as submitted


class TankRuleTests(StockTestCase):
    def test_nozzle_cannot_use_tank_of_other_product(self):
        self.n1.refresh_from_db()
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
        self.approved_sheet()
        self.client.force_login(self.manager)
        response = self.client.post(reverse("stock:receipt_create"), {
            "tank": self.t2.pk, "received_on": TODAY, "litres": "4000", "reference": "INV-1001", "notes": "",
        })
        self.assertRedirects(response, reverse("stock:receipt_list"))
        response = self.client.post(reverse("stock:sheet_create"), {"outlet": self.outlet.pk, "business_date": TODAY})
        sheet = StockSheet.objects.get()
        self.assertRedirects(response, reverse("stock:sheet_edit", args=[sheet.pk]))
        lines = list(sheet.lines.order_by("tank__code"))
        data = {"lines-TOTAL_FORMS": 2, "lines-INITIAL_FORMS": 2, "lines-MIN_NUM_FORMS": 0, "lines-MAX_NUM_FORMS": 1000,
                "sheet-notes": "", "action": "submit"}
        for i, (line, measured) in enumerate(zip(lines, ("980", "8900"))):
            data.update({f"lines-{i}-id": line.pk, f"lines-{i}-measured_closing": measured, f"lines-{i}-notes": ""})
        self.assertRedirects(self.client.post(reverse("stock:sheet_edit", args=[sheet.pk]), data), sheet.get_absolute_url())
        t2 = self.stock_line(sheet, self.t2)
        self.assertEqual((t2.fuel_received, t2.calculated_closing, t2.variation), (D("4000"), D("8900"), D("0")))
        self.client.force_login(self.dealer)
        self.client.post(reverse("stock:sheet_approve", args=[sheet.pk]))
        sheet.refresh_from_db()
        self.assertEqual(sheet.status, Status.APPROVED)

    def test_other_tenant_and_unassigned_manager_get_404(self):
        sheet = self.stock_sheet()
        receipt = self.receive(self.t1, "10")
        self.client.force_login(self.other_dealer)
        for url in (reverse("stock:sheet_detail", args=[sheet.pk]), reverse("stock:sheet_edit", args=[sheet.pk]),
                    reverse("stock:receipt_edit", args=[receipt.pk])):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(reverse("stock:receipt_delete", args=[receipt.pk])).status_code, 404)
        self.assertTrue(TankReceipt.objects.filter(pk=receipt.pk).exists())

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

    def test_manager_cannot_approve_stock(self):
        sheet = self.stock_sheet()
        self.dip(sheet, {self.t1: "1000", self.t2: "5000"})
        services.submit_stock_sheet(sheet, user=self.manager)
        self.client.force_login(self.manager)
        self.assertEqual(self.client.post(reverse("stock:sheet_approve", args=[sheet.pk])).status_code, 403)
