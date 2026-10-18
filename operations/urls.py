from django.urls import path

from . import views

app_name = "operations"

urlpatterns = [
    path("inventory/", views.InventoryView.as_view(), name="inventory"),
    path("inventory/move/", views.MovementCreateView.as_view(), name="movement_create"),
    path("inventory/items/", views.ItemListView.as_view(), name="item_list"),
    path("inventory/items/new/", views.ItemCreateView.as_view(), name="item_create"),
    path("inventory/items/<int:pk>/edit/", views.ItemUpdateView.as_view(), name="item_edit"),

    path("employees/", views.EmployeeListView.as_view(), name="employee_list"),
    path("employees/new/", views.EmployeeCreateView.as_view(), name="employee_create"),
    path("employees/<int:pk>/edit/", views.EmployeeUpdateView.as_view(), name="employee_edit"),
    path("attendance/", views.AttendanceView.as_view(), name="attendance"),

    path("reminders/", views.ReminderListView.as_view(), name="reminder_list"),
    path("reminders/new/", views.ReminderCreateView.as_view(), name="reminder_create"),
    path("reminders/<int:pk>/edit/", views.ReminderUpdateView.as_view(), name="reminder_edit"),
    path("reminders/<int:pk>/done/", views.ReminderCompleteView.as_view(), name="reminder_complete"),

    path("audit-log/", views.AuditLogView.as_view(), name="audit_log"),
]
