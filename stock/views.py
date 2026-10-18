"""Tank stock and fuel receipt screens. Rules live in stock.services."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Count, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.functional import cached_property
from django.views import View
from django.views.generic import FormView, ListView, TemplateView

from sales.services import viewable_outlets
from tenants.permissions import BusinessMemberRequiredMixin

from . import services
from .forms import ReceiptForm, StockNotesForm, StockPickForm, TankRowFormSet
from .models import TankReceipt


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
        outlets = viewable_outlets(self.request.user)
        context["outlets"] = outlets
        context["selected_outlet"] = self.request.GET.get("outlet", "")
        if context["selected_outlet"].isdigit():
            outlets = outlets.filter(pk=context["selected_outlet"])
        context["book"] = services.book_stock_for(outlets)
        return context


class StockSheetFormView(BusinessMemberRequiredMixin, View):
    """New or edit: one page with every tank's figures and its dip reading. Saved in one step."""

    template_name = "stock/sheet_form.html"

    @cached_property
    def sheet(self):
        if "pk" not in self.kwargs:
            return None
        return get_object_or_404(services.stock_sheets_for(self.request.user).select_related("outlet"), pk=self.kwargs["pk"])

    def _target(self, source):
        """(outlet, date, pick form) for a new sheet, from GET or POST data."""
        pick = StockPickForm(source or None, user=self.request.user)
        if pick.is_bound and pick.is_valid():
            return pick.cleaned_data["outlet"], pick.cleaned_data["business_date"], pick
        return None, None, pick

    def _render(self, pick, outlet, day, rows, formset, notes_form, errors=()):
        return render(self.request, self.template_name, {
            "sheet": self.sheet, "pick": pick, "outlet": outlet, "day": day,
            "rows": list(zip(formset.forms, rows)) if formset is not None else [],
            "formset": formset, "notes_form": notes_form, "load_errors": errors,
            "problems": services.day_problems(outlet, day) if outlet else [],
        })

    def _load(self, outlet, day):
        try:
            return services.tank_rows(outlet, day, self.sheet), []
        except ValidationError as error:
            return [], error.messages

    def get(self, request, *args, **kwargs):
        if self.sheet is not None:
            if not services.can_change(self.sheet, request.user):
                messages.info(request, "Only the latest stock sheet at an outlet can be edited.")
                return redirect(self.sheet)
            outlet, day, pick = self.sheet.outlet, self.sheet.business_date, None
        else:
            outlet, day, pick = self._target(request.GET)
        rows, errors = self._load(outlet, day) if outlet else ([], [])
        measured = {line.tank_id: line for line in self.sheet.lines.all()} if self.sheet else {}
        initial = [{"tank_id": row["tank"].pk,
                    "measured_closing": measured[row["tank"].pk].measured_closing if row["tank"].pk in measured else None,
                    "notes": measured[row["tank"].pk].notes if row["tank"].pk in measured else ""} for row in rows]
        formset = TankRowFormSet(initial=initial, prefix="tanks")
        notes = StockNotesForm(initial={"notes": self.sheet.notes if self.sheet else ""})
        return self._render(pick, outlet, day, rows, formset, notes, errors)

    def post(self, request, *args, **kwargs):
        if self.sheet is not None:
            outlet, day, pick = self.sheet.outlet, self.sheet.business_date, None
        else:
            outlet, day, pick = self._target(request.POST)
        if outlet is None:
            messages.error(request, "Choose the outlet and date first.")
            return redirect("stock:sheet_create")
        rows, errors = self._load(outlet, day)
        formset = TankRowFormSet(request.POST, prefix="tanks")
        notes = StockNotesForm(request.POST)
        if errors or not (formset.is_valid() and notes.is_valid()):
            messages.error(request, "Some entries need attention. Nothing was saved.")
            return self._render(pick, outlet, day, rows, formset, notes, errors)
        entries = {form.cleaned_data["tank_id"]: (form.cleaned_data["measured_closing"], form.cleaned_data["notes"])
                   for form in formset.forms}
        try:
            sheet = services.save_stock_sheet(user=request.user, outlet=outlet, business_date=day, entries=entries,
                                              notes=notes.cleaned_data["notes"], sheet=self.sheet, request=request)
        except ValidationError as error:
            _show_errors(request, error)
            return self._render(pick, outlet, day, rows, formset, notes)
        messages.success(request, f"{sheet} saved.")
        return redirect(sheet)


class StockSheetDetailView(StockSheetMixin, TemplateView):
    template_name = "stock/sheet_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        sheet = self.sheet
        context.update(
            sheet=sheet,
            lines=sheet.lines.select_related("tank", "product"),
            receipts=TankReceipt.objects.filter(outlet=sheet.outlet, received_on=sheet.business_date).select_related("tank"),
            can_change=services.can_change(sheet, self.request.user),
            stale_tanks=services.stale_tanks(sheet),
        )
        return context


class StockSheetDeleteView(StockSheetMixin, View):
    def post(self, request, *args, **kwargs):
        try:
            services.delete_stock_sheet(self.sheet, user=request.user, request=request)
        except ValidationError as error:
            _show_errors(request, error)
            return redirect(self.sheet)
        messages.success(request, "Stock sheet deleted. The deletion is recorded in the audit log.")
        return redirect("stock:sheet_list")


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
