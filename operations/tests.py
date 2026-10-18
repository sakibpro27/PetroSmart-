from datetime import date, timedelta
from decimal import Decimal as D

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import SimpleTestCase
from django.urls import reverse

from accounts.models import User
from audit.models import AuditLog
from sales.tests import TODAY, SalesTestCase
from tenants.test_utils import make_business, make_outlet, make_user

from . import services
from .models import Attendance, Employee, Reminder, ShopItem, StockMovement, add_months


class AddMonthsTests(SimpleTestCase):
    def test_add_months(self):
        self.assertEqual(add_months(date(2026, 1, 31), 1), date(2026, 2, 28))
        self.assertEqual(add_months(date(2028, 1, 31), 1), date(2028, 2, 29))
        self.assertEqual(add_months(date(2026, 11, 15), 3), date(2027, 2, 15))
        self.assertEqual(add_months(date(2026, 6, 30), 12), date(2027, 6, 30))


class OperationsTestCase(SalesTestCase):
    def setUp(self):
        super().setUp()
        self.oil = ShopItem.objects.create(business=self.business, name="20W-40 engine oil 1 L",
                                           selling_price=D("350"), reorder_level=D("5"))
        self.other = make_business("Om Sai Petroleum")
        self.other_dealer = make_user("omsai.dealer", self.other, User.Role.DEALER)

    def move(self, kind, quantity, price=""):
        self.client.force_login(self.manager)
        return self.client.post(reverse("operations:movement_create"), {
            "item": self.oil.pk, "outlet": self.outlet.pk, "moved_on": TODAY, "kind": kind,
            "quantity": quantity, "unit_price": price, "reference": "", "notes": "",
        })


class InventoryTests(OperationsTestCase):
    def test_stock_on_hand_from_movements(self):
        self.move("OPENING", "10")
        self.move("PURCHASE", "12", "300")
        response = self.move("SALE", "4", "350")
        self.assertRedirects(response, reverse("operations:inventory"))
        self.assertEqual(self.oil.stock_at(self.outlet), D("18"))
        sale = StockMovement.objects.get(kind="SALE")
        self.assertEqual((sale.quantity, sale.amount), (D("-4"), D("1400")))

    def test_cannot_sell_more_than_in_stock(self):
        self.move("OPENING", "3")
        response = self.move("SALE", "5", "350")
        self.assertContains(response, "Only 3.00")
        self.assertEqual(self.oil.stock_at(self.outlet), D("3"))

    def test_negative_adjustment_cannot_go_below_zero(self):
        self.move("OPENING", "2")
        response = self.move("ADJUSTMENT", "-3")
        self.assertContains(response, "in stock")

    def test_low_stock_flag_and_shop_sales_separate(self):
        self.move("OPENING", "6")
        self.move("SALE", "2", "350")
        rows = services.stock_table(self.dealer, [self.outlet])
        self.assertTrue(rows[0]["low"])  # 4 on hand, reorder level 5
        self.assertEqual(services.shop_sales(self.dealer, [self.outlet], TODAY, TODAY), D("700"))

    def test_manager_cannot_manage_items_and_other_tenant_isolated(self):
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(reverse("operations:item_create")).status_code, 403)
        self.client.force_login(self.other_dealer)
        self.assertEqual(self.client.get(reverse("operations:item_edit", args=[self.oil.pk])).status_code, 404)
        response = self.client.post(reverse("operations:movement_create"), {
            "item": self.oil.pk, "outlet": self.outlet.pk, "moved_on": TODAY, "kind": "OPENING", "quantity": "5"})
        self.assertIn("item", response.context["form"].errors)
        self.assertIn("outlet", response.context["form"].errors)


