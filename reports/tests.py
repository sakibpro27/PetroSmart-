from decimal import Decimal as D
from io import BytesIO

from django.urls import reverse
from openpyxl import load_workbook

from accounts.models import User
from finance.models import Expense, ExpenseCategory, PaymentMethod
from sales.tests import TODAY, SalesTestCase
from tenants.test_utils import make_business, make_outlet, make_user

from .definitions import REPORTS


class ReportTestCase(SalesTestCase):
    def setUp(self):
        super().setUp()
        self.card()  # N1: 20 L delivered, 2 L testing, ₹1,800; N2: 100 L, ₹9,000
        # A second tenant with its own approved sales that must never appear.
        self.other = make_business("Om Sai Petroleum")
        self.other_dealer = make_user("omsai.dealer", self.other, User.Role.DEALER)

    def report(self, slug, user=None, **params):
        self.client.force_login(user or self.dealer)
        return self.client.get(reverse("reports:report", args=[slug]),
                               {"date_from": TODAY, "date_to": TODAY, **params})


class DashboardTests(ReportTestCase):
    def test_dashboard_separates_testing_from_sales(self):
        self.client.force_login(self.dealer)
        response = self.client.get(reverse("core:home"))
        dash = response.context["dash"]
        self.assertEqual(dash["sales"]["MS"]["net_sales_litres"], D("18"))
        self.assertEqual(dash["sales"]["MS"]["testing_litres"], D("2"))
        self.assertEqual(dash["totals"]["total_delivery"], D("120"))
        self.assertEqual(dash["totals"]["sales_value"], D("10800.00"))
        self.assertEqual(dash["chart"]["ms"][-1], 18.0)
        self.assertContains(response, "Not counted as sales")

    def test_dashboard_for_manager_and_other_tenant(self):
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(reverse("core:home")).context["dash"]["totals"]["net_sales_litres"], D("118"))
        self.client.force_login(self.other_dealer)
        self.assertEqual(self.client.get(reverse("core:home")).context["dash"]["totals"]["net_sales_litres"], D("0"))

    def test_outlet_filter_ignores_other_tenants_outlet(self):
        foreign = make_outlet(self.other, "OSP-01")
        self.client.force_login(self.dealer)
        dash = self.client.get(reverse("core:home"), {"outlet": foreign.pk}).context["dash"]
        self.assertEqual(dash["totals"]["net_sales_litres"], D("0"))  # filtered to nothing, never to Om Sai's data

    def test_future_day_is_capped_to_today(self):
        self.client.force_login(self.dealer)
        self.assertEqual(self.client.get(reverse("core:home"), {"day": "2999-01-01"}).context["dash"]["day"], TODAY)


class ReportScreenTests(ReportTestCase):
    def test_every_report_renders(self):
        for slug in REPORTS:
            with self.subTest(slug=slug):
                self.assertEqual(self.report(slug).status_code, 200)

    def test_dealer_only_report_forbidden_for_manager(self):
        self.assertEqual(self.report("credit-outstanding", user=self.manager).status_code, 403)
        self.client.force_login(self.manager)
        self.assertNotContains(self.client.get(reverse("reports:index")), "Credit outstanding")

    def test_nozzle_report_totals(self):
        report = self.report("nozzle-readings").context["report"]
        self.assertEqual(report.totals[7:10], [D("120"), D("2"), D("118")])
        self.assertEqual(report.totals[11], D("10800.00"))

    def test_other_tenant_sees_none_of_the_rows(self):
        for slug in ("sales-summary", "nozzle-readings", "tank-stock", "purchases", "shift-cash", "expenses"):
            with self.subTest(slug=slug):
                self.assertEqual(self.report(slug, user=self.other_dealer).context["report"].rows, [])

    def test_unknown_report_is_404(self):
        self.client.force_login(self.dealer)
        self.assertEqual(self.client.get(reverse("reports:report", args=["nope"])).status_code, 404)


class ExportTests(ReportTestCase):
    def test_excel_export_matches_screen(self):
        response = self.report("sales-summary", group_by="product", export="xlsx")
        self.assertEqual(response["Content-Type"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        sheet = load_workbook(BytesIO(response.content)).active
        values = [[cell.value for cell in row] for row in sheet.iter_rows()]
        header = values.index(["Product", "Total nozzle delivery (L)", "Testing (L)", "Net customer sales (L)",
                               "Customer sales value (₹)"])
        body = {row[0]: row for row in values[header + 1:header + 4] if row[0]}
        self.assertEqual(body["Petrol (MS)"][1:], [20.0, 2.0, 18.0, 1800.0])
        self.assertEqual(body["Total"][1:], [120.0, 2.0, 118.0, 10800.0])
        self.assertTrue(any("not counted as customer sales" in str(row[0]) for row in values))

    def test_pdf_export(self):
        Expense.objects.create(business=self.business, outlet=self.outlet, expense_date=TODAY,
                               category=ExpenseCategory.objects.get(business=self.business, name="Rent"),
                               description="Rent <July> & deposit", amount=D("15000"),
                               method=PaymentMethod.objects.get(business=self.business, name="Cash"),
                               entered_by=self.dealer)
        for slug in REPORTS:
            with self.subTest(slug=slug):
                response = self.report(slug, export="pdf")
                self.assertEqual(response["Content-Type"], "application/pdf")
                self.assertTrue(response.content.startswith(b"%PDF"))
                self.assertIn("attachment;", response["Content-Disposition"])

    def test_export_is_audited(self):
        from audit.models import AuditLog
        self.report("tank-stock", export="xlsx")
        self.assertTrue(AuditLog.objects.filter(description__startswith="Exported report 'Tank stock").exists())
