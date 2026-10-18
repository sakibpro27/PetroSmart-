from datetime import timedelta
from decimal import Decimal as D

from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

from accounts.models import User
from audit.models import AuditLog
from sales.tests import TODAY, SalesTestCase
from tenants.test_utils import make_business, make_user

from . import services
from .models import CreditAdjustment, CreditCustomer, CustomerPayment, Expense, ExpenseCategory, PaymentMethod


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
        sheet = self.card(credits=[(self.customer, D("2500"), "", "")])
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
        self.card(credits=[(self.customer, D("1700"), "", "")], phone_wallet="3000", bank_card="1000",
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
        self.card(credits=[(self.customer, D("100"), "", "")])
        self.client.force_login(self.dealer)
        for name in ("customer_list", "customer_create", "payment_create", "expense_list", "expense_create",
                     "summary", "settings", "method_create", "category_create"):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(f"finance:{name}")).status_code, 200)
        self.assertEqual(self.client.get(self.customer.get_absolute_url()).status_code, 200)
