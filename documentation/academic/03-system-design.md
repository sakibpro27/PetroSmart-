# Chapter 3: System Design

## 3.1 System architecture

PetroSmart is a **multi-tenant web application** that follows Django's Model-View-Template (MVT)
pattern. One installation and one database serve every dealer business (tenant). Each business row
in the database is the tenant, and every table that holds business data carries a `business_id`
column pointing to it.

A request passes through these layers (Figure 3.1):

1. The **browser** sends an HTTPS request. In production Gunicorn runs the application and
   WhiteNoise serves the CSS, JavaScript and images; on Windows during development Django's
   `runserver` does both.
2. **Middleware** adds security headers, the session, CSRF protection and the logged-in user. The
   `LoginRequiredMiddleware` denies every page by default unless the page is explicitly public (the
   login and password reset pages). `TenantMiddleware` then sets `request.business` from the
   logged-in user, never from anything the browser sends.
3. **URL routing** (`config/urls.py`) sends the request to a view.
4. **Views** check the role through `BusinessMemberRequiredMixin` or `DealerRequiredMixin`, read and
   validate the forms, and call a service.
5. **Services** (`services.py` in each app) hold the business rules. They run each save in one
   database transaction and write the audit log. All formulas live in `calculations.py` files.
6. **Models** and the Django ORM read and write the database. Every tenant query goes through
   `for_business(business)`.
7. **Templates** with Bootstrap 5 and Chart.js produce the pages; **exports** produce Excel
   (openpyxl) and PDF (ReportLab) files.

{{diagram:architecture}}

## 3.2 Modules

The project is split into Django apps, one per module:

| App (module) | Responsibility |
|---|---|
| `tenants` | Businesses (tenants), outlets, subscription plans and renewals; tenant middleware, `TenantOwnedModel` and access-control mixins |
| `accounts` | Custom `User` model with the Dealer and Manager roles; login with lockout; user management by the Dealer |
| `audit` | The append-only `AuditLog` model and the `record()` helper |
| `station` | Outlet set-up: fuel products (MS, HSD), selling prices with effective dates, dispensers (MPD/DU), tanks, nozzles and shifts |
| `sales` | The Shift Card: formulas (`calculations.py`), saving, deleting and correcting cards (`services.py`), the card screen and summaries |
| `stock` | Fuel received into tanks, live book stock, daily stock sheets with dip readings and variation |
| `purchases` | Suppliers, fuel purchase invoices and their lines per tank |
| `finance` | Payment methods, credit customers and ledgers, payments and adjustments, credit bills, expenses, operational summary |
| `reports` | Report definitions and their Excel and PDF export |
| `operations` | Lubricant and shop items and their stock movements, employees and attendance, reminders, the audit log screen |
| `core` | Overview dashboard, shared form and view building blocks, Indian number formatting, demo data command |

## 3.3 UML diagrams

### 3.3.1 Use-case diagram

There are three actors (Figure 3.2). The Manager records the day's work at the outlets assigned to
them. The Dealer can do everything a Manager can at every outlet, and also sets up the business and
controls it. The platform administrator works only with tenants (businesses, plans and renewals) on
a separate admin site.

{{diagram:usecase}}

### 3.3.2 Class diagram

Figure 3.3 shows the main classes and their associations. A business has many users and outlets; an
outlet has tanks, dispensers and nozzles, and each nozzle draws from one tank. A Shift Card
(`DailySalesSheet`) has one line per nozzle of its MPD/DU, and credit slips are linked to the card on
which they were given.

{{diagram:classes}}

### 3.3.3 Activity diagram

Figure 3.4 shows the most important activity: filling in and saving a Shift Card. The system first
checks that a card can be started (earlier cards for the same nozzles exist in date order and a price
is set), and checks everything again on the server when the card is saved.

{{diagram:activity}}

### 3.3.4 Sequence diagram

Figure 3.5 shows the messages exchanged when a Shift Card is saved. The view checks permissions and
validates the forms; the service function `save_card` does the rest inside one transaction, so a
failure at any step leaves the database unchanged.

