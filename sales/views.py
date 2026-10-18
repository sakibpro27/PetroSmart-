"""
Daily Sales screens. Views only collect input and show results; the rules
live in sales.services and the formulas in sales.calculations.
"""

from collections import OrderedDict
from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.functional import cached_property
from django.views import View
from django.views.generic import DetailView, FormView, ListView, TemplateView

from finance import services as finance_services
from finance.forms import CollectionLineFormSet, CreditSaleFormSet
from finance.models import ShiftCollection
from tenants.permissions import BusinessMemberRequiredMixin, DealerRequiredMixin

from . import services
from .forms import CorrectionRequestForm, LineFormSet, NewSheetForm, ReviewNoteForm, SheetNotesForm, SummaryFilterForm
from .models import DailySalesSheet, SalesCorrection
from .reports import GROUPINGS, sales_summary, summary_lines

Status = DailySalesSheet.Status


def _messages_from(error):
    return error.messages if isinstance(error, ValidationError) else [str(error)]


class SheetMixin(BusinessMemberRequiredMixin):
    """Looks a sheet up only among the sheets this user may see (otherwise 404)."""

    @cached_property
    def sheet(self):
        return get_object_or_404(
            services.sheets_for(self.request.user).select_related("outlet", "shift"), pk=self.kwargs["pk"]
        )


# --- List and create ---------------------------------------------------------


class SheetListView(BusinessMemberRequiredMixin, ListView):
    template_name = "sales/sheet_list.html"
    context_object_name = "sheets"
    paginate_by = 25

    def get_queryset(self):
        sheets = services.sheets_for(self.request.user).select_related("outlet", "shift", "entered_by")
        params = self.request.GET
        if params.get("outlet", "").isdigit():
            sheets = sheets.filter(outlet_id=params["outlet"])
        if params.get("status") in Status.values:
            sheets = sheets.filter(status=params["status"])
        return sheets.annotate(
            total_delivery=Sum("lines__total_delivery"),
            testing_litres=Sum("lines__testing_litres"),
            net_sales_litres=Sum("lines__net_sales_litres"),
            sales_value=Sum("lines__sales_value"),
            # A subquery, not a join: joining corrections would multiply the sums above.
            pending_corrections=Exists(
                SalesCorrection.objects.filter(sheet=OuterRef("pk"), status=SalesCorrection.Status.PENDING)
            ),
        ).order_by("-business_date", "-shift_sort_order", "outlet__code")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            outlets=services.viewable_outlets(self.request.user),
            statuses=Status.choices,
            selected_outlet=self.request.GET.get("outlet", ""),
            selected_status=self.request.GET.get("status", ""),
        )
        return context


class SheetCreateView(BusinessMemberRequiredMixin, FormView):
    template_name = "crud/form.html"
    form_class = NewSheetForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            page_title="Start a Daily Sales sheet",
            page_subtitle="Opening readings and prices are filled in for you.",
            cancel_url=reverse("sales:sheet_list"),
        )
        return context

    def form_valid(self, form):
        try:
            sheet = services.create_sheet(
                user=self.request.user, shift=form.cleaned_data["shift"],
                business_date=form.cleaned_data["business_date"], request=self.request,
            )
        except ValidationError as error:
            for message in _messages_from(error):
                form.add_error(None, message)
            return self.form_invalid(form)
        messages.success(self.request, f"Sheet started for {sheet}. Enter the closing readings.")
        return redirect("sales:sheet_edit", pk=sheet.pk)


# --- Entry -------------------------------------------------------------------


