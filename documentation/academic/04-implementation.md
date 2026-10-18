# Chapter 4: Implementation

## 4.1 Development approach

The system was built in nine phases, each one finished with automated tests before the next began:

| Phase | Work done |
|---|---|
| 1 | Project set-up, design system, tenants, custom user model, login, audit log |
| 2 | Outlet set-up: products, prices, dispensers, tanks, nozzles, shifts; user management |
| 3 | Daily sales (Shift Card) formulas and entry |
| 4 | Tank stock: fuel received, daily stock sheet, reconciliation |
| 5 | Fuel purchases and suppliers |
| 6 | Credit customers, ledgers, bills, expenses |
| 7 | Dashboard, reports, PDF and Excel export |
| 8 | Lubricant inventory, employees and attendance, reminders, audit log screen |
| 9 | Security hardening, deployment settings, backups |

After the nine phases, the Shift Card was reworked to match the paper card used at pumps (money
details on the card itself, with no approval step), tank stock was made live, and one purchase
invoice was allowed to hold both MS and HSD lines.

## 4.2 Project structure

```
PetroSmart/
  config/          settings.py, urls.py, wsgi.py
  tenants/         Business, Outlet, plans; middleware.py, permissions.py
  accounts/        User model, login form with lockout, user screens
  audit/           AuditLog model
  station/         products, prices, dispensers, tanks, nozzles, shifts
  sales/           calculations.py, services.py, views.py (Shift Card)
  stock/           calculations.py, services.py (book stock, stock sheets)
  purchases/       suppliers, fuel purchases
  finance/         credit customers, bills, expenses
  reports/         definitions.py, exports.py (Excel and PDF)
  operations/      lubricants, employees, reminders, audit log screen
  core/            dashboard.py, crud.py, forms.py, ps_format.py filters
  templates/       HTML pages
  static/          css (design tokens, theme), js (shift-card.js, charts)
  documentation/   this report, diagrams, user manual, generator scripts
  manage.py, requirements.txt, render.yaml
```

Each app follows the same pattern: `models.py` (tables), `forms.py` (input validation), `services.py`
(business rules in transactions), `views.py` (screens) and `tests*.py` (automated tests).

## 4.3 Algorithms and formulas

All figures use Python's `Decimal` type. Money is rounded **half up to the paisa** (₹0.01).

### 4.3.1 Nozzle sales (Shift Card line)

Implemented once in `sales/calculations.py` (`calculate_line`) and used by the card screen, the
corrections and every report:

```
Total Nozzle Delivery (Sale Ltr) = Closing Reading − Opening Reading
Net Customer Sales (Net Ltr)     = Total Nozzle Delivery − Testing Litres
Customer Sales Value (Sale Rs)   = Net Customer Sales × Selling Price per Litre
```

**Algorithm: calculate_line(opening, closing, testing, price)**

1. If a meter reset is recorded, check that *before reset* ≥ opening and closing ≥ *after reset*;
   delivery = (before reset − opening) + (closing − after reset).
2. Otherwise, if closing < opening, reject: "Closing reading cannot be less than the opening
   reading". Else delivery = closing − opening.
3. Reject if testing < 0 or testing > delivery.
4. Reject if the price is not above ₹0.
5. Net = delivery − testing; value = net × price, rounded half up to paise.
6. Return delivery, testing, net and value. Values are never adjusted silently; every error is
   reported against the field that caused it.

**Worked example** (the same figures are checked by automated test T085, Appendix B). Opening
460.00 L, closing 480.00 L, testing 2.00 L, rate ₹100.00 per litre:

| Step | Calculation | Result |
|---|---|---|
| Total delivery | 480.00 − 460.00 | 20.00 L |
| Net customer sales | 20.00 − 2.00 | 18.00 L |
| Sales value | 18.00 × 100.00 | ₹1,800.00 |
| Litres leaving the tank | total delivery (testing included) | 20.00 L |

**Meter reset example.** The meter rolled over at 1,000,000.00 to 0 during the shift. Opening
999,950.00, closing 30.00: delivery = (1,000,000.00 − 999,950.00) + (30.00 − 0) = 80.00 L.

