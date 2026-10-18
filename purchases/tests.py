from decimal import Decimal as D

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from stock import services as stock_services
from stock.models import StockLine, TankReceipt
from stock.tests import StockTestCase
from tenants.test_utils import make_business, make_user

from .models import FuelPurchase, Supplier, round_off_for
from sales.tests import TODAY


class PurchaseTestCase(StockTestCase):
    def setUp(self):
        super().setUp()
        self.supplier = Supplier.objects.create(business=self.business, name="IOCL Terminal")

    def purchase_data(self, **overrides):
        """
        HSD 12 KL at ₹88,123.40/KL = ₹10,57,480.80, + delivery 1,500 + VAT 40,000 + cess 5,000 + TCS 19.20
        = ₹11,04,000.00 into T2, with 11,980 L actually received. The MS row is left empty (not delivered).
        """
        data = {
            "purchase-outlet": self.outlet.pk, "purchase-supplier": self.supplier.pk,
            "purchase-invoice_number": "INV-1001", "purchase-invoice_date": TODAY, "purchase-delivery_date": TODAY,
            "purchase-tanker_number": "MH12AB1234", "purchase-notes": "",
            "lines-TOTAL_FORMS": 2, "lines-INITIAL_FORMS": 0, "lines-MIN_NUM_FORMS": 0, "lines-MAX_NUM_FORMS": 20,
            "lines-0-product": self.ms.pk, "lines-0-tank": self.t1.pk,
            "lines-1-product": self.hsd.pk, "lines-1-tank": self.t2.pk, "lines-1-quantity_kl": "12",
            "lines-1-rate_per_kl": "88123.40", "lines-1-delivery_charges": "1500", "lines-1-vat": "40000",
            "lines-1-cess": "5000", "lines-1-tcs": "19.20", "lines-1-received_litres": "11980",
        }
        data.update(overrides)
        return data

    def post(self, data, url=None):
        return self.client.post(url or reverse("purchases:purchase_create"), data)