class SheetEditView(SheetMixin, View):
    template_name = "sales/sheet_edit.html"

    @cached_property
    def collection(self):
        """The payment breakdown (cash, UPI, card, credit) recorded for this sheet's shift."""
        return finance_services.collection_for_sheet(self.sheet, self.request.user)

    def _forms(self, data=None):
        lines = self.sheet.lines.select_related("nozzle__dispenser", "product").order_by("product__category", "nozzle__code")
        forms = {
            "formset": LineFormSet(data, queryset=lines, prefix="lines"),
            "notes_form": SheetNotesForm(data, instance=self.sheet, prefix="sheet"),
            "payment_lines": None, "credit_sales": None,
        }
        # The payment section is optional on save: only process it if it was on the submitted page.
        if data is not None and "methods-TOTAL_FORMS" not in data:
            return forms
        collection = self.collection
        if collection is not None and finance_services.can_edit_collection(collection, self.request.user):
            forms["payment_lines"] = CollectionLineFormSet(
                data, queryset=collection.lines.select_related("method").order_by("method__sort_order"), prefix="methods")
            forms["credit_sales"] = CreditSaleFormSet(
                data, queryset=collection.credit_sales.select_related("customer"), prefix="credit",
                form_kwargs={"business": collection.business})
        return forms

    def _render(self, forms):
        collection = self.collection  # created on first opening, so the payment fields can be shown
        return render(self.request, self.template_name, {
            "sheet": self.sheet, **forms, "collection": collection,
            "payment_figures": finance_services.collection_figures(collection) if collection else None,
        })

    def get(self, request, *args, **kwargs):
        if not services.can_edit(self.sheet, request.user):
            return redirect(self.sheet)
        return self._render(self._forms())

    def post(self, request, *args, **kwargs):
        if not services.can_edit(self.sheet, request.user):
            messages.error(request, "This sheet can no longer be edited.")
            return redirect(self.sheet)
        forms = self._forms(request.POST)
        if not all(form.is_valid() for form in forms.values() if form is not None):
            messages.error(request, "Some entries need attention. Nothing was saved.")
            return self._render(forms)
        try:
            with transaction.atomic():
                services.save_draft(self.sheet, forms["formset"], forms["notes_form"], user=request.user, request=request)
                if forms["payment_lines"] is not None:
                    finance_services.save_collection(self.collection, forms["payment_lines"], forms["credit_sales"],
                                                     None, user=request.user, request=request)
            over_limit = finance_services.customers_over_limit(self.collection) if forms["payment_lines"] is not None else []
            for customer in over_limit:
                messages.warning(request, f"{customer.name} is now over their credit limit of ₹{customer.credit_limit}.")
            if request.POST.get("action") == "submit":
                services.submit_sheet(self.sheet, user=request.user, request=request)
                messages.success(request, f"{self.sheet} submitted to the Dealer for approval.")
                return redirect(self.sheet)
        except ValidationError as error:
            for message in _messages_from(error):
                messages.error(request, message)
            return redirect("sales:sheet_edit", pk=self.sheet.pk)
        messages.success(request, "Draft saved.")
        return redirect("sales:sheet_edit", pk=self.sheet.pk)


# --- Read-only view with review actions --------------------------------------


def product_totals(lines):
    totals = OrderedDict()
    for line in lines:
        bucket = totals.setdefault(line.product.name, {
            "total_delivery": Decimal("0"), "testing_litres": Decimal("0"),
            "net_sales_litres": Decimal("0"), "sales_value": Decimal("0"),
        })
        for key in bucket:
            bucket[key] += getattr(line, key) or Decimal("0")
    return totals


class SheetDetailView(SheetMixin, DetailView):
    template_name = "sales/sheet_detail.html"
    context_object_name = "sheet"

    def get_object(self, queryset=None):
        return self.sheet

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user, sheet = self.request.user, self.sheet
        lines = list(sheet.lines.select_related("nozzle__dispenser", "product").order_by("product__category", "nozzle__code"))
        corrections = sheet.corrections.select_related("requested_by", "reviewed_by").prefetch_related("lines__line__nozzle")
        pending = next((c for c in corrections if c.status == SalesCorrection.Status.PENDING), None)
        totals = product_totals(lines)
        collection = ShiftCollection.objects.filter(outlet=sheet.outlet, business_date=sheet.business_date,
                                                    shift=sheet.shift).first()
        if collection is not None:
            context.update(
                collection=collection,
                payment_figures=finance_services.collection_figures(collection),
                payment_lines=collection.lines.select_related("method").order_by("method__sort_order"),
                credit_sales=collection.credit_sales.select_related("customer"),
            )
        context.update(
            lines=lines,
            product_totals=totals,
            grand_total={key: sum(t[key] for t in totals.values()) for key in
                         ("total_delivery", "testing_litres", "net_sales_litres", "sales_value")},
            corrections=corrections,
            pending_correction=pending,
            can_edit=services.can_edit(sheet, user),
            can_review=user.is_dealer and sheet.status == Status.SUBMITTED,
            can_return=user.is_dealer and sheet.status == Status.SUBMITTED and sheet.is_latest,
            can_request_correction=sheet.status == Status.APPROVED and pending is None
            and user.accessible_outlets().filter(pk=sheet.outlet_id).exists(),
            note_form=ReviewNoteForm(),
        )
        return context


