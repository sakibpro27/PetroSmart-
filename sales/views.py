"""
Shift Card screens. Views only collect input and show results; the rules
live in sales.services and the formulas in sales.calculations.
"""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.functional import cached_property
from django.views import View
from django.views.generic import FormView, ListView, TemplateView

from operations.models import ShopItem
from tenants.permissions import BusinessMemberRequiredMixin

from . import services
from .forms import (
    CardHeaderForm, CorrectionRequestForm, CreditFormSet, ExpenseFormSet, LubeFormSet, NozzleFormSet, ReceiptFormSet,
    SummaryFilterForm, filled_rows,
)
from .models import DENOMINATIONS
from .reports import GROUPINGS, sales_summary, summary_lines


def _messages_from(error):
    return error.messages if isinstance(error, ValidationError) else [str(error)]


class SheetMixin(BusinessMemberRequiredMixin):
    """Looks a card up only among the cards this user may see (otherwise 404)."""

    @cached_property
    def sheet(self):
        return get_object_or_404(
            services.sheets_for(self.request.user).select_related("outlet", "shift", "dispenser", "employee"),
            pk=self.kwargs["pk"],
        )


# --- List ------------------------------------------------------------------------------


class SheetListView(BusinessMemberRequiredMixin, ListView):
    template_name = "sales/sheet_list.html"
    context_object_name = "sheets"
    paginate_by = 25

    def get_queryset(self):
        sheets = services.sheets_for(self.request.user).select_related("outlet", "shift", "dispenser", "employee")
        if self.request.GET.get("outlet", "").isdigit():
            sheets = sheets.filter(outlet_id=self.request.GET["outlet"])
        if self.request.GET.get("date"):
            sheets = sheets.filter(business_date=self.request.GET["date"])
        return sheets.annotate(
            total_delivery=Sum("lines__total_delivery"),
            testing_litres=Sum("lines__testing_litres"),
            net_sales_litres=Sum("lines__net_sales_litres"),
        ).order_by("-business_date", "-shift_sort_order", "outlet__code", "pk")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        for sheet in context["sheets"]:
            sheet.figures = services.card_figures(sheet)
            sheet.by_category = services.category_split(sheet.figures["products"])
        context.update(outlets=services.viewable_outlets(self.request.user),
                       selected_outlet=self.request.GET.get("outlet", ""), selected_date=self.request.GET.get("date", ""))
        return context


# --- Create and edit ---------------------------------------------------------------------


