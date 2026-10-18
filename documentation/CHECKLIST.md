# Documentation checklist

Last updated: 18 October 2026, after **Phase 9**. **All nine development
phases are built.** Phase 9 added subscription renewals, a login lockout,
strict production settings and the deployment guide (`DEPLOYMENT.md`).
Automated tests: 231 run, 231 passed (`python manage.py test`, 18 Oct 2026, after the purchase, shift card and credit bill changes).
Production check: `manage.py check --deploy` reports only the optional HSTS
preload warning. Not yet verified: running on PostgreSQL and a real server.

**Next documentation step:** draft the chapters marked 🟡 below, then take
the screenshots (item 13) from the running application.

**Status key**

| Status | Meaning |
|---|---|
| ⬜ Not started | Nothing written yet |
| 🟡 Ready to draft | The code it describes exists, so writing can begin |
| ✏️ Draft | Written, but will grow as later phases are built |
| ✅ Final | Complete and checked against the code |
| ⏳ Waiting | Depends on a phase that isn't built yet |

## Academic report (`academic/`)

| # | Item | Depends on | Status | Notes |
|---|---|---|---|---|
| 1 | Title page, certificate, declaration, acknowledgement | None | 🟡 Ready to draft | All personal and college details as placeholders |
| 2 | Abstract and keywords | Phases 1–9 | ⏳ Waiting | Written last, so it describes only what was built |
| 3 | Introduction, problem statement, motivation, objectives, scope | None | 🟡 Ready to draft | Scope must match the built modules; review at the end |
| 4 | Existing system, its limitations, proposed system | None | 🟡 Ready to draft | Manual registers and spreadsheets at petrol pumps |
| 5 | Feasibility study (technical, operational, economic) | None | 🟡 Ready to draft | Economic figures shown as estimates, with assumptions stated |
| 6 | SRS: functional and non-functional requirements | Phase-by-phase | 🟡 Ready to draft | Requirements for Phase 1 modules can be marked *Implemented* |
| 7 | Hardware and software requirements | Phase 1 | 🟡 Ready to draft | Versions taken from `requirements.txt` |
| 8 | System architecture and module descriptions | Phase-by-phase | 🟡 Ready to draft | Phases 1–2: `accounts`, `tenants`, `audit`, `core`, `station` |
| 9a | Use-case diagram | Phases 2–8 | 🟡 Ready to draft | Actors: Dealer, Manager, Platform Admin |
| 9b | Class diagram | Phase-by-phase | 🟡 Ready to draft | + FuelProduct, FuelPrice, Dispenser, Nozzle, Shift |
| 9c | Activity diagrams | Phase 3 | 🟡 Ready to draft | Draft → Submitted → Approved, send-back, and correction flows (`sales/services.py`) |
| 9d | Sequence diagrams | Phase 1 / Phase 3 | 🟡 Ready to draft | Login and tenant check; Daily Sales submit, approve and correction |
| 10 | DFD Level 0 and Level 1 | Phases 3–7 | 🟡 Ready to draft | All modules are built |
| 11 | ERD and database schema | Phase-by-phase | 🟡 Ready to draft | Grows with every phase; finalise after Phase 9 |
| 12 | Data dictionary | Phase-by-phase | 🟡 Ready to draft | + station tables (product, price, dispenser, nozzle, shift) |
| 13 | UI screenshots and explanations | Phase-by-phase | 🟡 Ready to draft | + outlet set-up, products, users, business profile |
| 14 | Algorithms and formulas | Phases 3–4 | 🟡 Ready to draft | `sales/calculations.py` (sales, testing litres, meter reset) and `stock/calculations.py` (reconciliation without double subtraction) |
| 15 | Test plan, test cases, results | Phase-by-phase | 🟡 Ready to draft | 231 automated tests passed on 18 Oct 2026 (includes credit slips and bills, invoice-style purchases, MS/HSD split on shift cards) |
| 16 | Security, authentication, authorization, multi-tenant isolation | Phases 1–9 | 🟡 Ready to draft | Includes the login lockout, audit log, production settings check |
| 17 | Installation, configuration, execution (Windows) | Phase 1 | 🟡 Ready to draft | Root `README.md`; hosting in `DEPLOYMENT.md`; free demo hosting in `FREE_HOSTING.md` |
| 18 | User manual summary (Dealer and Manager) | Phases 2–9 | 🟡 Ready to draft | Summarises `user-manual/` |
| 19 | Limitations, future enhancements, conclusion, references | Phase 9 | 🟡 Ready to draft | Real limitations: manual readings only (no dispenser/payment integration), no GST or statutory accounting, observed litres only (no temperature correction), PostgreSQL deployment not yet tested, no dark mode, Indian grouping not applied inside Excel cells |