class SheetApproveView(DealerRequiredMixin, SheetMixin, View):
    def post(self, request, *args, **kwargs):
        try:
            services.approve_sheet(self.sheet, user=request.user, request=request)
            messages.success(request, f"{self.sheet} approved.")
        except ValidationError as error:
            for message in _messages_from(error):
                messages.error(request, message)
        return redirect(self.sheet)


class SheetReturnView(DealerRequiredMixin, SheetMixin, View):
    def post(self, request, *args, **kwargs):
        form = ReviewNoteForm(request.POST)
        note = form.cleaned_data["note"] if form.is_valid() else ""
        try:
            services.return_sheet(self.sheet, user=request.user, note=note, request=request)
            messages.success(request, f"{self.sheet} sent back to the manager.")
        except ValidationError as error:
            for message in _messages_from(error):
                messages.error(request, message)
        return redirect(self.sheet)


# --- Corrections ---------------------------------------------------------------


class CorrectionCreateView(SheetMixin, FormView):
    template_name = "sales/correction_form.html"
    form_class = CorrectionRequestForm

    def get(self, request, *args, **kwargs):
        if self.sheet.status != Status.APPROVED:
            messages.info(request, "Only approved sheets need a correction. Draft sheets can be edited directly.")
            return redirect(self.sheet)
        return super().get(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["sheet"] = self.sheet
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["sheet"] = self.sheet
        return context

    def form_valid(self, form):
        try:
            services.request_correction(
                self.sheet, user=self.request.user, reason=form.cleaned_data["reason"],
                changes=form.changes, request=self.request,
            )
        except ValidationError as error:
            for message in _messages_from(error):
                form.add_error(None, message)
            return self.form_invalid(form)
        messages.success(self.request, "Correction sent to the Dealer for approval. The approved figures stay unchanged until then.")
        return redirect(self.sheet)


class CorrectionReviewView(DealerRequiredMixin, View):
    def post(self, request, pk):
        correction = get_object_or_404(
            SalesCorrection.objects.for_business(request.business).select_related("sheet"), pk=pk
        )
        form = ReviewNoteForm(request.POST)
        note = form.cleaned_data["note"] if form.is_valid() else ""
        try:
            if request.POST.get("action") == "approve":
                services.approve_correction(correction, user=request.user, note=note, request=request)
                messages.success(request, "Correction approved. The figures and history have been updated.")
            else:
                services.reject_correction(correction, user=request.user, note=note, request=request)
                messages.success(request, "Correction rejected. The approved figures are unchanged.")
        except ValidationError as error:
            for message in _messages_from(error):
                messages.error(request, message)
        return redirect(correction.sheet)


# --- Dealer approvals and summaries ------------------------------------------


class ApprovalQueueView(DealerRequiredMixin, TemplateView):
    template_name = "sales/approvals.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        business = self.request.business
        context["sheets"] = (
            DailySalesSheet.objects.for_business(business).filter(status=Status.SUBMITTED)
            .select_related("outlet", "shift", "submitted_by")
            .annotate(net_sales_litres=Sum("lines__net_sales_litres"), testing_litres=Sum("lines__testing_litres"),
                      sales_value=Sum("lines__sales_value"),
                      meter_resets=Count("lines", filter=Q(lines__meter_reset=True)))
            .order_by("business_date", "shift_sort_order")
        )
        context["corrections"] = (
            SalesCorrection.objects.for_business(business).filter(status=SalesCorrection.Status.PENDING)
            .select_related("sheet__outlet", "sheet__shift", "requested_by")
        )
        return context


class SalesSummaryView(BusinessMemberRequiredMixin, TemplateView):
    template_name = "sales/summary.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        form = SummaryFilterForm(self.request.GET or None, user=user)
        context["form"] = form
        if self.request.GET and not form.is_valid():
            return context
        data = form.cleaned_data if self.request.GET else {
            name: form.fields[name].initial for name in form.fields
        }
        outlets = services.viewable_outlets(user)
        if data.get("outlet"):
            outlets = outlets.filter(pk=data["outlet"].pk)
        statuses = [Status.APPROVED, Status.SUBMITTED] if data.get("include_submitted") else [Status.APPROVED]
        lines = summary_lines(
            business=user.business, outlets=outlets, date_from=data["date_from"], date_to=data["date_to"],
            statuses=statuses, product=data.get("product"),
        )
        rows, totals = sales_summary(lines, data["group_by"])
        context.update(rows=rows, totals=totals, group_label=GROUPINGS[data["group_by"]][0], filters=data)
        return context
