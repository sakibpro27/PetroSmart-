from datetime import time, timedelta
from decimal import Decimal as D

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from audit.models import AuditLog
from core.templatetags.ps_format import indian_grouping, inr
from finance.models import CreditCustomer, CustomerPayment, Expense, ExpenseCategory
from operations.models import Employee, ShopItem, StockMovement
from station.models import Dispenser, FuelPrice, FuelProduct, Nozzle, Shift
from tenants.test_utils import make_business, make_outlet, make_user

from . import services
from .calculations import calculate_line
from .models import DailySalesLine, DailySalesSheet, SalesCorrection
from .reports import sales_summary, summary_lines

TODAY = timezone.localdate()


# --- The formulas ------------------------------------------------------------


class CalculationTests(SimpleTestCase):
    def test_master_prompt_example(self):
        """460 L opening, 480 L closing, 2 L testing, ₹100/L."""
        result = calculate_line(D("460"), D("480"), D("2"), D("100"))
        self.assertEqual(result.total_delivery, D("20"))
        self.assertEqual(result.net_sales_litres, D("18"))
        self.assertEqual(result.sales_value, D("1800.00"))
        self.assertEqual(result.stock_consumption, D("20"))  # stock uses 20 L, not 18 L

    def test_no_testing_means_net_equals_delivery(self):
        result = calculate_line(D("1000.50"), D("1250.75"), D("0"), D("94.72"))
        self.assertEqual(result.net_sales_litres, D("250.25"))
        self.assertEqual(result.sales_value, D("23703.68"))

    def test_value_is_rounded_to_paise_half_up(self):
        self.assertEqual(calculate_line(D("0"), D("0.05"), D("0"), D("100.10")).sales_value, D("5.01"))

    def test_closing_below_opening_is_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            calculate_line(D("480"), D("460"), D("0"), D("100"))
        self.assertIn("closing_reading", ctx.exception.message_dict)

    def test_negative_testing_is_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            calculate_line(D("460"), D("480"), D("-1"), D("100"))
        self.assertIn("testing_litres", ctx.exception.message_dict)

    def test_testing_more_than_delivery_is_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            calculate_line(D("460"), D("480"), D("20.01"), D("100"))
        self.assertIn("testing_litres", ctx.exception.message_dict)

    def test_testing_equal_to_delivery_is_allowed(self):
        self.assertEqual(calculate_line(D("460"), D("480"), D("20"), D("100")).net_sales_litres, D("0"))

    def test_meter_rollover(self):
        result = calculate_line(D("999990"), D("15"), D("1"), D("100"), meter_reset=True,
                                before_reset=D("1000000"), after_reset=D("0"))
        self.assertEqual((result.total_delivery, result.net_sales_litres), (D("25"), D("24")))

    def test_meter_replacement(self):
        result = calculate_line(D("5000"), D("130"), D("0"), D("100"), meter_reset=True,
                                before_reset=D("5020"), after_reset=D("100"))
        self.assertEqual(result.total_delivery, D("50"))

    def test_meter_reset_needs_both_readings(self):
        with self.assertRaises(ValidationError) as ctx:
            calculate_line(D("5000"), D("130"), D("0"), D("100"), meter_reset=True)
        self.assertIn("reading_before_reset", ctx.exception.message_dict)
        self.assertIn("reading_after_reset", ctx.exception.message_dict)


class IndianFormattingTests(SimpleTestCase):
    def test_grouping(self):
        self.assertEqual(indian_grouping(D("1234567.891")), "12,34,567.89")
        self.assertEqual(indian_grouping(D("999")), "999.00")
        self.assertEqual(indian_grouping(D("100000")), "1,00,000.00")
        self.assertEqual(inr(D("1800")), "₹1,800.00")
        self.assertEqual(inr(D("-5")), "−₹5.00")


# --- Shared set-up -------------------------------------------------------------


