"""
Generate the data dictionary and the ER diagrams straight from the Django
models, so the report always matches the real database schema.

Run from the project folder (with the virtual environment active):

    python documentation/tools/generate_schema_docs.py

Writes:
    documentation/academic/appendix-a-data-dictionary.md
    documentation/diagrams/erd.md
"""

import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.apps import apps  # noqa: E402
from django.db import connection, models  # noqa: E402

# The project's own apps, in the order they are described in the report.
PROJECT_APPS = [
    ("tenants", "Tenants: businesses, outlets and subscriptions"),
    ("accounts", "Accounts: users and roles"),
    ("audit", "Audit log"),
    ("station", "Outlet set-up: products, prices, dispensers, tanks, nozzles, shifts"),
    ("sales", "Shift Cards (Daily Sales)"),
    ("stock", "Tank stock"),
    ("purchases", "Fuel purchases"),
    ("finance", "Customer credit, bills and expenses"),
    ("operations", "Lubricant inventory, employees, reminders"),
]

ACADEMIC = ROOT / "documentation" / "academic"
DIAGRAMS = ROOT / "documentation" / "diagrams"


def description(model):
    doc = (model.__doc__ or "").strip()
    if not doc or doc.startswith(model.__name__ + "("):  # Django's automatic docstring
        return ""
    return " ".join(doc.split("\n\n")[0].split())


def field_type(field):
    db_type = field.db_type(connection) or ""
    if isinstance(field, models.ForeignKey):
        return f"FK → {field.related_model._meta.db_table}"
    if isinstance(field, models.DecimalField):
        return f"Decimal({field.max_digits},{field.decimal_places})"
    if isinstance(field, models.CharField):
        return f"Varchar({field.max_length})"
    if isinstance(field, models.AutoField):
        return "BigInt (auto)"
    return {"integer": "Integer", "bigint": "BigInt", "bool": "Boolean", "date": "Date",
            "datetime": "DateTime", "time": "Time", "text": "Text"}.get(db_type.split("(")[0].lower(),
                                                                    type(field).__name__.replace("Field", ""))


def constraints_for(field):
    notes = []
    if field.primary_key:
        notes.append("PK")
    if field.unique and not field.primary_key:
        notes.append("Unique")
    notes.append("Null" if field.null else "Not null")
    if field.choices:
        notes.append("One of: " + ", ".join(str(value) for value, _ in field.choices))
    if field.has_default() and not callable(field.default):
        default = getattr(field.default, "value", field.default)  # show "TRIAL", not Business.Status.TRIAL
        notes.append(f"Default {default!r}")
    for validator in ([] if field.primary_key else field.validators):
        limit = getattr(validator, "limit_value", None)
        if type(validator).__name__ == "MinValueValidator":
            notes.append(f"≥ {limit}")
    if isinstance(field, models.ForeignKey):
        notes.append(f"On delete {field.remote_field.on_delete.__name__}")
    return "; ".join(notes)


def field_description(field):
    text = str(field.help_text or "").strip()
    label = str(field.verbose_name)
    if text:
        return text
    return label[:1].upper() + label[1:]


def concrete_fields(model):
    return [f for f in model._meta.get_fields() if getattr(f, "concrete", False) and not f.many_to_many]


def many_to_many(model):
    return [f for f in model._meta.get_fields() if f.many_to_many and not f.auto_created]


def project_models():
    for label, title in PROJECT_APPS:
        yield label, title, [m for m in apps.get_app_config(label).get_models()]