### 4.3.2 Shift Card money balance

Implemented in `sales/services.py` (`card_figures`):

```
Cash collection      = Σ (notes × denomination for ₹2000, 500, 200, 100, 50, 20, 10) + coins
Cash to be collected = Total fuel + Lube/oil sale + Customer receipts
                       − Credit sale − General credit − Bank card − Company card
                       − Phone wallet − Expenses paid in cash by the DSM
Balance              = Cash collection − Cash to be collected
```

A negative balance means the cash is short; a positive balance means it is in excess.

**Example.** Total fuel ₹1,800.00; credit slips ₹500.00; bank card ₹200.00; phone wallet ₹300.00.
Cash to be collected = 1,800.00 − 500.00 − 200.00 − 300.00 = ₹800.00. The DSM hands over 1 × ₹500,
1 × ₹200, 4 × ₹20, 1 × ₹10 and ₹5.00 in coins = ₹795.00, so the balance is −₹5.00 (short by ₹5.00).

### 4.3.3 Tank stock

Implemented in `stock/services.py` (`book_stock`) and `stock/calculations.py` (`reconcile`):

```
Stock now          = last measured (dip) stock, or the tank's starting stock
                     + fuel received since then − total nozzle delivery since then
Calculated closing = Opening stock + Fuel received − Total nozzle delivery
Variation          = Measured closing (dip) − Calculated closing
```

Total delivery includes testing litres, because that fuel left the tank. A variation larger than the
tank's alert limit cannot be saved without a note explaining it.

**Example.** Opening stock 10,000.00 L, fuel received 4,000.00 L, total delivery 20.00 L (of which
2.00 L testing). Calculated closing = 10,000.00 + 4,000.00 − 20.00 = 13,980.00 L. Dip reading
13,970.00 L gives a variation of −10.00 L (a loss of 10 litres).

### 4.3.4 Fuel purchase invoice

Implemented in `purchases/models.py`:

```
Line base amount = Invoiced litres × Rate per KL ÷ 1000    (rounded half up to paise)
Line total       = Base amount + Delivery charges + VAT + Cess + TCS
Invoice total    = Σ line totals + Round off
Round off        = (total rounded half up to the nearest rupee) − total, if "round up" is ticked
```

Taxes are entered **as printed on the supplier's invoice**; the system does not calculate VAT or GST.
For example, 12,000 L at ₹88,450.00 per KL has a base amount of ₹10,61,400.00. A total of ₹5,574.40
gives a round off of −₹0.40, and ₹5,574.50 gives +₹0.50.

### 4.3.5 Credit slips and bills

- A credit slip's litres = amount ÷ the nozzle rate of that product on the card. Slip numbers run per
  outlet.
- A credit bill takes all unbilled slips of the customer at the outlet up to the bill date. Bill
  numbers run per outlet; a bill date cannot be earlier than the previous bill.
- Bill amount = slips total + round off; net amount = previous balance + bill amount.
- Customer balance = opening balance + credit slips − payments ± adjustments + round offs of issued
  bills.

### 4.3.6 Order of readings

