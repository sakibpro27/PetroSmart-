from datetime import time, timedelta
from decimal import Decimal as D

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from audit.models import AuditLog
from core.templatetags.ps_format import indian_grouping, inr
from station.models import Dispenser, FuelPrice, FuelProduct, Nozzle, Shift
from tenants.test_utils import make_business, make_outlet, make_user

from . import services
from .calculations import calculate_line
from .models import DailySalesLine, DailySalesSheet, SalesCorrection
from .reports import sales_summary, summary_lines

Status = DailySalesSheet.Status
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
        self.assertEqual(result.sales_value, D("23703.68"))  # 250.25 × 94.72 = 23703.68

    def test_value_is_rounded_to_paise_half_up(self):
        # 0.05 L × ₹100.10 = ₹5.005 -> ₹5.01
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
        # Meter counts to 1,000,000.00 then restarts at 0.
        result = calculate_line(D("999990"), D("15"), D("1"), D("100"), meter_reset=True,
                                before_reset=D("1000000"), after_reset=D("0"))
        self.assertEqual(result.total_delivery, D("25"))
        self.assertEqual(result.net_sales_litres, D("24"))

    def test_meter_replacement(self):
        # Old meter ended at 5020, new meter started at 100 and closed at 130.
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


# --- Workflow ------------------------------------------------------------------


class SalesTestCase(TestCase):
    """An outlet with two nozzles (MS and HSD), two shifts and prices, in two tenants."""

    def setUp(self):
        self.business = make_business("Shree Ganesh Fuels")
        self.outlet = make_outlet(self.business, "SGF-01", "Ganesh Highway")
        self.dealer = make_user("dealer", self.business, User.Role.DEALER)
        self.manager = make_user("manager", self.business, User.Role.MANAGER)
        self.manager.assigned_outlets.add(self.outlet)
        self.ms = FuelProduct.objects.get(business=self.business, code="MS")
        self.hsd = FuelProduct.objects.get(business=self.business, code="HSD")
        du = Dispenser.objects.create(business=self.business, outlet=self.outlet, code="DU-1")
        self.n1 = Nozzle.objects.create(business=self.business, outlet=self.outlet, dispenser=du, product=self.ms,
                                        code="N1", initial_reading=D("460"))
        self.n2 = Nozzle.objects.create(business=self.business, outlet=self.outlet, dispenser=du, product=self.hsd,
                                        code="N2", initial_reading=D("1000"))
        self.morning = Shift.objects.create(business=self.business, outlet=self.outlet, name="Morning",
                                            start_time=time(6), end_time=time(14), sort_order=1)
        self.evening = Shift.objects.create(business=self.business, outlet=self.outlet, name="Evening",
                                            start_time=time(14), end_time=time(22), sort_order=2)
        for product, price in ((self.ms, "100.00"), (self.hsd, "90.00")):
            FuelPrice.objects.create(business=self.business, outlet=self.outlet, product=product,
                                     effective_from=TODAY - timedelta(days=30), price_per_litre=D(price))

    def start(self, shift=None, day=TODAY, user=None):
        return services.create_sheet(user=user or self.manager, shift=shift or self.morning, business_date=day)

    def fill(self, sheet, readings):
        """readings: {nozzle_code: (closing, testing)}"""
        for line in sheet.lines.select_related("nozzle"):
            closing, testing = readings[line.nozzle.code]
            line.closing_reading, line.testing_litres = D(closing), D(testing)
            line.full_clean()
            line.save()

    def approved_sheet(self, shift=None, day=TODAY, readings=None):
        sheet = self.start(shift, day)
        self.fill(sheet, readings or {"N1": ("480", "2"), "N2": ("1100", "0")})
        services.submit_sheet(sheet, user=self.manager)
        return services.approve_sheet(sheet, user=self.dealer)

    def line(self, sheet, code):
        return DailySalesLine.objects.get(sheet=sheet, nozzle__code=code)