def write_data_dictionary():
    lines = [
        "# Appendix A: Data dictionary",
        "",
        f"*Generated from the Django models on {date.today():%d %B %Y} by "
        "`documentation/tools/generate_schema_docs.py`. Do not edit by hand: rerun the script after "
        "changing a model.*",
        "",
        "Every business table has a `business_id` column (the tenant). Views read tenant data only "
        "through `for_business(...)`, so one dealer can never see another's rows (see Chapter 4).",
        "",
        "Abbreviations: PK primary key, FK foreign key. Decimal(p,s) has p digits in total, s after the "
        "decimal point. Litres use Decimal(12,2); money uses Decimal(14,2).",
        "",
    ]
    number = 0
    for label, title, model_list in project_models():
        lines += [f"## A.{PROJECT_APPS.index((label, title)) + 1} {title}", ""]
        for model in model_list:
            number += 1
            meta = model._meta
            lines += [f"### Table A.{number}: `{meta.db_table}` ({meta.verbose_name})", ""]
            if description(model):
                lines += [description(model), ""]
            lines += ["| Field | Type | Constraints | Description |", "|---|---|---|---|"]
            for field in concrete_fields(model):
                lines.append(f"| `{field.column}` | {field_type(field)} | {constraints_for(field)} | "
                             f"{field_description(field).replace('|', '/')} |")
            for field in many_to_many(model):
                lines.append(f"| `{field.name}` | Many-to-many → {field.related_model._meta.db_table} "
                             f"(table `{field.m2m_db_table()}`) |  | {field_description(field)} |")
            table_rules = []
            for constraint in meta.constraints:
                fields = ", ".join(getattr(constraint, "fields", ()) or ())
                kind = "Unique" if isinstance(constraint, models.UniqueConstraint) else "Check"
                table_rules.append(f"- {kind} `{constraint.name}`" + (f" on ({fields})" if fields else ""))
            if table_rules:
                lines += ["", "Table rules:", *table_rules]
            lines.append("")
    (ACADEMIC / "appendix-a-data-dictionary.md").write_text("\n".join(lines), encoding="utf-8")
    return number


def write_erd():
    lines = [
        "# Entity Relationship Diagrams",
        "",
        f"*Generated from the Django models on {date.today():%d %B %Y} by "
        "`documentation/tools/generate_schema_docs.py`.*",
        "",
        "Mermaid `erDiagram` notation: `||--o{` means one to many. Only primary keys, foreign keys and a "
        "few key columns are shown; Appendix A lists every column. The `business` link that every table "
        "has is shown only in Figure 3.8a to keep the other diagrams readable.",
        "",
        "To turn a diagram into an image for the report: paste it into <https://mermaid.live> and use "
        "*Actions → PNG*, or preview it in VS Code with a Mermaid extension.",
        "",
    ]
    groups = [
        ("3.8a", "Tenants, users and outlet set-up", ["tenants", "accounts", "station"]),
        ("3.8b", "Shift Cards, stock and purchases", ["sales", "stock", "purchases"]),
        ("3.8c", "Credit, expenses and operations", ["finance", "operations"]),
    ]
    for figure, title, labels in groups:
        names = {m for label in labels for m in apps.get_app_config(label).get_models()}
        lines += [f"## Figure {figure}: {title}", "", "```mermaid", "erDiagram"]
        for model in sorted(names, key=lambda m: m._meta.db_table):
            meta = model._meta
            lines.append(f"    {meta.db_table} {{")
            for field in concrete_fields(model):
                if field.primary_key or isinstance(field, models.ForeignKey) or field.name in (
                        "name", "code", "business_date", "status", "invoice_number"):
                    kind = "PK" if field.primary_key else ("FK" if isinstance(field, models.ForeignKey) else "")
                    type_name = type(field).__name__.replace("Field", "").replace("ForeignKey", "bigint")
                    lines.append(f"        {type_name} {field.column} {kind}".rstrip())
            lines.append("    }")
        for model in sorted(names, key=lambda m: m._meta.db_table):
            for field in concrete_fields(model):
                if not isinstance(field, models.ForeignKey):
                    continue
                target = field.related_model
                if target not in names and figure != "3.8a":
                    continue
                if field.name == "business" and figure != "3.8a":
                    continue
                if target._meta.db_table == "accounts_user" and field.name in (
                        "entered_by", "updated_by", "created_by", "cancelled_by", "requested_by", "user"):
                    continue  # "who did it" links are in the data dictionary
                if target not in names:
                    continue
                optional = "o|" if field.null else "||"
                lines.append(f'    {target._meta.db_table} {optional}--o{{ {model._meta.db_table} : "{field.name}"')
        lines += ["```", ""]
    (DIAGRAMS / "erd.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    DIAGRAMS.mkdir(parents=True, exist_ok=True)
    tables = write_data_dictionary()
    write_erd()
    print(f"Data dictionary: {tables} tables. ER diagrams: 3 figures.")
