from datetime import timedelta
from decimal import Decimal as D

from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

from accounts.models import User
from audit.models import AuditLog
from sales.models import DailySalesSheet
from sales.tests import TODAY, SalesTestCase
from tenants.test_utils import make_business, make_outlet, make_user

from . import services
from .models import (
    CreditAdjustment, CreditCustomer, CreditSale, CustomerPayment, Expense, ExpenseCategory, PaymentMethod,
    ShiftCollection,
)


class FinanceTestCase(SalesTestCase):
    def setUp(self):
        super().setUp()
        self.cash = PaymentMethod.objects.get(business=self.business, name="Cash")
        self.upi = PaymentMethod.objects.get(business=self.business, name="UPI")
        self.customer = CreditCustomer.objects.create(business=self.business, name="Patil Transport",
                                                      opening_balance=D("5000"), opening_balance_date=TODAY - timedelta(days=10),
                                                      credit_limit=D("8000"))

    def collect(self, cash="0", upi="0", credit=None, shift=None):
        collection = services.create_collection(user=self.manager, shift=shift or self.morning, business_date=TODAY)
        collection.lines.filter(method=self.cash).update(amount=D(cash))
        collection.lines.filter(method=self.upi).update(amount=D(upi))
        for customer, amount in credit or []:
            CreditSale.objects.create(business=self.business, collection=collection, customer=customer, amount=D(amount))
        return collection


class DefaultsTests(FinanceTestCase):
    def test_new_business_gets_methods_and_categories(self):
        names = set(PaymentMethod.objects.for_business(self.business).values_list("name", flat=True))
        self.assertEqual(names, {"Cash", "UPI", "Card", "Bank transfer"})
        self.assertTrue(ExpenseCategory.objects.for_business(self.business).filter(name="Electricity").exists())


class CollectionTests(FinanceTestCase):
    def test_lines_created_for_active_methods(self):
        collection = self.collect()
        self.assertEqual(collection.lines.count(), 4)

    def test_compared_with_sales_value_without_assuming_equal(self):
        self.approved_sheet()  # sales value: 18 L × ₹100 + 100 L × ₹90 = ₹10,800
        collection = self.collect(cash="6000", upi="3000", credit=[(self.customer, "1700")])
        figures = services.collection_figures(collection)
        self.assertEqual(figures["sales_value"], D("10800.00"))
        self.assertEqual(figures["payments"], D("9000"))
        self.assertEqual(figures["credit"], D("1700"))
        self.assertEqual(figures["difference"], D("-100.00"))  # ₹100 short, shown, not hidden

    def test_no_sales_sheet_means_no_difference(self):
        figures = services.collection_figures(self.collect(cash="500"))
        self.assertIsNone(figures["sales_value"])
        self.assertIsNone(figures["difference"])

    def test_one_collection_per_outlet_date_shift(self):
        self.collect()
        with self.assertRaisesMessage(ValidationError, "already recorded"):
            self.collect()

    def test_verify_locks_and_reopen_needs_note(self):
        collection = self.collect(cash="100")
        with self.assertRaises(PermissionDenied):
            services.verify_collection(collection, user=self.manager)
        services.verify_collection(collection, user=self.dealer)
        collection.refresh_from_db()
        self.assertFalse(services.can_edit_collection(collection, self.manager))
        with self.assertRaisesMessage(ValidationError, "Write a note"):
            services.reopen_collection(collection, user=self.dealer, note="")
        services.reopen_collection(collection, user=self.dealer, note="UPI report arrived late")
        collection.refresh_from_db()
        self.assertTrue(services.can_edit_collection(collection, self.manager))

    def test_manager_cannot_collect_at_unassigned_outlet(self):
        other = make_outlet(self.business, "SGF-02")
        shift = other.shifts.create(business=self.business, name="Day", start_time="06:00", end_time="06:00", sort_order=1)
        with self.assertRaises(PermissionDenied):
            services.create_collection(user=self.manager, shift=shift, business_date=TODAY)