class CardFormView(BusinessMemberRequiredMixin, View):
    """The Shift Card. New cards pick date, shift and MPD/DU first; the nozzle rows then load."""

    template_name = "sales/card_form.html"

    @cached_property
    def sheet(self):
        if "pk" not in self.kwargs:
            return None
        return get_object_or_404(services.sheets_for(self.request.user).select_related("outlet", "shift", "dispenser"),
                                 pk=self.kwargs["pk"])

    def _rows_for_edit(self):
        lines = self.sheet.lines.select_related("nozzle__product").order_by("nozzle__code")
        return [{"nozzle": l.nozzle, "opening": l.opening_reading, "price": l.price_per_litre, "line": l} for l in lines]

    def _detail_initial(self):
        s = self.sheet
        if s is None:
            return {}
        return {
            "credit": [{"id": c.pk, "slip_no": c.slip_no, "customer": c.customer, "product": c.product,
                        "litres": c.litres, "amount": c.amount, "vehicle_number": c.vehicle_number}
                       for c in s.credit_sales.select_related("customer", "product")],
            "receipts": [{"customer": r.customer, "amount": r.amount, "reference": r.reference}
                         for r in s.customer_receipts.select_related("customer")],
            "lubes": [{"item": m.item, "quantity": -m.quantity, "rate": m.unit_price} for m in s.lube_sales.select_related("item")],
            "expenses": [{"category": e.category, "description": e.description, "amount": e.amount}
                         for e in s.dsm_expenses.select_related("category")],
        }

    def _detail_formsets(self, data=None):
        business = self.request.business
        initial = self._detail_initial() if data is None else {}
        kwargs = {"form_kwargs": {"business": business}}
        return {
            "credit": CreditFormSet(data, initial=initial.get("credit"), prefix="credit", **kwargs),
            "receipts": ReceiptFormSet(data, initial=initial.get("receipts"), prefix="receipts", **kwargs),
            "lubes": LubeFormSet(data, initial=initial.get("lubes"), prefix="lubes", **kwargs),
            "expenses": ExpenseFormSet(data, initial=initial.get("expenses"), prefix="expenses", **kwargs),
        }

    def _nozzle_formset(self, rows, data=None):
        initial = None
        if data is None:
            initial = []
            for row in rows:
                line = row.get("line")
                values = {"nozzle_id": row["nozzle"].pk}
                if line is not None:
                    values.update(closing_reading=line.closing_reading, testing_litres=line.testing_litres,
                                  meter_reset=line.meter_reset, reading_before_reset=line.reading_before_reset,
                                  reading_after_reset=line.reading_after_reset, notes=line.notes)
                initial.append(values)
        return NozzleFormSet(data, initial=initial, prefix="nozzles", rows=rows)

    def _render(self, header, rows, nozzles, details, load_errors=()):
        return render(self.request, self.template_name, {
            "sheet": self.sheet, "header": header, "nozzles": nozzles, "rows": list(zip(nozzles.forms, rows)),
            "details": details, "load_errors": load_errors,
            # MS first, then HSD: one subtotal row each under the pump readings.
            "card_products": sorted({row["nozzle"].product for row in rows},
                                    key=lambda p: (p.category != "MS", p.code)),
            "money_fields": [(d, header[f"notes_{d}"]) for d in DENOMINATIONS],
            "block_reason": services.change_block_reason(self.sheet) if self.sheet else None,
            # Selling price per product on this card, so credit slips can show litres for an amount.
            "credit_prices": {str(row["nozzle"].product_id): str(row["price"]) for row in rows},
            "lube_prices": {str(pk): str(price) for pk, price in
                            ShopItem.objects.for_business(self.request.business).values_list("pk", "selling_price")},
        })

    # GET ------------------------------------------------------------------------

    def get(self, request, *args, **kwargs):
        user = request.user
        if self.sheet is not None:
            if not services.can_change(self.sheet, user):
                messages.info(request, services.change_block_reason(self.sheet) or "You cannot edit this card.")
                return redirect(self.sheet)
            header = CardHeaderForm(instance=self.sheet, user=user, editing=True, initial={
                "business_date": self.sheet.business_date, "shift": self.sheet.shift, "dispenser": self.sheet.dispenser})
            rows = self._rows_for_edit()
            return self._render(header, rows, self._nozzle_formset(rows), self._detail_formsets())

        # New card: date, shift and MPD/DU come from the address so the nozzle rows can load.
        initial = {key: request.GET[key] for key in ("business_date", "shift", "dispenser") if request.GET.get(key)}
        header = CardHeaderForm(user=user, initial=initial)
        rows, load_errors = [], []
        picker = CardHeaderForm(request.GET, user=user)
        picker.is_valid()
        picked = {key: picker.cleaned_data.get(key) for key in ("business_date", "shift", "dispenser")}
        if all(picked.values()):
            if picked["shift"].outlet_id != picked["dispenser"].outlet_id:
                load_errors = ["The shift and the MPD / DU must belong to the same outlet."]
            else:
                try:
                    rows = services.nozzle_rows(picked["dispenser"], picked["business_date"], picked["shift"])
                except ValidationError as error:
                    load_errors = error.messages
                if not header.initial.get("time_from"):
                    header.initial.update(time_from=picked["shift"].start_time, time_to=picked["shift"].end_time)
        return self._render(header, rows, self._nozzle_formset(rows), self._detail_formsets(), load_errors)

    # POST -----------------------------------------------------------------------

    def post(self, request, *args, **kwargs):
        user = request.user
        editing = self.sheet is not None
        if editing and not services.can_change(self.sheet, user):
            messages.error(request, services.change_block_reason(self.sheet) or "You cannot edit this card.")
            return redirect(self.sheet)
        header = CardHeaderForm(request.POST, instance=self.sheet, user=user, editing=editing,
                                initial={"business_date": self.sheet.business_date, "shift": self.sheet.shift,
                                         "dispenser": self.sheet.dispenser} if editing else None)
        details = self._detail_formsets(request.POST)
        rows, load_errors = [], []
        if editing:
            rows = self._rows_for_edit()
        elif header.is_valid():
            try:
                rows = services.nozzle_rows(header.cleaned_data["dispenser"], header.cleaned_data["business_date"],
                                            header.cleaned_data["shift"])
            except ValidationError as error:
                load_errors = error.messages
        nozzles = self._nozzle_formset(rows, request.POST)

        valid = header.is_valid() and nozzles.is_valid() and all(f.is_valid() for f in details.values()) and not load_errors
        # Each posted row must be for the pump the server expects in that position
        # (protects against a stale page or a forged row).
        if valid and [f.cleaned_data["nozzle_id"] for f in nozzles.forms] != [r["nozzle"].pk for r in rows]:
            load_errors = ["The pump rows do not match this MPD / DU any more. Reload the page and try again."]
            valid = False
        if not valid:
            messages.error(request, "Some entries need attention. Nothing was saved.")
            return self._render(header, rows, nozzles, details, load_errors)

        data = header.cleaned_data
        row_data = [{**form.cleaned_data, "nozzle": row["nozzle"]} for form, row in zip(nozzles.forms, rows)]
        try:
            sheet, warnings = services.save_card(
                user=user, sheet=self.sheet, header=data, rows=row_data,
                credits=[form.cleaned_data for form in details["credit"].forms if form.cleaned_data],
                receipts=filled_rows(details["receipts"], "customer", "amount", "reference"),
                lubes=filled_rows(details["lubes"], "item", "quantity", "rate"),
                expenses=filled_rows(details["expenses"], "category", "description", "amount"),
                request=request,
            )
        except ValidationError as error:
            for message in _messages_from(error):
                messages.error(request, message)
            return self._render(header, rows, nozzles, details, load_errors)
        for warning in warnings:
            messages.warning(request, warning)
        messages.success(request, f"Shift card saved: {sheet}.")
        from stock.services import book_stock  # stock builds on sales

        tanks = {line.tank or line.nozzle.tank for line in sheet.lines.select_related("tank", "nozzle__tank")} - {None}
        if tanks:
            messages.info(request, "Stock now: " + ", ".join(
                f"{tank.code} {book_stock(tank)['stock']:,.2f} L" for tank in sorted(tanks, key=lambda t: t.code)))
        url = sheet.get_absolute_url()
        return redirect(f"{url}?print=1" if request.POST.get("action") == "print" else url)