class PurchaseFlowTests(PurchaseTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.manager)

    def test_purchase_creates_receipts_that_feed_stock(self):
        response = self.post(self.purchase_data())
        purchase = FuelPurchase.objects.get()
        self.assertRedirects(response, purchase.get_absolute_url())
        receipt = TankReceipt.objects.get()
        self.assertEqual((receipt.tank, receipt.litres, receipt.purchase, receipt.reference), (self.t2, D("11980"), purchase, "INV-1001"))
        sheet = self.save_stock({self.t1: "1000", self.t2: "16980"})
        self.assertEqual(StockLine.objects.get(sheet=sheet, tank=self.t2).fuel_received, D("11980"))

    def test_row_total_and_invoice_amount_are_calculated(self):
        self.post(self.purchase_data())
        purchase = FuelPurchase.objects.get()
        line = purchase.lines.get()
        self.assertEqual((line.invoiced_litres, line.quantity_kl), (D("12000"), D("12.000")))
        self.assertEqual(line.base_amount, D("1057480.80"))  # 12 KL × 88,123.40
        self.assertEqual(line.total, D("1104000.00"))
        self.assertEqual((purchase.round_off, purchase.invoice_amount), (D("0"), D("1104000.00")))

    def test_round_up_to_nearest_rupee(self):
        self.post(self.purchase_data(**{"purchase-round_up": "on", "lines-1-tcs": "19.60"}))
        purchase = FuelPurchase.objects.get()
        self.assertEqual(purchase.lines_total, D("1104000.40"))
        self.assertEqual((purchase.round_off, purchase.invoice_amount), (D("-0.40"), D("1104000.00")))
        purchase.lines.update(tcs=D("19.70"))
        self.assertEqual(round_off_for(purchase.lines_total, True), D("0.50"))  # half rounds up

    def test_received_litres_default_to_invoice_quantity(self):
        self.post(self.purchase_data(**{"lines-1-received_litres": ""}))
        self.assertEqual(TankReceipt.objects.get().litres, D("12000"))

    def test_detail_shows_shortage(self):
        self.post(self.purchase_data())
        page = self.client.get(FuelPurchase.objects.get().get_absolute_url())
        self.assertEqual(page.context["difference"], D("-20"))
        self.assertEqual(page.context["totals"]["vat"], D("40000"))
        self.assertContains(page, "Short")

    def test_ms_and_hsd_on_the_same_invoice(self):
        response = self.post(self.purchase_data(**{
            "lines-0-quantity_kl": "4", "lines-0-rate_per_kl": "94500", "lines-0-received_litres": "3990",
            "lines-1-received_litres": "12000",
        }))
        purchase = FuelPurchase.objects.get()
        self.assertRedirects(response, purchase.get_absolute_url())
        self.assertEqual(purchase.product_codes, "MS, HSD")
        self.assertEqual(purchase.total_invoiced_litres, D("16000"))
        self.assertEqual(purchase.invoice_amount, D("378000.00") + D("1104000.00"))
        lines = {line.product.code: line for line in purchase.lines.all()}
        self.assertEqual((lines["MS"].received, lines["MS"].difference), (D("3990"), D("-10")))
        self.assertEqual(lines["HSD"].difference, D("0"))
        # Both tanks get the fuel straight away.
        self.assertEqual(stock_services.book_stock(self.t1)["stock"], D("4990"))
        self.assertEqual(stock_services.book_stock(self.t2)["stock"], D("17000"))

    def test_incomplete_row_rejected(self):
        response = self.post(self.purchase_data(**{"lines-0-quantity_kl": "4"}))
        self.assertContains(response, "Fill in Rate (₹/KL), or clear the row.")
        response = self.post(self.purchase_data(**{"lines-1-tank": ""}))
        self.assertContains(response, "Fill in Tank, or clear the row.")
        self.assertFalse(FuelPurchase.objects.exists())

    def test_empty_invoice_rejected(self):
        response = self.post(self.purchase_data(**{"lines-TOTAL_FORMS": 1}))  # only the empty MS row
        self.assertContains(response, "Enter at least one item")

    def test_new_invoice_page_offers_ms_and_hsd_rows_with_their_tanks(self):
        page = self.client.get(reverse("purchases:purchase_create"))
        initial = [(form.initial.get("product"), form.initial.get("tank")) for form in page.context["lines"].forms]
        self.assertEqual(initial, [(self.ms, self.t1), (self.hsd, self.t2)])

    def test_split_delivery_across_tanks(self):
        second = self.t2.__class__.objects.create(business=self.business, outlet=self.outlet, product=self.hsd, code="T4",
                                                  capacity_litres=D("10000"), starting_stock=D("0"))
        self.post(self.purchase_data(**{
            "lines-TOTAL_FORMS": 3, "lines-1-quantity_kl": "8", "lines-1-received_litres": "",
            "lines-2-product": self.hsd.pk, "lines-2-tank": second.pk, "lines-2-quantity_kl": "4",
            "lines-2-rate_per_kl": "88123.40"}))
        self.assertEqual(sorted(TankReceipt.objects.values_list("litres", flat=True)), [D("4000"), D("8000")])

    def test_tank_must_hold_the_item(self):
        response = self.post(self.purchase_data(**{"lines-1-tank": self.t1.pk}))  # T1 holds MS
        self.assertContains(response, "holds Petrol (MS), not Diesel (HSD)")
        self.assertFalse(FuelPurchase.objects.exists())

    def test_same_tank_twice_rejected(self):
        response = self.post(self.purchase_data(**{
            "lines-TOTAL_FORMS": 3, "lines-2-product": self.hsd.pk, "lines-2-tank": self.t2.pk,
            "lines-2-quantity_kl": "1", "lines-2-rate_per_kl": "88000"}))
        self.assertContains(response, "Each tank can appear only once")

    def test_duplicate_invoice_for_same_supplier_rejected(self):
        self.post(self.purchase_data())
        response = self.post(self.purchase_data())
        self.assertContains(response, "already recorded")
        self.assertEqual(FuelPurchase.objects.count(), 1)

    def test_delivery_before_invoice_rejected(self):
        from datetime import timedelta
        response = self.post(self.purchase_data(**{"purchase-delivery_date": TODAY - timedelta(days=2),
                                                   "purchase-invoice_date": TODAY - timedelta(days=1)}))
        self.assertIn("delivery_date", response.context["form"].errors)

    def test_edit_replaces_rows_and_receipts_and_is_audited(self):
        self.post(self.purchase_data())
        purchase = FuelPurchase.objects.get()
        data = self.purchase_data(**{"lines-1-received_litres": "12000", "lines-INITIAL_FORMS": 2})
        self.post(data, reverse("purchases:purchase_edit", args=[purchase.pk]))
        self.assertEqual(list(TankReceipt.objects.values_list("litres", flat=True)), [D("12000")])
        from audit.models import AuditLog
        log = AuditLog.objects.filter(action=AuditLog.Action.UPDATE, object_type="purchases.FuelPurchase").get()
        self.assertIn("received 11980.00 L", log.changes["lines"]["from"][0])
        self.assertIn("received 12000.00 L", log.changes["lines"]["to"][0])

    def test_locked_after_stock_saved(self):
        self.post(self.purchase_data())
        purchase = FuelPurchase.objects.get()
        self.save_stock({self.t1: "1000", self.t2: "16980"})
        response = self.client.post(reverse("purchases:purchase_delete", args=[purchase.pk]))
        self.assertRedirects(response, purchase.get_absolute_url())
        self.assertTrue(FuelPurchase.objects.exists())
        response = self.post(self.purchase_data(**{"purchase-invoice_number": "INV-2"}))
        self.assertContains(response, "locked")

    def test_invoice_receipt_cannot_be_changed_from_receipts_screen(self):
        self.post(self.purchase_data())
        receipt = TankReceipt.objects.get()
        with self.assertRaisesMessage(ValidationError, "Change it from the fuel purchase"):
            stock_services.delete_receipt(receipt, user=self.manager)

    def test_delete_removes_receipts_and_is_audited(self):
        self.post(self.purchase_data())
        purchase = FuelPurchase.objects.get()
        self.client.post(reverse("purchases:purchase_delete", args=[purchase.pk]))
        self.assertFalse(FuelPurchase.objects.exists())
        self.assertFalse(TankReceipt.objects.exists())
        from audit.models import AuditLog
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.DELETE, changes__invoice_number="INV-1001").exists())

    def test_purchases_report_rows(self):
        from reports.definitions import purchases_report
        self.post(self.purchase_data(**{"lines-0-quantity_kl": "4", "lines-0-rate_per_kl": "94500"}))
        table = purchases_report(self.manager, self.manager.accessible_outlets(),
                                 {"date_from": TODAY, "date_to": TODAY})
        self.assertEqual([row[4] for row in table.rows], ["MS", "HSD"])
        self.assertEqual(table.rows[0][-1], D("1482000.00"))  # invoice amount shown once
        self.assertEqual(table.rows[1][-1], "")
        self.assertEqual(table.totals[6:9], [D("16000"), D("15980"), D("-20")])

    def test_list_totals(self):
        self.post(self.purchase_data())
        page = self.client.get(reverse("purchases:purchase_list"))
        self.assertEqual(page.context["totals"]["invoiced"], D("12000"))
        self.assertEqual(page.context["totals"]["received"], D("11980"))
        self.assertEqual(page.context["totals"]["difference"], D("-20"))
        self.assertEqual(page.context["totals"]["amount"], D("1104000.00"))


