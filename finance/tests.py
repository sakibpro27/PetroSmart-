from datetime import timedelta
from decimal import Decimal as D

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import SimpleTestCase
from django.urls import reverse

from accounts.models import User
from audit.models import AuditLog
from sales import services as services_sales
from sales.forms import CreditRowForm
from sales.tests import TODAY, SalesTestCase
from tenants.test_utils import make_business, make_outlet, make_user

from . import services
from .models import (
    CreditAdjustment, CreditBill, CreditCustomer, CreditSale, CustomerPayment, Expense, ExpenseCategory, PaymentMethod,
)
from .words import rupees_in_words


class FinanceTestCase(SalesTestCase):
    def setUp(self):
        super().setUp()
        self.cash = PaymentMethod.objects.get(business=self.business, name="Cash")
        self.customer = CreditCustomer.objects.create(business=self.business, name="Patil Transport",
                                                      opening_balance=D("5000"), opening_balance_date=TODAY - timedelta(days=10),
                                                      credit_limit=D("8000"))
        self.electricity = ExpenseCategory.objects.get(business=self.business, name="Electricity")


class DefaultsTests(FinanceTestCase):
    def test_new_business_gets_methods_and_categories(self):
        names = set(PaymentMethod.objects.for_business(self.business).values_list("name", flat=True))
        self.assertEqual(names, {"Cash", "UPI", "Card", "Bank transfer"})
        self.assertTrue(ExpenseCategory.objects.for_business(self.business).filter(name="Electricity").exists())


class CreditLedgerTests(FinanceTestCase):
    def test_balance_and_running_ledger(self):
        sheet = self.card(credits=[self.slip(self.customer, "2500")])
        CustomerPayment.objects.create(business=self.business, customer=self.customer, outlet=self.outlet,
                                       received_on=TODAY, amount=D("3000"), method=self.cash, entered_by=self.manager)
        CreditAdjustment.objects.create(business=self.business, customer=self.customer, adjusted_on=TODAY,
                                        amount=D("-100"), reason="Discount agreed", entered_by=self.dealer)
        self.assertEqual(self.customer.balance(), D("4400"))  # 5000 + 2500 - 3000 - 100
        rows = services.ledger(self.customer)
        self.assertEqual([row["kind"] for row in rows], ["Opening balance", "Credit sale", "Payment received", "Adjustment"])
        self.assertEqual([row["balance"] for row in rows], [D("5000"), D("7500"), D("4500"), D("4400")])
        self.assertEqual(rows[1]["link"], sheet.get_absolute_url())

    def test_only_dealer_deletes_office_payments(self):
        payment = CustomerPayment.objects.create(business=self.business, customer=self.customer, outlet=self.outlet,
                                                 received_on=TODAY, amount=D("100"), method=self.cash, entered_by=self.manager)
        with self.assertRaises(PermissionDenied):
            services.delete_payment(payment, user=self.manager)
        services.delete_payment(payment, user=self.dealer)
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.DELETE, changes__amount="100.00").exists())

    def test_receipt_taken_on_card_is_changed_on_the_card(self):
        self.card(receipts=[(self.customer, D("500"), "")])
        payment = CustomerPayment.objects.get()
        with self.assertRaisesMessage(ValidationError, "shift card"):
            services.delete_payment(payment, user=self.dealer)

    def test_zero_adjustment_rejected(self):
        with self.assertRaises(ValidationError):
            CreditAdjustment(business=self.business, customer=self.customer, adjusted_on=TODAY, amount=D("0"),
                             reason="x", entered_by=self.dealer).full_clean()


class SummaryTests(FinanceTestCase):
    def test_operational_summary_from_cards(self):
        self.card(credits=[self.slip(self.customer, "1700")], phone_wallet="3000", bank_card="1000",
                  expenses=[(self.electricity, "Bulb", D("100"))], notes_500=10)
        Expense.objects.create(business=self.business, outlet=self.outlet, expense_date=TODAY,
                               category=self.electricity, description="MSEB bill", amount=D("2400"),
                               method=self.cash, entered_by=self.manager)
        result = services.operational_summary(business=self.business, outlets=[self.outlet], date_from=TODAY, date_to=TODAY)
        self.assertEqual(result["total_fuel"], D("10800.00"))
        self.assertEqual(result["credit"], D("1700"))
        self.assertEqual(result["expected_cash"], D("5000.00"))  # 10,800 - 1,700 - 3,000 - 1,000 - 100
        self.assertEqual(result["cash_collection"], D("5000"))
        self.assertEqual(result["balance"], D("0.00"))
        self.assertEqual(result["expenses"], D("2500"))