class AttendanceTests(OperationsTestCase):
    def setUp(self):
        super().setUp()
        self.ravi = Employee.objects.create(business=self.business, outlet=self.outlet, name="Ravi")
        self.suresh = Employee.objects.create(business=self.business, outlet=self.outlet, name="Suresh")

    def post(self, rows, employee_ids=None):
        data = {"business_date": TODAY, "shift": self.morning.pk, "att-TOTAL_FORMS": len(rows),
                "att-INITIAL_FORMS": len(rows), "att-MIN_NUM_FORMS": 0, "att-MAX_NUM_FORMS": 1000}
        for i, (employee_id, status) in enumerate(rows):
            data.update({f"att-{i}-employee_id": employee_id, f"att-{i}-status": status, f"att-{i}-duty": ""})
        return self.client.post(reverse("operations:attendance"), data)

    def test_record_and_update_attendance(self):
        self.client.force_login(self.manager)
        self.post([(self.ravi.pk, "PRESENT"), (self.suresh.pk, "ABSENT")])
        self.post([(self.ravi.pk, "PRESENT"), (self.suresh.pk, "LEAVE")])
        self.assertEqual(Attendance.objects.count(), 2)
        self.assertEqual(Attendance.objects.get(employee=self.suresh).status, "LEAVE")
        page = self.client.get(reverse("operations:attendance"), {"business_date": TODAY, "shift": self.morning.pk})
        self.assertContains(page, "Suresh")

    def test_other_outlet_or_tenant_employee_refused(self):
        foreign = Employee.objects.create(business=self.other, outlet=make_outlet(self.other, "OSP-01"), name="X")
        self.client.force_login(self.manager)
        self.post([(foreign.pk, "PRESENT")])
        self.assertFalse(Attendance.objects.exists())

    def test_employees_are_not_logins(self):
        self.assertFalse(User.objects.filter(username__iexact="ravi").exists())


class ReminderTests(OperationsTestCase):
    def test_due_and_overdue_listed_and_repeat_scheduled(self):
        overdue = Reminder.objects.create(business=self.business, outlet=self.outlet, title="Dispenser stamping",
                                          category="CALIBRATION", due_date=TODAY - timedelta(days=3), repeat_months=12)
        Reminder.objects.create(business=self.business, title="Insurance", due_date=TODAY + timedelta(days=200))
        self.assertEqual(list(services.due_reminders(self.dealer)), [overdue])
        following = services.complete_reminder(overdue, user=self.dealer, note="Stamped by inspector")
        self.assertEqual(following.due_date, add_months(overdue.due_date, 12))
        self.assertFalse(services.due_reminders(self.dealer).exists())
        self.assertTrue(AuditLog.objects.filter(description__startswith="Completed reminder").exists())

    def test_only_dealer_completes_and_isolation(self):
        reminder = Reminder.objects.create(business=self.business, title="Fire extinguisher refill", due_date=TODAY)
        with self.assertRaises(PermissionDenied):
            services.complete_reminder(reminder, user=self.manager)
        self.assertEqual(list(services.due_reminders(self.other_dealer)), [])
        self.client.force_login(self.other_dealer)
        self.assertEqual(self.client.post(reverse("operations:reminder_complete", args=[reminder.pk])).status_code, 404)

    def test_dashboard_shows_due_reminder(self):
        Reminder.objects.create(business=self.business, title="Trade licence renewal", due_date=TODAY + timedelta(days=5))
        self.client.force_login(self.manager)
        self.assertContains(self.client.get(reverse("core:home")), "Trade licence renewal")


class AuditLogScreenTests(OperationsTestCase):
    def test_dealer_sees_own_business_log_only(self):
        AuditLog.record(AuditLog.Action.CREATE, "Ganesh event", user=self.dealer)
        AuditLog.record(AuditLog.Action.CREATE, "Om Sai event", user=self.other_dealer)
        self.client.force_login(self.dealer)
        page = self.client.get(reverse("operations:audit_log"), {"q": "event"})
        self.assertContains(page, "Ganesh event")
        self.assertNotContains(page, "Om Sai event")

    def test_manager_cannot_open_audit_log(self):
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(reverse("operations:audit_log")).status_code, 403)

    def test_all_pages_render(self):
        self.client.force_login(self.dealer)
        for name in ("inventory", "movement_create", "item_list", "item_create", "employee_list", "employee_create",
                     "attendance", "reminder_list", "reminder_create", "audit_log"):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(f"operations:{name}")).status_code, 200)