class SalesTestCase(TestCase):
    """One outlet: DU-1 with N1 (MS, starts at 460) and N2 (HSD, starts at 1000), two shifts, prices, an employee."""

    def setUp(self):
        self.business = make_business("Shree Ganesh Fuels")
        self.outlet = make_outlet(self.business, "SGF-01", "Ganesh Highway")
        self.dealer = make_user("dealer", self.business, User.Role.DEALER)
        self.manager = make_user("manager", self.business, User.Role.MANAGER)
        self.manager.assigned_outlets.add(self.outlet)
        self.ms = FuelProduct.objects.get(business=self.business, code="MS")
        self.hsd = FuelProduct.objects.get(business=self.business, code="HSD")
        self.du = Dispenser.objects.create(business=self.business, outlet=self.outlet, code="DU-1")
        self.n1 = Nozzle.objects.create(business=self.business, outlet=self.outlet, dispenser=self.du, product=self.ms,
                                        code="N1", initial_reading=D("460"))
        self.n2 = Nozzle.objects.create(business=self.business, outlet=self.outlet, dispenser=self.du, product=self.hsd,
                                        code="N2", initial_reading=D("1000"))
        self.morning = Shift.objects.create(business=self.business, outlet=self.outlet, name="Morning",
                                            start_time=time(6), end_time=time(14), sort_order=1)
        self.evening = Shift.objects.create(business=self.business, outlet=self.outlet, name="Evening",
                                            start_time=time(14), end_time=time(22), sort_order=2)
        for product, price in ((self.ms, "100.00"), (self.hsd, "90.00")):
            FuelPrice.objects.create(business=self.business, outlet=self.outlet, product=product,
                                     effective_from=TODAY - timedelta(days=30), price_per_litre=D(price))
        self.ravi = Employee.objects.create(business=self.business, outlet=self.outlet, name="Ravi")

    def card(self, shift=None, day=TODAY, readings=None, user=None, credits=(), receipts=(), lubes=(), expenses=(),
             **money):
        """Save a Shift Card. Default readings: N1 480 (2 L testing) and N2 1100: ₹1,800 + ₹9,000 = ₹10,800."""
        readings = readings or {"N1": ("480", "2"), "N2": ("1100", "0")}
        nozzles = {n.code: n for n in Nozzle.objects.filter(dispenser=self.du)}
        rows = [{"nozzle": nozzles[code], "closing_reading": D(closing), "testing_litres": D(testing)}
                for code, (closing, testing) in readings.items()]
        header = {"business_date": day, "shift": shift or self.morning, "dispenser": self.du, "employee": self.ravi,
                  **{key: D(value) if key in ("bank_card", "company_card", "phone_wallet", "general_credit", "coins")
                     else value for key, value in money.items()}}
        sheet, _warnings = services.save_card(user=user or self.manager, header=header, rows=rows, credits=credits,
                                              receipts=receipts, lubes=lubes, expenses=expenses)
        return sheet

    def slip(self, customer, amount, vehicle="", product=None, litres=None):
        """A credit slip row for card(): HSD (₹90/L) unless another product is given."""
        return {"id": None, "customer": customer, "product": product or self.hsd, "vehicle_number": vehicle,
                "amount": D(amount) if amount else None, "litres": D(litres) if litres else None}

    def line(self, sheet, code):
        return DailySalesLine.objects.get(sheet=sheet, nozzle__code=code)


# --- Saving cards ---------------------------------------------------------------------