class FinanceViewTests(FinanceTestCase):
    def setUp(self):
        super().setUp()
        self.other = make_business("Om Sai Petroleum")
        self.other_dealer = make_user("omsai.dealer", self.other, User.Role.DEALER)

    def test_expense_record_edit_delete(self):
        self.client.force_login(self.manager)
        data = {"outlet": self.outlet.pk, "expense_date": TODAY, "category": self.electricity.pk,
                "description": "MSEB bill", "amount": "2400", "method": self.cash.pk, "paid_to": "MSEDCL",
                "reference": "", "notes": ""}
        self.assertRedirects(self.client.post(reverse("finance:expense_create"), data), reverse("finance:expense_list"))
        expense = Expense.objects.get()
        self.client.post(reverse("finance:expense_edit", args=[expense.pk]), {**data, "amount": "2450"})
        expense.refresh_from_db()
        self.assertEqual(expense.amount, D("2450"))
        self.assertEqual(self.client.get(reverse("finance:expense_list")).context["total"], D("2450"))
        self.client.post(reverse("finance:expense_delete", args=[expense.pk]))
        self.assertFalse(Expense.objects.exists())
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.DELETE, object_type="finance.Expense").exists())

    def test_card_expense_cannot_be_deleted_from_expenses_screen(self):
        self.card(expenses=[(self.electricity, "Bulb", D("100"))])
        expense = Expense.objects.get()
        self.client.force_login(self.manager)
        self.client.post(reverse("finance:expense_delete", args=[expense.pk]))
        self.assertTrue(Expense.objects.exists())

    def test_future_expense_rejected(self):
        self.client.force_login(self.manager)
        response = self.client.post(reverse("finance:expense_create"), {
            "outlet": self.outlet.pk, "expense_date": TODAY + timedelta(days=1), "category": self.electricity.pk,
            "description": "x", "amount": "1", "method": self.cash.pk})
        self.assertContains(response, "future")

    def test_permissions_and_isolation(self):
        self.client.force_login(self.manager)
        for url in (reverse("finance:settings"), reverse("finance:summary"), reverse("finance:customer_create")):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.other_dealer)
        for url in (self.customer.get_absolute_url(), reverse("finance:customer_edit", args=[self.customer.pk])):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)
        self.assertNotContains(self.client.get(reverse("finance:customer_list")), "Patil Transport")

    def test_all_pages_render_for_dealer(self):
        self.card(credits=[self.slip(self.customer, "100")])
        self.client.force_login(self.dealer)
        for name in ("customer_list", "customer_create", "payment_create", "expense_list", "expense_create",
                     "summary", "settings", "method_create", "category_create"):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(f"finance:{name}")).status_code, 200)
        self.assertEqual(self.client.get(self.customer.get_absolute_url()).status_code, 200)


# --- Credit slips and bills ---------------------------------------------------------------