class PurchasePermissionTests(PurchaseTestCase):
    def test_manager_cannot_manage_suppliers(self):
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(reverse("purchases:supplier_list")).status_code, 403)
        self.assertEqual(self.client.get(reverse("purchases:supplier_create")).status_code, 403)

    def test_dealer_adds_supplier(self):
        self.client.force_login(self.dealer)
        self.client.post(reverse("purchases:supplier_create"), {"name": "BPCL Depot", "is_active": "on"})
        self.assertTrue(Supplier.objects.filter(business=self.business, name="BPCL Depot").exists())

    def test_other_tenant_cannot_see_or_use_purchase_data(self):
        self.client.force_login(self.manager)
        self.post(self.purchase_data())
        purchase = FuelPurchase.objects.get()
        other = make_business("Om Sai Petroleum")
        intruder = make_user("omsai.dealer", other, User.Role.DEALER)
        self.client.force_login(intruder)
        for url in (purchase.get_absolute_url(), reverse("purchases:purchase_edit", args=[purchase.pk]),
                    reverse("purchases:supplier_edit", args=[self.supplier.pk])):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(reverse("purchases:purchase_delete", args=[purchase.pk])).status_code, 404)
        # Ganesh's supplier and tank cannot be chosen by Om Sai.
        response = self.post(self.purchase_data(**{"purchase-invoice_number": "X"}))
        form = response.context["form"]
        self.assertIn("supplier", form.errors)
        self.assertIn("outlet", form.errors)
        self.assertIn("tank", response.context["lines"].forms[1].errors)