class CreditLedgerTests(FinanceTestCase):
    def test_balance_and_running_ledger(self):
        self.collect(credit=[(self.customer, "2500")])
        CustomerPayment.objects.create(business=self.business, customer=self.customer, outlet=self.outlet,
                                       received_on=TODAY, amount=D("3000"), method=self.cash, entered_by=self.manager)
        CreditAdjustment.objects.create(business=self.business, customer=self.customer, adjusted_on=TODAY,
                                        amount=D("-100"), reason="Discount agreed", entered_by=self.dealer)
        self.assertEqual(self.customer.balance(), D("4400"))  # 5000 + 2500 - 3000 - 100
        rows = services.ledger(self.customer)
        self.assertEqual([row["kind"] for row in rows], ["Opening balance", "Credit sale", "Payment received", "Adjustment"])
        self.assertEqual([row["balance"] for row in rows], [D("5000"), D("7500"), D("4500"), D("4400")])

    def test_over_limit_is_reported(self):
        collection = self.collect(credit=[(self.customer, "3500")])  # 5000 + 3500 > 8000
        self.assertEqual(services.customers_over_limit(collection), [self.customer])

    def test_only_dealer_adjusts_or_deletes_payments(self):
        payment = CustomerPayment.objects.create(business=self.business, customer=self.customer, outlet=self.outlet,
                                                 received_on=TODAY, amount=D("100"), method=self.cash, entered_by=self.manager)
        with self.assertRaises(PermissionDenied):
            services.delete_payment(payment, user=self.manager)
        services.delete_payment(payment, user=self.dealer)
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.DELETE, changes__amount="100.00").exists())

    def test_zero_adjustment_rejected(self):
        with self.assertRaises(ValidationError):
            CreditAdjustment(business=self.business, customer=self.customer, adjusted_on=TODAY, amount=D("0"),
                             reason="x", entered_by=self.dealer).full_clean()


class SummaryTests(FinanceTestCase):
    def test_operational_summary(self):
        self.approved_sheet()
        self.collect(cash="6000", upi="3000", credit=[(self.customer, "1700")])
        Expense.objects.create(business=self.business, outlet=self.outlet, expense_date=TODAY,
                               category=ExpenseCategory.objects.get(business=self.business, name="Electricity"),
                               description="MSEB bill", amount=D("2400"), method=self.cash, entered_by=self.manager)
        result = services.operational_summary(business=self.business, outlets=[self.outlet], date_from=TODAY, date_to=TODAY)
        self.assertEqual(result["sales_value"], D("10800.00"))
        self.assertEqual(result["collected"], D("9000"))
        self.assertEqual(result["credit"], D("1700"))
        self.assertEqual(result["difference"], D("-100.00"))
        self.assertEqual(result["expenses"], D("2400"))

    def test_unapproved_sales_not_in_sales_value(self):
        sheet = self.start()
        self.fill(sheet, {"N1": ("480", "2"), "N2": ("1100", "0")})
        result = services.operational_summary(business=self.business, outlets=[self.outlet], date_from=TODAY, date_to=TODAY)
        self.assertEqual(result["sales_value"], D("0"))


