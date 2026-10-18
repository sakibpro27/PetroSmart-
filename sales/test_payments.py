"""The cash / UPI / card / credit breakdown entered on the Daily Sales sheet."""

from decimal import Decimal as D

from django.urls import reverse

from finance.models import CreditCustomer, CreditSale, PaymentMethod, ShiftCollection
from finance.services import collection_figures

from .models import DailySalesSheet
from .tests import TODAY, SalesTestCase


class PaymentBreakdownTests(SalesTestCase):
    def setUp(self):
        super().setUp()
        self.customer = CreditCustomer.objects.create(business=self.business, name="Patil Transport",
                                                      opening_balance_date=TODAY)
        self.sheet = self.start()
        self.client.force_login(self.manager)
        self.page = self.client.get(reverse("sales:sheet_edit", args=[self.sheet.pk]))
        self.collection = ShiftCollection.objects.get(outlet=self.outlet, business_date=TODAY, shift=self.morning)

    def post(self, amounts, credit=None, action="save"):
        """amounts: {method name: amount}; credit: list of (customer, amount)."""
        lines = list(self.sheet.lines.select_related("nozzle").order_by("product__category", "nozzle__code"))
        data = {"lines-TOTAL_FORMS": len(lines), "lines-INITIAL_FORMS": len(lines), "lines-MIN_NUM_FORMS": 0,
                "lines-MAX_NUM_FORMS": 1000, "sheet-notes": "", "action": action}
        readings = {"N1": ("480", "2"), "N2": ("1100", "0")}  # value: 18 L × ₹100 + 100 L × ₹90 = ₹10,800
        for i, line in enumerate(lines):
            closing, testing = readings[line.nozzle.code]
            data.update({f"lines-{i}-id": line.pk, f"lines-{i}-closing_reading": closing,
                         f"lines-{i}-testing_litres": testing, f"lines-{i}-notes": ""})
        methods = list(self.collection.lines.select_related("method").order_by("method__sort_order"))
        data.update({"methods-TOTAL_FORMS": len(methods), "methods-INITIAL_FORMS": len(methods),
                     "methods-MIN_NUM_FORMS": 0, "methods-MAX_NUM_FORMS": 1000})
        for i, line in enumerate(methods):
            data.update({f"methods-{i}-id": line.pk, f"methods-{i}-amount": amounts.get(line.method.name, "0"),
                         f"methods-{i}-reference": ""})
        credit = credit or []
        data.update({"credit-TOTAL_FORMS": max(len(credit), 1), "credit-INITIAL_FORMS": 0,
                     "credit-MIN_NUM_FORMS": 0, "credit-MAX_NUM_FORMS": 1000})
        for i, (customer, amount) in enumerate(credit):
            data.update({f"credit-{i}-customer": customer.pk, f"credit-{i}-amount": amount,
                         f"credit-{i}-vehicle_number": "MH12AB1234", f"credit-{i}-slip_number": ""})
        return self.client.post(reverse("sales:sheet_edit", args=[self.sheet.pk]), data)

    def test_entry_page_shows_payment_fields(self):
        self.assertContains(self.page, "How the money was received")
        self.assertContains(self.page, "Cash counted")
        self.assertContains(self.page, "UPI")

    def test_cash_expected_after_upi_card_and_credit(self):
        self.post({"UPI": "3000", "Card": "1500", "Cash": "5100"}, credit=[(self.customer, "1200")])
        figures = collection_figures(self.collection)
        self.assertEqual(figures["sales_value"], D("10800.00"))
        self.assertEqual(figures["non_cash"], D("4500"))
        self.assertEqual(figures["credit"], D("1200"))
        self.assertEqual(figures["expected_cash"], D("5100.00"))  # 10,800 − 4,500 − 1,200
        self.assertEqual(figures["difference"], D("0.00"))
        self.assertEqual(self.customer.balance(), D("1200"))

    def test_cash_shortage_is_shown_not_hidden(self):
        self.post({"UPI": "3000", "Card": "1500", "Cash": "5000"}, credit=[(self.customer, "1200")])
        self.assertEqual(collection_figures(self.collection)["difference"], D("-100.00"))
        page = self.client.get(self.sheet.get_absolute_url())
        self.assertContains(page, "Short")

    def test_submit_with_payments_and_dealer_sees_breakdown(self):
        response = self.post({"UPI": "3000", "Card": "1500", "Cash": "5100"}, credit=[(self.customer, "1200")],
                             action="submit")
        self.assertRedirects(response, self.sheet.get_absolute_url())
        self.sheet.refresh_from_db()
        self.assertEqual(self.sheet.status, DailySalesSheet.Status.SUBMITTED)
        self.client.force_login(self.dealer)
        page = self.client.get(self.sheet.get_absolute_url())
        self.assertContains(page, "Cash expected")
        self.assertContains(page, "Patil Transport")
        self.assertEqual(page.context["payment_figures"]["expected_cash"], D("5100.00"))

    def test_same_record_as_collections_screen(self):
        self.post({"UPI": "3000"})
        self.assertEqual(ShiftCollection.objects.count(), 1)
        self.assertEqual(self.collection.lines.get(method__name="UPI").amount, D("3000"))

    def test_invalid_payment_saves_nothing(self):
        response = self.post({"UPI": "-5"})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self.line(self.sheet, "N1").closing_reading)  # readings not saved either
        self.assertFalse(CreditSale.objects.exists())

    def test_verified_collection_is_shown_locked(self):
        self.post({"UPI": "3000"})
        self.collection.status = ShiftCollection.Status.VERIFIED
        self.collection.save()
        page = self.client.get(reverse("sales:sheet_edit", args=[self.sheet.pk]))
        self.assertNotContains(page, 'name="methods-TOTAL_FORMS"')
        self.assertContains(page, "Verified")