class CardTests(SalesTestCase):
    def test_lines_opening_rate_and_figures(self):
        sheet = self.card()
        n1 = self.line(sheet, "N1")
        self.assertEqual((n1.opening_reading, n1.price_per_litre), (D("460"), D("100.00")))
        self.assertEqual((n1.total_delivery, n1.net_sales_litres, n1.sales_value), (D("20"), D("18"), D("1800.00")))
        self.assertEqual(n1.stock_consumption, D("20"))
        self.assertEqual((sheet.employee, sheet.dispenser, sheet.entered_by), (self.ravi, self.du, self.manager))
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.CREATE, object_id=str(sheet.pk)).exists())

    def test_ms_and_hsd_totals_are_separate(self):
        """N1 MS: 20 L delivered, 2 L testing, 18 L × ₹100. N2 HSD: 100 L × ₹90."""
        figures = services.card_figures(self.card())
        ms, hsd = figures["products"]
        self.assertEqual((ms["code"], ms["delivery"], ms["testing"], ms["net"], ms["amount"]),
                         ("MS", D("20"), D("2"), D("18"), D("1800.00")))
        self.assertEqual((hsd["code"], hsd["net"], hsd["amount"]), ("HSD", D("100"), D("9000.00")))
        self.assertEqual(ms["amount"] + hsd["amount"], figures["total_fuel"])
        split = services.category_split(figures["products"])
        self.assertEqual([part["net"] for part in split], [D("18"), D("100")])

    def test_no_approval_needed(self):
        sheet = self.card()
        self.assertFalse(hasattr(sheet, "status"))
        evening = self.card(self.evening, readings={"N1": ("500", "0"), "N2": ("1150", "0")})
        self.assertEqual(self.line(evening, "N1").opening_reading, D("480"))  # next card starts straight away

    def test_rate_in_force_on_the_date(self):
        FuelPrice.objects.create(business=self.business, outlet=self.outlet, product=self.ms, effective_from=TODAY,
                                 price_per_litre=D("101.50"))
        yesterday = self.card(day=TODAY - timedelta(days=1), readings={"N1": ("470", "0"), "N2": ("1010", "0")})
        self.assertEqual(self.line(yesterday, "N1").price_per_litre, D("100.00"))
        self.assertEqual(self.line(self.card(), "N1").price_per_litre, D("101.50"))

    def test_missing_price_and_future_date_blocked(self):
        with self.assertRaisesMessage(ValidationError, "future"):
            self.card(day=TODAY + timedelta(days=1))
        FuelPrice.objects.filter(product=self.hsd).delete()
        with self.assertRaisesMessage(ValidationError, "No selling price"):
            self.card()

    def test_readings_must_be_in_order_and_once_per_shift(self):
        self.card(self.evening)
        with self.assertRaisesMessage(ValidationError, "must be entered in order"):
            self.card(self.morning)
        with self.assertRaisesMessage(ValidationError, "must be entered in order"):
            self.card(self.evening, readings={"N1": ("490", "0"), "N2": ("1110", "0")})

    def test_invalid_readings_rejected(self):
        with self.assertRaisesMessage(ValidationError, "cannot be less than the opening"):
            self.card(readings={"N1": ("450", "0"), "N2": ("1100", "0")})
        with self.assertRaisesMessage(ValidationError, "cannot be more than the total nozzle delivery"):
            self.card(readings={"N1": ("480", "25"), "N2": ("1100", "0")})
        self.assertFalse(DailySalesSheet.objects.exists())

    def test_manager_cannot_use_unassigned_outlet(self):
        other = make_outlet(self.business, "SGF-02")
        du = Dispenser.objects.create(business=self.business, outlet=other, code="DU-9")
        shift = Shift.objects.create(business=self.business, outlet=other, name="Day", start_time=time(6),
                                     end_time=time(6), sort_order=1)
        with self.assertRaises(PermissionDenied):
            services.save_card(user=self.manager, header={"business_date": TODAY, "shift": shift, "dispenser": du},
                               rows=[])