class FinanceViewTests(FinanceTestCase):
    def setUp(self):
        super().setUp()
        self.other = make_business("Om Sai Petroleum")
        self.other_dealer = make_user("omsai.dealer", self.other, User.Role.DEALER)

    def test_collection_entry_through_screens(self):
        self.client.force_login(self.manager)
        self.client.post(reverse("finance:collection_create"), {"business_date": TODAY, "shift": self.morning.pk})
        collection = ShiftCollection.objects.get()
        lines = list(collection.lines.order_by("method__sort_order"))
        data = {"methods-TOTAL_FORMS": len(lines), "methods-INITIAL_FORMS": len(lines), "methods-MIN_NUM_FORMS": 0,
                "methods-MAX_NUM_FORMS": 1000, "credit-TOTAL_FORMS": 1, "credit-INITIAL_FORMS": 0,
                "credit-MIN_NUM_FORMS": 0, "credit-MAX_NUM_FORMS": 1000, "collection-notes": "",
                "credit-0-customer": self.customer.pk, "credit-0-amount": "1200", "credit-0-vehicle_number": "MH12XY9999",
                "credit-0-slip_number": "55"}
        for i, line in enumerate(lines):
            data.update({f"methods-{i}-id": line.pk, f"methods-{i}-amount": "1000" if line.method == self.cash else "0",
                         f"methods-{i}-reference": ""})
        response = self.client.post(reverse("finance:collection_edit", args=[collection.pk]), data)
        self.assertRedirects(response, collection.get_absolute_url())
        self.assertEqual(collection.payments_total(), D("1000"))
        self.assertEqual(collection.credit_total(), D("1200"))
        self.assertEqual(self.customer.balance(), D("6200"))

    def test_credit_sale_to_other_tenants_customer_rejected(self):
        foreign = CreditCustomer.objects.create(business=self.other, name="Foreign", opening_balance_date=TODAY)
        collection = self.collect()
        self.client.force_login(self.manager)
        lines = list(collection.lines.all())
        data = {"methods-TOTAL_FORMS": len(lines), "methods-INITIAL_FORMS": len(lines), "methods-MIN_NUM_FORMS": 0,
                "methods-MAX_NUM_FORMS": 1000, "credit-TOTAL_FORMS": 1, "credit-INITIAL_FORMS": 0,
                "credit-MIN_NUM_FORMS": 0, "credit-MAX_NUM_FORMS": 1000, "collection-notes": "",
                "credit-0-customer": foreign.pk, "credit-0-amount": "10", "credit-0-vehicle_number": "", "credit-0-slip_number": ""}
        for i, line in enumerate(lines):
            data.update({f"methods-{i}-id": line.pk, f"methods-{i}-amount": "0", f"methods-{i}-reference": ""})
        response = self.client.post(reverse("finance:collection_edit", args=[collection.pk]), data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(CreditSale.objects.exists())

    def test_expense_record_edit_delete(self):
        self.client.force_login(self.manager)
        category = ExpenseCategory.objects.get(business=self.business, name="Electricity")
        data = {"outlet": self.outlet.pk, "expense_date": TODAY, "category": category.pk, "description": "MSEB bill",
                "amount": "2400", "method": self.cash.pk, "paid_to": "MSEDCL", "reference": "", "notes": ""}
        self.assertRedirects(self.client.post(reverse("finance:expense_create"), data), reverse("finance:expense_list"))
        expense = Expense.objects.get()
        self.client.post(reverse("finance:expense_edit", args=[expense.pk]), {**data, "amount": "2450"})
        expense.refresh_from_db()
        self.assertEqual(expense.amount, D("2450"))
        page = self.client.get(reverse("finance:expense_list"))
        self.assertEqual(page.context["total"], D("2450"))
        self.client.post(reverse("finance:expense_delete", args=[expense.pk]))
        self.assertFalse(Expense.objects.exists())
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.DELETE, object_type="finance.Expense").exists())

    def test_future_expense_rejected(self):
        self.client.force_login(self.manager)
        category = ExpenseCategory.objects.get(business=self.business, name="Rent")
        response = self.client.post(reverse("finance:expense_create"), {
            "outlet": self.outlet.pk, "expense_date": TODAY + timedelta(days=1), "category": category.pk,
            "description": "x", "amount": "1", "method": self.cash.pk})
        self.assertContains(response, "future")

    def test_permissions_and_isolation(self):
        collection = self.collect()
        self.client.force_login(self.manager)
        for url in (reverse("finance:settings"), reverse("finance:summary"), reverse("finance:customer_create")):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.other_dealer)
        for url in (collection.get_absolute_url(), self.customer.get_absolute_url(),
                    reverse("finance:customer_edit", args=[self.customer.pk])):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)
        self.assertNotContains(self.client.get(reverse("finance:customer_list")), "Patil Transport")

    def test_all_pages_render_for_dealer(self):
        self.collect(credit=[(self.customer, "100")])
        self.client.force_login(self.dealer)
        for name in ("collection_list", "collection_create", "customer_list", "customer_create", "payment_create",
                     "expense_list", "expense_create", "summary", "settings", "method_create", "category_create"):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(f"finance:{name}")).status_code, 200)
        self.assertEqual(self.client.get(self.customer.get_absolute_url()).status_code, 200)
        self.assertEqual(self.client.get(ShiftCollection.objects.get().get_absolute_url()).status_code, 200)
