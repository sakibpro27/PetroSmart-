# PetroSmart

Multi-tenant petrol pump management system (Django). Each dealer business is a
separate tenant; within a business there are exactly two roles, **Dealer** and
**Manager**. The SaaS provider manages tenants through the platform admin site.

## Project layout

| Folder | Purpose |
|---|---|
| `config/` | Django settings and root URLs. All secrets come from `.env`. |
| `accounts/` | Custom `User` model (Dealer / Manager / platform admin), login forms. |
| `tenants/` | `Business` (tenant), `Outlet`, `SubscriptionPlan`, tenant isolation helpers. |
| `audit/` | Append-only `AuditLog`: logins, saves, corrections, edits, deletions and exports. |
| `core/` | Dashboard (`dashboard.py`), `seed_demo` command, shared form/view building blocks (`forms.py`, `crud.py`), INR number filters. |
| `station/` | Outlet set-up: fuel products (MS/HSD), selling prices, dispensers, tanks, nozzles, shifts. |
| `sales/` | Daily Sales: formulas (`calculations.py`), workflow rules (`services.py`), summaries (`reports.py`). |
| `stock/` | Fuel receipts and daily tank stock reconciliation (`calculations.py`, `services.py`). |
| `purchases/` | Suppliers and fuel purchase invoices, allocated to tanks. |
| `finance/` | Payment methods, credit customers and ledgers, credit bills, expenses, operational summary. |
| `reports/` | Report definitions, plus Excel (openpyxl) and PDF (ReportLab) export. |
| `operations/` | Lubricant/shop inventory, employees and attendance, reminders, audit log screen. |
| `templates/`, `static/` | Pages, CSS theme tokens (`static/css/tokens.css`), JS (entry previews, charts). |

Hosting for real customers is covered in [DEPLOYMENT.md](DEPLOYMENT.md).

## First-time setup (Windows PowerShell)

```powershell
cd C:\Users\sony\PetroSmart
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Create your .env from the example, then put a real secret key in it:
copy .env.example .env
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"

python manage.py migrate
python manage.py seed_demo          # optional demo data (DEBUG only)
python manage.py createsuperuser    # platform administrator account
```

If `Activate.ps1` is blocked, run once:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

## Running

```powershell
.\.venv\Scripts\Activate.ps1
python manage.py runserver
```

* Business app: http://127.0.0.1:8000/
* Platform admin: http://127.0.0.1:8000/platform-admin/

Demo users (password `PetroDemo@2026`): `ganesh.dealer`, `ganesh.manager`,
`omsai.dealer`, `omsai.manager`.

## Tests

```powershell
python manage.py test
```

## Tenant isolation rules (for developers)

* Every model holding business data inherits `tenants.models.TenantOwnedModel`.
* List data with `Model.objects.for_business(request.business)`.
* Fetch one record with `tenants.permissions.get_for_business(...)` (404 for other tenants).
* Protect views with `BusinessMemberRequiredMixin` or `DealerRequiredMixin`.
* Forms that save tenant data inherit `core.forms.TenantModelForm`: the business
  and outlet are set by the server, and limited choice lists stop cross-tenant links.
* Add/edit views use `core.crud` mixins, which write every change to the audit log.

The test run uses a fast password hasher (see `config/settings.py`), so the
whole suite finishes in about 20 seconds. Real logins always use PBKDF2.

## Backup and restore

**SQLite (development):** stop the server and copy `db.sqlite3` somewhere safe.
Restore by copying it back.

**PostgreSQL (production):**

```powershell
pg_dump -Fc -U petrosmart -h localhost petrosmart > petrosmart_YYYYMMDD.dump
pg_restore -c -U petrosmart -h localhost -d petrosmart petrosmart_YYYYMMDD.dump
```

Keep backups off the server, test a restore regularly, and never store `.env`
alongside public backups.