{{diagram:sequence}}

## 3.4 Data flow diagrams

### 3.4.1 Level 0 (context diagram)

At Level 0 the whole system is one process (Figure 3.6). The Manager supplies readings, testing
litres, money and dip readings; the Dealer supplies the set-up and prices and receives reports; the
supplier's invoice details are entered as purchases; credit customers receive bills and make
payments; the platform administrator supplies plans, businesses and renewals.

{{diagram:dfd0}}

### 3.4.2 Level 1

Figure 3.7 breaks the system into seven processes and six data stores. The opening readings and rates
for a Shift Card come from the set-up store (D2) and the previous card; the card's total delivery
feeds tank stock reconciliation (process 4.0); credit slips and receipts go to the credit ledger
(D5), from which bills are made.

{{diagram:dfd1}}

## 3.5 Database design

### 3.5.1 Entity relationship diagram

Figure 3.8 gives a simplified ERD of the main entities. The full ERDs, with keys and the main columns
of all 35 tables, are in `documentation/diagrams/erd.md` (Figures 3.8a to 3.8c, Mermaid notation), and
every column is listed in Appendix A.

{{diagram:erd}}

### 3.5.2 Schema summary

The database has 35 application tables. The most important are:

| Table | Purpose | Key constraints |
|---|---|---|
| `tenants_business` | The tenant (dealer business) | Plan, status, subscription end date |
| `tenants_outlet` | A petrol pump outlet of the business | Code unique per business |
| `accounts_user` | Login account | Role Dealer or Manager; business required for these roles |
| `station_tank` | Underground tank | Holds one product; capacity, starting stock, variation alert limit |
| `station_nozzle` | Nozzle of a dispenser | Linked to one tank and product; initial totalizer reading |
| `station_fuelprice` | Selling price | Per outlet and product, effective from a date |
| `sales_dailysalessheet` | Shift Card header and money details | Date, shift, MPD/DU and employee; note counts, cards, wallet |
| `sales_dailysalesline` | One nozzle's readings on a card | Unique (card, nozzle); delivery, net litres and value stored |
| `sales_salescorrection` | Correction to an older card | Reason required; old and new values kept in `sales_correctionline` |
| `stock_stocksheet`, `stock_stockline` | Daily tank stock and dip | One sheet per outlet and date; one line per tank |
| `stock_tankreceipt` | Fuel unloaded into a tank | Created from a purchase line, or entered directly |
| `purchases_fuelpurchase`, `purchases_purchaseline` | Supplier invoice and its lines | One line per tank per invoice |
| `finance_creditcustomer` | Credit customer | Credit limit, opening balance |
| `finance_creditsale` | Credit slip on a Shift Card | Slip number per outlet; linked to the card and later to a bill |
| `finance_creditbill` | Numbered credit bill | Bill number per outlet; can be cancelled with a reason |
| `audit_auditlog` | Audit trail | Never edited or deleted through the application |

### 3.5.3 Design decisions

- **Shared database, tenant column.** Every business table has a `business_id` foreign key, and the
  only approved way to list rows is `Model.objects.for_business(business)`. This is simpler and
  cheaper than one database per dealer, and the isolation is checked by automated tests (Chapter 5).
- **Exact decimals.** Litres are `Decimal(12,2)`, money `Decimal(14,2)` and prices `Decimal(7,2)`.
  Floating point is never used for money or volumes.
- **Stored results.** Each card line stores its total delivery, net litres and value, calculated by
  one function when it is saved, so reports never recalculate from changed prices.
- **Readings form a chain.** A nozzle's opening reading is always the previous card's closing reading
  for that nozzle; this is why only the latest card can be edited, and why a correction updates the
  next card's opening reading.
- **Nothing silently overwritten.** Corrections keep the old and new values, cancelled bills keep
  their reason, and every change is in the audit log.
- **Protected deletes.** Foreign keys use `PROTECT`, so set-up data (for example a tank that has
  sales) cannot be deleted by accident.