# --- View, delete, correct ---------------------------------------------------------------


class SheetDetailView(SheetMixin, TemplateView):
    template_name = "sales/sheet_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        sheet, user = self.sheet, self.request.user
        works_here = user.accessible_outlets().filter(pk=sheet.outlet_id).exists()
        context.update(
            sheet=sheet,
            lines=sheet.lines.select_related("nozzle", "product").order_by("nozzle__code"),
            figures=services.card_figures(sheet),
            money_rows=[(d, getattr(sheet, f"notes_{d}"), getattr(sheet, f"notes_{d}") * d) for d in DENOMINATIONS],
            credit_sales=sheet.credit_sales.select_related("customer", "product", "bill"),
            receipts=sheet.customer_receipts.select_related("customer"),
            lube_sales=[{"item": m.item, "quantity": -m.quantity, "rate": m.unit_price, "amount": m.amount}
                        for m in sheet.lube_sales.select_related("item")],
            expenses=sheet.dsm_expenses.select_related("category"),
            corrections=sheet.corrections.select_related("requested_by").prefetch_related("lines__line__nozzle"),
            can_change=works_here and services.change_block_reason(sheet) is None,
            can_correct=works_here and sheet.has_later_readings(),
            print_now=self.request.GET.get("print") == "1",
        )
        return context


class SheetDeleteView(SheetMixin, View):
    def post(self, request, *args, **kwargs):
        try:
            services.delete_card(self.sheet, user=request.user, request=request)
        except ValidationError as error:
            for message in _messages_from(error):
                messages.error(request, message)
            return redirect(self.sheet)
        messages.success(request, "Shift card deleted. The deletion is recorded in the audit log.")
        return redirect("sales:sheet_list")


class CorrectionCreateView(SheetMixin, FormView):
    template_name = "sales/correction_form.html"
    form_class = CorrectionRequestForm

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "sheet": self.sheet}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["sheet"] = self.sheet
        return context

    def form_valid(self, form):
        try:
            services.correct_card(self.sheet, user=self.request.user, reason=form.cleaned_data["reason"],
                                  changes=form.changes, request=self.request)
        except ValidationError as error:
            for message in _messages_from(error):
                form.add_error(None, message)
            return self.form_invalid(form)
        messages.success(self.request, "Correction applied. The old values are kept in the card's history.")
        return redirect(self.sheet)


# --- Summary -------------------------------------------------------------------------------


class SalesSummaryView(BusinessMemberRequiredMixin, TemplateView):
    template_name = "sales/summary.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        form = SummaryFilterForm(self.request.GET or None, user=user)
        context["form"] = form
        if self.request.GET and not form.is_valid():
            return context
        data = form.cleaned_data if self.request.GET else {name: form.fields[name].initial for name in form.fields}
        outlets = services.viewable_outlets(user)
        if data.get("outlet"):
            outlets = outlets.filter(pk=data["outlet"].pk)
        lines = summary_lines(business=user.business, outlets=outlets, date_from=data["date_from"],
                              date_to=data["date_to"], product=data.get("product"))
        rows, totals = sales_summary(lines, data["group_by"])
        context.update(rows=rows, totals=totals, group_label=GROUPINGS[data["group_by"]][0], filters=data)
        return context