class CreditSlipTests(FinanceTestCase):
    def test_slip_numbers_are_automatic_and_run_per_outlet(self):
        sheet = self.card(credits=[self.slip(self.customer, "300"), self.slip(self.customer, "474", "MH12AB1234")])
        self.assertEqual(list(sheet.credit_sales.values_list("slip_no", flat=True)), [1, 2])
        evening = self.card(self.evening, readings={"N1": ("490", "0"), "N2": ("1150", "0")},
                            credits=[self.slip(self.customer, "100")])
        self.assertEqual(evening.credit_sales.get().slip_no, 3)
        # Another outlet starts its own series.
        other = CreditSale(business=self.business, outlet=make_outlet(self.business, "SGF-02"), sheet=sheet,
                           customer=self.customer, amount=D("1"), slip_no=1)
        other.save()  # no clash with slip 1 at SGF-01

    def test_litres_worked_out_from_amount_or_amount_from_litres(self):
        sheet = self.card(credits=[self.slip(self.customer, "300"),  # HSD at ₹90/L
                                   self.slip(self.customer, "", product=self.ms, litres="2.5")])
        by_product = {sale.product.code: sale for sale in sheet.credit_sales.all()}
        self.assertEqual((by_product["HSD"].rate, by_product["HSD"].litres), (D("90.00"), D("3.33")))
        self.assertEqual((by_product["MS"].amount, by_product["MS"].litres), (D("250.00"), D("2.50")))

    def test_editing_a_card_keeps_slip_numbers(self):
        sheet = self.card(credits=[self.slip(self.customer, "300"), self.slip(self.customer, "500")])
        first, second = sheet.credit_sales.order_by("slip_no")
        rows = [{**self.slip(self.customer, "350"), "id": first.pk}, self.slip(self.customer, "50")]  # second removed
        services_sales.save_card(user=self.manager, sheet=sheet, header={}, credits=rows, rows=[
            {"nozzle": line.nozzle, "closing_reading": line.closing_reading, "testing_litres": line.testing_litres}
            for line in sheet.lines.all()])
        slips = {sale.slip_no: sale.amount for sale in sheet.credit_sales.all()}
        self.assertEqual(slips, {1: D("350.00"), 3: D("50.00")})  # slip 2 is never reused

    def test_slip_number_cannot_be_typed(self):
        self.assertTrue(CreditRowForm(business=self.business).fields["slip_no"].disabled)

    def test_slip_on_card_screen(self):
        self.client.force_login(self.manager)
        sheet = self.card(credits=[self.slip(self.customer, "300", "MH12AB1234")])
        page = self.client.get(sheet.get_absolute_url())
        self.assertContains(page, "Not billed")
        self.assertContains(page, "MH12AB1234")