class SheetCreationTests(SalesTestCase):
    def test_lines_for_active_nozzles_with_opening_and_price(self):
        sheet = self.start()
        n1 = self.line(sheet, "N1")
        self.assertEqual((n1.opening_reading, n1.price_per_litre, n1.product), (D("460"), D("100.00"), self.ms))
        self.assertEqual(self.line(sheet, "N2").price_per_litre, D("90.00"))
        self.assertEqual(sheet.status, Status.DRAFT)
        self.assertEqual(sheet.entered_by, self.manager)

    def test_opening_is_previous_closing(self):
        self.approved_sheet()
        evening = self.start(self.evening)
        self.assertEqual(self.line(evening, "N1").opening_reading, D("480"))
        self.assertEqual(self.line(evening, "N2").opening_reading, D("1100"))

    def test_price_is_the_one_in_force_on_the_business_date(self):
        FuelPrice.objects.create(business=self.business, outlet=self.outlet, product=self.ms,
                                 effective_from=TODAY, price_per_litre=D("101.50"))
        yesterday = self.start(day=TODAY - timedelta(days=1))
        self.assertEqual(self.line(yesterday, "N1").price_per_litre, D("100.00"))
        self.fill(yesterday, {"N1": ("470", "0"), "N2": ("1010", "0")})
        services.submit_sheet(yesterday, user=self.manager)
        self.assertEqual(self.line(self.start(), "N1").price_per_litre, D("101.50"))

    def test_missing_price_blocks_sheet(self):
        FuelPrice.objects.filter(product=self.hsd).delete()
        with self.assertRaisesMessage(ValidationError, "No selling price"):
            self.start()

    def test_future_date_blocked(self):
        with self.assertRaisesMessage(ValidationError, "future date"):
            self.start(day=TODAY + timedelta(days=1))

    def test_sheets_must_be_in_order(self):
        self.approved_sheet(self.evening)
        with self.assertRaisesMessage(ValidationError, "entered in order"):
            self.start(self.morning)  # earlier shift on the same day

    def test_previous_sheet_must_be_submitted(self):
        self.start()
        with self.assertRaisesMessage(ValidationError, "Finish and submit"):
            self.start(self.evening)

    def test_manager_cannot_start_sheet_at_unassigned_outlet(self):
        other = make_outlet(self.business, "SGF-02")
        shift = Shift.objects.create(business=self.business, outlet=other, name="Day", start_time=time(6),
                                     end_time=time(6), sort_order=1)
        with self.assertRaises(PermissionDenied):
            self.start(shift)

    def test_no_nozzles_blocks_sheet(self):
        Nozzle.objects.update(is_active=False)
        with self.assertRaisesMessage(ValidationError, "no active nozzles"):
            self.start()


class SubmitApproveTests(SalesTestCase):
    def test_figures_stored_on_save(self):
        sheet = self.start()
        self.fill(sheet, {"N1": ("480", "2"), "N2": ("1100", "0")})
        n1 = self.line(sheet, "N1")
        self.assertEqual((n1.total_delivery, n1.net_sales_litres, n1.sales_value), (D("20"), D("18"), D("1800.00")))
        self.assertEqual(n1.stock_consumption, D("20"))

    def test_submit_requires_every_closing_reading(self):
        sheet = self.start()
        line = self.line(sheet, "N1")
        line.closing_reading = D("480")
        line.save()
        with self.assertRaisesMessage(ValidationError, "N2"):
            services.submit_sheet(sheet, user=self.manager)

    def test_approval_keeps_readings_unchanged(self):
        sheet = self.start()
        self.fill(sheet, {"N1": ("480", "2"), "N2": ("1100", "0")})
        services.submit_sheet(sheet, user=self.manager)
        before = list(sheet.lines.values_list("opening_reading", "closing_reading", "testing_litres", "sales_value"))
        services.approve_sheet(sheet, user=self.dealer)
        sheet.refresh_from_db()
        self.assertEqual(sheet.status, Status.APPROVED)
        self.assertEqual(sheet.approved_by, self.dealer)
        self.assertIsNotNone(sheet.approved_at)
        after = list(sheet.lines.values_list("opening_reading", "closing_reading", "testing_litres", "sales_value"))
        self.assertEqual(before, after)
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.APPROVE, object_id=str(sheet.pk)).exists())

    def test_manager_cannot_approve(self):
        sheet = self.start()
        self.fill(sheet, {"N1": ("480", "2"), "N2": ("1100", "0")})
        services.submit_sheet(sheet, user=self.manager)
        with self.assertRaises(PermissionDenied):
            services.approve_sheet(sheet, user=self.manager)

    def test_submitted_sheet_cannot_be_edited(self):
        sheet = self.start()
        self.fill(sheet, {"N1": ("480", "2"), "N2": ("1100", "0")})
        services.submit_sheet(sheet, user=self.manager)
        sheet.refresh_from_db()
        self.assertFalse(services.can_edit(sheet, self.manager))

    def test_return_latest_sheet_to_draft(self):
        sheet = self.start()
        self.fill(sheet, {"N1": ("480", "2"), "N2": ("1100", "0")})
        services.submit_sheet(sheet, user=self.manager)
        with self.assertRaisesMessage(ValidationError, "Write a note"):
            services.return_sheet(sheet, user=self.dealer, note=" ")
        services.return_sheet(sheet, user=self.dealer, note="N1 testing looks high")
        sheet.refresh_from_db()
        self.assertEqual((sheet.status, sheet.review_note), (Status.DRAFT, "N1 testing looks high"))

    def test_cannot_return_sheet_that_a_later_sheet_depends_on(self):
        morning = self.start()
        self.fill(morning, {"N1": ("480", "2"), "N2": ("1100", "0")})
        services.submit_sheet(morning, user=self.manager)
        self.start(self.evening)
        with self.assertRaisesMessage(ValidationError, "later sheet"):
            services.return_sheet(morning, user=self.dealer, note="fix")