Opening readings form a chain from shift to shift. When a new card is opened, the system finds, for
each nozzle, the line on the closest earlier shift (by date, then by the shift's sort order); its
closing reading becomes the opening reading. If the nozzle already has a reading on the same or a
later shift, the card cannot be started. Because of this chain:

- only the latest card of a nozzle can be edited or deleted directly;
- an older card is fixed by a **correction**: the old and new values are kept, and the next card's
  opening reading is moved to the new closing reading, after checking that the next card stays valid;
- once the day's tank stock sheet is saved, that day's cards are locked until the stock sheet is
  edited or deleted.

### 4.3.7 Indian number format

The template filter `inr` (`core/templatetags/ps_format.py`) groups digits in the Indian way: the last
three digits, then pairs. For example 123456.78 is shown as ₹1,23,456.78, and a negative amount as
−₹500.00.

## 4.4 Security and multi-tenancy

### 4.4.1 Tenant isolation

| Mechanism | Where | What it does |
|---|---|---|
| Tenant from the login | `tenants/middleware.py` | `request.business` comes from the logged-in user, never from a URL, form field or cookie |
| Tenant column | `TenantOwnedModel` | Every business table has a `business` foreign key |
| Filtered queries | `for_business(business)` | The only approved way to list tenant data; returns nothing if there is no business |
| Single records | `get_for_business(...)` | Returns **404 Not Found** for another tenant's record, so its existence is not revealed |
| Forms | `core.forms.TenantModelForm` | The server sets the business and outlet; choice lists are limited to the tenant's own records |
| Cross-links | `check_same_business(...)` in model `clean()` | A record cannot point to another tenant's record (for example a nozzle to another dealer's tank) |
| Manager outlets | `User.accessible_outlets()` | A Manager works only at outlets assigned to them; services check this again before saving |
| Subscription | `BusinessMemberRequiredMixin` | A suspended or expired business is sent to a notice page and cannot use the system |

### 4.4.2 Authentication and sessions

- **Default deny:** `LoginRequiredMiddleware` requires login for every page except those marked public.
- **Password storage:** PBKDF2 with SHA-256 and a random salt (Django default). Minimum length
  10 characters; common and all-number passwords are rejected.
- **Login lockout:** after 5 failed attempts for a username, or 20 from one IP address, within
  15 minutes, further attempts are refused. Failed logins are written to the audit log.
- **Sessions:** cookies are `HttpOnly` and `SameSite=Lax`, expire after 8 hours or when the browser
  closes, and are marked `Secure` in production.
- **Password reset** by email with Django's one-time token links.

### 4.4.3 Other protections

| Threat | Protection |
|---|---|
| Cross-site request forgery | CSRF token on every form (`CsrfViewMiddleware`) |
| SQL injection | All queries through the Django ORM, which uses parameters |
| Cross-site scripting | Templates escape all output automatically |
| Clickjacking | `X-Frame-Options: DENY` |
| Changed or forged form rows | The server rebuilds the list of nozzle and tank rows and rejects a form whose rows differ |
| Silent changes | Append-only audit log of logins, creates, edits, deletes, corrections and exports, with user, time, IP address and old/new values |
| Unsafe production settings | With `DEBUG` off, the app refuses to start without a secret key of at least 40 characters or with `ALLOWED_HOSTS` set to `*`; HTTPS redirect and HSTS are set by environment variables |
| Secrets in code | The secret key, database address and email password come from environment variables (`.env`), which are not stored in Git |

## 4.5 User interface

The interface uses Bootstrap 5 with a custom design system: a warm ivory background, forest-green
primary colour and a dark green sidebar grouped into *Operations*, *Money*, *Outlet*, *Set-up* and
*Business*. Status is always shown with text or an icon as well as colour. The layout adapts to phone,
tablet and desktop screens. Figures are right-aligned and shown in Indian format.

The screenshots below were taken from the running application with demo data (sample businesses,
prices and readings created by `seed_demo` plus a few shift cards, a stock sheet, a purchase and a
credit bill entered through the application's own functions). The images are in
`documentation/screenshots/`; to replace one, save a new image with the same file name and rebuild the
report.

{{screenshot:01-login.png|Login page}}

{{screenshot:02-dashboard.png|Overview dashboard (Dealer)}}

{{screenshot:03-shift-card.png|Shift Card entry: pump readings and money details}}

{{screenshot:04-shift-card-view.png|Saved Shift Card with totals and balance}}

{{screenshot:05-tank-stock.png|Daily tank stock sheet with variation}}

{{screenshot:06-fuel-purchase.png|Fuel purchase invoice with MS and HSD lines}}

{{screenshot:07-credit-bill.png|Printed credit bill}}

{{screenshot:08-reports.png|Reports with PDF and Excel export}}

{{screenshot:09-audit-log.png|Audit log}}

{{screenshot:10-outlet-setup.png|Outlet set-up: tanks, MPD/DU, nozzles, shifts}}