class CreditBillTests(FinanceTestCase):
    """Slips on three days: ₹300.40 and ₹474.00 two days ago, ₹1,000 yesterday, ₹200 today."""

    def setUp(self):
        super().setUp()
        self.d2, self.d1 = TODAY - timedelta(days=2), TODAY - timedelta(days=1)
        self.card(day=self.d2, readings={"N1": ("470", "0"), "N2": ("1010", "0")},
                  credits=[self.slip(self.customer, "300.40", "MH12"), self.slip(self.customer, "474")])
        self.card(day=self.d1, readings={"N1": ("475", "0"), "N2": ("1020", "0")},
                  credits=[self.slip(self.customer, "1000")])
        self.today_card = self.card(credits=[self.slip(self.customer, "200")])

    def bill(self, day=None, user=None):
        return services.create_bill(self.customer, self.outlet, day or self.d1, user=user or self.manager)

    def test_first_bill_covers_unbilled_slips_up_to_the_date(self):
        bill = self.bill()
        self.assertEqual((bill.bill_no, bill.period_from, bill.bill_date), (1, self.d2, self.d1))
        self.assertEqual(list(bill.sales.values_list("slip_no", flat=True)), [1, 2, 3])
        self.assertEqual(bill.slips_total, D("1774.40"))
        self.assertEqual((bill.round_off, bill.amount), (D("-0.40"), D("1774.00")))
        # Opening 5,000 was owed before; net = what is owed on the bill date.
        self.assertEqual((bill.previous_balance, bill.net_amount), (D("5000.00"), D("6774.00")))
        self.assertEqual(self.customer.balance(), D("6974.00"))  # + today's ₹200 slip, round off included

    def test_next_bill_runs_from_the_day_after_the_last_one(self):
        first = self.bill()
        second = self.bill(TODAY)
        self.assertEqual((second.bill_no, second.period_from), (2, TODAY))
        self.assertEqual(list(second.sales.values_list("slip_no", flat=True)), [4])
        self.assertEqual(second.previous_balance, first.net_amount)
        with self.assertRaisesMessage(ValidationError, "no unbilled credit slips"):
            self.bill(TODAY)

    def test_slip_entered_late_for_billed_period_goes_on_next_bill(self):
        first = self.bill()
        # A slip dated yesterday (inside bill 1) that was not on bill 1, e.g. a card from another pump entered late.
        CreditSale.objects.filter(slip_no=4).update(sheet=first.sales.get(slip_no=3).sheet)
        bill = self.bill(TODAY)
        self.assertEqual((bill.period_from, list(bill.sales.values_list("slip_no", flat=True))), (self.d1, [4]))

    def test_bill_date_rules(self):
        self.bill()
        with self.assertRaisesMessage(ValidationError, "cannot be before the previous bill"):
            self.bill(self.d2)
        with self.assertRaisesMessage(ValidationError, "future"):
            self.bill(TODAY + timedelta(days=1))

    def test_billed_slip_is_locked(self):
        self.bill(TODAY)
        sheet = self.today_card  # the latest card, so only the bill stops it being deleted
        with self.assertRaisesMessage(ValidationError, "is on bill 1"):
            services_sales.delete_card(sheet, user=self.manager)
        with self.assertRaisesMessage(ValidationError, "is on bill 1"):
            services_sales.save_credit_slips(sheet, self.outlet, sheet.business_date, [])

    def test_cancel_releases_slips_and_number_is_not_reused(self):
        bill = self.bill()
        with self.assertRaises(PermissionDenied):
            services.cancel_bill(bill, "Wrong date", user=self.manager)
        services.cancel_bill(bill, "Wrong date", user=self.dealer)
        bill.refresh_from_db()
        self.assertTrue(bill.is_cancelled)
        self.assertFalse(CreditSale.objects.filter(bill__isnull=False).exists())
        self.assertEqual(self.customer.balance(), D("6974.40"))  # round off no longer applies
        again = self.bill()
        self.assertEqual(again.bill_no, 2)
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.DELETE, object_type="finance.CreditBill").exists())

    def test_ledger_shows_bill_round_off(self):
        self.bill()
        rows = services.ledger(self.customer)
        bill_row = next(row for row in rows if row["kind"] == "Bill 1")
        self.assertEqual((bill_row["debit"], bill_row["credit"]), (D("0"), D("0.40")))
        self.assertEqual(rows[-1]["balance"], self.customer.balance())

    def test_bill_screens(self):
        self.outlet.gstin, self.outlet.oil_company = "27CHWPS8054F1ZJ", "BPCL"
        self.outlet.bill_terms = "Goods once sold will not be taken back.\nPayment within 15 days."
        self.outlet.save()
        self.client.force_login(self.manager)
        url = reverse("finance:bill_create", args=[self.customer.pk])
        preview = self.client.get(url, {"outlet": self.outlet.pk, "bill_date": self.d1.isoformat()})
        self.assertEqual(len(preview.context["preview"]["slips"]), 3)
        response = self.client.post(url, {"outlet": self.outlet.pk, "bill_date": self.d1.isoformat()})
        bill = CreditBill.objects.get()
        self.assertRedirects(response, bill.get_absolute_url())
        page = self.client.get(bill.get_absolute_url())
        for text in ("AUTHORISED DEALER OF BHARAT PETROLEUM CORPORATION LTD.", "27CHWPS8054F1ZJ", "INVOICE",
                     "PATIL TRANSPORT", "DIESEL", "One Thousand Seven Hundred Seventy Four Rupees Only",
                     "Payment within 15 days.", "Diesel(", "Net Amount"):
            self.assertContains(page, text)
        self.assertEqual(self.client.get(reverse("finance:bill_list")).context["bills"][0], bill)

    def test_other_tenant_cannot_see_bill(self):
        bill = self.bill()
        intruder = make_user("omsai.dealer", make_business("Om Sai Petroleum"), User.Role.DEALER)
        self.client.force_login(intruder)
        self.assertEqual(self.client.get(bill.get_absolute_url()).status_code, 404)
        self.assertEqual(self.client.post(reverse("finance:bill_cancel", args=[bill.pk]), {"reason": "x"}).status_code, 404)
        self.assertEqual(self.client.get(reverse("finance:bill_create", args=[self.customer.pk])).status_code, 404)


class AmountInWordsTests(SimpleTestCase):
    def test_indian_words(self):
        self.assertEqual(rupees_in_words(D("5574")), "Five Thousand Five Hundred Seventy Four Rupees Only")
        self.assertEqual(rupees_in_words(D("81916")), "Eighty One Thousand Nine Hundred Sixteen Rupees Only")
        self.assertEqual(rupees_in_words(D("1234567.50")),
                         "Twelve Lakh Thirty Four Thousand Five Hundred Sixty Seven Rupees and Fifty Paise Only")
        self.assertEqual(rupees_in_words(D("21000000")), "Two Crore Ten Lakh Rupees Only")
        self.assertEqual(rupees_in_words(D("0")), "Zero Rupees Only")