class MoneyTests(SalesTestCase):
    def setUp(self):
        super().setUp()
        self.customer = CreditCustomer.objects.create(business=self.business, name="Patil Transport",
                                                      opening_balance=D("5000"), opening_balance_date=TODAY,
                                                      credit_limit=D("6000"))
        self.oil = ShopItem.objects.create(business=self.business, name="20W-40 oil", selling_price=D("350"))
        StockMovement.objects.create(business=self.business, item=self.oil, outlet=self.outlet, moved_on=TODAY,
                                     kind="OPENING", quantity=D("10"), entered_by=self.dealer)
        self.rent = ExpenseCategory.objects.get(business=self.business, name="Other")

    def test_balance_formula(self):
        # Fuel 10,800 + lube 700 + receipt 500 - credit 1,200 - gen credit 300 - bank 2,000
        # - company 1,000 - wallet 3,000 - expense 100 = cash to collect 4,400.
        sheet = self.card(credits=[self.slip(self.customer, "1200", "MH12AB1234")],
                          receipts=[(self.customer, D("500"), "R-1")],
                          lubes=[(self.oil, D("2"), D("350"))],
                          expenses=[(self.rent, "Tea for staff", D("100"))],
                          general_credit="300", general_credit_party="Local farmer", bank_card="2000",
                          company_card="1000", phone_wallet="3000", notes_500=8, notes_100=3, notes_10=5, coins="40")
        figures = services.card_figures(sheet)
        self.assertEqual(figures["total_fuel"], D("10800.00"))
        self.assertEqual(figures["lube"], D("700.00"))
        self.assertEqual(figures["cash_collection"], D("4390"))  # 8×500 + 3×100 + 5×10 + 40
        self.assertEqual(figures["expected_cash"], D("4400.00"))
        self.assertEqual(figures["balance"], D("-10.00"))  # ₹10 short

    def test_linked_records_update_ledgers_stock_and_expenses(self):
        sheet = self.card(credits=[self.slip(self.customer, "1200")], receipts=[(self.customer, D("500"), "")],
                          lubes=[(self.oil, D("2"), D("350"))], expenses=[(self.rent, "Tea", D("100"))])
        self.assertEqual(self.customer.balance(), D("5700"))  # 5000 + 1200 - 500
        self.assertEqual(self.oil.stock_at(self.outlet), D("8"))
        self.assertEqual(Expense.objects.get().sheet, sheet)
        self.assertEqual(CustomerPayment.objects.get().sheet, sheet)

    def test_over_limit_warning(self):
        _sheet, warnings = services.save_card(
            user=self.manager, header={"business_date": TODAY, "shift": self.morning, "dispenser": self.du,
                                       "employee": self.ravi},
            rows=[{"nozzle": self.n1, "closing_reading": D("480"), "testing_litres": D("0")},
                  {"nozzle": self.n2, "closing_reading": D("1000"), "testing_litres": D("0")}],
            credits=[self.slip(self.customer, "1500")])
        self.assertIn("over their credit limit", warnings[0])

    def test_cannot_sell_more_lube_than_in_stock(self):
        with self.assertRaisesMessage(ValidationError, "in stock"):
            self.card(lubes=[(self.oil, D("11"), D("350"))])
        self.assertFalse(DailySalesSheet.objects.exists())

    def test_edit_replaces_linked_records(self):
        sheet = self.card(credits=[self.slip(self.customer, "1200")], lubes=[(self.oil, D("2"), D("350"))])
        services.save_card(user=self.manager, sheet=sheet, header={"employee": self.ravi, "phone_wallet": D("50")},
                           rows=[{"nozzle": self.n1, "closing_reading": D("481"), "testing_litres": D("2")},
                                 {"nozzle": self.n2, "closing_reading": D("1100"), "testing_litres": D("0")}],
                           credits=[self.slip(self.customer, "200")], lubes=[(self.oil, D("1"), D("350"))])
        sheet.refresh_from_db()
        self.assertEqual(sheet.phone_wallet, D("50"))
        self.assertEqual(self.line(sheet, "N1").net_sales_litres, D("19"))
        self.assertEqual(self.customer.balance(), D("5200"))
        self.assertEqual(self.oil.stock_at(self.outlet), D("9"))
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.UPDATE, object_id=str(sheet.pk)).exists())

    def test_delete_card_removes_linked_records(self):
        sheet = self.card(credits=[self.slip(self.customer, "1200")], lubes=[(self.oil, D("2"), D("350"))],
                          expenses=[(self.rent, "Tea", D("100"))])
        services.delete_card(sheet, user=self.manager)
        self.assertFalse(DailySalesSheet.objects.exists())
        self.assertEqual(self.customer.balance(), D("5000"))
        self.assertEqual(self.oil.stock_at(self.outlet), D("10"))
        self.assertFalse(Expense.objects.exists())
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.DELETE).exists())


