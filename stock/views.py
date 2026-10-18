"""Tank stock and fuel receipt screens. Rules live in stock.services."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Count, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.functional import cached_property
from django.views import View
from django.views.generic import DetailView, FormView, ListView

from sales.forms import ReviewNoteForm
from sales.services import viewable_outlets
from tenants.permissions import BusinessMemberRequiredMixin, DealerRequiredMixin

from . import services
from .forms import NewStockSheetForm, ReceiptForm, StockLineFormSet, StockNotesForm
from .models import StockSheet, TankReceipt

Status = StockSheet.Status


def _show_errors(request, error):
    for message in error.messages:
        messages.error(request, message)


class StockSheetMixin(BusinessMemberRequiredMixin):
    @cached_property
    def sheet(self):
        return get_object_or_404(services.stock_sheets_for(self.request.user).select_related("outlet"), pk=self.kwargs["pk"])


class StockSheetListView(BusinessMemberRequiredMixin, ListView):
    template_name = "stock/sheet_list.html"
    context_object_name = "sheets"
    paginate_by = 25

    def get_queryset(self):
        sheets = services.stock_sheets_for(self.request.user).select_related("outlet")
        if self.request.GET.get("outlet", "").isdigit():
            sheets = sheets.filter(outlet_id=self.request.GET["outlet"])
        return sheets.annotate(
            received=Sum("lines__fuel_received"),
            delivery=Sum("lines__total_delivery"),
            variation=Sum("lines__variation"),
            tank_count=Count("lines"),
        ).order_by("-business_date", "outlet__code")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["outlets"] = viewable_outlets(self.request.user)
        context["selected_outlet"] = self.request.GET.get("outlet", "")
        return context


class StockSheetCreateView(BusinessMemberRequiredMixin, FormView):
    template_name = "crud/form.html"
    form_class = NewStockSheetForm

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "user": self.request.user}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(page_title="Start a tank stock sheet",
                       page_subtitle="Record the dip stock of every tank at the end of the business day.",
                       cancel_url=reverse("stock:sheet_list"))
        return context

    def form_valid(self, form):
        try:
            sheet = services.create_stock_sheet(user=self.request.user, outlet=form.cleaned_data["outlet"],
                                                business_date=form.cleaned_data["business_date"], request=self.request)
        except ValidationError as error:
            for message in error.messages:
                form.add_error(None, message)
            return self.form_invalid(form)
        messages.success(self.request, f"{sheet} started. Enter each tank's measured (dip) stock.")
        return redirect("stock:sheet_edit", pk=sheet.pk)


class StockSheetEditView(StockSheetMixin, View):
    template_name = "stock/sheet_edit.html"

    def _forms(self, data=None):
        lines = self.sheet.lines.select_related("tank", "product")
        return StockLineFormSet(data, queryset=lines, prefix="lines"), StockNotesForm(data, instance=self.sheet, prefix="sheet")

    def _render(self, formset, notes_form):
        return render(self.request, self.template_name, {
            "sheet": self.sheet, "formset": formset, "notes_form": notes_form,
            "problems": services.day_problems(self.sheet.outlet, self.sheet.business_date),
        })

    def get(self, request, *args, **kwargs):
        if not services.can_edit(self.sheet, request.user):
            return redirect(self.sheet)
        services.refresh_draft(self.sheet)  # show the latest receipts and sales
        return self._render(*self._forms())

    def post(self, request, *args, **kwargs):
        if not services.can_edit(self.sheet, request.user):
            messages.error(request, "This stock sheet can no longer be edited.")
            return redirect(self.sheet)
        formset, notes_form = self._forms(request.POST)
        if not (formset.is_valid() and notes_form.is_valid()):
            messages.error(request, "Some entries need attention. Nothing was saved.")
            return self._render(formset, notes_form)
        try:
            services.save_draft(self.sheet, formset, notes_form, user=request.user, request=request)
            if request.POST.get("action") == "submit":
                services.submit_stock_sheet(self.sheet, user=request.user, request=request)
                messages.success(request, f"{self.sheet} submitted to the Dealer for approval.")
                return redirect(self.sheet)
        except ValidationError as error:
            _show_errors(request, error)
            return redirect("stock:sheet_edit", pk=self.sheet.pk)
        messages.success(request, "Draft saved.")
        return redirect("stock:sheet_edit", pk=self.sheet.pk)


class StockSheetDetailView(StockSheetMixin, DetailView):
    template_name = "stock/sheet_detail.html"
    context_object_name = "sheet"

    def get_object(self, queryset=None):
        return self.sheet

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        sheet, user = self.sheet, self.request.user
        context.update(
            lines=sheet.lines.select_related("tank", "product"),
            receipts=TankReceipt.objects.filter(outlet=sheet.outlet, received_on=sheet.business_date).select_related("tank"),
            can_edit=services.can_edit(sheet, user),
            can_review=user.is_dealer and sheet.status == Status.SUBMITTED,
            can_return=user.is_dealer and sheet.status == Status.SUBMITTED and sheet.is_latest,
            stale_tanks=services.stale_tanks(sheet) if sheet.status != Status.DRAFT else [],
            note_form=ReviewNoteForm(),
        )
        return context


class StockSheetApproveView(DealerRequiredMixin, StockSheetMixin, View):
    def post(self, request, *args, **kwargs):
        try:
            services.approve_stock_sheet(self.sheet, user=request.user, request=request)
            messages.success(request, f"{self.sheet} approved.")
        except ValidationError as error:
            _show_errors(request, error)
        return redirect(self.sheet)


class StockSheetReturnView(DealerRequiredMixin, StockSheetMixin, View):
    def post(self, request, *args, **kwargs):
        form = ReviewNoteForm(request.POST)
        note = form.cleaned_data["note"] if form.is_valid() else ""
        try:
            services.return_stock_sheet(self.sheet, user=request.user, note=note, request=request)
            messages.success(request, f"{self.sheet} sent back to the manager.")
        except ValidationError as error:
            _show_errors(request, error)
        return redirect(self.sheet)


# --- Fuel receipts ------------------------------------------------------------


class ReceiptListView(BusinessMemberRequiredMixin, ListView):
    template_name = "stock/receipt_list.html"
    context_object_name = "receipts"
    paginate_by = 50

    def get_queryset(self):
        return services.receipts_for(self.request.user).select_related("outlet", "tank__product", "entered_by", "purchase")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        for receipt in context["receipts"]:
            receipt.locked = services.stock_locked(receipt.outlet, receipt.received_on)
        return context


class ReceiptFormView(BusinessMemberRequiredMixin, FormView):
    template_name = "crud/form.html"
    form_class = ReceiptForm

    @cached_property
    def receipt(self):
        if "pk" not in self.kwargs:
            return None
        return get_object_or_404(services.receipts_for(self.request.user), pk=self.kwargs["pk"])

    def get_form_kwargs(self):
        kwargs = {**super().get_form_kwargs(), "user": self.request.user}
        if self.receipt is not None:
            kwargs["instance"] = self.receipt
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(page_title="Edit fuel receipt" if self.receipt else "Record fuel received",
                       page_subtitle="Litres unloaded into a tank from a tanker.",
                       cancel_url=reverse("stock:receipt_list"))
        return context

    def form_valid(self, form):
        try:
            services.save_receipt(form, user=self.request.user, request=self.request)
        except ValidationError as error:
            for message in error.messages:
                form.add_error(None, message)
            return self.form_invalid(form)
        messages.success(self.request, "Fuel receipt saved.")
        return redirect("stock:receipt_list")


class ReceiptDeleteView(BusinessMemberRequiredMixin, View):
    def post(self, request, pk):
        receipt = get_object_or_404(services.receipts_for(request.user).select_related("tank__outlet"), pk=pk)
        try:
            services.delete_receipt(receipt, user=request.user, request=request)
            messages.success(request, "Fuel receipt deleted. The deletion is recorded in the audit log.")
        except ValidationError as error:
            _show_errors(request, error)
        return redirect("stock:receipt_list")
