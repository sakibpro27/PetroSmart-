from django.urls import path

from . import views

app_name = "sales"

urlpatterns = [
    path("", views.SheetListView.as_view(), name="sheet_list"),
    path("new/", views.CardFormView.as_view(), name="sheet_create"),
    path("summary/", views.SalesSummaryView.as_view(), name="summary"),
    path("<int:pk>/", views.SheetDetailView.as_view(), name="sheet_detail"),
    path("<int:pk>/edit/", views.CardFormView.as_view(), name="sheet_edit"),
    path("<int:pk>/delete/", views.SheetDeleteView.as_view(), name="sheet_delete"),
    path("<int:pk>/correction/", views.CorrectionCreateView.as_view(), name="correction_create"),
]
