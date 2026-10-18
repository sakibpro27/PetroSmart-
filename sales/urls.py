from django.urls import path

from . import views

app_name = "sales"

urlpatterns = [
    path("", views.SheetListView.as_view(), name="sheet_list"),
    path("new/", views.SheetCreateView.as_view(), name="sheet_create"),
    path("approvals/", views.ApprovalQueueView.as_view(), name="approvals"),
    path("summary/", views.SalesSummaryView.as_view(), name="summary"),
    path("<int:pk>/", views.SheetDetailView.as_view(), name="sheet_detail"),
    path("<int:pk>/edit/", views.SheetEditView.as_view(), name="sheet_edit"),
    path("<int:pk>/approve/", views.SheetApproveView.as_view(), name="sheet_approve"),
    path("<int:pk>/return/", views.SheetReturnView.as_view(), name="sheet_return"),
    path("<int:pk>/correction/", views.CorrectionCreateView.as_view(), name="correction_create"),
    path("corrections/<int:pk>/review/", views.CorrectionReviewView.as_view(), name="correction_review"),
]