class EditAndCorrectionTests(SalesTestCase):
    def setUp(self):
        super().setUp()
        self.morning_card = self.card()

    def test_latest_card_can_be_edited_and_deleted(self):
        self.assertTrue(services.can_change(self.morning_card, self.manager))

    def test_older_card_cannot_be_edited_but_can_be_corrected(self):
        evening = self.card(self.evening, readings={"N1": ("500", "0"), "N2": ("1150", "0")})
        self.assertFalse(services.can_change(self.morning_card, self.manager))
        with self.assertRaisesMessage(ValidationError, "Use Correct instead"):
            services.save_card(user=self.manager, sheet=self.morning_card, header={}, rows=[])
        with self.assertRaisesMessage(ValidationError, "cannot be deleted"):
            services.delete_card(self.morning_card, user=self.manager)

        n1 = self.line(self.morning_card, "N1")
        services.correct_card(self.morning_card, user=self.manager, reason="Closing misread",
                              changes=[(n1, D("482"), D("2"), D("100.00"))])
        n1.refresh_from_db()
        evening_n1 = self.line(evening, "N1")
        self.assertEqual(n1.closing_reading, D("482"))
        self.assertEqual((evening_n1.opening_reading, evening_n1.total_delivery), (D("482"), D("18")))
        item = SalesCorrection.objects.get().lines.get()
        self.assertEqual((item.old_closing_reading, item.next_old_opening), (D("480"), D("480")))
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.CORRECT).exists())

    def test_correction_that_breaks_next_card_is_refused(self):
        self.card(self.evening, readings={"N1": ("500", "0"), "N2": ("1150", "0")})
        n1 = self.line(self.morning_card, "N1")
        with self.assertRaisesMessage(ValidationError, "next card"):
            services.correct_card(self.morning_card, user=self.manager, reason="x",
                                  changes=[(n1, D("510"), D("2"), D("100.00"))])
        self.assertFalse(SalesCorrection.objects.exists())


class ReportTests(SalesTestCase):
    def setUp(self):
        super().setUp()
        self.card()  # N1: 20 L, 2 L testing; N2: 100 L
        self.card(self.evening, readings={"N1": ("510", "1"), "N2": ("1150", "0")})  # N1: 30 L, 1 L testing; N2: 50 L

    def summary(self, group_by, outlets=None):
        lines = summary_lines(business=self.business, outlets=outlets or [self.outlet], date_from=TODAY, date_to=TODAY)
        return sales_summary(lines, group_by)

    def test_totals_separate_testing_from_sales(self):
        _, totals = self.summary("day")
        self.assertEqual(totals["total_delivery"], D("200"))
        self.assertEqual(totals["testing_litres"], D("3"))
        self.assertEqual(totals["net_sales_litres"], D("197"))
        self.assertEqual(totals["sales_value"], D("4700") + D("13500"))  # 47 L × 100 + 150 L × 90

    def test_groupings(self):
        by_code = {row["product__code"]: row for row in self.summary("product")[0]}
        self.assertEqual((by_code["MS"]["total_delivery"], by_code["MS"]["net_sales_litres"]), (D("50"), D("47")))
        self.assertEqual([row["sheet__shift__name"] for row in self.summary("shift")[0]], ["Morning", "Evening"])
        self.assertEqual({row["nozzle__code"]: row["net_sales_litres"] for row in self.summary("nozzle")[0]},
                         {"N1": D("47"), "N2": D("150")})

    def test_outlets_are_separate(self):
        _, totals = self.summary("day", outlets=[make_outlet(self.business, "SGF-02")])
        self.assertIsNone(totals["net_sales_litres"])


