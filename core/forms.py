"""
Shared form building blocks.

* BootstrapFormMixin  - adds Bootstrap classes and accessible error markers.
* AuditedModelForm    - remembers field values so the audit log can record
                        exactly what changed.
* TenantModelForm     - base for every form that saves a dealer's data. The
                        business (and outlet) are set by the server from the
                        logged-in user, never taken from the browser.
"""

from django import forms
from django.core.exceptions import FieldDoesNotExist


class BootstrapFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, (forms.CheckboxInput, forms.CheckboxSelectMultiple)):
                css = "form-check-input"
            elif isinstance(widget, forms.Select):
                css = "form-select"
            else:
                css = "form-control"
            widget.attrs.setdefault("class", css)

    def full_clean(self):
        super().full_clean()
        # Mark invalid fields so they are highlighted and announced by screen readers.
        for name in self.errors:
            if name in self.fields:
                attrs = self.fields[name].widget.attrs
                attrs["class"] = f"{attrs.get('class', '')} is-invalid".strip()
                attrs["aria-invalid"] = "true"
                attrs["aria-describedby"] = f"{self[name].auto_id}-error"


def _plain(value):
    """Turn a field value into something JSON can store in the audit log."""
    if value is None or isinstance(value, bool):
        return value
    return str(value)


class AuditedModelForm(BootstrapFormMixin, forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._original_values = self.audit_values() if self.instance.pk else None

    def audit_values(self):
        """Current values of the model fields shown on this form."""
        values = {}
        for name in self.fields:
            try:
                model_field = self.instance._meta.get_field(name)
            except FieldDoesNotExist:
                continue  # form-only fields such as passwords are never logged
            if model_field.many_to_many:
                related = getattr(self.instance, name).all() if self.instance.pk else []
                values[name] = sorted(str(obj) for obj in related)
            else:
                values[name] = _plain(getattr(self.instance, name, None))
        return values

    def audit_changes(self):
        """
        Call after save(). For a new record: all saved values. For an edit:
        {"field": {"from": old, "to": new}} for each field that changed.
        """
        current = self.audit_values()
        if self._original_values is None:
            return current
        return {
            name: {"from": self._original_values.get(name), "to": value}
            for name, value in current.items()
            if self._original_values.get(name) != value
        }


class TenantModelForm(AuditedModelForm):
    def __init__(self, *args, business, outlet=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.business = business
        self.outlet = outlet
        self.instance.business = business
        if outlet is not None:
            self.instance.outlet = outlet

    def _get_validation_exclusions(self):
        # Django skips uniqueness checks that involve fields not shown on the
        # form. Our "unique per business/outlet" rules use exactly those
        # fields, so include them: the user then sees a clear message
        # instead of a database error.
        exclude = super()._get_validation_exclusions()
        exclude.discard("business")
        if self.outlet is not None:
            exclude.discard("outlet")
        return exclude