## User manual (`user-manual/`)

| Item | Depends on | Status |
|---|---|---|
| Logging in, logging out, resetting a password | Phase 1 | 🟡 Ready to draft |
| Dealer: business setup, outlets, users, products, nozzles, shifts | Phase 2 | 🟡 Ready to draft |
| Manager: daily sales entry and testing litres | Phase 3 | 🟡 Ready to draft |
| Dealer: reviewing and approving entries, corrections | Phase 3 | 🟡 Ready to draft |
| Tank stock (dip entry, variation, approval) and fuel received | Phase 4 | 🟡 Ready to draft |
| Fuel purchases (invoice rows with VAT/cess/TCS), collections, credit slips and credit bills, expenses | Phases 5–6 | 🟡 Ready to draft |
| Dashboard and reports (PDF / Excel) | Phase 7 | 🟡 Ready to draft |
| Inventory, employees, reminders, audit log | Phase 8 | 🟡 Ready to draft |
| Subscription and renewal | Phase 9 | 🟡 Ready to draft |

## Diagrams (`diagrams/`)

| Diagram | Status |
|---|---|
| Use-case | 🟡 Ready to draft |
| Class (Phase 1 models) | 🟡 Ready to draft |
| Activity (Daily Sales approval) | 🟡 Ready to draft |
| Sequence (login and tenant check) | 🟡 Ready to draft |
| Sequence (Daily Sales submit and approve) | 🟡 Ready to draft |
| DFD Level 0 | 🟡 Ready to draft |
| DFD Level 1 | 🟡 Ready to draft |
| ERD | 🟡 Ready to draft (Phase 1 tables) |

## Final deliverable

| Item | Status |
|---|---|
| Final report in DOCX format | ⏳ Waiting: produced only after all built features and test results have been checked |

## Update log

| Date | Phase | What changed |
|---|---|---|
| 18 Oct 2026 | Phase 1 | Checklist and outline created |
| 18 Oct 2026 | Phase 2 | Station set-up and user management built; items 8, 9b, 11–13, 15 and the Phase 2 user-manual item updated |
| 18 Oct 2026 | Phase 3 | Daily Sales built; items 9c, 9d, 14, 15 and the Phase 3 user-manual items updated |
| 18 Oct 2026 | Phase 4 | Tank stock built; items 14, 15 and the stock user-manual item updated. The test suite now uses a fast password hasher (8 s instead of about 5 min) |
| 18 Oct 2026 | Phases 5–6 | Purchases and finance built; items 15 and the user-manual items updated |
| 18 Oct 2026 | Phases 7–8 | Dashboard, reports and exports, inventory, staff, reminders and audit log built |
| 18 Oct 2026 | Phase 9 | Subscriptions, hardening and the deployment guide; every remaining item is now ready to draft |
| 18 Oct 2026 | After Phase 9 | Fuel purchase screen redesigned like a dealer invoice (KL, rate per KL, delivery charges, VAT, cess, TCS, tank per row, round off); MS and HSD shown separately on shift cards; credit slips get automatic slip numbers, item, litres and rate; credit bills with automatic bill numbers, period from the last bill, amount in words and print layout; free hosting guide. 231 tests pass |
