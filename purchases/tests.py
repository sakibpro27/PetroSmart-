from decimal import Decimal as D

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from stock import services as stock_services
from stock.models import StockLine, TankReceipt
from stock.tests import StockTestCase
from tenants.test_utils import make_business, make_user

from .models import FuelPurchase, Supplier
from sales.tests import TODAY


class PurchaseTestCase(StockTestCase):
    def setUp(self):
        super().setUp()
        self.supplier = Supplier.objects.create(business=self.business, name="IOCL Terminal")

    def purchase_data(self, **overrides):
        data = {
            "purchase-outlet": self.outlet.pk, "purchase-supplier": self.supplier.pk,
            "purchase-invoice_number": "INV-1001", "purchase-invoice_date": TODAY, "purchase-delivery_date": TODAY,
            "purchase-invoice_amount": "1104000.00", "purchase-tanker_number": "MH12AB1234", "purchase-notes": "",
            # Product rows: MS row left empty (not delivered), HSD 12,000 L.
            "lines-TOTAL_FORMS": 2, "lines-INITIAL_FORMS": 0, "lines-MIN_NUM_FORMS": 2, "lines-MAX_NUM_FORMS": 10,
            "lines-0-product": self.ms.pk, "lines-0-invoiced_litres": "", "lines-0-purchase_rate": "",
            "lines-1-product": self.hsd.pk, "lines-1-invoiced_litres": "12000", "lines-1-purchase_rate": "88.1234",
            "tanks-TOTAL_FORMS": 2, "tanks-INITIAL_FORMS": 0, "tanks-MIN_NUM_FORMS": 0, "tanks-MAX_NUM_FORMS": 10,
            "tanks-0-tank": self.t2.pk, "tanks-0-litres": "11980", "tanks-1-tank": "", "tanks-1-litres": "",
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

    def test_detail_shows_shortage_and_charges(self):
        self.post(self.purchase_data())
        purchase = FuelPurchase.objects.get()
        page = self.client.get(purchase.get_absolute_url())
        self.assertEqual(page.context["difference"], D("-20"))
        self.assertContains(page, "Short")
        # 12000 × 88.1234 = 1,057,480.80, so other charges = 46,519.20
        self.assertEqual(purchase.base_amount, D("1057480.80"))
        self.assertEqual(purchase.other_charges, D("46519.20"))

    def test_ms_and_hsd_on_the_same_invoice(self):
        response = self.post(self.purchase_data(**{
            "lines-0-invoiced_litres": "4000", "lines-0-purchase_rate": "94.5000",
            "tanks-0-tank": self.t1.pk, "tanks-0-litres": "3990", "tanks-1-tank": self.t2.pk, "tanks-1-litres": "12000",
        }))
        purchase = FuelPurchase.objects.get()
        self.assertRedirects(response, purchase.get_absolute_url())
        self.assertEqual(purchase.product_codes, "MS, HSD")
        self.assertEqual(purchase.total_invoiced_litres, D("16000"))
        self.assertEqual(purchase.base_amount, D("378000.00") + D("1057480.80"))  # 4000×94.5 + 12000×88.1234
        page = self.client.get(purchase.get_absolute_url())
        by_code = {row["line"].product.code: row for row in page.context["products"]}
        self.assertEqual((by_code["MS"]["received"], by_code["MS"]["difference"]), (D("3990"), D("-10")))
        self.assertEqual((by_code["HSD"]["received"], by_code["HSD"]["difference"]), (D("12000"), D("0")))
        # Both tanks get the fuel straight away.
        self.assertEqual(stock_services.book_stock(self.t1)["stock"], D("4990"))
        self.assertEqual(stock_services.book_stock(self.t2)["stock"], D("17000"))

    def test_each_invoiced_product_must_reach_a_tank(self):
        response = self.post(self.purchase_data(**{"lines-0-invoiced_litres": "4000", "lines-0-purchase_rate": "94.5"}))
        self.assertContains(response, "Allocate the received litres of Petrol (MS)")
        self.assertFalse(FuelPurchase.objects.exists())

    def test_incomplete_product_row_rejected(self):
        response = self.post(self.purchase_data(**{"lines-0-invoiced_litres": "4000"}))
        self.assertContains(response, "Fill in the product, quantity and rate")

    def test_new_invoice_page_offers_ms_and_hsd_rows(self):
        page = self.client.get(reverse("purchases:purchase_create"))
        products = [form.initial.get("product") for form in page.context["lines"].forms]
        self.assertEqual(products, [self.ms, self.hsd])

    def test_split_delivery_across_tanks(self):
        second = self.t2.__class__.objects.create(business=self.business, outlet=self.outlet, product=self.hsd, code="T4",
                                                  capacity_litres=D("10000"), starting_stock=D("0"))
        self.post(self.purchase_data(**{"tanks-0-litres": "8000", "tanks-1-tank": second.pk, "tanks-1-litres": "4000"}))
        self.assertEqual(sorted(TankReceipt.objects.values_list("litres", flat=True)), [D("4000"), D("8000")])

    def test_tank_must_hold_the_invoiced_product(self):
        response = self.post(self.purchase_data(**{"tanks-0-tank": self.t1.pk}))  # T1 holds MS
        self.assertContains(response, "holds Petrol (MS), which is not on this invoice")
        self.assertFalse(FuelPurchase.objects.exists())

    def test_at_least_one_tank_and_complete_rows(self):
        response = self.post(self.purchase_data(**{"tanks-0-tank": "", "tanks-0-litres": ""}))
        self.assertContains(response, "at least one tank")
        response = self.post(self.purchase_data(**{"tanks-0-litres": ""}))
        self.assertContains(response, "or leave both empty")

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

    def test_edit_replaces_receipts_and_is_audited(self):
        self.post(self.purchase_data())
        purchase = FuelPurchase.objects.get()
        data = self.purchase_data(**{"tanks-0-litres": "12000", "tanks-INITIAL_FORMS": 1})
        self.post(data, reverse("purchases:purchase_edit", args=[purchase.pk]))
        self.assertEqual(list(TankReceipt.objects.values_list("litres", flat=True)), [D("12000")])
        from audit.models import AuditLog
        log = AuditLog.objects.filter(action=AuditLog.Action.UPDATE, object_type="purchases.FuelPurchase").get()
        self.assertEqual(log.changes["tank_allocation"], {"from": {"T2": "11980.00"}, "to": {"T2": "12000.00"}})

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

    def test_list_totals(self):
        self.post(self.purchase_data())
        page = self.client.get(reverse("purchases:purchase_list"))
        self.assertEqual(page.context["totals"]["invoiced"], D("12000"))
        self.assertEqual(page.context["totals"]["received"], D("11980"))
        self.assertEqual(page.context["totals"]["difference"], D("-20"))


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
        self.assertIn("tank", response.context["formset"].forms[0].errors)
