# Chapter 5: Testing

## 5.1 Testing approach

| Level | How it was done |
|---|---|
| **Unit testing** | The formula functions (`sales/calculations.py`, `stock/calculations.py`, purchase totals, round off, Indian number format) are tested directly with known inputs and expected outputs, including boundary values. |
| **Integration testing** | Service functions (saving, editing, deleting and correcting Shift Cards, stock sheets, purchases, bills) are tested with a real temporary database, checking every linked record, the audit log and the transaction rollback on errors. |
| **System (screen) testing** | Django's test client logs in as a Dealer or Manager and requests real pages and form submissions, checking status codes, redirects, messages and the data saved. |
| **Security testing** | Tests log in as one tenant and try to read or change another tenant's records by ID, by changed form fields and by forged rows; they check login lockout, role limits and subscription expiry. |
| **Manual testing** | Each phase was also checked in the browser with the demo data (`seed_demo`) on Windows, and the deployed copy was checked on Render. |

All automated tests are run with one command:

```
python manage.py test
```

Django creates a temporary test database, runs every test class in every app, and deletes the
database afterwards. Each test starts from a clean state.

## 5.2 Test plan

| Module | What is tested | Tests |
|---|---|---|
| Accounts | Login, lockout, roles, Manager outlets, user management limits | 26 |
| Core | Login flow, public pages, overview page per role and tenant | 11 |
| Tenants | Tenant query isolation, 404 for other tenants, subscriptions and renewals | 20 |
| Station | Outlet set-up, price dates, nozzle–tank–product links, cross-tenant links | 26 |
| Sales | Formulas, card screen, saving, editing, deleting, corrections, summaries | 41 |
| Stock | Book stock, receipts, stock sheet, variation note, locking, order of dates, exact decimal totals | 32 |
| Purchases | Invoice lines, totals, round off, receipts into tanks, locking, isolation | 23 |
| Finance | Credit slips, ledgers, bills and cancellation, payments, expenses | 26 |
| Reports | Dashboard figures, report filters, PDF and Excel export | 12 |
| Operations | Lubricant stock, employees, attendance, reminders, audit log screen | 15 |
| **Total** | | **232** |

## 5.3 Key test cases

The test IDs refer to Appendix B, which lists all 232 tests with their results.

| ID | Test case | Input | Expected result | Actual |
|---|---|---|---|---|
| T085 | Nozzle formula | Opening 460 L, closing 480 L, testing 2 L, ₹100/L | Delivery 20 L, net 18 L, value ₹1,800.00 | Pass |
| T088 | Meter rollover | Reading passes the meter's maximum | Delivery counts both parts | Pass |
| T092 | Testing more than delivery | Testing larger than Sale Ltr | Rejected with a message | Pass |
| T093 | Rounding | Value with a fraction of a paisa | Rounded half up to paise | Pass |
| T096 | Forged nozzle rows | Card form with a nozzle of another MPD/DU added | Refused, nothing saved | Pass |
| T107 | Missing price, future date | Card for a date with no price, or a future date | Card cannot be started | Pass |
| T129 | Stock after a sale | Save a card with testing litres | Stock now falls by the total delivery, testing included | Pass |
| T131 | Locking | Edit a card after that day's stock is saved | Refused | Pass |
| T137 | Testing not counted twice | Stock with testing litres | Testing subtracted once only | Pass |
| T140 | Large variation | Dip far from calculated stock, no note | Note required | Pass |
| T172 | Round off | Invoice total with paise, round up ticked | Rounded to the nearest rupee | Pass |
| T006 | Login lockout | 5 wrong passwords, then the right one | Still refused | Pass |
| T054 | Tenant isolation | Fetch another tenant's record by ID | 404 Not Found | Pass |
| T062 | Cross-tenant edit | POST to change another tenant's nozzle | Refused, nothing changed | Pass |
| T101 | Cards of another tenant | View or change another tenant's card | Not visible, not changeable | Pass |
| T188 | Bills of another tenant | Open another tenant's bill | Not visible | Pass |
| T207 | Dashboard | Day with testing litres | Testing shown apart from sales | Pass |
| T216 | Reports | Report for another tenant's data | No rows shown | Pass |

## 5.4 Test results

The full suite was run on 19 October 2026 on the development PC (Windows 10, Python 3.13.2, SQLite
test database) with `documentation/tools/generate_test_report.py`, which runs the same tests as
`manage.py test` and records each result:

| Measure | Result |
|---|---|
| Tests run | 232 |
| Passed | 232 |
| Failed or errors | 0 |
| Time taken | about 37 seconds |

Appendix B is generated from this run, so it shows only tests that actually ran. To repeat the run
and refresh Appendix B:

```
python documentation/tools/generate_test_report.py
```

## 5.5 Defects found and fixed during development

| Defect | How it was found | Fix |
|---|---|---|
| Testing litres could be subtracted from stock twice (once as testing, once inside delivery) | Formula review and test T137 | Stock uses total delivery only; testing is shown separately |
| A changed web form could add a nozzle row from another MPD/DU | Security test T096 | The server rebuilds the expected rows and rejects any difference |
| Editing an older card would break the next card's opening reading | Integration tests on corrections | Only the latest card can be edited; older cards are corrected, and the next opening is moved after checking it stays valid |
| Cards could change after the day's stock was saved | Locking tests T131 and T134 | Cards and receipts for that date are locked until the stock sheet is changed |
| A database migration failed on SQLite when an old table was removed | Running `migrate` on a fresh database | Migration steps reordered |
| A template error (duplicate end tag) on the overview page | Opening the overview page during development | Template corrected |
| On SQLite, adding up litres with decimals (for example 927.20 + 1,034.60) gave 1,961.80000000000, and the stock sheet refused to save ("no more than 12 digits") | Entering demo data with realistic decimal readings for the screenshots in Chapter 4 | Summed litres are rounded to 0.01 L in the stock service; regression test T138 added |
| On large screens the menu lost its green background because Bootstrap makes the slide-in menu transparent there; on phones the open menu could not scroll down to the last items | Screenshots for this report, and a report from a user on a phone | Stylesheet sets the background for large screens and lets the phone menu scroll |
| The production install failed because a pinned database driver version was not available | Deployment on Render | Driver version updated in `requirements.txt` |
