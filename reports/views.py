"""Report screens and their Excel / PDF downloads."""

from datetime import date

from django import forms
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.text import slugify
from django.views import View
from django.views.generic import TemplateView

from audit.models import AuditLog
from core.forms import BootstrapFormMixin
from sales.reports import GROUPINGS
from sales.services import viewable_outlets
from station.models import FuelProduct
from stock.forms import DATE_INPUT
from tenants.permissions import BusinessMemberRequiredMixin

from .definitions import REPORTS
from .exports import to_pdf, to_xlsx


class ReportFilterForm(BootstrapFormMixin, forms.Form):
    date_from = forms.DateField(label="From", widget=DATE_INPUT)
    date_to = forms.DateField(label="To", widget=DATE_INPUT)
    outlet = forms.ModelChoiceField(queryset=None, required=False, empty_label="All outlets")
    group_by = forms.ChoiceField(choices=[(k, label) for k, (label, _) in GROUPINGS.items()], required=False, label="Group by")
    product = forms.ModelChoiceField(queryset=None, required=False, empty_label="All products")
    include_submitted = forms.BooleanField(required=False, label="Include sheets awaiting approval")

    def __init__(self, *args, user, options, **kwargs):
        super().__init__(*args, **kwargs)
        today = timezone.localdate()
        self.fields["date_from"].initial = date(today.year, today.month, 1)
        self.fields["date_to"].initial = today
        self.fields["outlet"].queryset = viewable_outlets(user)
        self.fields["product"].queryset = FuelProduct.objects.for_business(user.business)
        for name in ("group_by", "product", "include_submitted"):
            if name not in options:
                del self.fields[name]

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("date_from") and cleaned.get("date_to") and cleaned["date_from"] > cleaned["date_to"]:
            self.add_error("date_to", "The end date must be on or after the start date.")
        return cleaned

    def params(self):
        if self.is_bound and self.is_valid():
            return dict(self.cleaned_data)
        return {name: field.initial for name, field in self.fields.items()}


class ReportIndexView(BusinessMemberRequiredMixin, TemplateView):
    template_name = "reports/index.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["reports"] = [
            {"slug": slug, **spec} for slug, spec in REPORTS.items()
            if not spec["dealer_only"] or self.request.user.is_dealer
        ]
        return context


class ReportView(BusinessMemberRequiredMixin, View):
    def get(self, request, slug):
        spec = REPORTS.get(slug)
        if spec is None:
            raise Http404("Unknown report.")
        if spec["dealer_only"] and not request.user.is_dealer:
            raise PermissionDenied("Only the Dealer can see this report.")

        form = ReportFilterForm(request.GET or None, user=request.user, options=spec["options"])
        params = form.params()
        outlets = viewable_outlets(request.user)
        if params.get("outlet"):
            outlets = outlets.filter(pk=params["outlet"].pk)
        report = spec["build"](request.user, outlets, params)

        export = request.GET.get("export")
        if export in ("xlsx", "pdf"):
            AuditLog.record(AuditLog.Action.CREATE, f"Exported report '{report.title}' as {export.upper()}",
                            user=request.user, changes={"subtitle": report.subtitle}, request=request)
            filename = f"{slugify(report.title)}-{timezone.localdate():%Y%m%d}.{export}"
            if export == "xlsx":
                content = to_xlsx(report, business=request.business, user=request.user)
                content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            else:
                content = to_pdf(report, business=request.business, user=request.user)
                content_type = "application/pdf"
            response = HttpResponse(content, content_type=content_type)
            response["Content-Disposition"] = f'attachment; filename="{filename}"'
            return response

        query = request.GET.copy()
        query.pop("export", None)
        return render(request, "reports/report.html", {
            "report": report, "form": form, "slug": slug, "spec": spec, "query": query.urlencode(),
            "rows": [list(zip(row, report.columns)) for row in report.rows],
            "totals": list(zip(report.totals, report.columns)) if report.totals else None,
        })