# --- Screens ---------------------------------------------------------------------------


class CardScreenTests(SalesTestCase):
    def setUp(self):
        super().setUp()
        self.other = make_business("Om Sai Petroleum")
        self.other_dealer = make_user("omsai.dealer", self.other, User.Role.DEALER)
        self.customer = CreditCustomer.objects.create(business=self.business, name="Patil Transport",
                                                      opening_balance_date=TODAY)

    def post_card(self, url=None, readings=None, **extra):
        readings = readings or {"N1": ("480", "2"), "N2": ("1100", "0")}
        data = {"business_date": TODAY, "shift": self.morning.pk, "dispenser": self.du.pk, "employee": self.ravi.pk,
                "cashier_name": "", "helper_name": "", "time_from": "06:00", "time_to": "14:00", "notes": "",
                "general_credit": "0", "general_credit_party": "", "bank_card": "0", "company_card": "0",
                "phone_wallet": "3000", "coins": "0", "action": "save",
                "nozzles-TOTAL_FORMS": 2, "nozzles-INITIAL_FORMS": 2, "nozzles-MIN_NUM_FORMS": 0, "nozzles-MAX_NUM_FORMS": 1000}
        for d in (2000, 500, 200, 100, 50, 20, 10):
            data[f"notes_{d}"] = "0"
        data["notes_500"] = "15"
        for i, (code, (closing, testing)) in enumerate(sorted(readings.items())):
            nozzle = {"N1": self.n1, "N2": self.n2}[code]
            data.update({f"nozzles-{i}-nozzle_id": nozzle.pk, f"nozzles-{i}-closing_reading": closing,
                         f"nozzles-{i}-testing_litres": testing, f"nozzles-{i}-notes": ""})
        for prefix in ("credit", "receipts", "lubes", "expenses"):
            data.update({f"{prefix}-TOTAL_FORMS": 1, f"{prefix}-INITIAL_FORMS": 0, f"{prefix}-MIN_NUM_FORMS": 0,
                         f"{prefix}-MAX_NUM_FORMS": 50})
        data.update(extra)
        return self.client.post(url or reverse("sales:sheet_create"), data)

    def test_new_card_page_loads_pump_rows(self):
        self.client.force_login(self.manager)
        page = self.client.get(reverse("sales:sheet_create"),
                               {"business_date": TODAY, "shift": self.morning.pk, "dispenser": self.du.pk})
        self.assertContains(page, "Shift Card")
        self.assertContains(page, "Money Details")
        self.assertContains(page, "Balance / Short")
        self.assertEqual(len(page.context["rows"]), 2)

    def test_save_card_through_screen_with_credit_row(self):
        self.client.force_login(self.manager)
        response = self.post_card(**{"credit-0-customer": self.customer.pk, "credit-0-product": self.hsd.pk,
                                     "credit-0-amount": "300", "credit-0-vehicle_number": "MH12"})
        sheet = DailySalesSheet.objects.get()
        self.assertRedirects(response, sheet.get_absolute_url())
        figures = services.card_figures(sheet)
        self.assertEqual(figures["cash_collection"], D("7500"))  # 15 × 500
        self.assertEqual(figures["expected_cash"], D("7500.00"))  # 10,800 - 300 credit - 3,000 wallet
        self.assertEqual(figures["balance"], D("0.00"))
        page = self.client.get(sheet.get_absolute_url())
        self.assertContains(page, "matches")
        self.assertContains(page, "Patil Transport")

    def test_save_and_print_redirects_to_print_view(self):
        self.client.force_login(self.manager)
        response = self.post_card(action="print")
        self.assertTrue(response.url.endswith("?print=1"))

    def test_invalid_reading_shows_error_and_saves_nothing(self):
        self.client.force_login(self.manager)
        response = self.post_card(readings={"N1": ("450", "0"), "N2": ("1100", "0")})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "cannot be less than the opening reading")
        self.assertFalse(DailySalesSheet.objects.exists())

    def test_opening_and_rate_cannot_be_posted(self):
        self.client.force_login(self.manager)
        self.post_card(**{"nozzles-0-opening_reading": "0", "nozzles-0-price_per_litre": "1"})
        n1 = self.line(DailySalesSheet.objects.get(), "N1")
        self.assertEqual((n1.opening_reading, n1.price_per_litre), (D("460"), D("100.00")))

    def test_forged_nozzle_rows_refused(self):
        self.client.force_login(self.manager)
        response = self.post_card(**{"nozzles-1-nozzle_id": self.n1.pk})  # same nozzle twice
        self.assertEqual(response.status_code, 200)
        self.assertFalse(DailySalesSheet.objects.exists())

    def test_edit_and_delete_through_screens(self):
        self.client.force_login(self.manager)
        self.post_card()
        sheet = DailySalesSheet.objects.get()
        edit_url = reverse("sales:sheet_edit", args=[sheet.pk])
        self.assertEqual(self.client.get(edit_url).status_code, 200)
        self.post_card(url=edit_url, readings={"N1": ("485", "2"), "N2": ("1100", "0")})
        self.assertEqual(self.line(sheet, "N1").closing_reading, D("485"))
        self.client.post(reverse("sales:sheet_delete", args=[sheet.pk]))
        self.assertFalse(DailySalesSheet.objects.exists())

    def test_correction_through_screen(self):
        morning = self.card()
        self.card(self.evening, readings={"N1": ("500", "0"), "N2": ("1150", "0")})
        self.client.force_login(self.manager)
        self.assertRedirects(self.client.get(reverse("sales:sheet_edit", args=[morning.pk])), morning.get_absolute_url())
        data = {"reason": "Testing was 4 L"}
        for line in morning.lines.all():
            data.update({f"closing_{line.pk}": line.closing_reading, f"testing_{line.pk}": line.testing_litres,
                         f"price_{line.pk}": line.price_per_litre})
        data[f"testing_{self.line(morning, 'N1').pk}"] = "4"
        self.assertRedirects(self.client.post(reverse("sales:correction_create", args=[morning.pk]), data),
                             morning.get_absolute_url())
        self.assertEqual(self.line(morning, "N1").net_sales_litres, D("16"))

    def test_other_tenant_cannot_see_or_change_cards(self):
        sheet = self.card()
        self.client.force_login(self.other_dealer)
        for name in ("sales:sheet_detail", "sales:sheet_edit", "sales:correction_create"):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name, args=[sheet.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("sales:sheet_delete", args=[sheet.pk])).status_code, 404)
        self.assertNotContains(self.client.get(reverse("sales:sheet_list")), "Ganesh")
        page = self.client.get(reverse("sales:sheet_create"), {"business_date": TODAY, "shift": self.morning.pk,
                                                               "dispenser": self.du.pk})
        self.assertEqual(page.context["rows"], [])  # another tenant's pump cannot be loaded

    def test_manager_only_sees_assigned_outlets(self):
        other_outlet = make_outlet(self.business, "SGF-02")
        hidden = DailySalesSheet.objects.create(
            business=self.business, outlet=other_outlet, business_date=TODAY, entered_by=self.dealer, shift_sort_order=1,
            shift=Shift.objects.create(business=self.business, outlet=other_outlet, name="Day", start_time=time(6),
                                       end_time=time(6), sort_order=1))
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(reverse("sales:sheet_detail", args=[hidden.pk])).status_code, 404)