class CorrectionTests(SalesTestCase):
    def setUp(self):
        super().setUp()
        self.morning_sheet = self.approved_sheet()
        self.n1 = self.line(self.morning_sheet, "N1")

    def request(self, closing="480", testing="2", price="100.00", user=None):
        return services.request_correction(
            self.morning_sheet, user=user or self.manager, reason="Testing litres were written wrongly",
            changes=[(self.n1, D(closing), D(testing), D(price))],
        )

    def test_correction_changes_nothing_until_approved(self):
        self.request(testing="5")
        self.n1.refresh_from_db()
        self.assertEqual(self.n1.testing_litres, D("2"))

    def test_approved_correction_updates_figures_and_keeps_history(self):
        correction = self.request(testing="5")
        services.approve_correction(correction, user=self.dealer)
        self.n1.refresh_from_db()
        self.assertEqual((self.n1.testing_litres, self.n1.net_sales_litres, self.n1.sales_value),
                         (D("5"), D("15"), D("1500.00")))
        self.assertEqual(self.n1.total_delivery, D("20"))  # delivery is unchanged by testing litres
        item = correction.lines.get()
        self.assertEqual((item.old_testing_litres, item.new_testing_litres), (D("2"), D("5")))
        self.morning_sheet.refresh_from_db()
        self.assertEqual(self.morning_sheet.status, Status.APPROVED)
        log = AuditLog.objects.get(action=AuditLog.Action.CORRECT)
        self.assertEqual(log.changes["N1"]["testing_litres"], ["2.00", "5.00"])

    def test_closing_correction_updates_next_shift_opening(self):
        evening = self.approved_sheet(self.evening, readings={"N1": ("500", "0"), "N2": ("1150", "0")})
        correction = self.request(closing="482")
        services.approve_correction(correction, user=self.dealer)
        evening_n1 = self.line(evening, "N1")
        self.assertEqual(evening_n1.opening_reading, D("482"))
        self.assertEqual(evening_n1.total_delivery, D("18"))  # 500 - 482
        item = correction.lines.get()
        self.assertEqual((item.next_line, item.next_old_opening, item.next_new_opening), (evening_n1, D("480"), D("482")))
        # Over both shifts the nozzle still delivered 40 L in total.
        self.n1.refresh_from_db()
        self.assertEqual(self.n1.total_delivery + evening_n1.total_delivery, D("40"))

    def test_correction_that_breaks_next_shift_is_rejected(self):
        self.approved_sheet(self.evening, readings={"N1": ("500", "0"), "N2": ("1150", "0")})
        with self.assertRaisesMessage(ValidationError, "next shift"):
            self.request(closing="510")  # evening closing 500 would be below its new opening

    def test_invalid_correction_values_rejected(self):
        with self.assertRaisesMessage(ValidationError, "Testing litres cannot be more"):
            self.request(testing="25")

    def test_one_pending_correction_at_a_time(self):
        self.request(testing="5")
        with self.assertRaisesMessage(ValidationError, "already has a correction"):
            self.request(testing="3")

    def test_rejection_needs_note_and_keeps_values(self):
        correction = self.request(testing="5")
        with self.assertRaisesMessage(ValidationError, "Write a note"):
            services.reject_correction(correction, user=self.dealer, note="")
        services.reject_correction(correction, user=self.dealer, note="The register shows 2 L")
        self.n1.refresh_from_db()
        self.assertEqual(self.n1.testing_litres, D("2"))
        correction.refresh_from_db()
        self.assertEqual(correction.status, SalesCorrection.Status.REJECTED)

    def test_manager_cannot_approve_correction(self):
        correction = self.request(testing="5")
        with self.assertRaises(PermissionDenied):
            services.approve_correction(correction, user=self.manager)

    def test_draft_sheets_are_not_corrected(self):
        draft = self.start(self.evening)
        with self.assertRaisesMessage(ValidationError, "only for approved"):
            services.request_correction(draft, user=self.manager, reason="x",
                                        changes=[(self.line(draft, "N1"), D("490"), D("0"), D("100"))])


# --- Reports -----------------------------------------------------------------


class ReportTests(SalesTestCase):
    def setUp(self):
        super().setUp()
        # Morning approved: N1 20 L delivered, 2 L testing; N2 100 L, 0 testing.
        self.approved_sheet()
        # Evening submitted only: N1 30 L (1 L testing), N2 50 L.
        evening = self.start(self.evening)
        self.fill(evening, {"N1": ("510", "1"), "N2": ("1150", "0")})
        services.submit_sheet(evening, user=self.manager)

    def summary(self, group_by, statuses=(Status.APPROVED,), outlets=None):
        lines = summary_lines(business=self.business, outlets=outlets or [self.outlet], date_from=TODAY,
                              date_to=TODAY, statuses=statuses)
        return sales_summary(lines, group_by)

    def test_totals_separate_testing_from_sales(self):
        _, totals = self.summary("day")
        self.assertEqual(totals["total_delivery"], D("120"))
        self.assertEqual(totals["testing_litres"], D("2"))
        self.assertEqual(totals["net_sales_litres"], D("118"))
        self.assertEqual(totals["sales_value"], D("1800") + D("9000"))  # 18×100 + 100×90

    def test_only_approved_by_default_and_submitted_on_request(self):
        _, approved = self.summary("day")
        _, both = self.summary("day", statuses=(Status.APPROVED, Status.SUBMITTED))
        self.assertEqual(approved["net_sales_litres"], D("118"))
        self.assertEqual(both["net_sales_litres"], D("118") + D("29") + D("50"))
        self.assertEqual(both["testing_litres"], D("3"))

    def test_group_by_product(self):
        rows, _ = self.summary("product", statuses=(Status.APPROVED, Status.SUBMITTED))
        by_code = {row["product__code"]: row for row in rows}
        self.assertEqual(by_code["MS"]["total_delivery"], D("50"))
        self.assertEqual(by_code["MS"]["testing_litres"], D("3"))
        self.assertEqual(by_code["MS"]["net_sales_litres"], D("47"))
        self.assertEqual(by_code["MS"]["sales_value"], D("4700.00"))
        self.assertEqual(by_code["HSD"]["net_sales_litres"], D("150"))

    def test_group_by_shift_nozzle_month_outlet(self):
        statuses = (Status.APPROVED, Status.SUBMITTED)
        shifts, _ = self.summary("shift", statuses=statuses)
        self.assertEqual([row["sheet__shift__name"] for row in shifts], ["Morning", "Evening"])
        nozzles, _ = self.summary("nozzle", statuses=statuses)
        self.assertEqual({row["nozzle__code"]: row["net_sales_litres"] for row in nozzles}, {"N1": D("47"), "N2": D("150")})
        months, totals = self.summary("month", statuses=statuses)
        self.assertEqual(len(months), 1)
        self.assertEqual(months[0]["net_sales_litres"], totals["net_sales_litres"])
        outlets, _ = self.summary("outlet", statuses=statuses)
        self.assertEqual(outlets[0]["sheet__outlet__code"], "SGF-01")

    def test_outlets_are_reported_separately(self):
        second = make_outlet(self.business, "SGF-02")
        _, totals = self.summary("day", outlets=[second])
        self.assertIsNone(totals["net_sales_litres"])


# --- Screens, permissions and tenant isolation -------------------------------


class SalesViewTests(SalesTestCase):
    def setUp(self):
        super().setUp()
        self.other = make_business("Om Sai Petroleum")
        self.other_dealer = make_user("omsai.dealer", self.other, User.Role.DEALER)

    def post_lines(self, sheet, readings, action="save"):
        lines = list(sheet.lines.select_related("nozzle").order_by("product__category", "nozzle__code"))
        data = {"lines-TOTAL_FORMS": len(lines), "lines-INITIAL_FORMS": len(lines),
                "lines-MIN_NUM_FORMS": 0, "lines-MAX_NUM_FORMS": 1000, "sheet-notes": "", "action": action}
        for i, line in enumerate(lines):
            closing, testing = readings[line.nozzle.code]
            data.update({f"lines-{i}-id": line.pk, f"lines-{i}-closing_reading": closing,
                         f"lines-{i}-testing_litres": testing, f"lines-{i}-notes": ""})
        return self.client.post(reverse("sales:sheet_edit", args=[sheet.pk]), data)

    def test_complete_workflow_manager_entry_to_dealer_approval_and_report(self):
        self.client.force_login(self.manager)
        response = self.client.post(reverse("sales:sheet_create"), {"business_date": TODAY, "shift": self.morning.pk})
        sheet = DailySalesSheet.objects.get()
        self.assertRedirects(response, reverse("sales:sheet_edit", args=[sheet.pk]))

        response = self.post_lines(sheet, {"N1": ("480", "2"), "N2": ("1100", "0")}, action="submit")
        self.assertRedirects(response, sheet.get_absolute_url())
        sheet.refresh_from_db()
        self.assertEqual(sheet.status, Status.SUBMITTED)
        page = self.client.get(sheet.get_absolute_url())
        self.assertContains(page, "₹1,800.00")
        self.assertContains(page, "18.00")
        self.assertNotContains(page, "Approve sheet")  # manager has no approve button

        self.client.force_login(self.dealer)
        self.assertContains(self.client.get(reverse("sales:approvals")), "Review")
        self.client.post(reverse("sales:sheet_approve", args=[sheet.pk]))
        sheet.refresh_from_db()
        self.assertEqual(sheet.status, Status.APPROVED)

        report = self.client.get(reverse("sales:summary"), {
            "group_by": "product", "date_from": TODAY, "date_to": TODAY,
        })
        self.assertContains(report, "Petrol (MS)")
        self.assertEqual(report.context["totals"]["testing_litres"], D("2"))
        self.assertEqual(report.context["totals"]["net_sales_litres"], D("118"))

    def test_invalid_entry_is_not_saved(self):
        sheet = self.start()
        self.client.force_login(self.manager)
        response = self.post_lines(sheet, {"N1": ("450", "0"), "N2": ("1100", "200")})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "cannot be less than the opening reading")
        self.assertContains(response, "cannot be more than the total nozzle delivery")
        self.assertIsNone(self.line(sheet, "N1").closing_reading)

    def test_opening_reading_and_price_cannot_be_posted(self):
        sheet = self.start()
        self.client.force_login(self.manager)
        line = self.line(sheet, "N1")
        data = {"lines-TOTAL_FORMS": 1, "lines-INITIAL_FORMS": 1, "lines-MIN_NUM_FORMS": 0, "lines-MAX_NUM_FORMS": 1000,
                "lines-0-id": line.pk, "lines-0-closing_reading": "480", "lines-0-testing_litres": "0",
                "lines-0-opening_reading": "0", "lines-0-price_per_litre": "1", "sheet-notes": "", "action": "save"}
        self.client.post(reverse("sales:sheet_edit", args=[sheet.pk]), data)
        line.refresh_from_db()
        self.assertEqual((line.opening_reading, line.price_per_litre, line.total_delivery), (D("460"), D("100.00"), D("20")))

    def test_line_of_another_sheet_cannot_be_posted(self):
        sheet = self.approved_sheet()
        other_line = self.line(sheet, "N1")
        evening = self.start(self.evening)
        self.client.force_login(self.manager)
        data = {"lines-TOTAL_FORMS": 1, "lines-INITIAL_FORMS": 1, "lines-MIN_NUM_FORMS": 0, "lines-MAX_NUM_FORMS": 1000,
                "lines-0-id": other_line.pk, "lines-0-closing_reading": "999", "lines-0-testing_litres": "0",
                "sheet-notes": "", "action": "save"}
        self.client.post(reverse("sales:sheet_edit", args=[evening.pk]), data)
        other_line.refresh_from_db()
        self.assertEqual(other_line.closing_reading, D("480"))

    def test_other_tenant_cannot_see_or_act_on_sheets(self):
        sheet = self.start()
        self.client.force_login(self.other_dealer)
        for name in ("sales:sheet_detail", "sales:sheet_edit", "sales:correction_create"):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name, args=[sheet.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("sales:sheet_approve", args=[sheet.pk])).status_code, 404)
        self.assertNotContains(self.client.get(reverse("sales:sheet_list")), "Ganesh")

    def test_manager_only_sees_assigned_outlets(self):
        other_outlet = make_outlet(self.business, "SGF-02")
        hidden = DailySalesSheet.objects.create(
            business=self.business, outlet=other_outlet, business_date=TODAY, entered_by=self.dealer,
            shift=Shift.objects.create(business=self.business, outlet=other_outlet, name="Day", start_time=time(6),
                                       end_time=time(6), sort_order=1),
            shift_sort_order=1,
        )
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(reverse("sales:sheet_detail", args=[hidden.pk])).status_code, 404)
        form = self.client.get(reverse("sales:sheet_create")).context["form"]
        self.assertNotIn(hidden.shift, form.fields["shift"].queryset)

    def test_manager_cannot_open_approvals_or_approve(self):
        sheet = self.start()
        self.fill(sheet, {"N1": ("480", "2"), "N2": ("1100", "0")})
        services.submit_sheet(sheet, user=self.manager)
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(reverse("sales:approvals")).status_code, 403)
        self.assertEqual(self.client.post(reverse("sales:sheet_approve", args=[sheet.pk])).status_code, 403)
        sheet.refresh_from_db()
        self.assertEqual(sheet.status, Status.SUBMITTED)

    def test_correction_request_and_approval_through_screens(self):
        sheet = self.approved_sheet()
        line = self.line(sheet, "N1")
        self.client.force_login(self.manager)
        data = {"reason": "Testing was 4 L, not 2 L"}
        for item in sheet.lines.all():
            data.update({f"closing_{item.pk}": item.closing_reading, f"testing_{item.pk}": item.testing_litres,
                         f"price_{item.pk}": item.price_per_litre})
        data[f"testing_{line.pk}"] = "4"
        self.assertRedirects(self.client.post(reverse("sales:correction_create", args=[sheet.pk]), data),
                             sheet.get_absolute_url())
        correction = SalesCorrection.objects.get()
        self.client.force_login(self.dealer)
        self.client.post(reverse("sales:correction_review", args=[correction.pk]), {"action": "approve", "note": ""})
        line.refresh_from_db()
        self.assertEqual(line.net_sales_litres, D("16"))
        self.assertContains(self.client.get(sheet.get_absolute_url()), "Testing was 4 L")

    def test_list_totals_not_multiplied_by_corrections(self):
        sheet = self.approved_sheet()
        line = self.line(sheet, "N1")
        for testing in ("3", "4"):
            correction = services.request_correction(sheet, user=self.manager, reason="r",
                                                     changes=[(line, line.closing_reading, D(testing), line.price_per_litre)])
            services.reject_correction(correction, user=self.dealer, note="no")
        services.request_correction(sheet, user=self.manager, reason="r",
                                    changes=[(line, line.closing_reading, D("5"), line.price_per_litre)])
        self.client.force_login(self.dealer)
        listed = self.client.get(reverse("sales:sheet_list")).context["sheets"][0]
        self.assertEqual(listed.total_delivery, D("120"))
        self.assertTrue(listed.pending_corrections)
